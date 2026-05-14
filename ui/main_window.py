from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk  # type: ignore[import-untyped]
from PIL import Image, ImageOps, ImageTk  # type: ignore[import-untyped]

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


class AutoWatermarkWindow(ctk.CTk):
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
        # Ratio (0.0–1.0) of full-res image; None = use preset
        self._logo_pos_ratio: tuple[float, float] | None = None
        self._drag_start_evt: tuple[int, int] | None = None
        self._drag_start_logo_canvas: tuple[float, float] | None = None
        self._prev_scale: float = 1.0
        self._prev_img_offset: tuple[int, int] = (0, 0)
        self._prev_base_size: tuple[int, int] = (TARGET_WIDTH, 720)
        self._prev_logo_size_canvas: tuple[int, int] = (0, 0)

        # ── UI variables ───────────────────────────────────────────────
        self.position_thai_var = ctk.StringVar(value=POSITION_THAI["top-right"])
        self.output_size_var = ctk.StringVar(value=OUTPUT_SIZE_RESIZE_1280)
        self.logo_scale_var = ctk.IntVar(value=18)
        self.scale_display_var = ctk.StringVar(value="18%")
        self.progress_var = ctk.DoubleVar(value=0.0)
        self.status_var = ctk.StringVar(value="")

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

    # ── Left panel ─────────────────────────────────────────────────────

    def _build_left_panel(self) -> None:
        panel = ctk.CTkFrame(self, width=264, corner_radius=0)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_propagate(False)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(4, weight=1)

        brand = ctk.CTkFrame(panel, fg_color="transparent")
        brand.grid(row=0, column=0, padx=16, pady=(20, 14), sticky="ew")
        ctk.CTkLabel(
            brand, text="Auto Watermark",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand, text="Resize · Watermark · Export",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray55"),
        ).pack(anchor="w")

        self._build_logo_zone(panel, row=1)
        self._build_input_zone(panel, row=2)
        self._build_settings(panel, row=3)
        ctk.CTkFrame(panel, fg_color="transparent").grid(row=4, column=0, sticky="nsew")
        self._build_progress_section(panel, row=5)
        self._build_footer(panel, row=6)

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
        ctk.CTkLabel(
            txt, text="โลโก้ (.png)",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w")
        self.logo_name_label = ctk.CTkLabel(
            txt, text="ยังไม่ได้เลือก",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray55"),
            wraplength=130, justify="left",
        )
        self.logo_name_label.pack(anchor="w")

        ctk.CTkButton(
            self.logo_card, text="เลือก",
            width=58, height=30, font=ctk.CTkFont(size=12),
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
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        self.image_count_badge = ctk.CTkLabel(
            header, text="",
            font=ctk.CTkFont(size=11),
            fg_color=TEAL, text_color="white", corner_radius=8,
        )

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.grid(row=1, column=0, padx=14, pady=(0, 6), sticky="ew")
        btn_row.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(
            btn_row, text="เลือกหลายไฟล์",
            height=34, font=ctk.CTkFont(size=12),
            command=self._choose_files,
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(
            btn_row, text="เลือกโฟลเดอร์",
            height=34, font=ctk.CTkFont(size=12),
            command=self._choose_folder,
        ).grid(row=0, column=1, padx=(4, 0), sticky="ew")

        self.clear_button = ctk.CTkButton(
            card, text="🗑  ล้างรายการทั้งหมด",
            height=28, font=ctk.CTkFont(size=11),
            fg_color="transparent",
            text_color=("gray40", "gray60"),
            hover_color=("gray80", "gray28"),
            border_width=1,
            border_color=("gray70", "gray40"),
            command=self._clear_images,
        )
        self.clear_button.grid(row=2, column=0, padx=14, pady=(0, 6), sticky="ew")
        self.clear_button.grid_remove()

        self.input_status_label = ctk.CTkLabel(
            card, text="ยังไม่ได้เลือกรูปภาพ",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray55"),
        )
        self.input_status_label.grid(row=3, column=0, padx=14, pady=(0, 10), sticky="w")

    def _build_settings(self, parent: ctk.CTkFrame, row: int) -> None:
        self.settings_card = ctk.CTkFrame(parent, corner_radius=12)
        self.settings_card.grid(row=row, column=0, padx=12, pady=(0, 8), sticky="ew")
        self.settings_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.settings_card, text="⚙  ตั้งค่าโลโก้",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=14, pady=(12, 8), sticky="w")

        ctk.CTkLabel(
            self.settings_card, text="ตำแหน่ง", font=ctk.CTkFont(size=12),
        ).grid(row=1, column=0, padx=14, pady=(0, 4), sticky="w")

        ctk.CTkOptionMenu(
            self.settings_card,
            values=list(POSITION_THAI.values()),
            variable=self.position_thai_var,
            command=self._on_position_changed,
        ).grid(row=2, column=0, padx=14, pady=(0, 6), sticky="ew")

        self.custom_pos_label = ctk.CTkLabel(
            self.settings_card,
            text="📍 กำหนดเอง  (ลากโลโก้บน preview)",
            font=ctk.CTkFont(size=11), text_color=TEAL,
        )
        self.custom_pos_label.grid(row=3, column=0, padx=14, pady=(0, 2), sticky="w")
        self.custom_pos_label.grid_remove()

        self.reset_pos_button = ctk.CTkButton(
            self.settings_card, text="รีเซ็ตตำแหน่ง",
            height=26, font=ctk.CTkFont(size=11),
            fg_color=("gray78", "gray32"),
            text_color=("gray10", "gray90"),
            hover_color=("gray68", "gray42"),
            command=self._reset_logo_position,
        )
        self.reset_pos_button.grid(row=4, column=0, padx=14, pady=(0, 6), sticky="ew")
        self.reset_pos_button.grid_remove()

        scale_header = ctk.CTkFrame(self.settings_card, fg_color="transparent")
        scale_header.grid(row=5, column=0, padx=14, pady=(4, 4), sticky="ew")
        scale_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            scale_header, text="ขนาดโลโก้", font=ctk.CTkFont(size=12),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            scale_header, textvariable=self.scale_display_var,
            font=ctk.CTkFont(size=12), text_color=TEAL,
        ).grid(row=0, column=1, sticky="e")

        ctk.CTkSlider(
            self.settings_card,
            from_=5, to=40,
            variable=self.logo_scale_var,
            button_color=TEAL, button_hover_color=TEAL_DARK, progress_color=TEAL,
            command=self._on_scale_changed,
        ).grid(row=6, column=0, padx=14, pady=(0, 8), sticky="ew")

        ctk.CTkLabel(
            self.settings_card, text="ขนาดเอาต์พุต", font=ctk.CTkFont(size=12),
        ).grid(row=7, column=0, padx=14, pady=(8, 4), sticky="w")

        ctk.CTkSegmentedButton(
            self.settings_card,
            values=[OUTPUT_SIZE_RESIZE_1280, OUTPUT_SIZE_ORIGINAL],
            variable=self.output_size_var,
            selected_color=TEAL,
            selected_hover_color=TEAL_DARK,
            font=ctk.CTkFont(size=11),
            command=self._on_output_size_changed,
        ).grid(row=8, column=0, padx=14, pady=(0, 8), sticky="ew")

        ctk.CTkLabel(
            self.settings_card,
            text="💡 ลากโลโก้บน preview · Scroll ปรับขนาด",
            font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray55"),
        ).grid(row=9, column=0, padx=14, pady=(0, 12), sticky="w")

    def _build_progress_section(self, parent: ctk.CTkFrame, row: int) -> None:
        self.progress_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.progress_frame.grid(row=row, column=0, padx=12, pady=(0, 4), sticky="ew")
        self.progress_frame.grid_columnconfigure(0, weight=1)
        self.progress_frame.grid_remove()

        ctk.CTkLabel(
            self.progress_frame, textvariable=self.status_var,
            font=ctk.CTkFont(size=11),
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
            height=52, font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=TEAL, hover_color=TEAL_DARK,
            command=self._start_processing,
            state="disabled",
        )
        self.start_button.grid(row=0, column=0, sticky="ew")

        self.open_folder_button = ctk.CTkButton(
            footer, text="📂  เปิดโฟลเดอร์ผลลัพธ์",
            height=36, font=ctk.CTkFont(size=12),
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
        bg = self.filmstrip_inner.cget("bg")
        for p, container in self._thumb_containers.items():
            container.configure(bg=TEAL if p == path else bg)
        self._render_preview(path)

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

            # Prepare logo at full resolution
            logo_w = max(1, round(base_w * self.logo_scale_var.get() / 100))
            logo_h = max(1, round(logo_w * self._logo_pil.height / self._logo_pil.width))
            logo_resized = self._logo_pil.resize(
                (logo_w, logo_h), Image.Resampling.LANCZOS)

            # Compute logo position in full-res image coords
            if self._logo_pos_ratio is not None:
                lx = max(0, min(
                    round(self._logo_pos_ratio[0] * base_w), base_w - logo_w))
                ly = max(0, min(
                    round(self._logo_pos_ratio[1] * base_h), base_h - logo_h))
            else:
                pos_key = THAI_TO_POSITION.get(
                    self.position_thai_var.get(), "bottom-right")
                lx, ly = calculate_position(
                    base.size, (logo_w, logo_h), pos_key, 0, 0, 0)

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
        new_val = max(5, min(40, self.logo_scale_var.get() + delta))
        self.logo_scale_var.set(new_val)
        self.scale_display_var.set(f"{new_val}%")
        self._schedule_preview()

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

        # Store as ratio of full-res image
        self._logo_pos_ratio = (
            (new_cx - ox) / (bw * scale),
            (new_cy - oy) / (bh * scale),
        )

        # Show indicator
        self.custom_pos_label.grid(row=3, column=0, padx=14, pady=(0, 2), sticky="w")
        self.reset_pos_button.grid(row=4, column=0, padx=14, pady=(0, 6), sticky="ew")

    # ═══════════════════════════════════════════════════════════════════
    # SETTINGS HELPERS
    # ═══════════════════════════════════════════════════════════════════

    def _on_output_size_changed(self, _: str) -> None:
        self._schedule_preview()

    def _on_position_changed(self, _: str) -> None:
        self._logo_pos_ratio = None
        self.custom_pos_label.grid_remove()
        self.reset_pos_button.grid_remove()
        self._schedule_preview()

    def _reset_logo_position(self) -> None:
        self._logo_pos_ratio = None
        self.custom_pos_label.grid_remove()
        self.reset_pos_button.grid_remove()
        self._schedule_preview()

    def _on_scale_changed(self, value: float) -> None:
        self.scale_display_var.set(f"{int(value)}%")
        self._schedule_preview()

    def _get_settings(self) -> PlacementSettings:
        pos = THAI_TO_POSITION.get(self.position_thai_var.get(), "bottom-right")
        return PlacementSettings(
            landscape_position=pos,
            portrait_position=pos,
            output_size_mode=self.output_size_var.get(),
            logo_scale_percent=self.logo_scale_var.get(),
            margin=0,
        )

    def _build_settings_by_path(self) -> dict[Path, PlacementSettings]:
        """Per-image settings when logo was dragged to a custom position."""
        if self._logo_pos_ratio is None or self._logo_pil is None:
            return {}

        ratio_x, ratio_y = self._logo_pos_ratio
        scale_pct = self.logo_scale_var.get()
        result: dict[Path, PlacementSettings] = {}

        for path in self.image_paths:
            try:
                with Image.open(path) as img:
                    orig_w, orig_h = img.size
                out_w = TARGET_WIDTH
                out_h = round(TARGET_WIDTH / orig_w * orig_h)
                logo_w = max(1, round(out_w * scale_pct / 100))
                logo_h = max(1, round(
                    logo_w * self._logo_pil.height / self._logo_pil.width))
                logo_x = max(0, min(round(ratio_x * out_w), out_w - logo_w))
                logo_y = max(0, min(round(ratio_y * out_h), out_h - logo_h))
                result[path] = PlacementSettings(
                    landscape_position="top-left",
                    portrait_position="top-left",
                    margin=0,
                    offset_x=logo_x,
                    offset_y=logo_y,
                    logo_scale_percent=scale_pct,
                )
            except Exception:
                pass
        return result

    def _update_start_button(self) -> None:
        if self.logo_path and self.image_paths:
            self.start_button.configure(state="normal")
        else:
            self.start_button.configure(state="disabled")

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