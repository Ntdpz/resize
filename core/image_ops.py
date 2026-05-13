from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps  # type: ignore[import-untyped]

from core.models import (
    OUTPUT_SIZE_ORIGINAL,
    POSITION_PRESETS,
    PlacementSettings,
)


TARGET_WIDTH = 1280
PREVIEW_MAX_DIMENSION = 520


@dataclass(frozen=True)
class WatermarkScene:
    base_image: Image.Image
    logo_image: Image.Image
    position: tuple[int, int]


def resize_image(
    image: Image.Image,
    should_resize: bool = True,
    target_width: int = TARGET_WIDTH,
) -> Image.Image:
    if not should_resize:
        return image.copy()

    if image.width == target_width:
        return image.copy()

    target_height = round((target_width / image.width) * image.height)
    return image.resize(
        (target_width, target_height),
        Image.Resampling.LANCZOS,
    )


def get_orientation(image: Image.Image) -> str:
    return "landscape" if image.width > image.height else "portrait"


def calculate_logo_size(
    base_width: int,
    logo: Image.Image,
    scale_percent: int,
) -> tuple[int, int]:
    scale_percent = max(5, min(scale_percent, 60))
    target_width = max(1, round(base_width * (scale_percent / 100)))
    target_height = max(1, round(target_width * (logo.height / logo.width)))
    return target_width, target_height


def calculate_position(
    image_size: tuple[int, int],
    logo_size: tuple[int, int],
    preset: str,
    offset_x: int,
    offset_y: int,
    margin: int,
) -> tuple[int, int]:
    if preset not in POSITION_PRESETS:
        raise ValueError(f"Unsupported logo preset: {preset}")

    image_width, image_height = image_size
    logo_width, logo_height = logo_size

    horizontal_positions = {
        "left": margin,
        "center": round((image_width - logo_width) / 2),
        "right": image_width - logo_width - margin,
    }
    vertical_positions = {
        "top": margin,
        "middle": round((image_height - logo_height) / 2),
        "bottom": image_height - logo_height - margin,
    }

    vertical_key, horizontal_key = (
        preset.split("-") if "-" in preset else ("middle", "center")
    )
    if preset == "center":
        vertical_key, horizontal_key = "middle", "center"

    x = horizontal_positions[horizontal_key] + offset_x
    y = vertical_positions[vertical_key] + offset_y

    x = max(0, min(x, image_width - logo_width))
    y = max(0, min(y, image_height - logo_height))
    return x, y


def apply_watermark(
    image: Image.Image,
    logo: Image.Image,
    settings: PlacementSettings,
) -> Image.Image:
    scene = build_watermark_scene(image, logo, settings)
    composite = scene.base_image.copy()
    composite.alpha_composite(scene.logo_image, dest=scene.position)
    return composite


def build_watermark_scene(
    image: Image.Image,
    logo: Image.Image,
    settings: PlacementSettings,
    preview: bool = False,
) -> WatermarkScene:
    transposed_image = ImageOps.exif_transpose(image) or image
    base_image = (
        create_preview_base(transposed_image)
        if preview
        else resize_image(
            transposed_image.convert("RGBA"),
            should_resize=settings.output_size_mode != OUTPUT_SIZE_ORIGINAL,
        )
    )
    orientation = get_orientation(base_image)
    preset = (
        settings.landscape_position
        if orientation == "landscape"
        else settings.portrait_position
    )

    transposed_logo = ImageOps.exif_transpose(logo) or logo
    logo_rgba = transposed_logo.convert("RGBA")
    logo_size = calculate_logo_size(
        base_image.width,
        logo_rgba,
        settings.logo_scale_percent,
    )
    resized_logo = logo_rgba.resize(logo_size, Image.Resampling.LANCZOS)
    position = calculate_position(
        base_image.size,
        resized_logo.size,
        preset,
        settings.offset_x,
        settings.offset_y,
        settings.margin,
    )
    return WatermarkScene(
        base_image=base_image,
        logo_image=resized_logo,
        position=position,
    )


def create_preview_base(
    image: Image.Image,
    max_dimension: int = PREVIEW_MAX_DIMENSION,
) -> Image.Image:
    preview = (ImageOps.exif_transpose(image) or image).convert("RGBA")
    preview.thumbnail(
        (max_dimension, max_dimension),
        Image.Resampling.LANCZOS,
    )
    return preview


def apply_watermark_preview(
    image: Image.Image,
    logo: Image.Image,
    settings: PlacementSettings,
) -> Image.Image:
    scene = build_watermark_scene(image, logo, settings, preview=True)
    composite = scene.base_image.copy()
    composite.alpha_composite(scene.logo_image, dest=scene.position)
    return composite


def save_processed_image(
    image: Image.Image,
    output_path: Path,
    quality: int,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    normalized_quality = max(90, min(quality, 100))
    suffix = output_path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        image.convert("RGB").save(
            output_path,
            quality=normalized_quality,
            optimize=True,
        )
        return

    image.save(output_path, optimize=True)
