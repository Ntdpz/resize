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
    logo_scale_percent: int = 18
    quality: int = 95


@dataclass(frozen=True)
class BatchRequest:
    logo_path: Path
    settings: PlacementSettings
    source_folder: Path | None = None
    source_paths: tuple[Path, ...] = ()
    output_folder: Path | None = None
    settings_by_path: dict[Path, PlacementSettings] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class ProcessedFile:
    source_path: Path
    output_path: Path
    width: int
    height: int
