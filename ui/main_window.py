from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import cast

import customtkinter as ctk  # type: ignore[import-untyped]
from PIL import Image, ImageTk  # type: ignore[import-untyped]

from core.image_ops import build_watermark_scene, create_preview_base
from core.models import (
    OUTPUT_SIZE_ORIGINAL,
    OUTPUT_SIZE_RESIZE_1280,
    POSITION_PRESETS,
    BatchRequest,
    PlacementSettings,
    ProcessedFile,
)
from core.processor import discover_images, get_output_folder, process_batch


ProgressPayload = tuple[int, int, str]
AppEvent = tuple[str, object]
PREVIEW_IMAGE_SIZE = (320, 220)
LOGO_PREVIEW_SIZE = (180, 180)
SOURCE_PREVIEW_SIZE = (220, 220)
RESULT_CANVAS_SIZE = (360, 520)


class AutoWatermarkWindow(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Auto Watermark & Resize Tool")
        self.geometry("1360x880")
        self.minsize(1120, 760)

        self.logo_path: Path | None = None
        self.selection_anchor_path: Path | None = None
        self.selected_paths: tuple[Path, ...] = ()
        self.preview_source_path: Path | None = None
        self.last_output_folder: Path | None = None

        self._worker: threading.Thread | None = None
        self._events: queue.Queue[AppEvent] = queue.Queue()

        self._logo_preview_image: ctk.CTkImage | None = None
        self._source_preview_image: ctk.CTkImage | None = None
        self._result_preview_base_image: ImageTk.PhotoImage | None = None
        self._result_preview_logo_image: ImageTk.PhotoImage | None = None
        self._result_preview_logo_bbox: tuple[int, int, int, int] | None = None
        self._result_preview_anchor_position: tuple[int, int] | None = None
        self._result_preview_drag_origin: tuple[int, int] | None = None
        self._result_preview_drag_position: tuple[int, int] | None = None

        self.selection_mode_var = ctk.StringVar(value="folder")
        self.output_size_var = ctk.StringVar(value=OUTPUT_SIZE_RESIZE_1280)
        self.landscape_position_var = ctk.StringVar(value="bottom-right")
        self.portrait_position_var = ctk.StringVar(value="top-right")
        self.offset_x_var = ctk.IntVar(value=0)
        self.offset_y_var = ctk.IntVar(value=0)
        self.logo_scale_var = ctk.IntVar(value=18)

        self.progress_var = ctk.DoubleVar(value=0)
        self.status_var = ctk.StringVar(value="พร้อมเริ่มทำงาน")
        self.logo_name_var = ctk.StringVar(value="ยังไม่ได้เลือกโลโก้")
        self.source_name_var = ctk.StringVar(
            value="ยังไม่ได้เลือกรูปหรือโฟลเดอร์"
        )
        self.image_count_var = ctk.StringVar(value="โหมดโฟลเดอร์")
        self.output_size_note_var = ctk.StringVar(
            value="ผลลัพธ์จะถูกย่อให้กว้าง 1280px"
        )
        self.scale_value_var = ctk.StringVar(value="18%")
        self.offset_x_value_var = ctk.StringVar(value="0 px")
        self.offset_y_value_var = ctk.StringVar(value="0 px")

        self._build_layout()
        self._render_previews()
        self.after(120, self._poll_events)

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        container = ctk.CTkScrollableFrame(self, corner_radius=20)
        container.grid(row=0, column=0, padx=18, pady=18, sticky="nsew")
        container.grid_columnconfigure(0, minsize=420)
        container.grid_columnconfigure(1, weight=1)
        container.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(container, fg_color="transparent")
        header.grid(
            row=0,
            column=0,
            columnspan=2,
            padx=24,
            pady=(24, 12),
            sticky="ew",
        )
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Auto Watermark & Resize Tool",
            font=ctk.CTkFont(size=28, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text=(
                "เลือกรูปเดี่ยวหรือทั้งโฟลเดอร์ พร้อมดู preview "
                "โลโก้ ต้นฉบับ และผลลัพธ์ก่อนเริ่มงาน"
            ),
            text_color=("#5b6472", "#b0b8c4"),
            font=ctk.CTkFont(size=14),
        ).grid(row=1, column=0, pady=(4, 0), sticky="w")

        left_panel = ctk.CTkFrame(container)
        left_panel.grid(
            row=1,
            column=0,
            padx=(24, 12),
            pady=(0, 24),
            sticky="nsew",
        )
        left_panel.grid_columnconfigure(0, weight=1)

        right_panel = ctk.CTkFrame(container)
        right_panel.grid(
            row=1,
            column=1,
            padx=(12, 24),
            pady=(0, 24),
            sticky="nsew",
        )
        right_panel.grid_columnconfigure(0, weight=0, minsize=220)
        right_panel.grid_columnconfigure(1, weight=0, minsize=240)
        right_panel.grid_columnconfigure(2, weight=1, minsize=380)
        right_panel.grid_rowconfigure(1, weight=1)

        self._build_selection_section(left_panel)
        self._build_controls_section(left_panel)
        self._build_status_section(left_panel)
        self._build_footer(left_panel)
        self._build_preview_section(right_panel)

    def _build_selection_section(self, parent: ctk.CTkFrame) -> None:
        selection_frame = ctk.CTkFrame(parent)
        selection_frame.grid(
            row=0,
            column=0,
            padx=18,
            pady=(18, 10),
            sticky="ew",
        )
        selection_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            selection_frame,
            text="1. เลือกโลโก้และรูปต้นฉบับ",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=(18, 12), sticky="w")

        self._build_picker_card(
            selection_frame,
            row=1,
            title="ไฟล์โลโก้ PNG",
            value_var=self.logo_name_var,
            action_text="เลือกไฟล์โลโก้ .png",
            callback=self._choose_logo,
        )

        source_card = ctk.CTkFrame(selection_frame)
        source_card.grid(row=2, column=0, padx=18, pady=(10, 18), sticky="ew")
        source_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            source_card,
            text="รูปต้นฉบับ",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=(18, 10), sticky="w")
        ctk.CTkSegmentedButton(
            source_card,
            values=["folder", "single"],
            variable=self.selection_mode_var,
            command=self._on_selection_mode_changed,
        ).grid(row=1, column=0, padx=18, pady=(0, 12), sticky="ew")
        ctk.CTkLabel(
            source_card,
            textvariable=self.source_name_var,
            wraplength=340,
            justify="left",
        ).grid(row=2, column=0, padx=18, pady=(0, 6), sticky="w")
        ctk.CTkLabel(
            source_card,
            textvariable=self.image_count_var,
            text_color=("#5b6472", "#b0b8c4"),
        ).grid(row=3, column=0, padx=18, pady=(0, 10), sticky="w")
        self.source_picker_button = ctk.CTkButton(
            source_card,
            text="เลือกโฟลเดอร์รูปภาพ",
            command=self._choose_source,
        )
        self.source_picker_button.grid(
            row=4,
            column=0,
            padx=18,
            pady=(0, 18),
            sticky="ew",
        )

    def _build_controls_section(self, parent: ctk.CTkFrame) -> None:
        controls = ctk.CTkFrame(parent)
        controls.grid(row=1, column=0, padx=18, pady=10, sticky="ew")
        controls.grid_columnconfigure((0, 1), weight=1)

        left_controls = ctk.CTkFrame(controls)
        left_controls.grid(row=0, column=0, padx=(0, 8), pady=0, sticky="nsew")
        left_controls.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            left_controls,
            text="2. ตำแหน่งโลโก้",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(
            row=0,
            column=0,
            columnspan=2,
            padx=18,
            pady=(18, 10),
            sticky="w",
        )
        self._add_option_menu(
            left_controls,
            row=1,
            label="Landscape",
            variable=self.landscape_position_var,
            values=list(POSITION_PRESETS),
        )
        self._add_option_menu(
            left_controls,
            row=2,
            label="Portrait / Square",
            variable=self.portrait_position_var,
            values=list(POSITION_PRESETS),
        )
        ctk.CTkLabel(
            left_controls,
            text="Output Size",
        ).grid(row=3, column=0, padx=18, pady=(10, 6), sticky="w")
        ctk.CTkSegmentedButton(
            left_controls,
            values=[OUTPUT_SIZE_RESIZE_1280, OUTPUT_SIZE_ORIGINAL],
            variable=self.output_size_var,
            command=self._on_output_size_changed,
            dynamic_resizing=False,
        ).grid(
            row=4,
            column=0,
            columnspan=2,
            padx=18,
            pady=(0, 6),
            sticky="ew",
        )
        ctk.CTkLabel(
            left_controls,
            textvariable=self.output_size_note_var,
            wraplength=320,
            justify="left",
            text_color=("#5b6472", "#b0b8c4"),
        ).grid(
            row=5,
            column=0,
            columnspan=2,
            padx=18,
            pady=(0, 18),
            sticky="w",
        )

        right_controls = ctk.CTkFrame(controls)
        right_controls.grid(
            row=0,
            column=1,
            padx=(8, 0),
            pady=0,
            sticky="nsew",
        )
        right_controls.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            right_controls,
            text="3. ขนาดและระยะขยับ",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=(18, 10), sticky="w")
        self._add_slider(
            right_controls,
            row=1,
            label="ขนาดโลโก้",
            variable=self.logo_scale_var,
            display_var=self.scale_value_var,
            from_=5,
            to=40,
            suffix="%",
        )
        self._add_slider(
            right_controls,
            row=2,
            label="เลื่อนแนวนอน",
            variable=self.offset_x_var,
            display_var=self.offset_x_value_var,
            from_=-300,
            to=300,
            suffix=" px",
        )
        self._add_slider(
            right_controls,
            row=3,
            label="เลื่อนแนวตั้ง",
            variable=self.offset_y_var,
            display_var=self.offset_y_value_var,
            from_=-300,
            to=300,
            suffix=" px",
        )

    def _build_status_section(self, parent: ctk.CTkFrame) -> None:
        progress_frame = ctk.CTkFrame(parent)
        progress_frame.grid(row=2, column=0, padx=18, pady=10, sticky="ew")
        progress_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            progress_frame,
            text="4. สถานะ",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=(18, 10), sticky="w")
        ctk.CTkLabel(
            progress_frame,
            textvariable=self.status_var,
            font=ctk.CTkFont(size=14),
        ).grid(row=1, column=0, padx=18, pady=(0, 10), sticky="w")

        self.progress_bar = ctk.CTkProgressBar(
            progress_frame,
            variable=self.progress_var,
        )
        self.progress_bar.grid(
            row=2,
            column=0,
            padx=18,
            pady=(0, 18),
            sticky="ew",
        )
        self.progress_bar.set(0)

    def _build_footer(self, parent: ctk.CTkFrame) -> None:
        footer = ctk.CTkFrame(parent, fg_color="transparent")
        footer.grid(row=3, column=0, padx=18, pady=(10, 18), sticky="ew")
        footer.grid_columnconfigure((0, 1), weight=1)

        self.start_button = ctk.CTkButton(
            footer,
            text="START / เริ่มประมวลผล",
            height=52,
            font=ctk.CTkFont(size=17, weight="bold"),
            command=self._start_processing,
        )
        self.start_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.open_output_button = ctk.CTkButton(
            footer,
            text="เปิดโฟลเดอร์ผลลัพธ์",
            height=52,
            command=self._open_output_folder,
            state="disabled",
        )
        self.open_output_button.grid(row=0, column=1, padx=(8, 0), sticky="ew")

    def _build_preview_section(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(
            parent,
            text="Preview",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(
            row=0,
            column=0,
            columnspan=3,
            padx=8,
            pady=(18, 12),
            sticky="w",
        )

        self.logo_preview_label = self._build_preview_card(
            parent,
            column=0,
            title="Logo",
            placeholder="ยังไม่มีโลโก้",
            width=220,
            height=220,
        )
        self.source_preview_label = self._build_preview_card(
            parent,
            column=1,
            title="Source",
            placeholder="ยังไม่มีรูปต้นฉบับ",
            width=240,
            height=300,
        )
        self.result_preview_canvas = self._build_result_preview_card(
            parent,
            column=2,
            title="Result",
        )

    def _build_picker_card(
        self,
        parent: ctk.CTkFrame,
        row: int,
        title: str,
        value_var: ctk.StringVar,
        action_text: str,
        callback,
    ) -> None:
        frame = ctk.CTkFrame(parent)
        frame.grid(row=row, column=0, padx=18, pady=0, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            frame,
            text=title,
            font=ctk.CTkFont(size=17, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=(18, 10), sticky="w")
        ctk.CTkLabel(
            frame,
            textvariable=value_var,
            wraplength=340,
            justify="left",
        ).grid(row=1, column=0, padx=18, pady=(0, 10), sticky="w")
        ctk.CTkButton(frame, text=action_text, command=callback).grid(
            row=2,
            column=0,
            padx=18,
            pady=(0, 18),
            sticky="ew",
        )

    def _build_preview_card(
        self,
        parent: ctk.CTkFrame,
        column: int,
        title: str,
        placeholder: str,
        width: int = 340,
        height: int = 250,
    ) -> ctk.CTkLabel:
        frame = ctk.CTkFrame(parent)
        frame.grid(row=1, column=column, padx=8, pady=(0, 18), sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            frame,
            text=title,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=(16, 10), sticky="w")

        preview_label = ctk.CTkLabel(
            frame,
            text=placeholder,
            width=width,
            height=height,
            corner_radius=14,
            fg_color=("#f1f3f7", "#1f2430"),
            text_color=("#6a7280", "#c4cad4"),
        )
        preview_label.grid(
            row=1,
            column=0,
            padx=16,
            pady=(0, 16),
            sticky="nsew",
        )
        return preview_label

    def _build_result_preview_card(
        self,
        parent: ctk.CTkFrame,
        column: int,
        title: str,
    ) -> tk.Canvas:
        frame = ctk.CTkFrame(parent)
        frame.grid(row=1, column=column, padx=8, pady=(0, 18), sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            frame,
            text=title,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")
        ctk.CTkLabel(
            frame,
            text="ลากโลโก้เพื่อขยับ และหมุนล้อเมาส์เพื่อย่อ/ขยาย",
            text_color=("#5b6472", "#b0b8c4"),
        ).grid(row=1, column=0, padx=16, pady=(0, 10), sticky="w")

        canvas = tk.Canvas(
            frame,
            width=RESULT_CANVAS_SIZE[0],
            height=RESULT_CANVAS_SIZE[1],
            bd=0,
            highlightthickness=0,
            background="#1f2430",
            cursor="arrow",
        )
        canvas.grid(row=2, column=0, padx=16, pady=(0, 16), sticky="nsew")
        canvas.bind("<Button-1>", self._on_result_preview_press)
        canvas.bind("<B1-Motion>", self._on_result_preview_drag)
        canvas.bind("<ButtonRelease-1>", self._on_result_preview_release)
        canvas.bind("<Motion>", self._on_result_preview_motion)
        canvas.bind("<MouseWheel>", self._on_result_preview_wheel)
        return canvas

    def _add_option_menu(
        self,
        parent: ctk.CTkFrame,
        row: int,
        label: str,
        variable: ctk.StringVar,
        values: list[str],
    ) -> None:
        ctk.CTkLabel(parent, text=label).grid(
            row=row,
            column=0,
            padx=18,
            pady=10,
            sticky="w",
        )
        ctk.CTkOptionMenu(
            parent,
            variable=variable,
            values=values,
            command=lambda _value: self._render_previews(),
        ).grid(row=row, column=1, padx=(0, 18), pady=10, sticky="ew")

    def _add_slider(
        self,
        parent: ctk.CTkFrame,
        row: int,
        label: str,
        variable: ctk.IntVar,
        display_var: ctk.StringVar,
        from_: int,
        to: int,
        suffix: str,
    ) -> None:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, padx=18, pady=8, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)

        def on_change(value: float) -> None:
            display_var.set(f"{round(value)}{suffix}")
            self._render_previews()

        ctk.CTkLabel(frame, text=label).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(frame, textvariable=display_var).grid(
            row=0,
            column=1,
            sticky="e",
        )
        ctk.CTkSlider(
            frame,
            from_=from_,
            to=to,
            number_of_steps=to - from_,
            variable=variable,
            command=on_change,
        ).grid(row=1, column=0, columnspan=2, pady=(6, 0), sticky="ew")

    def _on_selection_mode_changed(self, mode: str) -> None:
        self.selection_mode_var.set(mode)
        self.selection_anchor_path = None
        self.selected_paths = ()
        self.preview_source_path = None
        self.source_name_var.set("ยังไม่ได้เลือกรูปหรือโฟลเดอร์")
        self.image_count_var.set(
            "โหมดโฟลเดอร์" if mode == "folder" else "โหมดรูปเดี่ยว"
        )
        button_text = (
            "เลือกโฟลเดอร์รูปภาพ"
            if mode == "folder"
            else "เลือกไฟล์รูปภาพ"
        )
        self.source_picker_button.configure(text=button_text)
        self._set_status("สลับโหมดเลือกต้นฉบับแล้ว")
        self._render_previews()

    def _on_output_size_changed(self, mode: str) -> None:
        self.output_size_var.set(mode)
        if mode == OUTPUT_SIZE_ORIGINAL:
            self.output_size_note_var.set("ผลลัพธ์จะคงขนาดต้นฉบับไว้")
            self._set_status("เปลี่ยนเป็นโหมด Original Size แล้ว")
        else:
            self.output_size_note_var.set(
                "ผลลัพธ์จะถูกย่อให้กว้าง 1280px"
            )
            self._set_status("เปลี่ยนเป็นโหมด Resize 1280px แล้ว")
        self._render_previews()

    def _choose_logo(self) -> None:
        selection = filedialog.askopenfilename(
            title="เลือกไฟล์โลโก้ PNG",
            filetypes=(("PNG files", "*.png"), ("All files", "*.*")),
        )
        if not selection:
            return

        self.logo_path = Path(selection)
        self.logo_name_var.set(self.logo_path.name)
        self._set_status("เลือกโลโก้เรียบร้อยแล้ว")
        self._render_previews()

    def _choose_source(self) -> None:
        if self.selection_mode_var.get() == "single":
            self._choose_single_image()
            return
        self._choose_folder()

    def _choose_single_image(self) -> None:
        selection = filedialog.askopenfilename(
            title="เลือกไฟล์รูปภาพ",
            filetypes=(
                ("Image files", "*.jpg;*.jpeg;*.png"),
                ("All files", "*.*"),
            ),
        )
        if not selection:
            return

        selected_path = Path(selection)
        self.selection_anchor_path = selected_path
        self.selected_paths = (selected_path,)
        self.preview_source_path = selected_path
        self.source_name_var.set(str(selected_path))
        self.image_count_var.set("เลือกรูปเดี่ยว 1 ไฟล์")
        self._set_status("เลือกไฟล์รูปภาพเรียบร้อยแล้ว")
        self._render_previews()

    def _choose_folder(self) -> None:
        selection = filedialog.askdirectory(title="เลือกโฟลเดอร์รูปภาพ")
        if not selection:
            return

        source_folder = Path(selection)
        images = tuple(discover_images(source_folder))
        self.selection_anchor_path = source_folder
        self.selected_paths = images
        self.preview_source_path = images[0] if images else None
        self.source_name_var.set(str(source_folder))
        self.image_count_var.set(f"พบรูปภาพ {len(images)} ไฟล์")
        self._set_status("เลือกโฟลเดอร์เรียบร้อยแล้ว")
        self._render_previews()

    def _current_settings(self) -> PlacementSettings:
        return PlacementSettings(
            landscape_position=self.landscape_position_var.get(),
            portrait_position=self.portrait_position_var.get(),
            output_size_mode=self.output_size_var.get(),
            offset_x=self.offset_x_var.get(),
            offset_y=self.offset_y_var.get(),
            logo_scale_percent=self.logo_scale_var.get(),
        )

    def _build_request(self) -> BatchRequest | None:
        if self.logo_path is None:
            return None
        if not self.selected_paths:
            return None

        anchor_path = self.selection_anchor_path or self.selected_paths[0]
        return BatchRequest(
            logo_path=self.logo_path,
            settings=self._current_settings(),
            source_folder=anchor_path if anchor_path.is_dir() else None,
            source_paths=self.selected_paths,
            output_folder=get_output_folder(anchor_path),
        )

    def _start_processing(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return

        request = self._build_request()
        if request is None:
            if self.logo_path is None:
                messagebox.showwarning(
                    "ยังไม่พร้อม",
                    "กรุณาเลือกไฟล์โลโก้ PNG ก่อนเริ่มงาน",
                )
                return
            messagebox.showwarning(
                "ยังไม่พร้อม",
                "กรุณาเลือกไฟล์รูปภาพหรือโฟลเดอร์ก่อนเริ่มงาน",
            )
            return

        if not request.source_paths:
            messagebox.showwarning(
                "ไม่พบรูปภาพ",
                "รายการที่เลือกยังไม่มีไฟล์ .jpg, .jpeg หรือ .png",
            )
            return

        total_files = len(request.source_paths)
        self.progress_var.set(0)
        self.open_output_button.configure(state="disabled")
        self.start_button.configure(state="disabled")
        self._set_status(f"Processing... 0/{total_files}")

        def run_worker() -> None:
            try:
                results = process_batch(
                    request,
                    progress_callback=self._push_progress,
                )
                self._events.put(("done", results))
            except Exception as exc:  # noqa: BLE001
                self._events.put(("error", str(exc)))

        self._worker = threading.Thread(target=run_worker, daemon=True)
        self._worker.start()

    def _push_progress(
        self,
        index: int,
        total: int,
        current_path: Path,
    ) -> None:
        self._events.put(("progress", (index, total, current_path.name)))

    def _poll_events(self) -> None:
        try:
            while True:
                event_name, payload = self._events.get_nowait()
                if event_name == "progress":
                    index, total, file_name = cast(ProgressPayload, payload)
                    self.progress_var.set(index / total)
                    self._set_status(
                        f"Processing... {index}/{total} - {file_name}"
                    )
                elif event_name == "done":
                    self._handle_done(cast(list[ProcessedFile], payload))
                elif event_name == "error":
                    self._handle_error(cast(str, payload))
        except queue.Empty:
            pass
        finally:
            self.after(120, self._poll_events)

    def _handle_done(self, results: list[ProcessedFile]) -> None:
        self.progress_var.set(1)
        self.start_button.configure(state="normal")
        self.last_output_folder = (
            results[0].output_path.parent if results else None
        )
        if self.last_output_folder is not None:
            self.open_output_button.configure(state="normal")

        success_count = len(results)
        self._set_status(f"เสร็จสิ้น! ประมวลผลครบ {success_count} ไฟล์")
        messagebox.showinfo(
            "เสร็จสิ้น",
            "ประมวลผลรูปภาพเรียบร้อยแล้ว "
            f"{success_count} ไฟล์\n"
            "ผลลัพธ์ถูกบันทึกไว้ที่:\n"
            f"{self.last_output_folder}",
        )
        self._render_previews()

    def _handle_error(self, message: str) -> None:
        self.start_button.configure(state="normal")
        self.progress_var.set(0)
        self._set_status("เกิดข้อผิดพลาดระหว่างประมวลผล")
        messagebox.showerror("เกิดข้อผิดพลาด", message)

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _render_previews(self) -> None:
        self._set_preview_image(
            self.logo_preview_label,
            self._load_logo_preview(),
            "_logo_preview_image",
            "ยังไม่มีโลโก้",
        )
        self._set_preview_image(
            self.source_preview_label,
            self._load_source_preview(),
            "_source_preview_image",
            "ยังไม่มีรูปต้นฉบับ",
        )
        self._render_result_preview()

    def _load_logo_preview(self) -> Image.Image | None:
        if self.logo_path is None:
            return None
        return self._load_thumbnail_from_path(
            self.logo_path,
            keep_alpha=True,
            target_size=LOGO_PREVIEW_SIZE,
        )

    def _load_source_preview(self) -> Image.Image | None:
        if self.preview_source_path is None:
            return None
        return self._load_thumbnail_from_path(
            self.preview_source_path,
            target_size=SOURCE_PREVIEW_SIZE,
        )

    def _load_result_scene(self):
        if self.logo_path is None or self.preview_source_path is None:
            return None

        try:
            with Image.open(self.preview_source_path) as source_image:
                with Image.open(self.logo_path) as logo_image:
                    return build_watermark_scene(
                        source_image,
                        logo_image,
                        self._current_settings(),
                        preview=True,
                    )
        except OSError:
            return None

    def _render_result_preview(self) -> None:
        canvas = self.result_preview_canvas
        canvas.delete("all")

        scene = self._load_result_scene()
        if scene is None:
            self._result_preview_base_image = None
            self._result_preview_logo_image = None
            self._result_preview_logo_bbox = None
            self._result_preview_anchor_position = None
            canvas.create_text(
                RESULT_CANVAS_SIZE[0] / 2,
                RESULT_CANVAS_SIZE[1] / 2,
                text="ยังไม่มีผลลัพธ์ preview",
                fill="#c4cad4",
                font=("Segoe UI", 14),
            )
            return

        canvas_width = max(canvas.winfo_width(), RESULT_CANVAS_SIZE[0])
        canvas_height = max(canvas.winfo_height(), RESULT_CANVAS_SIZE[1])
        origin_x = round((canvas_width - scene.base_image.width) / 2)
        origin_y = round((canvas_height - scene.base_image.height) / 2)

        base_image = scene.base_image.copy()
        logo_image = scene.logo_image.copy()
        self._result_preview_base_image = ImageTk.PhotoImage(base_image)
        self._result_preview_logo_image = ImageTk.PhotoImage(logo_image)
        canvas.create_image(
            origin_x,
            origin_y,
            anchor=tk.NW,
            image=self._result_preview_base_image,
        )

        logo_x = origin_x + scene.position[0]
        logo_y = origin_y + scene.position[1]
        canvas.create_image(
            logo_x,
            logo_y,
            anchor=tk.NW,
            image=self._result_preview_logo_image,
        )

        bbox = (
            logo_x,
            logo_y,
            logo_x + logo_image.width,
            logo_y + logo_image.height,
        )
        self._result_preview_logo_bbox = bbox
        self._result_preview_anchor_position = (
            scene.position[0] - self._current_settings().offset_x,
            scene.position[1] - self._current_settings().offset_y,
        )
        canvas.create_rectangle(
            bbox[0],
            bbox[1],
            bbox[2],
            bbox[3],
            outline="#3b8edb",
            width=2,
            dash=(4, 3),
        )

    def _point_in_logo_preview(self, x: int, y: int) -> bool:
        if self._result_preview_logo_bbox is None:
            return False
        left, top, right, bottom = self._result_preview_logo_bbox
        return left <= x <= right and top <= y <= bottom

    def _on_result_preview_motion(self, event: tk.Event) -> None:
        cursor = (
            "fleur"
            if self._point_in_logo_preview(event.x, event.y)
            else "arrow"
        )
        self.result_preview_canvas.configure(cursor=cursor)

    def _on_result_preview_press(self, event: tk.Event) -> None:
        if not self._point_in_logo_preview(event.x, event.y):
            self._result_preview_drag_origin = None
            self._result_preview_drag_position = None
            return

        self._result_preview_drag_origin = (event.x, event.y)
        current_scene = self._load_result_scene()
        if current_scene is None:
            self._result_preview_drag_position = None
            return
        self._result_preview_drag_position = current_scene.position

    def _on_result_preview_drag(self, event: tk.Event) -> None:
        if (
            self._result_preview_drag_origin is None
            or self._result_preview_drag_position is None
            or self._result_preview_anchor_position is None
        ):
            return

        current_scene = self._load_result_scene()
        if current_scene is None:
            return

        dx = event.x - self._result_preview_drag_origin[0]
        dy = event.y - self._result_preview_drag_origin[1]
        desired_x = self._result_preview_drag_position[0] + dx
        desired_y = self._result_preview_drag_position[1] + dy

        anchor_x, anchor_y = self._result_preview_anchor_position
        min_offset_x = -anchor_x
        max_offset_x = (
            current_scene.base_image.width
            - current_scene.logo_image.width
            - anchor_x
        )
        min_offset_y = -anchor_y
        max_offset_y = (
            current_scene.base_image.height
            - current_scene.logo_image.height
            - anchor_y
        )
        offset_x = max(
            min_offset_x,
            min(desired_x - anchor_x, max_offset_x),
        )
        offset_y = max(
            min_offset_y,
            min(desired_y - anchor_y, max_offset_y),
        )
        self._set_offset_values(round(offset_x), round(offset_y))
        self._render_previews()

    def _on_result_preview_release(self, _event: tk.Event) -> None:
        self._result_preview_drag_origin = None
        self._result_preview_drag_position = None

    def _on_result_preview_wheel(self, event: tk.Event) -> None:
        if not self._point_in_logo_preview(event.x, event.y):
            return

        current_value = self.logo_scale_var.get()
        step = 1 if event.delta > 0 else -1
        self._set_logo_scale_value(current_value + step)
        self._render_previews()

    def _load_thumbnail_from_path(
        self,
        image_path: Path,
        keep_alpha: bool = False,
        target_size: tuple[int, int] = PREVIEW_IMAGE_SIZE,
    ) -> Image.Image | None:
        try:
            with Image.open(image_path) as image:
                preview_image = image.copy()
        except OSError:
            return None

        if keep_alpha:
            return self._thumbnail_image(
                create_preview_base(preview_image),
                target_size=target_size,
            )
        return self._thumbnail_image(preview_image, target_size=target_size)

    def _thumbnail_image(
        self,
        image: Image.Image,
        target_size: tuple[int, int] = PREVIEW_IMAGE_SIZE,
    ) -> Image.Image:
        thumbnail = image.copy()
        thumbnail.thumbnail(target_size, Image.Resampling.LANCZOS)
        return thumbnail

    def _set_offset_values(self, offset_x: int, offset_y: int) -> None:
        self.offset_x_var.set(offset_x)
        self.offset_y_var.set(offset_y)
        self.offset_x_value_var.set(f"{offset_x} px")
        self.offset_y_value_var.set(f"{offset_y} px")

    def _set_logo_scale_value(self, value: int) -> None:
        clamped_value = max(5, min(value, 40))
        self.logo_scale_var.set(clamped_value)
        self.scale_value_var.set(f"{clamped_value}%")

    def _set_preview_image(
        self,
        widget: ctk.CTkLabel,
        image: Image.Image | None,
        cache_attr: str,
        placeholder: str,
    ) -> None:
        if image is None:
            setattr(self, cache_attr, None)
            widget.configure(image=None, text=placeholder)
            return

        ctk_image = ctk.CTkImage(
            light_image=image,
            dark_image=image,
            size=image.size,
        )
        setattr(self, cache_attr, ctk_image)
        widget.configure(image=ctk_image, text="")

    def _open_output_folder(self) -> None:
        if (
            self.last_output_folder is None
            or not self.last_output_folder.exists()
        ):
            messagebox.showwarning(
                "ยังไม่พบผลลัพธ์",
                "ยังไม่มีโฟลเดอร์ผลลัพธ์ให้เปิด",
            )
            return

        os.startfile(self.last_output_folder)
