from __future__ import annotations

import dataclasses
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image  # type: ignore[import-untyped]

from core.image_ops import (
    apply_all_watermarks,
    prepare_logo_rgba,
    save_processed_image,
)
from core.models import BatchRequest, PlacementSettings, ProcessedFile, SUPPORTED_EXTENSIONS


ProgressCallback = Callable[[int, int, Path], None]


def discover_images(source_folder: Path) -> list[Path]:
    return sorted(
        path
        for path in source_folder.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def sanitize_image_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[Path] = set()
    valid_paths: list[Path] = []

    for path in paths:
        resolved_path = path.resolve()
        if resolved_path in seen:
            continue
        if not resolved_path.is_file():
            continue
        if resolved_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        seen.add(resolved_path)
        valid_paths.append(resolved_path)

    return sorted(valid_paths)


def get_output_folder(input_path: Path) -> Path:
    base_folder = input_path if input_path.is_dir() else input_path.parent
    return base_folder.parent / f"{base_folder.name}_Processed"


def resolve_images(request: BatchRequest) -> list[Path]:
    if request.source_paths:
        return sanitize_image_paths(request.source_paths)
    if request.source_folder is None:
        return []
    return discover_images(request.source_folder)


def process_batch(
    request: BatchRequest,
    progress_callback: ProgressCallback | None = None,
) -> list[ProcessedFile]:
    image_paths = resolve_images(request)
    if not image_paths:
        raise ValueError(
            "No supported image files were found in the selected folder."
        )
    if not request.logos:
        raise ValueError("No logos provided in the batch request.")

    output_folder = request.output_folder or get_output_folder(image_paths[0])
    output_folder.mkdir(parents=True, exist_ok=True)

    # Pre-process logos to RGBA once — avoids redundant work per image
    prepared_logos: list[Image.Image] = []
    raw_logos: list = []
    try:
        for lc in request.logos:
            raw = Image.open(lc.logo_path)  # type: ignore[assignment]
            raw_logos.append(raw)
            prepared_logos.append(prepare_logo_rgba(raw))
    finally:
        for raw in raw_logos:
            raw.close()

    total = len(image_paths)
    counter_lock = threading.Lock()
    counter = [0]

    def process_one(image_path: Path) -> ProcessedFile:
        per_logo_overrides = request.logo_settings_by_path.get(image_path, {})
        logo_settings_list: list[tuple[Image.Image, PlacementSettings]] = []
        for logo_idx, (logo_cfg, logo_img) in enumerate(
            zip(request.logos, prepared_logos)
        ):
            logo_settings = per_logo_overrides.get(logo_idx, logo_cfg.settings)
            effective = dataclasses.replace(
                logo_settings,
                output_size_mode=request.settings.output_size_mode,
                quality=request.settings.quality,
            )
            logo_settings_list.append((logo_img, effective))

        with Image.open(image_path) as source_image:
            result_image = apply_all_watermarks(
                source_image, logo_settings_list
            )

        output_path = output_folder / image_path.name
        save_processed_image(
            result_image, output_path, request.settings.quality
        )

        if progress_callback is not None:
            with counter_lock:
                counter[0] += 1
                current = counter[0]
            progress_callback(current, total, image_path)

        return ProcessedFile(
            source_path=image_path,
            output_path=output_path,
            width=result_image.width,
            height=result_image.height,
        )

    # Cap at 4 workers to avoid RAM exhaustion on low-spec machines
    max_workers = min(4, max(1, os.cpu_count() or 1))
    results_map: dict[int, ProcessedFile] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_one, path): i
            for i, path in enumerate(image_paths)
        }
        for future in as_completed(futures):
            idx = futures[future]
            results_map[idx] = future.result()  # re-raises on worker error

    return [results_map[i] for i in range(total)]


def iter_processed_files(
    paths: Iterable[ProcessedFile],
) -> Iterable[tuple[str, str]]:
    for item in paths:
        yield str(item.source_path), str(item.output_path)
