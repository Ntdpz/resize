from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path

import customtkinter as ctk  # type: ignore[import-untyped]
from PIL import Image, ImageTk  # type: ignore[import-untyped]
try:
    from tkinterdnd2 import TkinterDnD  # type: ignore[import-untyped]
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False

from core.models import (
    OUTPUT_SIZE_RESIZE_1280,
    PlacementSettings,
)
from ui._mixins._constants import (
    TARGET_WIDTH,
    POSITION_THAI,
    THAI_TO_POSITION,
)
from ui._mixins import (
    BuildMixin,
    TemplateMixin,
    LogoMixin,
    InputMixin,
    FilmstripMixin,
    CanvasMixin,
    SettingsMixin,
    ProcessingMixin,
)

AppEvent = tuple[str, object]


if _DND_AVAILABLE:
    class _DndBase(ctk.CTk, TkinterDnD.DnDWrapper):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self.TkdndVersion = TkinterDnD._require(self)
else:
    class _DndBase(ctk.CTk):  # type: ignore[misc]
        pass


class AutoWatermarkWindow(
    BuildMixin,
    TemplateMixin,
    LogoMixin,
    InputMixin,
    FilmstripMixin,
    CanvasMixin,
    SettingsMixin,
    ProcessingMixin,
    _DndBase,
):
    """Main window — left controls, right canvas preview + filmstrip."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Auto Watermark & Resize")
        self.geometry("1020x700")
        self.minsize(820, 560)

        # ── App state ──────────────────────────────────────────────────
        self.image_paths: list[Path] = []
        self.selected_preview_path: Path | None = None
        self.last_output_folder: Path | None = None

        # ── Multi-logo state ───────────────────────────────────────────
        self._logo_paths: list[Path] = []
        self._logo_pils: list[Image.Image | None] = []   # RGBA PIL images
        self._logo_ctks: list[ctk.CTkImage | None] = []  # thumbnail CTkImage
        self._selected_logo_idx: int = 0
        # Per-logo global settings (parallels _logo_paths)
        self._logo_landscape_scales: list[int] = []
        self._logo_portrait_scales: list[int] = []
        self._logo_positions: list[str] = []   # Thai display string
        self._logo_opacities: list[float] = []
        self._logo_offset_x: list[int] = []    # horizontal queue offset (px)
        # template drag defaults per orientation: [{"landscape": (rx,ry)|None, "portrait": ...}]
        self._logo_default_pos_ratios: list[dict] = []
        self._logo_list_rows: list[ctk.CTkFrame] = []  # UI row frames

        # ── Threading ──────────────────────────────────────────────────
        self._worker: threading.Thread | None = None
        self._events: queue.Queue[AppEvent] = queue.Queue()
        self._preview_debounce_id: str | None = None

        # ── Image caches ───────────────────────────────────────────────
        self._preview_base_photo: ImageTk.PhotoImage | None = None
        self._preview_logo_photos: list[ImageTk.PhotoImage | None] = []
        self._thumb_pil_cache: dict[Path, Image.Image] = {}
        self._thumb_photos: dict[Path, ImageTk.PhotoImage] = {}
        self._thumb_labels: dict[Path, tk.Label] = {}
        self._thumb_containers: dict[Path, tk.Frame] = {}

        # ── Drag / free-position state ─────────────────────────────────
        self._canvas_logo_ids: dict[int, int] = {}   # logo_idx → canvas item id
        self._canvas_handle_id: int | None = None    # resize handle circle
        self._canvas_selection_id: int | None = None # dashed border
        self._drag_logo_idx: int = 0                 # which logo is being dragged
        # Per-image per-logo drag ratios: path → logo_idx → (rx, ry)
        self._per_image_pos_ratios: dict[Path, dict[int, tuple[float, float]]] = {}
        self._drag_start_evt: tuple[int, int] | None = None
        self._drag_start_logo_canvas: tuple[float, float] | None = None
        self._prev_scale: float = 1.0
        self._prev_img_offset: tuple[int, int] = (0, 0)
        self._prev_base_size: tuple[int, int] = (TARGET_WIDTH, 720)
        self._prev_logo_size_canvas: tuple[int, int] = (0, 0)
        # Resize-handle drag state
        self._resize_dragging: bool = False
        self._resize_start_evt: tuple[int, int] | None = None
        self._resize_start_scale: int = 18
        self._resize_start_logo_w_canvas: int = 0

        # ── UI variables ───────────────────────────────────────────────
        self.position_thai_var = ctk.StringVar(value=POSITION_THAI["top-right"])
        self.output_size_var = ctk.StringVar(value=OUTPUT_SIZE_RESIZE_1280)
        self.logo_scale_var = ctk.IntVar(value=18)          # landscape scale
        self.scale_display_var = ctk.StringVar(value="18%")
        self.logo_scale_portrait_var = ctk.IntVar(value=18)  # portrait scale
        self.scale_portrait_display_var = ctk.StringVar(value="18%")
        self.opacity_var = ctk.DoubleVar(value=100.0)        # 0–100 %
        self.opacity_display_var = ctk.StringVar(value="100%")
        self.progress_var = ctk.DoubleVar(value=0.0)
        self.status_var = ctk.StringVar(value="")

        # ── Per-image override state ───────────────────────────────────
        # [Path][logo_idx] = PlacementSettings override for that logo on that image
        self._per_image_overrides: dict[Path, dict[int, PlacementSettings]] = {}
        # True global scale / position defaults (used when no per-logo settings exist)
        self._global_landscape_scale: int = 18
        self._global_portrait_scale: int = 18
        # Monotonic counter — incremented on each render request to cancel stale ones
        self._preview_token: int = 0

        self._build_ui()
        self._refresh_template_buttons()
        self.after(100, self._poll_events)

