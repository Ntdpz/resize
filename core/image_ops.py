from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps  # type: ignore[import-untyped]

from core.models import (
    OUTPUT_SIZE_ORIGINAL,
    POSITION_PRESETS,
    PlacementSettings,
)

from PIL import ImageEnhance  # type: ignore[import-untyped]


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


def prepare_logo_rgba(logo: Image.Image) -> Image.Image:
    """Pre-process logo to RGBA once before batch processing."""
    transposed = ImageOps.exif_transpose(logo) or logo
    return transposed.convert("RGBA")


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


def apply_all_watermarks(
    image: Image.Image,
    logo_settings: list[tuple[Image.Image, PlacementSettings]],
) -> Image.Image:
    """Apply all watermarks in a single composite pass."""
    if not logo_settings:
        return image

    # Build base image once — output_size_mode is shared across logo entries
    first_settings = logo_settings[0][1]
    transposed_image = ImageOps.exif_transpose(image) or image
    base_image = resize_image(
        transposed_image.convert("RGBA"),
        should_resize=first_settings.output_size_mode != OUTPUT_SIZE_ORIGINAL,
    )
    orientation = get_orientation(base_image)

    # Composite all logos onto one overlay layer, then apply to base once
    overlay = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
    for logo_img, settings in logo_settings:
        preset = (
            settings.landscape_position if orientation == "landscape"
            else settings.portrait_position
        )
        # Skip exif_transpose + convert if logo is already prepared as RGBA
        logo_rgba = (
            logo_img if logo_img.mode == "RGBA"
            else (
                ImageOps.exif_transpose(logo_img) or logo_img
            ).convert("RGBA")
        )
        effective_scale = (
            settings.effective_landscape_scale() if orientation == "landscape"
            else settings.effective_portrait_scale()
        )
        logo_size = calculate_logo_size(
            base_image.width, logo_rgba, effective_scale
        )
        resized_logo = logo_rgba.resize(logo_size, Image.Resampling.BILINEAR)
        if settings.opacity < 1.0:
            opacity_val = max(0.0, min(1.0, settings.opacity))
            r, g, b, a = resized_logo.split()
            a = a.point(lambda x: int(x * opacity_val))
            resized_logo = Image.merge("RGBA", (r, g, b, a))
        position = calculate_position(
            base_image.size, resized_logo.size, preset,
            settings.offset_x, settings.offset_y, settings.margin,
        )
        overlay.alpha_composite(resized_logo, dest=position)

    base_image.alpha_composite(overlay)
    return base_image


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
    effective_scale = (
        settings.effective_landscape_scale()
        if orientation == "landscape"
        else settings.effective_portrait_scale()
    )
    logo_size = calculate_logo_size(
        base_image.width,
        logo_rgba,
        effective_scale,
    )
    resized_logo = logo_rgba.resize(logo_size, Image.Resampling.BILINEAR)
    # Apply opacity by scaling the alpha channel
    if settings.opacity < 1.0:
        opacity_val = max(0.0, min(1.0, settings.opacity))
        r, g, b, a = resized_logo.split()
        a = a.point(lambda x: int(x * opacity_val))
        resized_logo = Image.merge("RGBA", (r, g, b, a))
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
