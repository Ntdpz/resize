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
    OUTPUT_SIZE_RESIZE_1280,
    OUTPUT_SIZE_ORIGINAL,
    PlacementSettings,
    SUPPORTED_EXTENSIONS,
)
from core.processor import process_batch

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
        self.logo_path: Path | None = None
        self.image_paths: list[Path] = []
        self.selected_preview_path: Path | None = None
        self.last_output_folder: Path | None = None

        # ── Threading ──────────────────────────────────────────────────
        self._worker: threading.Thread | None = None
        self._events: queue.Queue[AppEvent] = queue.Queue()
        self._preview_debounce_id: str | None = None

        # ── Image caches ───────────────────────────────────────────────
        self._logo_pil: Image.Image | None = None
        self._logo_ctk: ctk.CTkImage | None = None
        self._preview_base_photo: ImageTk.PhotoImage | None = None
        self._preview_logo_photo: ImageTk.PhotoImage | None = None
        self._thumb_pil_cache: dict[Path, Image.Image] = {}
        self._thumb_photos: dict[Path, ImageTk.PhotoImage] = {}
        self._thumb_labels: dict[Path, tk.Label] = {}
        self._thumb_containers: dict[Path, tk.Frame] = {}

        # ── Drag / free-position state ─────────────────────────────────
        self._canvas_logo_id: int | None = None
        self._canvas_handle_id: int | None = None   # resize handle circle
        self._canvas_selection_id: int | None = None  # dashed border
        # Ratio (0.0–1.0) of full-res image; None = use preset
        # Now per-image: path → (ratio_x, ratio_y)
        self._logo_pos_ratio: tuple[float, float] | None = None  # current image
        self._per_image_pos_ratios: dict[Path, tuple[float, float]] = {}  # all images
        self._drag_start_evt: tuple[int, int] | None = None
        self._drag_start_logo_canvas: tuple[float, float] | None = None
        self._prev_scale: float = 1.0
        self._prev_img_offset: tuple[int, int] = (0, 0)
        self._prev_base_size: tuple[int, int] = (TARGET_WIDTH, 720)
        self._prev_logo_size_canvas: tuple[int, int] = (0, 0)
        # Resize-handle drag state
        self._resize_dragging: bool = False
        self._resize_start_evt: tuple[int, int] | None = None
        self._resize_start_scale: int = 18   # logo_scale_var value at drag start
        self._resize_start_logo_w_canvas: int = 0   # canvas-px logo width at drag start

        # ── UI variables ───────────────────────────────────────────────
        self.position_thai_var = ctk.StringVar(value=POSITION_THAI["top-right"])
        self.output_size_var = ctk.StringVar(value=OUTPUT_SIZE_RESIZE_1280)
        self.logo_scale_var = ctk.IntVar(value=18)          # landscape scale
        self.scale_display_var = ctk.StringVar(value="18%")
        self.logo_scale_portrait_var = ctk.IntVar(value=18)  # portrait scale
        self.scale_portrait_display_var = ctk.StringVar(value="18%")
        self.progress_var = ctk.DoubleVar(value=0.0)
        self.status_var = ctk.StringVar(value="")

        # ── Per-image override state ───────────────────────────────────
        # dict[Path, PlacementSettings] — every image gets its own settings
        self._per_image_overrides: dict[Path, PlacementSettings] = {}
        # True global scale / position defaults used to initialize new images
        self._global_landscape_scale: int = 18
        self._global_portrait_scale: int = 18

        self._build_ui()
        self.after(100, self._poll_events)

    # ═══════════════════════════════════════════════════════════════════
    # BUILD UI
    # ═══════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_left_panel()
        self._build_right_panel()
        self._update_step_indicators()

    # ── Left panel ─────────────────────────────────────────────────────

    def _build_left_panel(self) -> None:
        outer = ctk.CTkFrame(self, width=280, corner_radius=0)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.grid_propagate(False)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(0, weight=1)

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

        self._build_logo_zone(panel, row=1)
        self._build_input_zone(panel, row=2)
        ctk.CTkFrame(panel, height=1, fg_color=("gray70", "gray35")).grid(
            row=3, column=0, padx=16, pady=(0, 4), sticky="ew")
        self._build_settings(panel, row=4)
        self._build_per_image_actions(panel, row=5)
        self._build_progress_section(panel, row=6)
        self._build_footer(panel, row=7)

    def _build_logo_zone(self, parent: ctk.CTkFrame, row: int) -> None:
        self.logo_card = ctk.CTkFrame(parent, corner_radius=12)
        self.logo_card.grid(row=row, column=0, padx=12, pady=(0, 8), sticky="ew")
        self.logo_card.grid_columnconfigure(1, weight=1)

        self.logo_thumb_label = ctk.CTkLabel(
            self.logo_card, text="🖼",
            font=ctk.CTkFont(size=24),
            width=52, height=52, corner_radius=8,
            fg_color=("gray82", "gray25"),
        )
        self.logo_thumb_label.grid(row=0, column=0, padx=(12, 8), pady=12)

        txt = ctk.CTkFrame(self.logo_card, fg_color="transparent")
        txt.grid(row=0, column=1, pady=12, sticky="ew")
        self.step1_badge = ctk.CTkLabel(
            txt, text="STEP 1",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("gray75", "gray30"), text_color=("gray50", "gray55"),
            corner_radius=4,
        )
        self.step1_badge.pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(
            txt, text="โลโก้ (.png)",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w")
        self.logo_name_label = ctk.CTkLabel(
            txt, text="ยังไม่ได้เลือก",
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray55"),
            wraplength=130, justify="left",
        )
        self.logo_name_label.pack(anchor="w")

        ctk.CTkButton(
            self.logo_card, text="เลือก",
            width=62, height=32, font=ctk.CTkFont(size=13),
            fg_color=("gray78", "gray32"),
            text_color=("gray10", "gray90"),
            hover_color=("gray68", "gray42"),
            command=self._choose_logo,
        ).grid(row=0, column=2, padx=(0, 12))

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

        ctk.CTkLabel(
            self.settings_card, text="ขนาดเอาต์พุต", font=ctk.CTkFont(size=13),
        ).grid(row=9, column=0, padx=14, pady=(8, 4), sticky="w")

        self._output_size_segmented = ctk.CTkSegmentedButton(
            self.settings_card,
            values=[OUTPUT_SIZE_RESIZE_1280, OUTPUT_SIZE_ORIGINAL],
            variable=self.output_size_var,
            selected_color=TEAL,
            selected_hover_color=TEAL_DARK,
            font=ctk.CTkFont(size=11),
            command=self._on_output_size_changed,
        )
        self._output_size_segmented.grid(row=10, column=0, padx=14, pady=(0, 8), sticky="ew")

        ctk.CTkLabel(
            self.settings_card,
            text="💡 ลากโลโก้บน preview · Scroll ปรับขนาด",
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray55"),
        ).grid(row=11, column=0, padx=14, pady=(0, 12), sticky="w")

        self._settings_interactive_widgets = [
            self._position_option,
            self._scale_landscape_slider,
            self._scale_portrait_slider,
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
        right = ctk.CTkFrame(self, corner_radius=0, fg_color=("gray90", "gray13"))
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
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
    # LOGO
    # ═══════════════════════════════════════════════════════════════════

    def _choose_logo(self) -> None:
        path_str = filedialog.askopenfilename(
            title="เลือกไฟล์โลโก้",
            filetypes=[("PNG files", "*.png"), ("All files", "*.*")],
        )
        if not path_str:
            return
        self.logo_path = Path(path_str)
        try:
            img = Image.open(self.logo_path)
            self._logo_pil = img.convert("RGBA")
            thumb = self._logo_pil.copy()
            thumb.thumbnail((48, 48), Image.Resampling.LANCZOS)
            self._logo_ctk = ctk.CTkImage(
                light_image=thumb, dark_image=thumb, size=(48, 48))
            self.logo_thumb_label.configure(
                image=self._logo_ctk, text="",
                fg_color=("gray82", "gray25"))
        except Exception:
            self._logo_pil = None
        self.logo_name_label.configure(text=self.logo_path.name)
        self.logo_card.configure(border_width=2, border_color=TEAL)
        self._update_start_button()
        self._schedule_preview()

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
        for p in new_paths:
            rp = p.resolve()
            if (rp not in seen
                    and rp.is_file()
                    and rp.suffix.lower() in SUPPORTED_EXTENSIONS):
                seen.add(rp)
                self.image_paths.append(p)
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
        self._per_image_mode = False
        self._logo_pos_ratio = None
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
        override = self._per_image_overrides.get(path)
        if override is not None:
            self.logo_scale_var.set(override.effective_landscape_scale())
            self.scale_display_var.set(f"{override.effective_landscape_scale()}%")
            self.logo_scale_portrait_var.set(override.effective_portrait_scale())
            self.scale_portrait_display_var.set(f"{override.effective_portrait_scale()}%")
            pos_key = override.landscape_position
            self.position_thai_var.set(
                POSITION_THAI.get(pos_key, POSITION_THAI["top-right"]))
            self.output_size_var.set(override.output_size_mode)
        else:
            self.logo_scale_var.set(self._global_landscape_scale)
            self.scale_display_var.set(f"{self._global_landscape_scale}%")
            self.logo_scale_portrait_var.set(self._global_portrait_scale)
            self.scale_portrait_display_var.set(f"{self._global_portrait_scale}%")

        # Sync drag-position indicator for this image
        has_drag = path in self._per_image_pos_ratios
        if has_drag:
            self.custom_pos_label.grid(row=3, column=0, padx=14, pady=(0, 2), sticky="w")
            self.reset_pos_button.grid(row=4, column=0, padx=14, pady=(0, 6), sticky="ew")
        else:
            self.custom_pos_label.grid_remove()
            self.reset_pos_button.grid_remove()

    def _filmstrip_scroll(self, event: tk.Event) -> None:
        self.filmstrip_canvas.xview_scroll(
            int(-1 * (event.delta / 120)), "units")

    # ═══════════════════════════════════════════════════════════════════
    # PREVIEW  (2-layer canvas: base + draggable logo)
    # ═══════════════════════════════════════════════════════════════════

    def _render_preview(self, path: Path) -> None:
        if self._logo_pil is None:
            return
        cw = self.preview_canvas.winfo_width()
        ch = self.preview_canvas.winfo_height()
        if cw < 10 or ch < 10:
            # Canvas not laid out yet — retry after layout pass
            self.after(150, lambda: self._render_preview(path))
            return

        try:
            with Image.open(path) as raw:
                raw = (ImageOps.exif_transpose(raw) or raw).convert("RGBA")

            # Resize base to TARGET_WIDTH
            if raw.width != TARGET_WIDTH:
                new_h = round(TARGET_WIDTH / raw.width * raw.height)
                base = raw.resize((TARGET_WIDTH, new_h), Image.Resampling.LANCZOS)
            else:
                base = raw.copy()
            base_w, base_h = base.size
            orientation = "landscape" if base_w > base_h else "portrait"

            # Resolve effective settings: per-image override → global
            override = self._per_image_overrides.get(path)
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
                    self._global_landscape_scale
                    if orientation == "landscape"
                    else self._global_portrait_scale
                )
                pos_key = THAI_TO_POSITION.get(
                    self.position_thai_var.get(), "bottom-right")

            logo_w = max(1, round(base_w * active_scale / 100))
            logo_h = max(1, round(logo_w * self._logo_pil.height / self._logo_pil.width))
            logo_resized = self._logo_pil.resize(
                (logo_w, logo_h), Image.Resampling.LANCZOS)

            # Compute logo position: per-image drag ratio → preset
            pos_ratio = self._per_image_pos_ratios.get(path)
            if pos_ratio is not None:
                lx = max(0, min(round(pos_ratio[0] * base_w), base_w - logo_w))
                ly = max(0, min(round(pos_ratio[1] * base_h), base_h - logo_h))
            else:
                lx, ly = calculate_position(
                    base.size, (logo_w, logo_h), pos_key, 0, 0, 0)

            # Keep global _logo_pos_ratio in sync for drag-state helpers
            self._logo_pos_ratio = pos_ratio

            # Scale base to fit canvas
            preview_base = base.convert("RGB")
            preview_base.thumbnail((cw, ch), Image.Resampling.LANCZOS)
            pw, ph = preview_base.size
            scale = pw / base_w

            # Center image on canvas
            ox = (cw - pw) // 2
            oy = (ch - ph) // 2

            # Scale logo for canvas display
            clw = max(1, round(logo_w * scale))
            clh = max(1, round(logo_h * scale))
            canvas_logo = logo_resized.resize(
                (clw, clh), Image.Resampling.LANCZOS)
            clx = ox + round(lx * scale)
            cly = oy + round(ly * scale)

            # Store values for drag coordinate mapping
            self._prev_scale = scale
            self._prev_img_offset = (ox, oy)
            self._prev_base_size = (base_w, base_h)
            self._prev_logo_size_canvas = (clw, clh)

            self._preview_base_photo = ImageTk.PhotoImage(preview_base)
            self._preview_logo_photo = ImageTk.PhotoImage(canvas_logo)

            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(
                ox, oy, image=self._preview_base_photo,
                anchor="nw", tags="base")
            self._canvas_logo_id = self.preview_canvas.create_image(
                clx, cly, image=self._preview_logo_photo,
                anchor="nw", tags="logo")

            # ── Selection border (dashed) around logo ──
            self._canvas_selection_id = self.preview_canvas.create_rectangle(
                clx, cly, clx + clw, cly + clh,
                outline=TEAL, width=2, dash=(6, 4), fill="",
                tags="selection",
            )
            # ── Resize handle: circle at bottom-right corner ──
            HR = 8  # radius
            self._canvas_handle_id = self.preview_canvas.create_oval(
                clx + clw - HR, cly + clh - HR,
                clx + clw + HR, cly + clh + HR,
                fill="white", outline=TEAL, width=2,
                tags="handle",
            )

            self.preview_canvas.tag_bind(
                "logo", "<ButtonPress-1>", self._on_logo_drag_start)
            self.preview_canvas.tag_bind(
                "logo", "<B1-Motion>", self._on_logo_drag_motion)
            self.preview_canvas.tag_bind(
                "logo", "<Enter>",
                lambda e: self.preview_canvas.configure(cursor="fleur"))
            self.preview_canvas.tag_bind(
                "logo", "<Leave>",
                lambda e: self.preview_canvas.configure(cursor=""))
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
        if self._canvas_logo_id is not None and self._canvas_logo_id in items:
            self._on_logo_scroll(event)

    def _on_logo_scroll(self, event: tk.Event) -> None:
        """Mouse wheel over logo → resize by ±1% per notch."""
        delta = 1 if event.delta > 0 else -1
        # Determine which scale var to adjust based on current preview image orientation
        if (self.selected_preview_path is not None
                and self._prev_base_size[0] <= self._prev_base_size[1]):
            # portrait
            new_val = max(5, min(60, self.logo_scale_portrait_var.get() + delta))
            self.logo_scale_portrait_var.set(new_val)
            self.scale_portrait_display_var.set(f"{new_val}%")
        else:
            new_val = max(5, min(60, self.logo_scale_var.get() + delta))
            self.logo_scale_var.set(new_val)
            self.scale_display_var.set(f"{new_val}%")
        self._save_current_settings_if_per_image()
        self._schedule_preview()

    # ── Move drag ──────────────────────────────────────────────────────────────

    def _on_logo_drag_start(self, event: tk.Event) -> None:
        self._drag_start_evt = (event.x, event.y)
        if self._canvas_logo_id is not None:
            coords = self.preview_canvas.coords(self._canvas_logo_id)
            if coords:
                self._drag_start_logo_canvas = (coords[0], coords[1])

    def _on_logo_drag_motion(self, event: tk.Event) -> None:
        if (self._drag_start_evt is None
                or self._drag_start_logo_canvas is None
                or self._canvas_logo_id is None):
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

        # Move logo instantly — no re-render
        self.preview_canvas.coords(self._canvas_logo_id, new_cx, new_cy)

        # Store as ratio of full-res image — per-image
        ratio = (
            (new_cx - ox) / (bw * scale),
            (new_cy - oy) / (bh * scale),
        )
        self._logo_pos_ratio = ratio
        if self.selected_preview_path is not None:
            self._per_image_pos_ratios[self.selected_preview_path] = ratio

        # Show indicator
        self.custom_pos_label.grid(row=3, column=0, padx=14, pady=(0, 2), sticky="w")
        self.reset_pos_button.grid(row=4, column=0, padx=14, pady=(0, 6), sticky="ew")
        self._save_current_settings_if_per_image()
        # Keep handle in sync with new logo position
        self._update_handle_pos()

    def _update_handle_pos(self) -> None:
        """Move selection border and resize handle to match current logo on canvas."""
        if self._canvas_logo_id is None or self._canvas_handle_id is None:
            return
        coords = self.preview_canvas.coords(self._canvas_logo_id)
        if not coords:
            return
        clx, cly = coords[0], coords[1]
        clw, clh = self._prev_logo_size_canvas
        HR = 8
        # Selection border
        if hasattr(self, '_canvas_selection_id') and self._canvas_selection_id:
            self.preview_canvas.coords(
                self._canvas_selection_id,
                clx, cly, clx + clw, cly + clh)
        # Circle handle
        self.preview_canvas.coords(
            self._canvas_handle_id,
            clx + clw - HR, cly + clh - HR,
            clx + clw + HR, cly + clh + HR,
        )

    # ── Resize drag ──────────────────────────────────────────────────────────

    def _on_handle_drag_start(self, event: tk.Event) -> None:
        self._resize_dragging = True
        self._resize_start_evt = (event.x, event.y)
        # Use orientation-specific scale as the drag baseline
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
        # Apply to orientation-specific slider
        is_portrait = self._prev_base_size[0] <= self._prev_base_size[1]
        if is_portrait:
            if new_val == self.logo_scale_portrait_var.get():
                return
            self.logo_scale_portrait_var.set(new_val)
            self.scale_portrait_display_var.set(f"{new_val}%")
        else:
            if new_val == self.logo_scale_var.get():
                return
            self.logo_scale_var.set(new_val)
            self.scale_display_var.set(f"{new_val}%")

        # ── Live resize: update canvas image directly, no full re-render ──
        if self._logo_pil is not None and self._canvas_logo_id is not None:
            bw, _ = self._prev_base_size
            logo_w = max(1, round(bw * new_val / 100))
            logo_h = max(1, round(logo_w * self._logo_pil.height / self._logo_pil.width))
            clw = max(1, round(logo_w * self._prev_scale))
            clh = max(1, round(logo_h * self._prev_scale))
            live_logo = self._logo_pil.resize((clw, clh), Image.Resampling.BILINEAR)
            self._preview_logo_photo = ImageTk.PhotoImage(live_logo)
            self.preview_canvas.itemconfig(
                self._canvas_logo_id, image=self._preview_logo_photo)
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
        # Clear drag ratio for current image when preset is explicitly chosen
        if self.selected_preview_path is not None:
            self._per_image_pos_ratios.pop(self.selected_preview_path, None)
        self._logo_pos_ratio = None
        self.custom_pos_label.grid_remove()
        self.reset_pos_button.grid_remove()
        self._save_current_image_settings()
        self._schedule_preview()

    def _reset_logo_position(self) -> None:
        if self.selected_preview_path is not None:
            self._per_image_pos_ratios.pop(self.selected_preview_path, None)
        self._logo_pos_ratio = None
        self.custom_pos_label.grid_remove()
        self.reset_pos_button.grid_remove()
        self._save_current_image_settings()
        self._schedule_preview()

    def _on_scale_changed(self, value: float) -> None:
        v = int(value)
        self.scale_display_var.set(f"{v}%")
        if self.selected_preview_path is None:
            self._global_landscape_scale = v
        self._save_current_image_settings()
        self._schedule_preview()

    def _on_scale_portrait_changed(self, value: float) -> None:
        v = int(value)
        self.scale_portrait_display_var.set(f"{v}%")
        if self.selected_preview_path is None:
            self._global_portrait_scale = v
        self._save_current_image_settings()
        self._schedule_preview()

    def _toggle_per_image_mode(self) -> None:
        pass  # kept for compatibility; no longer used

    def _reset_per_image_override(self) -> None:
        pass  # kept for compatibility; no longer used

    def _save_current_settings_if_per_image(self, force: bool = False) -> None:
        self._save_current_image_settings()

    def _save_current_image_settings(self) -> None:
        """Persist current UI state as this image's override."""
        if self.selected_preview_path is None:
            return
        pos = THAI_TO_POSITION.get(self.position_thai_var.get(), "bottom-right")
        self._per_image_overrides[self.selected_preview_path] = PlacementSettings(
            landscape_position=pos,
            portrait_position=pos,
            output_size_mode=self.output_size_var.get(),
            logo_scale_percent=self.logo_scale_var.get(),
            landscape_logo_scale_percent=self.logo_scale_var.get(),
            portrait_logo_scale_percent=self.logo_scale_portrait_var.get(),
            margin=0,
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
        """Copy the current image's settings only to images of the given orientation."""
        if self.selected_preview_path is None:
            return
        self._save_current_image_settings()
        src = self._per_image_overrides.get(self.selected_preview_path)
        if src is None:
            return
        ratio = self._per_image_pos_ratios.get(self.selected_preview_path)
        for path in self.image_paths:
            if self._get_image_orientation(path) != orientation:
                continue
            self._per_image_overrides[path] = src
            if ratio is not None:
                self._per_image_pos_ratios[path] = ratio
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
        """Copy the current image's settings to every loaded image."""
        if self.selected_preview_path is None:
            return
        self._save_current_image_settings()
        src = self._per_image_overrides.get(self.selected_preview_path)
        if src is None:
            return
        for path in self.image_paths:
            self._per_image_overrides[path] = src
            # Copy drag position too
            ratio = self._per_image_pos_ratios.get(self.selected_preview_path)
            if ratio is not None:
                self._per_image_pos_ratios[path] = ratio
            else:
                self._per_image_pos_ratios.pop(path, None)
        self._update_filmstrip_badges()

    def _reset_all_overrides(self) -> None:
        """Clear all per-image overrides; every image reverts to global defaults."""
        self._per_image_overrides.clear()
        self._per_image_pos_ratios.clear()
        self._logo_pos_ratio = None
        self.custom_pos_label.grid_remove()
        self.reset_pos_button.grid_remove()
        # Reload current image (will show global defaults)
        if self.selected_preview_path is not None:
            self._load_settings_for_image(self.selected_preview_path)
        self._update_filmstrip_badges()
        self._schedule_preview()

    def _update_filmstrip_badges(self) -> None:
        """Refresh thumbnail borders: teal=selected, default=others."""
        bg = self.filmstrip_inner.cget("bg")
        for p, container in self._thumb_containers.items():
            container.configure(bg=TEAL if p == self.selected_preview_path else bg)

    def _get_settings(self) -> PlacementSettings:
        pos = THAI_TO_POSITION.get(self.position_thai_var.get(), "bottom-right")
        return PlacementSettings(
            landscape_position=pos,
            portrait_position=pos,
            output_size_mode=self.output_size_var.get(),
            logo_scale_percent=self._global_landscape_scale,
            landscape_logo_scale_percent=self._global_landscape_scale,
            portrait_logo_scale_percent=self._global_portrait_scale,
            margin=0,
        )

    def _build_settings_by_path(self) -> dict[Path, PlacementSettings]:
        """Combine per-image overrides with per-image drag-position adjustments."""
        result: dict[Path, PlacementSettings] = {}

        # Build per-image settings: merge scale override + drag position for every image
        if self._logo_pil is None:
            return result

        for path in self.image_paths:
            override = self._per_image_overrides.get(path)
            ratio = self._per_image_pos_ratios.get(path)

            # No custom settings at all → use global (no entry needed)
            if override is None and ratio is None:
                continue

            # Resolve scale and output_size from override or globals
            l_scale = override.effective_landscape_scale() if override else self._global_landscape_scale
            p_scale = override.effective_portrait_scale()  if override else self._global_portrait_scale
            output_size = override.output_size_mode if override else self.output_size_var.get()
            pos_key = override.landscape_position if override else THAI_TO_POSITION.get(
                self.position_thai_var.get(), "top-right")

            if ratio is None:
                # Scale/settings override only — no drag position
                result[path] = override  # type: ignore[assignment]
                continue

            # Drag position exists: embed it as pixel offset
            try:
                with Image.open(path) as img:
                    orig_w, orig_h = img.size

                from core.models import OUTPUT_SIZE_ORIGINAL
                if output_size == OUTPUT_SIZE_ORIGINAL:
                    out_w, out_h = orig_w, orig_h
                else:
                    out_w = TARGET_WIDTH
                    out_h = round(TARGET_WIDTH / orig_w * orig_h)

                orientation = "landscape" if orig_w > orig_h else "portrait"
                scale_pct = l_scale if orientation == "landscape" else p_scale

                logo_w = max(1, round(out_w * scale_pct / 100))
                logo_h = max(1, round(logo_w * self._logo_pil.height / self._logo_pil.width))
                logo_x = max(0, min(round(ratio[0] * out_w), out_w - logo_w))
                logo_y = max(0, min(round(ratio[1] * out_h), out_h - logo_h))

                result[path] = PlacementSettings(
                    landscape_position="top-left",
                    portrait_position="top-left",
                    output_size_mode=output_size,
                    margin=0,
                    offset_x=logo_x,
                    offset_y=logo_y,
                    logo_scale_percent=l_scale,
                    landscape_logo_scale_percent=l_scale,
                    portrait_logo_scale_percent=p_scale,
                )
            except Exception:
                if override is not None:
                    result[path] = override

        return result

    def _update_start_button(self) -> None:
        if self.logo_path and self.image_paths:
            self.start_button.configure(state="normal")
        else:
            self.start_button.configure(state="disabled")
        self._update_step_indicators()

    def _update_step_indicators(self) -> None:
        step1_done = self.logo_path is not None
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
        if not self.logo_path or not self.image_paths:
            return
        if self._worker and self._worker.is_alive():
            return

        self.start_button.configure(state="disabled", text="กำลังประมวลผล...")
        self.progress_frame.grid()
        self.progress_bar.set(0)
        self.status_var.set("กำลังเริ่มต้น...")

        request = BatchRequest(
            logo_path=self.logo_path,
            settings=self._get_settings(),
            source_paths=tuple(self.image_paths),
            settings_by_path=self._build_settings_by_path(),
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