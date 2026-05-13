from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from PIL import Image  # type: ignore[import-untyped]

from core.image_ops import apply_watermark, save_processed_image
from core.models import BatchRequest, ProcessedFile, SUPPORTED_EXTENSIONS


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

    output_folder = request.output_folder or get_output_folder(image_paths[0])
    processed_files: list[ProcessedFile] = []

    with Image.open(request.logo_path) as logo_image:
        for index, image_path in enumerate(image_paths, start=1):
            image_settings = request.settings_by_path.get(
                image_path,
                request.settings,
            )
            with Image.open(image_path) as source_image:
                result_image = apply_watermark(
                    source_image,
                    logo_image,
                    image_settings,
                )

            output_path = output_folder / image_path.name
            save_processed_image(
                result_image,
                output_path,
                image_settings.quality,
            )
            processed_files.append(
                ProcessedFile(
                    source_path=image_path,
                    output_path=output_path,
                    width=result_image.width,
                    height=result_image.height,
                )
            )

            if progress_callback is not None:
                progress_callback(index, len(image_paths), image_path)

    return processed_files


def iter_processed_files(
    paths: Iterable[ProcessedFile],
) -> Iterable[tuple[str, str]]:
    for item in paths:
        yield str(item.source_path), str(item.output_path)
