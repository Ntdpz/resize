from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
LANDSCAPE_DEFAULT = "bottom-right"
PORTRAIT_DEFAULT = "top-right"
OUTPUT_SIZE_RESIZE_1280 = "Resize 1280px"
OUTPUT_SIZE_ORIGINAL = "Original Size"
POSITION_PRESETS = (
    "top-left",
    "top-center",
    "top-right",
    "middle-left",
    "center",
    "middle-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
)


@dataclass(frozen=True)
class PlacementSettings:
    landscape_position: str = LANDSCAPE_DEFAULT
    portrait_position: str = PORTRAIT_DEFAULT
    output_size_mode: str = OUTPUT_SIZE_RESIZE_1280
    offset_x: int = 0
    offset_y: int = 0
    margin: int = 50
    logo_scale_percent: int = 18          # kept for backward-compat / fallback
    landscape_logo_scale_percent: int = 0  # 0 = use logo_scale_percent
    portrait_logo_scale_percent: int = 0   # 0 = use logo_scale_percent
    quality: int = 95
    opacity: float = 1.0                   # 0.0 (transparent) – 1.0 (opaque)

    def effective_landscape_scale(self) -> int:
        return self.landscape_logo_scale_percent or self.logo_scale_percent

    def effective_portrait_scale(self) -> int:
        return self.portrait_logo_scale_percent or self.logo_scale_percent


@dataclass(frozen=True)
class LogoConfig:
    """One logo entry: its source file plus placement/style settings."""
    logo_path: Path
    settings: PlacementSettings


@dataclass(frozen=True)
class BatchRequest:
    logos: tuple[LogoConfig, ...]          # one or more logos (replaces logo_path)
    settings: PlacementSettings            # image-level defaults (output_size, quality)
    source_folder: Path | None = None
    source_paths: tuple[Path, ...] = ()
    output_folder: Path | None = None
    # [image_path][logo_idx] = per-image per-logo override (position/scale/opacity)
    logo_settings_by_path: dict[Path, dict[int, PlacementSettings]] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class ProcessedFile:
    source_path: Path
    output_path: Path
    width: int
    height: int
