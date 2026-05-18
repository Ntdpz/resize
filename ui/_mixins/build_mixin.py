from __future__ import annotations
import tkinter as tk
import customtkinter as ctk  # type: ignore[import-untyped]
try:
    from tkinterdnd2 import DND_FILES  # type: ignore[import-untyped]
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False
    DND_FILES = None  # type: ignore[assignment]
from core.models import OUTPUT_SIZE_RESIZE_1280,OUTPUT_SIZE_ORIGINAL
from ui._mixins._constants import TEAL,TEAL_DARK,POSITION_THAI


class BuildMixin:

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


    def _draw_placeholder(self) -> None:
        self.preview_canvas.delete("all")
        w = max(self.preview_canvas.winfo_width(), 10)
        h = max(self.preview_canvas.winfo_height(), 10)
        self.preview_canvas.create_text(
            w // 2, h // 2,
            text="เลือกโลโก้และรูปภาพ\nจากนั้นคลิก thumbnail ด้านล่างเพื่อดู preview",
            fill="#606060", font=("Helvetica", 13), justify="center",
        )

