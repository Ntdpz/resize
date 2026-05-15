from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk  # type: ignore[import-untyped]
from PIL import Image, ImageOps, ImageTk  # type: ignore[import-untyped]
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES  # type: ignore[import-untyped]
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False

from core.image_ops import calculate_position
from core.models import (
    BatchRequest,
    LogoConfig,
    OUTPUT_SIZE_RESIZE_1280,
    OUTPUT_SIZE_ORIGINAL,
    PlacementSettings,
    SUPPORTED_EXTENSIONS,
)
from core.processor import process_batch
from core import template_store

# ── Constants ──────────────────────────────────────────────────────────
TEAL = "#00c896"
TEAL_DARK = "#00a87a"
THUMB_SIZE = (90, 90)
PREVIEW_DEBOUNCE_MS = 350
TARGET_WIDTH = 1280

AppEvent = tuple[str, object]

POSITION_THAI: dict[str, str] = {
    "top-left":      "มุมซ้ายบน",
    "top-center":    "กลางบน",
    "top-right":     "มุมขวาบน",
    "middle-left":   "กลางซ้าย",
    "center":        "ตรงกลาง",
    "middle-right":  "กลางขวา",
    "bottom-left":   "มุมซ้ายล่าง",
    "bottom-center": "กลางล่าง",
    "bottom-right":  "มุมขวาล่าง",
}
THAI_TO_POSITION: dict[str, str] = {v: k for k, v in POSITION_THAI.items()}

# Gap (px at 1280-wide reference) between logos in the auto-arrange queue
_QUEUE_GAP: int = 8


if _DND_AVAILABLE:
    class _DndBase(ctk.CTk, TkinterDnD.DnDWrapper):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self.TkdndVersion = TkinterDnD._require(self)
else:
    class _DndBase(ctk.CTk):  # type: ignore[misc]
        pass


class AutoWatermarkWindow(_DndBase):
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

        self._build_ui()
        self._refresh_template_buttons()
        self.after(100, self._poll_events)

    # ═══════════════════════════════════════════════════════════════════
    # BUILD UI
    # ═══════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        is_dark = ctk.get_appearance_mode().lower() == "dark"
        sash_bg = "#1a1a2a" if is_dark else "#b0b0b0"
        self._paned = tk.PanedWindow(
            self,
            orient=tk.HORIZONTAL,
            sashwidth=6,
            sashrelief="flat",
            sashcursor="sb_h_double_arrow",
            bg=sash_bg,
        )
        self._paned.grid(row=0, column=0, sticky="nsew")

        self._build_left_panel()
        self._build_right_panel()
        self._update_step_indicators()

    # ── Left panel ─────────────────────────────────────────────────────

    def _build_left_panel(self) -> None:
        outer = ctk.CTkFrame(self._paned, width=280, corner_radius=0)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(0, weight=1)
        self._paned.add(outer, minsize=180, width=280)

        panel = ctk.CTkScrollableFrame(outer, corner_radius=0, fg_color="transparent")
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)

        brand = ctk.CTkFrame(panel, fg_color="transparent")
        brand.grid(row=0, column=0, padx=16, pady=(20, 14), sticky="ew")
        ctk.CTkLabel(
            brand, text="Auto Watermark",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand, text="Resize · Watermark · Export",
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray55"),
        ).pack(anchor="w")

        self._build_template_zone(panel, row=1)
        self._build_logo_zone(panel, row=2)
        self._build_input_zone(panel, row=3)
        ctk.CTkFrame(panel, height=1, fg_color=("gray70", "gray35")).grid(
            row=4, column=0, padx=16, pady=(0, 4), sticky="ew")
        self._build_settings(panel, row=5)
        self._build_per_image_actions(panel, row=6)
        self._build_progress_section(panel, row=7)
        self._build_footer(panel, row=8)

    def _build_template_zone(self, parent: ctk.CTkFrame, row: int) -> None:
        card = ctk.CTkFrame(parent, corner_radius=12)
        card.grid(row=row, column=0, padx=12, pady=(0, 8), sticky="ew")
        card.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=14, pady=(10, 4), sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            hdr, text="💾  Templates",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self._template_list_frame = ctk.CTkFrame(card, fg_color="transparent")
        self._template_list_frame.grid(row=1, column=0, padx=8, pady=(0, 4), sticky="ew")
        self._template_list_frame.grid_columnconfigure(0, weight=1)

        self._template_empty_label = ctk.CTkLabel(
            self._template_list_frame,
            text="ยังไม่มี template  กดบันทึกเพื่อสร้าง",
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray55"),
        )
        self._template_empty_label.grid(row=0, column=0, pady=4, sticky="ew")

        ctk.CTkButton(
            card, text="💾  บันทึก template ปัจจุบัน",
            height=32, font=ctk.CTkFont(size=12),
            fg_color=("gray78", "gray32"),
            text_color=("gray10", "gray90"),
            hover_color=("gray68", "gray42"),
            command=self._save_template,
        ).grid(row=2, column=0, padx=14, pady=(0, 10), sticky="ew")

    def _build_logo_zone(self, parent: ctk.CTkFrame, row: int) -> None:
        card = ctk.CTkFrame(parent, corner_radius=12)
        card.grid(row=row, column=0, padx=12, pady=(0, 8), sticky="ew")
        card.grid_columnconfigure(0, weight=1)

        # ── Header ────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=14, pady=(12, 6), sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            hdr, text="🎨  โลโก้",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        self.step1_badge = ctk.CTkLabel(
            hdr, text="STEP 1",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("gray75", "gray30"), text_color=("gray50", "gray55"),
            corner_radius=4,
        )
        self.step1_badge.grid(row=0, column=1)

        # ── Scrollable logo list ──────────────────────────────────────
        self.logo_list_frame = ctk.CTkFrame(card, fg_color="transparent")
        self.logo_list_frame.grid(row=1, column=0, padx=8, pady=(0, 4), sticky="ew")
        self.logo_list_frame.grid_columnconfigure(0, weight=1)

        # Placeholder shown when no logos added
        self._logo_empty_label = ctk.CTkLabel(
            self.logo_list_frame,
            text="ยังไม่มีโลโก้  กดปุ่มด้านล่างเพื่อเพิ่ม",
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray55"),
        )
        self._logo_empty_label.grid(row=0, column=0, pady=(4, 4), sticky="ew")

        # ── Add button ────────────────────────────────────────────────
        ctk.CTkButton(
            card, text="+  เพิ่มโลโก้",
            height=34, font=ctk.CTkFont(size=13),
            fg_color=TEAL, hover_color=TEAL_DARK,
            command=self._add_logo,
        ).grid(row=2, column=0, padx=14, pady=(0, 12), sticky="ew")

    def _build_input_zone(self, parent: ctk.CTkFrame, row: int) -> None:
        card = ctk.CTkFrame(parent, corner_radius=12)
        card.grid(row=row, column=0, padx=12, pady=(0, 8), sticky="ew")
        card.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, padx=14, pady=(12, 6), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text="📁  รูปภาพต้นฉบับ",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        self.image_count_badge = ctk.CTkLabel(
            header, text="",
            font=ctk.CTkFont(size=12),
            fg_color=TEAL, text_color="white", corner_radius=8,
        )
        self.step2_badge = ctk.CTkLabel(
            header, text="STEP 2",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("gray75", "gray30"), text_color=("gray50", "gray55"),
            corner_radius=4,
        )
        self.step2_badge.grid(row=0, column=2, padx=(4, 0))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.grid(row=1, column=0, padx=14, pady=(0, 6), sticky="ew")
        btn_row.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(
            btn_row, text="เลือกหลายไฟล์",
            height=36, font=ctk.CTkFont(size=13),
            command=self._choose_files,
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(
            btn_row, text="เลือกโฟลเดอร์",
            height=36, font=ctk.CTkFont(size=13),
            command=self._choose_folder,
        ).grid(row=0, column=1, padx=(4, 0), sticky="ew")

        # ── Drop zone ──────────────────────────────────────────────────
        self._drop_zone = tk.Frame(
            card,
            height=52,
            relief="flat",
            highlightthickness=2,
            highlightbackground="#4a4a6a",
            bg="#1e1e2e",
            cursor="hand2",
        )
        self._drop_zone.grid(row=2, column=0, padx=14, pady=(0, 6), sticky="ew")
        self._drop_zone.grid_propagate(False)
        self._drop_zone_label = tk.Label(
            self._drop_zone,
            text="⬇  ลากไฟล์หรือโฟลเดอร์มาวางที่นี่",
            bg="#1e1e2e",
            fg="#8888bb",
            font=("Segoe UI", 11),
        )
        self._drop_zone_label.place(relx=0.5, rely=0.5, anchor="center")
        if _DND_AVAILABLE:
            for w in (self._drop_zone, self._drop_zone_label):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_dnd_drop)
                w.dnd_bind("<<DragEnter>>", self._on_dnd_enter)
                w.dnd_bind("<<DragLeave>>", self._on_dnd_leave)
        else:
            self._drop_zone_label.configure(
                text="⬇  ลากไฟล์ (ต้องการ tkinterdnd2)",
                fg="#666688",
            )

        self.clear_button = ctk.CTkButton(
            card, text="🗑  ล้างรายการทั้งหมด",
            height=30, font=ctk.CTkFont(size=12),
            fg_color="transparent",
            text_color=("gray40", "gray60"),
            hover_color=("gray80", "gray28"),
            border_width=1,
            border_color=("gray70", "gray40"),
            command=self._clear_images,
        )
        self.clear_button.grid(row=3, column=0, padx=14, pady=(0, 6), sticky="ew")
        self.clear_button.grid_remove()

        self.input_status_label = ctk.CTkLabel(
            card, text="ยังไม่ได้เลือกรูปภาพ",
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray55"),
        )
        self.input_status_label.grid(row=4, column=0, padx=14, pady=(0, 10), sticky="w")

    def _build_settings(self, parent: ctk.CTkFrame, row: int) -> None:
        self.settings_card = ctk.CTkFrame(parent, corner_radius=12)
        self.settings_card.grid(row=row, column=0, padx=12, pady=(0, 8), sticky="ew")
        self.settings_card.grid_columnconfigure(0, weight=1)

        settings_hdr = ctk.CTkFrame(self.settings_card, fg_color="transparent")
        settings_hdr.grid(row=0, column=0, padx=14, pady=(12, 8), sticky="ew")
        settings_hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            settings_hdr, text="⚙  ตั้งค่าโลโก้",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        self.step3_badge = ctk.CTkLabel(
            settings_hdr, text="STEP 3",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("gray75", "gray30"), text_color=("gray50", "gray55"),
            corner_radius=4,
        )
        self.step3_badge.grid(row=0, column=1)

        ctk.CTkLabel(
            self.settings_card, text="ตำแหน่ง", font=ctk.CTkFont(size=13),
        ).grid(row=1, column=0, padx=14, pady=(0, 4), sticky="w")

        self._position_option = ctk.CTkOptionMenu(
            self.settings_card,
            values=list(POSITION_THAI.values()),
            variable=self.position_thai_var,
            command=self._on_position_changed,
        )
        self._position_option.grid(row=2, column=0, padx=14, pady=(0, 6), sticky="ew")

        self.custom_pos_label = ctk.CTkLabel(
            self.settings_card,
            text="📍 กำหนดเอง  (ลากโลโก้บน preview)",
            font=ctk.CTkFont(size=12), text_color=TEAL,
        )
        self.custom_pos_label.grid(row=3, column=0, padx=14, pady=(0, 2), sticky="w")
        self.custom_pos_label.grid_remove()

        self.reset_pos_button = ctk.CTkButton(
            self.settings_card, text="รีเซ็ตตำแหน่ง",
            height=28, font=ctk.CTkFont(size=12),
            fg_color=("gray78", "gray32"),
            text_color=("gray10", "gray90"),
            hover_color=("gray68", "gray42"),
            command=self._reset_logo_position,
        )
        self.reset_pos_button.grid(row=4, column=0, padx=14, pady=(0, 6), sticky="ew")
        self.reset_pos_button.grid_remove()

        # ── Scale: Landscape ───────────────────────────────────────────
        scale_h_l = ctk.CTkFrame(self.settings_card, fg_color="transparent")
        scale_h_l.grid(row=5, column=0, padx=14, pady=(4, 2), sticky="ew")
        scale_h_l.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            scale_h_l, text="ขนาดโลโก้  🖼 แนวนอน", font=ctk.CTkFont(size=13),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            scale_h_l, textvariable=self.scale_display_var,
            font=ctk.CTkFont(size=13), text_color=TEAL,
        ).grid(row=0, column=1, sticky="e")

        self._scale_landscape_slider = ctk.CTkSlider(
            self.settings_card,
            from_=5, to=60,
            variable=self.logo_scale_var,
            button_color=TEAL, button_hover_color=TEAL_DARK, progress_color=TEAL,
            command=self._on_scale_changed,
        )
        self._scale_landscape_slider.grid(row=6, column=0, padx=14, pady=(0, 6), sticky="ew")

        # ── Scale: Portrait ────────────────────────────────────────────
        scale_h_p = ctk.CTkFrame(self.settings_card, fg_color="transparent")
        scale_h_p.grid(row=7, column=0, padx=14, pady=(2, 2), sticky="ew")
        scale_h_p.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            scale_h_p, text="ขนาดโลโก้  📱 แนวตั้ง", font=ctk.CTkFont(size=13),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            scale_h_p, textvariable=self.scale_portrait_display_var,
            font=ctk.CTkFont(size=13), text_color=TEAL,
        ).grid(row=0, column=1, sticky="e")

        self._scale_portrait_slider = ctk.CTkSlider(
            self.settings_card,
            from_=5, to=60,
            variable=self.logo_scale_portrait_var,
            button_color=TEAL, button_hover_color=TEAL_DARK, progress_color=TEAL,
            command=self._on_scale_portrait_changed,
        )
        self._scale_portrait_slider.grid(row=8, column=0, padx=14, pady=(0, 8), sticky="ew")

        # ── Opacity ────────────────────────────────────────────────────
        opacity_hdr = ctk.CTkFrame(self.settings_card, fg_color="transparent")
        opacity_hdr.grid(row=9, column=0, padx=14, pady=(4, 2), sticky="ew")
        opacity_hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            opacity_hdr, text="ความทึบ (Opacity)", font=ctk.CTkFont(size=13),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            opacity_hdr, textvariable=self.opacity_display_var,
            font=ctk.CTkFont(size=13), text_color=TEAL,
        ).grid(row=0, column=1, sticky="e")

        self._opacity_slider = ctk.CTkSlider(
            self.settings_card,
            from_=0, to=100,
            variable=self.opacity_var,
            button_color=TEAL, button_hover_color=TEAL_DARK, progress_color=TEAL,
            command=self._on_opacity_changed,
        )
        self._opacity_slider.grid(row=10, column=0, padx=14, pady=(0, 8), sticky="ew")

        ctk.CTkLabel(
            self.settings_card, text="ขนาดเอาต์พุต", font=ctk.CTkFont(size=13),
        ).grid(row=11, column=0, padx=14, pady=(8, 4), sticky="w")

        self._output_size_segmented = ctk.CTkSegmentedButton(
            self.settings_card,
            values=[OUTPUT_SIZE_RESIZE_1280, OUTPUT_SIZE_ORIGINAL],
            variable=self.output_size_var,
            selected_color=TEAL,
            selected_hover_color=TEAL_DARK,
            font=ctk.CTkFont(size=11),
            command=self._on_output_size_changed,
        )
        self._output_size_segmented.grid(row=12, column=0, padx=14, pady=(0, 8), sticky="ew")

        ctk.CTkLabel(
            self.settings_card,
            text="💡 ลากโลโก้บน preview · Scroll ปรับขนาด",
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray55"),
        ).grid(row=13, column=0, padx=14, pady=(0, 12), sticky="w")

        self._settings_interactive_widgets = [
            self._position_option,
            self._scale_landscape_slider,
            self._scale_portrait_slider,
            self._opacity_slider,
            self._output_size_segmented,
        ]

    def _build_per_image_actions(self, parent: ctk.CTkFrame, row: int) -> None:
        card = ctk.CTkFrame(parent, corner_radius=12)
        card.grid(row=row, column=0, padx=12, pady=(0, 8), sticky="ew")
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text="⚠  การตั้งค่าข้างต้นใช้กับรูปนี้เท่านั้น",
            font=ctk.CTkFont(size=11),
            text_color=("gray45", "gray58"),
            wraplength=220, justify="left",
        ).grid(row=0, column=0, padx=14, pady=(10, 4), sticky="w")

        ctk.CTkButton(
            card,
            text="�  นำค่านี้ → รูปแนวนอนทั้งหมด",
            height=32, font=ctk.CTkFont(size=12),
            fg_color=("gray78", "gray32"),
            text_color=("gray10", "gray90"),
            hover_color=("gray68", "gray42"),
            command=self._apply_to_landscape,
        ).grid(row=1, column=0, padx=14, pady=(0, 4), sticky="ew")

        ctk.CTkButton(
            card,
            text="📱  นำค่านี้ → รูปแนวตั้งทั้งหมด",
            height=32, font=ctk.CTkFont(size=12),
            fg_color=("gray78", "gray32"),
            text_color=("gray10", "gray90"),
            hover_color=("gray68", "gray42"),
            command=self._apply_to_portrait,
        ).grid(row=2, column=0, padx=14, pady=(0, 4), sticky="ew")

        ctk.CTkButton(
            card,
            text="🔄  รีเซ็ตทุกรูปเป็นค่าเริ่มต้น",
            height=32, font=ctk.CTkFont(size=12),
            fg_color="transparent",
            text_color=("gray40", "gray60"),
            hover_color=("gray80", "gray28"),
            border_width=1,
            border_color=("gray70", "gray40"),
            command=self._reset_all_overrides,
        ).grid(row=3, column=0, padx=14, pady=(0, 10), sticky="ew")

    def _build_progress_section(self, parent: ctk.CTkFrame, row: int) -> None:
        self.progress_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.progress_frame.grid(row=row, column=0, padx=12, pady=(0, 4), sticky="ew")
        self.progress_frame.grid_columnconfigure(0, weight=1)
        self.progress_frame.grid_remove()

        ctk.CTkLabel(
            self.progress_frame, textvariable=self.status_var,
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray55"),
        ).grid(row=0, column=0, pady=(0, 4), sticky="w")

        self.progress_bar = ctk.CTkProgressBar(
            self.progress_frame, variable=self.progress_var, progress_color=TEAL)
        self.progress_bar.grid(row=1, column=0, sticky="ew")
        self.progress_bar.set(0)

    def _build_footer(self, parent: ctk.CTkFrame, row: int) -> None:
        footer = ctk.CTkFrame(parent, fg_color="transparent")
        footer.grid(row=row, column=0, padx=12, pady=(4, 18), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)

        self.start_button = ctk.CTkButton(
            footer,
            text="▶  START เริ่มประมวลผล",
            height=54, font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=TEAL, hover_color=TEAL_DARK,
            command=self._start_processing,
            state="disabled",
        )
        self.start_button.grid(row=0, column=0, sticky="ew")

        self.open_folder_button = ctk.CTkButton(
            footer, text="📂  เปิดโฟลเดอร์ผลลัพธ์",
            height=38, font=ctk.CTkFont(size=13),
            command=self._open_output_folder,
        )

    # ── Right panel ────────────────────────────────────────────────────

    def _build_right_panel(self) -> None:
        right = ctk.CTkFrame(self._paned, corner_radius=0, fg_color=("gray90", "gray13"))
        right.grid_columnconfigure(0, weight=1)
        self._paned.add(right, minsize=400)
        right.grid_rowconfigure(0, weight=1)
        right.grid_rowconfigure(1, minsize=118)

        # Preview canvas (2 layers: base + draggable logo)
        self.preview_outer = ctk.CTkFrame(
            right, corner_radius=0, fg_color=("gray85", "gray11"))
        self.preview_outer.grid(row=0, column=0, sticky="nsew")
        self.preview_outer.grid_columnconfigure(0, weight=1)
        self.preview_outer.grid_rowconfigure(0, weight=1)

        is_dark = ctk.get_appearance_mode().lower() == "dark"
        canvas_bg = "#111111" if is_dark else "#d8d8d8"

        self.preview_canvas = tk.Canvas(
            self.preview_outer,
            bg=canvas_bg,
            highlightthickness=0,
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", self._on_preview_resize)
        self.preview_canvas.bind("<MouseWheel>", self._on_canvas_scroll)

        # Filmstrip
        film_outer = ctk.CTkFrame(
            right, height=118, corner_radius=0,
            fg_color=("gray75", "gray18"))
        film_outer.grid(row=1, column=0, sticky="nsew")
        film_outer.grid_propagate(False)
        film_outer.grid_columnconfigure(0, weight=1)
        film_outer.grid_rowconfigure(0, weight=1)

        film_bg = "#282828" if is_dark else "#c0c0c0"
        self.filmstrip_canvas = tk.Canvas(
            film_outer, height=96, bg=film_bg, highlightthickness=0)
        self.filmstrip_canvas.grid(row=0, column=0, sticky="ew", pady=(4, 0))

        film_scroll = tk.Scrollbar(
            film_outer, orient="horizontal",
            command=self.filmstrip_canvas.xview)
        film_scroll.grid(row=1, column=0, sticky="ew")
        self.filmstrip_canvas.configure(xscrollcommand=film_scroll.set)

        self.filmstrip_inner = tk.Frame(self.filmstrip_canvas, bg=film_bg)
        self._canvas_window = self.filmstrip_canvas.create_window(
            (0, 0), window=self.filmstrip_inner, anchor="nw")
        self.filmstrip_inner.bind(
            "<Configure>",
            lambda e: self.filmstrip_canvas.configure(
                scrollregion=self.filmstrip_canvas.bbox("all")))
        self.filmstrip_canvas.bind("<MouseWheel>", self._filmstrip_scroll)

    # ═══════════════════════════════════════════════════════════════════
    # PLACEHOLDER
    # ═══════════════════════════════════════════════════════════════════

    def _draw_placeholder(self) -> None:
        self.preview_canvas.delete("all")
        w = max(self.preview_canvas.winfo_width(), 10)
        h = max(self.preview_canvas.winfo_height(), 10)
        self.preview_canvas.create_text(
            w // 2, h // 2,
            text="เลือกโลโก้และรูปภาพ\nจากนั้นคลิก thumbnail ด้านล่างเพื่อดู preview",
            fill="#606060", font=("Helvetica", 13), justify="center",
        )

    # ═══════════════════════════════════════════════════════════════════
    # TEMPLATE MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════

    def _refresh_template_buttons(self) -> None:
        """Rebuild the template button list from disk."""
        for w in self._template_list_frame.winfo_children():
            if w is not self._template_empty_label:
                w.destroy()

        templates = template_store.load_all()
        if not templates:
            self._template_empty_label.grid(row=0, column=0, pady=4, sticky="ew")
            return

        self._template_empty_label.grid_remove()
        for i, name in enumerate(templates.keys()):
            row_frame = ctk.CTkFrame(self._template_list_frame, fg_color="transparent")
            row_frame.grid(row=i, column=0, padx=0, pady=(0, 2), sticky="ew")
            row_frame.grid_columnconfigure(0, weight=1)

            ctk.CTkButton(
                row_frame, text=name,
                height=30, font=ctk.CTkFont(size=12),
                fg_color=(TEAL, TEAL_DARK),
                hover_color=(TEAL_DARK, "#007a5a"),
                anchor="w",
                command=lambda n=name: self._load_template(n),
            ).grid(row=0, column=0, padx=(0, 4), sticky="ew")

            ctk.CTkButton(
                row_frame, text="×", width=28, height=30,
                font=ctk.CTkFont(size=14, weight="bold"),
                fg_color="transparent",
                text_color=("gray40", "gray60"),
                hover_color=("gray70", "gray35"),
                command=lambda n=name: self._delete_template(n),
            ).grid(row=0, column=1)

    def _save_template(self) -> None:
        """Save current logo + settings configuration as a named template."""
        self._save_ui_to_logo_settings(self._selected_logo_idx)

        if not self._logo_paths:
            messagebox.showwarning("Template", "กรุณาเพิ่มโลโก้ก่อนบันทึก template")
            return

        dialog = ctk.CTkInputDialog(text="ใส่ชื่อ template:", title="บันทึก Template")
        name = dialog.get_input()
        if not name or not name.strip():
            return
        name = name.strip()

        logos = []
        for i, path in enumerate(self._logo_paths):
            drag_landscape: tuple[float, float] | None = None
            drag_portrait: tuple[float, float] | None = None
            for img_path in self.image_paths:
                ratio = self._per_image_pos_ratios.get(img_path, {}).get(i)
                if ratio is None:
                    continue
                orient = self._get_img_orientation(img_path)
                if orient == "landscape" and drag_landscape is None:
                    drag_landscape = ratio
                elif orient == "portrait" and drag_portrait is None:
                    drag_portrait = ratio
                if drag_landscape and drag_portrait:
                    break
            logos.append({
                "logo_path": str(path),
                "landscape_scale": self._logo_landscape_scales[i],
                "portrait_scale": self._logo_portrait_scales[i],
                "position": THAI_TO_POSITION.get(
                    self._logo_positions[i], "top-right"),
                "opacity": self._logo_opacities[i],
                "offset_x": self._logo_offset_x[i],
                "drag_x_landscape": drag_landscape[0] if drag_landscape else None,
                "drag_y_landscape": drag_landscape[1] if drag_landscape else None,
                "drag_x_portrait": drag_portrait[0] if drag_portrait else None,
                "drag_y_portrait": drag_portrait[1] if drag_portrait else None,
            })

        data = {
            "logos": logos,
            "output_size_mode": self.output_size_var.get(),
        }
        template_store.save_template(name, data)
        self._refresh_template_buttons()

    def _load_template(self, name: str) -> None:
        """Load a saved template: restore logos and their settings."""
        templates = template_store.load_all()
        data = templates.get(name)
        if not data:
            return

        # Clear all existing logos at once (avoids repeated preview rerenders)
        for row_widget in self._logo_list_rows:
            row_widget.destroy()
        self._logo_list_rows.clear()
        self._logo_paths.clear()
        self._logo_pils.clear()
        self._logo_ctks.clear()
        self._logo_landscape_scales.clear()
        self._logo_portrait_scales.clear()
        self._logo_positions.clear()
        self._logo_opacities.clear()
        self._logo_offset_x.clear()
        self._logo_default_pos_ratios.clear()
        self._per_image_overrides.clear()
        self._per_image_pos_ratios.clear()
        self._selected_logo_idx = 0
        self._logo_empty_label.grid(row=0, column=0, pady=(4, 4), sticky="ew")

        missing: list[str] = []
        for entry in data.get("logos", []):
            path = Path(entry["logo_path"])
            if not path.exists():
                missing.append(path.name)
                continue
            try:
                img = Image.open(path).convert("RGBA")
            except Exception:
                missing.append(path.name)
                continue

            idx = len(self._logo_paths)
            self._logo_paths.append(path)
            self._logo_pils.append(img)
            self._logo_ctks.append(None)
            self._logo_landscape_scales.append(int(entry.get("landscape_scale", 18)))
            self._logo_portrait_scales.append(int(entry.get("portrait_scale", 18)))
            pos_key = entry.get("position", "top-right")
            self._logo_positions.append(
                POSITION_THAI.get(pos_key, POSITION_THAI["top-right"]))
            self._logo_opacities.append(float(entry.get("opacity", 1.0)))
            self._logo_offset_x.append(int(entry.get("offset_x", 0)))
            dx_l = entry.get("drag_x_landscape") or entry.get("drag_x")
            dy_l = entry.get("drag_y_landscape") or entry.get("drag_y")
            dx_p = entry.get("drag_x_portrait") or entry.get("drag_x")
            dy_p = entry.get("drag_y_portrait") or entry.get("drag_y")
            self._logo_default_pos_ratios.append({
                "landscape": (float(dx_l), float(dy_l))
                    if dx_l is not None and dy_l is not None else None,
                "portrait": (float(dx_p), float(dy_p))
                    if dx_p is not None and dy_p is not None else None,
            })
            self._add_logo_row(idx)

        if self._logo_paths:
            self._logo_empty_label.grid_remove()
            self._select_logo(0)

        # Apply default drag ratios to images already loaded before this template
        if self.image_paths:
            self._apply_default_drag_ratios(self.image_paths)

        if "output_size_mode" in data:
            self.output_size_var.set(data["output_size_mode"])

        if missing:
            messagebox.showwarning(
                "Template",
                "ไม่พบไฟล์โลโก้ต่อไปนี้:\n" + "\n".join(missing),
            )

        self._update_start_button()
        self._schedule_preview()

    def _delete_template(self, name: str) -> None:
        """Delete a saved template after confirmation."""
        if not messagebox.askyesno(
            "ลบ Template", f"ต้องการลบ template '{name}' ใช่ไหม?"
        ):
            return
        template_store.delete_template(name)
        self._refresh_template_buttons()

    def _get_img_orientation(self, path: Path) -> str:
        """Return 'landscape' or 'portrait' for an image path."""
        cached = self._thumb_pil_cache.get(path)
        if cached:
            w, h = cached.size
            return "landscape" if w >= h else "portrait"
        try:
            with Image.open(path) as img:
                w, h = img.size
            return "landscape" if w >= h else "portrait"
        except Exception:
            return "landscape"

    def _apply_default_drag_ratios(self, img_paths: list[Path]) -> None:
        """Apply template drag ratios (per orientation) to given image paths."""
        if not any(
            r.get("landscape") is not None or r.get("portrait") is not None
            for r in self._logo_default_pos_ratios
        ):
            return
        for img_path in img_paths:
            orient = self._get_img_orientation(img_path)
            for logo_idx, ratios in enumerate(self._logo_default_pos_ratios):
                ratio = ratios.get(orient)
                if ratio is not None:
                    self._per_image_pos_ratios.setdefault(
                        img_path, {})[logo_idx] = ratio

    # ═══════════════════════════════════════════════════════════════════
    # LOGO MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════

    def _add_logo(self) -> None:
        paths_str = filedialog.askopenfilenames(
            title="เลือกไฟล์โลโก้ (เลือกได้หลายไฟล์)",
            filetypes=[("PNG files", "*.png"), ("All files", "*.*")],
        )
        if not paths_str:
            return
        for path_str in paths_str:
            path = Path(path_str)
            if path in self._logo_paths:
                continue  # skip duplicate
            try:
                img = Image.open(path).convert("RGBA")
            except Exception:
                continue
            idx = len(self._logo_paths)
            self._logo_paths.append(path)
            self._logo_pils.append(img)
            self._logo_ctks.append(None)
            self._logo_landscape_scales.append(18)
            self._logo_portrait_scales.append(18)
            self._logo_positions.append(POSITION_THAI["top-right"])
            self._logo_opacities.append(1.0)
            self._logo_offset_x.append(0)
            self._logo_default_pos_ratios.append({"landscape": None, "portrait": None})
            self._add_logo_row(idx)

        if self._logo_paths:
            self._logo_empty_label.grid_remove()
            self._select_logo(len(self._logo_paths) - 1)

        self._apply_auto_arrange()
        self._update_start_button()
        self._schedule_preview()

    def _add_logo_row(self, idx: int) -> None:
        """Build a UI row for the logo at index idx in logo_list_frame."""
        path = self._logo_paths[idx]
        logo_pil = self._logo_pils[idx]

        row = ctk.CTkFrame(
            self.logo_list_frame, corner_radius=8,
            fg_color=("gray82", "gray22"),
        )
        row.grid(row=idx, column=0, padx=0, pady=(0, 4), sticky="ew")
        row.grid_columnconfigure(1, weight=1)
        row.bind("<Button-1>", lambda e, i=idx: self._select_logo(i))

        # Thumbnail
        thumb_label = ctk.CTkLabel(
            row, text="🖼",
            font=ctk.CTkFont(size=16), width=36, height=36,
            corner_radius=6, fg_color=("gray75", "gray30"),
        )
        thumb_label.grid(row=0, column=0, padx=(8, 6), pady=6)
        thumb_label.bind("<Button-1>", lambda e, i=idx: self._select_logo(i))

        # Build ctk thumbnail from PIL image
        if logo_pil is not None:
            t = logo_pil.copy()
            t.thumbnail((36, 36), Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=t, dark_image=t, size=(36, 36))
            self._logo_ctks[idx] = ctk_img
            thumb_label.configure(image=ctk_img, text="")

        # Filename label
        name_label = ctk.CTkLabel(
            row, text=path.name,
            font=ctk.CTkFont(size=12),
            anchor="w", wraplength=130, justify="left",
        )
        name_label.grid(row=0, column=1, padx=(0, 4), pady=6, sticky="ew")
        name_label.bind("<Button-1>", lambda e, i=idx: self._select_logo(i))

        # Remove button
        remove_btn = ctk.CTkButton(
            row, text="×", width=28, height=28,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="transparent",
            text_color=("gray40", "gray60"),
            hover_color=("gray70", "gray35"),
            command=lambda i=idx: self._remove_logo(i),
        )
        remove_btn.grid(row=0, column=2, padx=(0, 6), pady=6)

        self._logo_list_rows.append(row)

    def _apply_auto_arrange(self) -> None:
        """Queue logos side-by-side in a horizontal row anchored at top-right.
        Logo 0 is rightmost; each subsequent logo extends the queue to the left.
        Acts as a default starting point — user can still drag/change position."""
        n = len(self._logo_paths)
        # Single logo: keep top-right with no offset
        if n == 1:
            self._logo_positions[0] = POSITION_THAI["top-right"]
            self._logo_offset_x[0] = 0
            if self._selected_logo_idx == 0:
                self.position_thai_var.set(self._logo_positions[0])
            return
        if n < 2:
            return
        # Multiple logos: all top-right, offset_x spreads them left from the right edge
        cumulative = 0
        for i in range(n):
            self._logo_positions[i] = POSITION_THAI["top-right"]
            self._logo_offset_x[i] = -cumulative
            est_w = max(1, round(1280 * self._logo_landscape_scales[i] / 100))
            cumulative += est_w + _QUEUE_GAP
        # Sync dropdown UI for the currently selected logo
        sel = self._selected_logo_idx
        if 0 <= sel < n:
            self.position_thai_var.set(self._logo_positions[sel])

    def _remove_logo(self, idx: int) -> None:
        if idx >= len(self._logo_paths):
            return

        # Destroy the UI row
        if idx < len(self._logo_list_rows):
            self._logo_list_rows[idx].destroy()
            self._logo_list_rows.pop(idx)

        # Remove from all lists
        self._logo_paths.pop(idx)
        self._logo_pils.pop(idx)
        self._logo_ctks.pop(idx)
        self._logo_landscape_scales.pop(idx)
        self._logo_portrait_scales.pop(idx)
        self._logo_positions.pop(idx)
        self._logo_opacities.pop(idx)
        self._logo_offset_x.pop(idx)
        if idx < len(self._logo_default_pos_ratios):
            self._logo_default_pos_ratios.pop(idx)

        # Re-grid remaining rows (their index shifted)
        for i, row in enumerate(self._logo_list_rows):
            row.grid(row=i, column=0, padx=0, pady=(0, 4), sticky="ew")

        # Clean per-image data for removed logo index
        for path_overrides in self._per_image_overrides.values():
            path_overrides.pop(idx, None)
        for path_ratios in self._per_image_pos_ratios.values():
            path_ratios.pop(idx, None)

        if not self._logo_paths:
            self._logo_empty_label.grid(row=0, column=0, pady=(4, 4), sticky="ew")
            self._selected_logo_idx = 0
        else:
            new_idx = min(idx, len(self._logo_paths) - 1)
            self._selected_logo_idx = new_idx
            self._highlight_logo_row(new_idx)
            self._load_logo_settings_into_ui(new_idx)

        self._update_start_button()
        self._apply_auto_arrange()
        self._schedule_preview()

    def _select_logo(self, idx: int) -> None:
        """Set the active logo for editing; sync settings panel."""
        if idx == self._selected_logo_idx and idx < len(self._logo_paths):
            return
        # Save current settings back to the previously selected logo
        self._save_ui_to_logo_settings(self._selected_logo_idx)
        self._selected_logo_idx = idx
        self._highlight_logo_row(idx)
        self._load_logo_settings_into_ui(idx)
        self._schedule_preview()

    def _highlight_logo_row(self, idx: int) -> None:
        for i, row in enumerate(self._logo_list_rows):
            if i == idx:
                row.configure(fg_color=(TEAL, "#005540"))
            else:
                row.configure(fg_color=("gray82", "gray22"))

    def _load_logo_settings_into_ui(self, idx: int) -> None:
        """Load logo[idx]'s global settings (or per-image override) into the settings panel."""
        if idx >= len(self._logo_paths):
            return
        # Check for per-image override first
        override: PlacementSettings | None = None
        if self.selected_preview_path is not None:
            override = self._per_image_overrides.get(
                self.selected_preview_path, {}).get(idx)

        if override is not None:
            l_scale = override.effective_landscape_scale()
            p_scale = override.effective_portrait_scale()
            pos_thai = POSITION_THAI.get(override.landscape_position, POSITION_THAI["top-right"])
            opacity_pct = override.opacity * 100
        else:
            l_scale = self._logo_landscape_scales[idx]
            p_scale = self._logo_portrait_scales[idx]
            pos_thai = self._logo_positions[idx]
            opacity_pct = self._logo_opacities[idx] * 100

        self.logo_scale_var.set(l_scale)
        self.scale_display_var.set(f"{l_scale}%")
        self.logo_scale_portrait_var.set(p_scale)
        self.scale_portrait_display_var.set(f"{p_scale}%")
        self.position_thai_var.set(pos_thai)
        self.opacity_var.set(opacity_pct)
        self.opacity_display_var.set(f"{int(opacity_pct)}%")

        # Drag position indicator
        has_drag = (
            self.selected_preview_path is not None
            and self._per_image_pos_ratios.get(
                self.selected_preview_path, {}).get(idx) is not None
        )
        if has_drag:
            self.custom_pos_label.grid(row=3, column=0, padx=14, pady=(0, 2), sticky="w")
            self.reset_pos_button.grid(row=4, column=0, padx=14, pady=(0, 6), sticky="ew")
        else:
            self.custom_pos_label.grid_remove()
            self.reset_pos_button.grid_remove()

    def _save_ui_to_logo_settings(self, idx: int) -> None:
        """Write current settings-panel state back to the global logo settings arrays."""
        if idx >= len(self._logo_paths):
            return
        self._logo_landscape_scales[idx] = self.logo_scale_var.get()
        self._logo_portrait_scales[idx] = self.logo_scale_portrait_var.get()
        self._logo_positions[idx] = self.position_thai_var.get()
        self._logo_opacities[idx] = self.opacity_var.get() / 100.0

    # ═══════════════════════════════════════════════════════════════════
    # INPUT — FILES / FOLDER
    # ═══════════════════════════════════════════════════════════════════

    # ── Drag-and-drop handlers ─────────────────────────────────────────
    def _on_dnd_enter(self, event: object) -> None:
        self._drop_zone.configure(highlightbackground=TEAL, bg="#1a2e2a")
        self._drop_zone_label.configure(fg=TEAL, bg="#1a2e2a")

    def _on_dnd_leave(self, event: object) -> None:
        self._drop_zone.configure(highlightbackground="#4a4a6a", bg="#1e1e2e")
        self._drop_zone_label.configure(fg="#8888bb", bg="#1e1e2e")

    def _on_dnd_drop(self, event: object) -> None:
        self._on_dnd_leave(event)
        raw: str = event.data  # type: ignore[attr-defined]
        paths = self._parse_dnd_data(raw)
        merged: list[Path] = []
        for p in paths:
            if p.is_dir():
                merged.extend(
                    sorted(
                        f for f in p.iterdir()
                        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
                    )
                )
            elif p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                merged.append(p)
        if merged:
            self._merge_paths(merged)

    @staticmethod
    def _parse_dnd_data(raw: str) -> list[Path]:
        """Parse tkinterdnd2 drop data — handles paths with spaces wrapped in {}."""
        paths: list[Path] = []
        raw = raw.strip()
        i = 0
        while i < len(raw):
            if raw[i] == "{":
                end = raw.find("}", i)
                if end == -1:
                    break
                paths.append(Path(raw[i + 1:end]))
                i = end + 2  # skip "} "
            else:
                # find next space that is not inside braces
                j = i
                while j < len(raw) and raw[j] != " ":
                    j += 1
                token = raw[i:j]
                if token:
                    paths.append(Path(token))
                i = j + 1
        return paths

    def _choose_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="เลือกรูปภาพ (Ctrl+click เลือกหลายไฟล์)",
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png"),
                ("All files", "*.*"),
            ],
        )
        if not paths:
            return
        self._merge_paths([Path(p) for p in paths])

    def _choose_folder(self) -> None:
        folder_str = filedialog.askdirectory(title="เลือกโฟลเดอร์รูปภาพ")
        if not folder_str:
            return
        folder = Path(folder_str)
        new_paths = sorted(
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        self._merge_paths(new_paths)

    def _merge_paths(self, new_paths: list[Path]) -> None:
        seen: set[Path] = {p.resolve() for p in self.image_paths}
        newly_added: list[Path] = []
        for p in new_paths:
            rp = p.resolve()
            if (rp not in seen
                    and rp.is_file()
                    and rp.suffix.lower() in SUPPORTED_EXTENSIONS):
                seen.add(rp)
                self.image_paths.append(p)
                newly_added.append(p)
        # Apply template default drag ratios to newly added images
        if newly_added:
            self._apply_default_drag_ratios(newly_added)
        self.image_paths.sort()
        n = len(self.image_paths)
        self.input_status_label.configure(text=f"เลือกแล้ว {n} รูป")
        self.image_count_badge.configure(text=f"  {n} รูป  ")
        self.image_count_badge.grid(row=0, column=1, padx=(8, 0), sticky="e")
        if n > 0:
            self.clear_button.grid()
        self._update_start_button()
        self._load_filmstrip()
        # Auto-preview the first image if no selection yet
        if self.image_paths and self.selected_preview_path is None:
            self.after(300, lambda: self._on_thumb_click(self.image_paths[0]))

    def _clear_images(self) -> None:
        self.image_paths.clear()
        self._thumb_pil_cache.clear()
        self._per_image_overrides.clear()
        self._per_image_pos_ratios.clear()
        self.selected_preview_path = None
        self.input_status_label.configure(text="ยังไม่ได้เลือกรูปภาพ")
        self.image_count_badge.grid_remove()
        self.clear_button.grid_remove()
        self._update_start_button()
        for w in self.filmstrip_inner.winfo_children():
            w.destroy()
        self._thumb_labels.clear()
        self._thumb_containers.clear()
        self._thumb_photos.clear()
        self.preview_canvas.delete("all")
        self._draw_placeholder()

    # ═══════════════════════════════════════════════════════════════════
    # FILMSTRIP
    # ═══════════════════════════════════════════════════════════════════

    def _load_filmstrip(self) -> None:
        for w in self.filmstrip_inner.winfo_children():
            w.destroy()
        self._thumb_labels.clear()
        self._thumb_containers.clear()
        self._thumb_photos.clear()

        paths = list(self.image_paths)
        if not paths:
            return

        bg = self.filmstrip_inner.cget("bg")
        for col, path in enumerate(paths):
            container = tk.Frame(
                self.filmstrip_inner, bg=bg,
                width=THUMB_SIZE[0] + 4, height=THUMB_SIZE[1] + 4)
            container.grid(row=0, column=col, padx=3, pady=3)
            container.grid_propagate(False)

            label = tk.Label(container, text="", bg=bg, cursor="hand2", relief="flat")
            label.place(x=2, y=2, width=THUMB_SIZE[0], height=THUMB_SIZE[1])
            label.bind("<Button-1>", lambda e, p=path: self._on_thumb_click(p))
            label.bind("<MouseWheel>", self._filmstrip_scroll)
            self._thumb_labels[path] = label
            self._thumb_containers[path] = container

        threading.Thread(
            target=self._load_thumbs_worker, args=(paths,), daemon=True).start()

    def _load_thumbs_worker(self, paths: list[Path]) -> None:
        for path in paths:
            if path in self._thumb_pil_cache:
                self._events.put(("thumb_ready", path))
                continue
            try:
                with Image.open(path) as img:
                    img = (ImageOps.exif_transpose(img) or img).convert("RGB")
                    w, h = img.size
                    s = min(w, h)
                    left, top = (w - s) // 2, (h - s) // 2
                    img = img.crop((left, top, left + s, top + s))
                    img = img.resize(THUMB_SIZE, Image.Resampling.LANCZOS)
                    self._thumb_pil_cache[path] = img
                self._events.put(("thumb_ready", path))
            except Exception:
                pass

    def _apply_thumb(self, path: Path) -> None:
        label = self._thumb_labels.get(path)
        pil = self._thumb_pil_cache.get(path)
        if label is None or pil is None:
            return
        photo = ImageTk.PhotoImage(pil)
        self._thumb_photos[path] = photo
        label.configure(image=photo, bg=self.filmstrip_inner.cget("bg"))

    def _on_thumb_click(self, path: Path) -> None:
        self.selected_preview_path = path
        self._load_settings_for_image(path)
        self._update_filmstrip_badges()
        self._render_preview(path)

    def _load_settings_for_image(self, path: Path) -> None:
        """Load this image's settings into UI controls when switching images."""
        self._load_logo_settings_into_ui(self._selected_logo_idx)

    def _filmstrip_scroll(self, event: tk.Event) -> None:
        self.filmstrip_canvas.xview_scroll(
            int(-1 * (event.delta / 120)), "units")

    # ═══════════════════════════════════════════════════════════════════
    # PREVIEW  (2-layer canvas: base + draggable logo)
    # ═══════════════════════════════════════════════════════════════════

    def _render_preview(self, path: Path) -> None:
        if not self._logo_pils:
            return
        cw = self.preview_canvas.winfo_width()
        ch = self.preview_canvas.winfo_height()
        if cw < 10 or ch < 10:
            self.after(150, lambda: self._render_preview(path))
            return

        try:
            with Image.open(path) as raw:
                raw = (ImageOps.exif_transpose(raw) or raw).convert("RGBA")

            if raw.width != TARGET_WIDTH:
                new_h = round(TARGET_WIDTH / raw.width * raw.height)
                base = raw.resize((TARGET_WIDTH, new_h), Image.Resampling.LANCZOS)
            else:
                base = raw.copy()
            base_w, base_h = base.size
            orientation = "landscape" if base_w > base_h else "portrait"

            preview_base = base.convert("RGB")
            preview_base.thumbnail((cw, ch), Image.Resampling.LANCZOS)
            pw, ph = preview_base.size
            scale = pw / base_w
            ox = (cw - pw) // 2
            oy = (ch - ph) // 2

            self._prev_scale = scale
            self._prev_img_offset = (ox, oy)
            self._prev_base_size = (base_w, base_h)

            self._preview_base_photo = ImageTk.PhotoImage(preview_base)
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(
                ox, oy, image=self._preview_base_photo, anchor="nw", tags="base")

            self._canvas_logo_ids.clear()
            self._preview_logo_photos = [None] * len(self._logo_pils)

            for idx, logo_pil in enumerate(self._logo_pils):
                if logo_pil is None:
                    continue

                # Resolve settings: per-image per-logo override → logo global
                img_overrides = self._per_image_overrides.get(path, {})
                override = img_overrides.get(idx)
                if override is not None:
                    active_scale = (
                        override.effective_landscape_scale()
                        if orientation == "landscape"
                        else override.effective_portrait_scale()
                    )
                    pos_key = (
                        override.landscape_position
                        if orientation == "landscape"
                        else override.portrait_position
                    )
                else:
                    active_scale = (
                        self._logo_landscape_scales[idx]
                        if orientation == "landscape"
                        else self._logo_portrait_scales[idx]
                    )
                    pos_key = THAI_TO_POSITION.get(
                        self._logo_positions[idx], "top-right")

                logo_opacity = self._logo_opacities[idx]

                logo_w = max(1, round(base_w * active_scale / 100))
                logo_h = max(1, round(logo_w * logo_pil.height / logo_pil.width))
                logo_resized = logo_pil.resize(
                    (logo_w, logo_h), Image.Resampling.LANCZOS)

                # Apply opacity
                if logo_opacity < 1.0:
                    r, g, b, a = logo_resized.split()
                    a = a.point(lambda x, op=logo_opacity: int(x * op))
                    logo_resized = Image.merge("RGBA", (r, g, b, a))

                # Resolve position: drag ratio → preset
                drag_ratio = self._per_image_pos_ratios.get(path, {}).get(idx)
                if drag_ratio is not None:
                    lx = max(0, min(round(drag_ratio[0] * base_w), base_w - logo_w))
                    ly = max(0, min(round(drag_ratio[1] * base_h), base_h - logo_h))
                else:
                    auto_ox = (
                        self._logo_offset_x[idx]
                        if idx < len(self._logo_offset_x) else 0
                    )
                    lx, ly = calculate_position(
                        base.size, (logo_w, logo_h), pos_key, auto_ox, 0, 0)

                clw = max(1, round(logo_w * scale))
                clh = max(1, round(logo_h * scale))
                canvas_logo = logo_resized.resize(
                    (clw, clh), Image.Resampling.LANCZOS)
                clx = ox + round(lx * scale)
                cly = oy + round(ly * scale)

                tag = f"logo_{idx}"
                photo = ImageTk.PhotoImage(canvas_logo)
                self._preview_logo_photos[idx] = photo
                canvas_id = self.preview_canvas.create_image(
                    clx, cly, image=photo, anchor="nw", tags=("logo", tag))
                self._canvas_logo_ids[idx] = canvas_id

                # Selection decoration only for the selected logo
                if idx == self._selected_logo_idx:
                    self._prev_logo_size_canvas = (clw, clh)
                    self._canvas_selection_id = self.preview_canvas.create_rectangle(
                        clx, cly, clx + clw, cly + clh,
                        outline=TEAL, width=2, dash=(6, 4), fill="",
                        tags="selection")
                    HR = 8
                    self._canvas_handle_id = self.preview_canvas.create_oval(
                        clx + clw - HR, cly + clh - HR,
                        clx + clw + HR, cly + clh + HR,
                        fill="white", outline=TEAL, width=2, tags="handle")

                # Per-logo drag/enter bindings
                self.preview_canvas.tag_bind(
                    tag, "<ButtonPress-1>",
                    lambda e, i=idx: self._on_logo_drag_start(e, i))
                self.preview_canvas.tag_bind(
                    tag, "<B1-Motion>", self._on_logo_drag_motion)
                self.preview_canvas.tag_bind(
                    tag, "<Enter>",
                    lambda e: self.preview_canvas.configure(cursor="fleur"))
                self.preview_canvas.tag_bind(
                    tag, "<Leave>",
                    lambda e: self.preview_canvas.configure(cursor=""))

            # Handle resize bindings (shared, affects selected logo)
            self.preview_canvas.tag_bind(
                "handle", "<ButtonPress-1>", self._on_handle_drag_start)
            self.preview_canvas.tag_bind(
                "handle", "<B1-Motion>", self._on_handle_drag_motion)
            self.preview_canvas.tag_bind(
                "handle", "<ButtonRelease-1>", self._on_handle_drag_end)
            self.preview_canvas.tag_bind(
                "handle", "<Enter>",
                lambda e: self.preview_canvas.configure(cursor="size_nw_se"))
            self.preview_canvas.tag_bind(
                "handle", "<Leave>",
                lambda e: self.preview_canvas.configure(cursor=""))

        except Exception as exc:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text=f"⚠️ ไม่สามารถแสดง preview ได้\n{exc}",
                fill="#e05555", font=("Helvetica", 12), justify="center",
            )

    def _schedule_preview(self) -> None:
        if self._preview_debounce_id:
            self.after_cancel(self._preview_debounce_id)
        self._preview_debounce_id = self.after(
            PREVIEW_DEBOUNCE_MS,
            lambda: (
                self._render_preview(self.selected_preview_path)
                if self.selected_preview_path else None
            ),
        )

    def _on_preview_resize(self, _event: tk.Event) -> None:
        if self.selected_preview_path:
            self._schedule_preview()
        else:
            self._draw_placeholder()

    # ═══════════════════════════════════════════════════════════════════
    # DRAG  — move logo freely on the canvas
    # ═══════════════════════════════════════════════════════════════════

    def _on_canvas_scroll(self, event: tk.Event) -> None:
        """Canvas-level scroll — resize logo only when cursor is over it."""
        items = self.preview_canvas.find_overlapping(
            event.x, event.y, event.x, event.y)
        for logo_idx, canvas_id in self._canvas_logo_ids.items():
            if canvas_id in items:
                if logo_idx != self._selected_logo_idx:
                    self._select_logo(logo_idx)
                self._on_logo_scroll(event)
                break

    def _on_logo_scroll(self, event: tk.Event) -> None:
        """Mouse wheel over logo → resize by ±1% per notch."""
        if not self._logo_paths:
            return
        idx = self._selected_logo_idx
        delta = 1 if event.delta > 0 else -1
        if (self.selected_preview_path is not None
                and self._prev_base_size[0] <= self._prev_base_size[1]):
            # portrait
            new_val = max(5, min(60, self.logo_scale_portrait_var.get() + delta))
            self.logo_scale_portrait_var.set(new_val)
            self.scale_portrait_display_var.set(f"{new_val}%")
            self._logo_portrait_scales[idx] = new_val
        else:
            new_val = max(5, min(60, self.logo_scale_var.get() + delta))
            self.logo_scale_var.set(new_val)
            self.scale_display_var.set(f"{new_val}%")
            self._logo_landscape_scales[idx] = new_val
        self._save_current_image_settings()
        self._schedule_preview()

    # ── Move drag ──────────────────────────────────────────────────────────────

    def _on_logo_drag_start(self, event: tk.Event, logo_idx: int) -> None:
        self._drag_logo_idx = logo_idx
        # Select this logo if not already selected
        if logo_idx != self._selected_logo_idx:
            self._select_logo(logo_idx)
        canvas_id = self._canvas_logo_ids.get(logo_idx)
        self._drag_start_evt = (event.x, event.y)
        if canvas_id is not None:
            coords = self.preview_canvas.coords(canvas_id)
            if coords:
                self._drag_start_logo_canvas = (coords[0], coords[1])

    def _on_logo_drag_motion(self, event: tk.Event) -> None:
        if (self._drag_start_evt is None
                or self._drag_start_logo_canvas is None):
            return
        idx = self._drag_logo_idx
        canvas_id = self._canvas_logo_ids.get(idx)
        if canvas_id is None:
            return

        dx = event.x - self._drag_start_evt[0]
        dy = event.y - self._drag_start_evt[1]
        new_cx = self._drag_start_logo_canvas[0] + dx
        new_cy = self._drag_start_logo_canvas[1] + dy

        ox, oy = self._prev_img_offset
        scale = self._prev_scale
        bw, bh = self._prev_base_size
        clw, clh = self._prev_logo_size_canvas
        canvas_bw = round(bw * scale)
        canvas_bh = round(bh * scale)

        new_cx = max(float(ox), min(new_cx, float(ox + canvas_bw - clw)))
        new_cy = max(float(oy), min(new_cy, float(oy + canvas_bh - clh)))

        self.preview_canvas.coords(canvas_id, new_cx, new_cy)

        ratio = (
            (new_cx - ox) / (bw * scale),
            (new_cy - oy) / (bh * scale),
        )
        if self.selected_preview_path is not None:
            self._per_image_pos_ratios.setdefault(
                self.selected_preview_path, {})[idx] = ratio

        # Show indicator
        self.custom_pos_label.grid(row=3, column=0, padx=14, pady=(0, 2), sticky="w")
        self.reset_pos_button.grid(row=4, column=0, padx=14, pady=(0, 6), sticky="ew")
        self._save_current_image_settings()
        self._update_handle_pos()

    def _update_handle_pos(self) -> None:
        """Move selection border and resize handle to match selected logo on canvas."""
        idx = self._selected_logo_idx
        canvas_id = self._canvas_logo_ids.get(idx)
        if canvas_id is None or self._canvas_handle_id is None:
            return
        coords = self.preview_canvas.coords(canvas_id)
        if not coords:
            return
        clx, cly = coords[0], coords[1]
        clw, clh = self._prev_logo_size_canvas
        HR = 8
        if self._canvas_selection_id:
            self.preview_canvas.coords(
                self._canvas_selection_id,
                clx, cly, clx + clw, cly + clh)
        self.preview_canvas.coords(
            self._canvas_handle_id,
            clx + clw - HR, cly + clh - HR,
            clx + clw + HR, cly + clh + HR,
        )

    # ── Resize drag ──────────────────────────────────────────────────────────

    def _on_handle_drag_start(self, event: tk.Event) -> None:
        self._resize_dragging = True
        self._resize_start_evt = (event.x, event.y)
        is_portrait = self._prev_base_size[0] <= self._prev_base_size[1]
        self._resize_start_scale = (
            self.logo_scale_portrait_var.get()
            if is_portrait
            else self.logo_scale_var.get()
        )
        self._resize_start_logo_w_canvas = self._prev_logo_size_canvas[0]

    def _on_handle_drag_motion(self, event: tk.Event) -> None:
        if not self._resize_dragging or self._resize_start_evt is None:
            return
        dx = event.x - self._resize_start_evt[0]
        dy = event.y - self._resize_start_evt[1]
        diag = (dx + dy) / 2
        if self._resize_start_logo_w_canvas <= 0:
            return
        factor = (self._resize_start_logo_w_canvas + diag) / self._resize_start_logo_w_canvas
        new_val = max(5, min(60, round(self._resize_start_scale * factor)))
        is_portrait = self._prev_base_size[0] <= self._prev_base_size[1]
        idx = self._selected_logo_idx
        if is_portrait:
            if new_val == self.logo_scale_portrait_var.get():
                return
            self.logo_scale_portrait_var.set(new_val)
            self.scale_portrait_display_var.set(f"{new_val}%")
            if idx < len(self._logo_portrait_scales):
                self._logo_portrait_scales[idx] = new_val
        else:
            if new_val == self.logo_scale_var.get():
                return
            self.logo_scale_var.set(new_val)
            self.scale_display_var.set(f"{new_val}%")
            if idx < len(self._logo_landscape_scales):
                self._logo_landscape_scales[idx] = new_val

        logo_pil = self._logo_pils[idx] if idx < len(self._logo_pils) else None
        canvas_id = self._canvas_logo_ids.get(idx)
        if logo_pil is not None and canvas_id is not None:
            bw, _ = self._prev_base_size
            logo_w = max(1, round(bw * new_val / 100))
            logo_h = max(1, round(logo_w * logo_pil.height / logo_pil.width))
            clw = max(1, round(logo_w * self._prev_scale))
            clh = max(1, round(logo_h * self._prev_scale))
            live_logo = logo_pil.resize((clw, clh), Image.Resampling.BILINEAR)
            photo = ImageTk.PhotoImage(live_logo)
            self._preview_logo_photos[idx] = photo
            self.preview_canvas.itemconfig(canvas_id, image=photo)
            self._prev_logo_size_canvas = (clw, clh)
            self._update_handle_pos()

    def _on_handle_drag_end(self, event: tk.Event) -> None:
        self._resize_dragging = False
        self._save_current_settings_if_per_image()
        # Full quality re-render after drag ends
        self._schedule_preview()

    # ═══════════════════════════════════════════════════════════════════
    # SETTINGS HELPERS
    # ═══════════════════════════════════════════════════════════════════

    def _on_output_size_changed(self, _: str) -> None:
        self._save_current_image_settings()
        self._schedule_preview()

    def _on_position_changed(self, _: str) -> None:
        idx = self._selected_logo_idx
        if idx < len(self._logo_positions):
            self._logo_positions[idx] = self.position_thai_var.get()
        # Clear drag ratio for current image + selected logo
        if self.selected_preview_path is not None:
            self._per_image_pos_ratios.get(
                self.selected_preview_path, {}).pop(idx, None)
        self.custom_pos_label.grid_remove()
        self.reset_pos_button.grid_remove()
        self._save_current_image_settings()
        self._schedule_preview()

    def _reset_logo_position(self) -> None:
        idx = self._selected_logo_idx
        if self.selected_preview_path is not None:
            self._per_image_pos_ratios.get(
                self.selected_preview_path, {}).pop(idx, None)
        self.custom_pos_label.grid_remove()
        self.reset_pos_button.grid_remove()
        self._save_current_image_settings()
        self._schedule_preview()

    def _on_scale_changed(self, value: float) -> None:
        v = int(value)
        self.scale_display_var.set(f"{v}%")
        idx = self._selected_logo_idx
        if idx < len(self._logo_landscape_scales):
            self._logo_landscape_scales[idx] = v
        self._save_current_image_settings()
        self._schedule_preview()

    def _on_scale_portrait_changed(self, value: float) -> None:
        v = int(value)
        self.scale_portrait_display_var.set(f"{v}%")
        idx = self._selected_logo_idx
        if idx < len(self._logo_portrait_scales):
            self._logo_portrait_scales[idx] = v
        self._save_current_image_settings()
        self._schedule_preview()

    def _on_opacity_changed(self, value: float) -> None:
        v = int(value)
        self.opacity_display_var.set(f"{v}%")
        idx = self._selected_logo_idx
        if idx < len(self._logo_opacities):
            self._logo_opacities[idx] = value / 100.0
        self._save_current_image_settings()
        self._schedule_preview()

    def _toggle_per_image_mode(self) -> None:
        pass  # kept for compatibility

    def _reset_per_image_override(self) -> None:
        pass  # kept for compatibility

    def _save_current_settings_if_per_image(self, force: bool = False) -> None:
        self._save_current_image_settings()

    def _save_current_image_settings(self) -> None:
        """Persist current UI state as a per-image per-logo override."""
        if self.selected_preview_path is None:
            return
        idx = self._selected_logo_idx
        if idx >= len(self._logo_paths):
            return
        pos = THAI_TO_POSITION.get(self.position_thai_var.get(), "bottom-right")
        l_scale = self.logo_scale_var.get()
        p_scale = self.logo_scale_portrait_var.get()
        opacity = self.opacity_var.get() / 100.0
        self._per_image_overrides.setdefault(
            self.selected_preview_path, {}
        )[idx] = PlacementSettings(
            landscape_position=pos,
            portrait_position=pos,
            output_size_mode=self.output_size_var.get(),
            logo_scale_percent=l_scale,
            landscape_logo_scale_percent=l_scale,
            portrait_logo_scale_percent=p_scale,
            margin=0,
            opacity=opacity,
        )
        self._update_filmstrip_badges()

    def _get_image_orientation(self, path: Path) -> str:
        """Return 'landscape' or 'portrait' based on the image's actual dimensions."""
        try:
            with Image.open(path) as img:
                w, h = img.size
            return "landscape" if w > h else "portrait"
        except Exception:
            return "landscape"

    def _apply_to_orientation(self, orientation: str) -> None:
        """Copy the current image's per-logo overrides to all images of the given orientation."""
        if self.selected_preview_path is None:
            return
        self._save_current_image_settings()
        src_overrides = self._per_image_overrides.get(self.selected_preview_path, {})
        src_ratios = self._per_image_pos_ratios.get(self.selected_preview_path, {})
        for path in self.image_paths:
            if self._get_image_orientation(path) != orientation:
                continue
            self._per_image_overrides[path] = dict(src_overrides)
            if src_ratios:
                self._per_image_pos_ratios[path] = dict(src_ratios)
            else:
                self._per_image_pos_ratios.pop(path, None)
        self._update_filmstrip_badges()

    def _apply_to_landscape(self) -> None:
        """Copy current settings to all landscape images."""
        self._apply_to_orientation("landscape")

    def _apply_to_portrait(self) -> None:
        """Copy current settings to all portrait images."""
        self._apply_to_orientation("portrait")

    def _apply_to_all(self) -> None:
        """Copy the current image's per-logo overrides to every loaded image."""
        if self.selected_preview_path is None:
            return
        self._save_current_image_settings()
        src_overrides = self._per_image_overrides.get(self.selected_preview_path, {})
        src_ratios = self._per_image_pos_ratios.get(self.selected_preview_path, {})
        for path in self.image_paths:
            self._per_image_overrides[path] = dict(src_overrides)
            if src_ratios:
                self._per_image_pos_ratios[path] = dict(src_ratios)
            else:
                self._per_image_pos_ratios.pop(path, None)
        self._update_filmstrip_badges()

    def _reset_all_overrides(self) -> None:
        """Clear all per-image overrides; every image reverts to global defaults."""
        self._per_image_overrides.clear()
        self._per_image_pos_ratios.clear()
        self.custom_pos_label.grid_remove()
        self.reset_pos_button.grid_remove()
        if self.selected_preview_path is not None:
            self._load_logo_settings_into_ui(self._selected_logo_idx)
        self._update_filmstrip_badges()
        self._schedule_preview()

    def _update_filmstrip_badges(self) -> None:
        """Refresh thumbnail borders: teal=selected, default=others."""
        bg = self.filmstrip_inner.cget("bg")
        for p, container in self._thumb_containers.items():
            container.configure(bg=TEAL if p == self.selected_preview_path else bg)

    def _get_settings(self) -> PlacementSettings:
        """Return image-level settings (output_size, quality). Position/scale come per-logo."""
        return PlacementSettings(
            output_size_mode=self.output_size_var.get(),
            quality=95,
            margin=0,
        )

    def _build_logo_settings_by_path(
        self,
    ) -> dict[Path, dict[int, PlacementSettings]]:
        """Build per-image per-logo PlacementSettings, embedding drag positions."""
        result: dict[Path, dict[int, PlacementSettings]] = {}

        for path in self.image_paths:
            img_overrides = self._per_image_overrides.get(path, {})
            img_ratios = self._per_image_pos_ratios.get(path, {})

            if not img_overrides and not img_ratios:
                continue

            per_logo: dict[int, PlacementSettings] = {}

            for logo_idx, logo_pil in enumerate(self._logo_pils):
                if logo_pil is None:
                    continue
                override = img_overrides.get(logo_idx)
                ratio = img_ratios.get(logo_idx)

                if ratio is None:
                    if override is not None:
                        per_logo[logo_idx] = override
                    continue

                # Drag ratio → pixel offsets
                l_scale = (
                    override.effective_landscape_scale()
                    if override else self._logo_landscape_scales[logo_idx]
                )
                p_scale = (
                    override.effective_portrait_scale()
                    if override else self._logo_portrait_scales[logo_idx]
                )
                output_size = (
                    override.output_size_mode
                    if override else self.output_size_var.get()
                )
                opacity = (
                    override.opacity
                    if override else self._logo_opacities[logo_idx]
                )
                pos_key = (
                    override.landscape_position
                    if override else THAI_TO_POSITION.get(
                        self._logo_positions[logo_idx], "top-right")
                )

                try:
                    with Image.open(path) as img:
                        orig_w, orig_h = img.size
                    if output_size == OUTPUT_SIZE_ORIGINAL:
                        out_w, out_h = orig_w, orig_h
                    else:
                        out_w = TARGET_WIDTH
                        out_h = round(TARGET_WIDTH / orig_w * orig_h)

                    orientation = "landscape" if orig_w > orig_h else "portrait"
                    scale_pct = l_scale if orientation == "landscape" else p_scale

                    logo_w = max(1, round(out_w * scale_pct / 100))
                    logo_h = max(1, round(logo_w * logo_pil.height / logo_pil.width))
                    logo_x = max(0, min(round(ratio[0] * out_w), out_w - logo_w))
                    logo_y = max(0, min(round(ratio[1] * out_h), out_h - logo_h))

                    per_logo[logo_idx] = PlacementSettings(
                        landscape_position="top-left",
                        portrait_position="top-left",
                        output_size_mode=output_size,
                        margin=0,
                        offset_x=logo_x,
                        offset_y=logo_y,
                        logo_scale_percent=l_scale,
                        landscape_logo_scale_percent=l_scale,
                        portrait_logo_scale_percent=p_scale,
                        opacity=opacity,
                    )
                except Exception:
                    if override is not None:
                        per_logo[logo_idx] = override

            if per_logo:
                result[path] = per_logo

        return result

    def _update_start_button(self) -> None:
        if self._logo_paths and self.image_paths:
            self.start_button.configure(state="normal")
        else:
            self.start_button.configure(state="disabled")
        self._update_step_indicators()

    def _update_step_indicators(self) -> None:
        step1_done = bool(self._logo_paths)
        step2_done = bool(self.image_paths)

        if step1_done:
            self.step1_badge.configure(fg_color=TEAL, text_color="white", text="✓ STEP 1")
        else:
            self.step1_badge.configure(
                fg_color=("gray75", "gray30"), text_color=("gray50", "gray55"), text="STEP 1")

        if step2_done:
            self.step2_badge.configure(fg_color=TEAL, text_color="white", text="✓ STEP 2")
        else:
            self.step2_badge.configure(
                fg_color=("gray75", "gray30"), text_color=("gray50", "gray55"), text="STEP 2")

        if step1_done:
            self.step3_badge.configure(fg_color=TEAL, text_color="white", text="✓ STEP 3")
        else:
            self.step3_badge.configure(
                fg_color=("gray75", "gray30"), text_color=("gray50", "gray55"), text="STEP 3")

        new_state = "normal" if step1_done else "disabled"
        for w in self._settings_interactive_widgets:
            w.configure(state=new_state)

    # ═══════════════════════════════════════════════════════════════════
    # PROCESSING
    # ═══════════════════════════════════════════════════════════════════

    def _start_processing(self) -> None:
        if not self._logo_paths or not self.image_paths:
            return
        if self._worker and self._worker.is_alive():
            return

        self.start_button.configure(state="disabled", text="กำลังประมวลผล...")
        self.progress_frame.grid()
        self.progress_bar.set(0)
        self.status_var.set("กำลังเริ่มต้น...")

        # Build LogoConfig for each logo
        logo_configs = []
        for logo_idx, logo_path in enumerate(self._logo_paths):
            pos = THAI_TO_POSITION.get(
                self._logo_positions[logo_idx], "top-right")
            l_scale = self._logo_landscape_scales[logo_idx]
            p_scale = self._logo_portrait_scales[logo_idx]
            opacity = self._logo_opacities[logo_idx]
            logo_settings = PlacementSettings(
                landscape_position=pos,
                portrait_position=pos,
                output_size_mode=self.output_size_var.get(),
                logo_scale_percent=l_scale,
                landscape_logo_scale_percent=l_scale,
                portrait_logo_scale_percent=p_scale,
                margin=0,
                opacity=opacity,
                offset_x=self._logo_offset_x[logo_idx],
            )
            logo_configs.append(LogoConfig(logo_path=logo_path, settings=logo_settings))

        request = BatchRequest(
            logos=tuple(logo_configs),
            settings=self._get_settings(),
            source_paths=tuple(self.image_paths),
            logo_settings_by_path=self._build_logo_settings_by_path(),
        )
        self._worker = threading.Thread(
            target=self._worker_fn, args=(request,), daemon=True)
        self._worker.start()

    def _worker_fn(self, request: BatchRequest) -> None:
        def on_progress(current: int, total: int, path: Path) -> None:
            self._events.put(("progress", (current, total, path.name)))

        try:
            results = process_batch(request, progress_callback=on_progress)
            folder = results[0].output_path.parent if results else None
            self._events.put(("done", folder))
        except Exception as exc:
            self._events.put(("error", str(exc)))

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self._events.get_nowait()
                if event == "progress":
                    cur, total, name = payload  # type: ignore[misc]
                    self.progress_var.set(cur / total)
                    self.status_var.set(f"กำลังทำ {cur} / {total}  —  {name}")
                elif event == "done":
                    self.last_output_folder = payload  # type: ignore[assignment]
                    self._on_done()
                elif event == "error":
                    messagebox.showerror("เกิดข้อผิดพลาด", str(payload))
                    self.start_button.configure(
                        state="normal", text="▶  START เริ่มประมวลผล")
                elif event == "thumb_ready":
                    self._apply_thumb(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.after(80, self._poll_events)

    def _on_done(self) -> None:
        self.progress_bar.set(1.0)
        self.status_var.set(f"เสร็จสิ้น ✓  ({len(self.image_paths)} รูป)")
        self.start_button.configure(state="normal", text="▶  START ใหม่อีกครั้ง")
        self.open_folder_button.grid(row=1, column=0, pady=(8, 0), sticky="ew")
        messagebox.showinfo(
            "เสร็จสิ้น",
            f"ประมวลผลรูปภาพเรียบร้อยแล้ว {len(self.image_paths)} รูป\n\n"
            f"บันทึกไปที่:\n{self.last_output_folder}",
        )

    def _on_logo_drag(self, event) -> None:
        pass

    def _open_output_folder(self) -> None:
        if self.last_output_folder and self.last_output_folder.exists():
            os.startfile(str(self.last_output_folder))