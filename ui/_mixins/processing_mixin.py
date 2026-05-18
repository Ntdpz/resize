from __future__ import annotations
from pathlib import Path
import os,queue,threading
from tkinter import messagebox
from core.models import BatchRequest,LogoConfig,PlacementSettings
from core.processor import process_batch
from ui._mixins._constants import TEAL,THAI_TO_POSITION


class ProcessingMixin:

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
                elif event == "preview_ready":
                    self._apply_preview_result(payload)  # type: ignore[arg-type]
                elif event == "preview_error":
                    self.preview_canvas.delete("all")
                    self.preview_canvas.create_text(
                        self.preview_canvas.winfo_width() // 2,
                        self.preview_canvas.winfo_height() // 2,
                        text=f"⚠️ ไม่สามารถแสดง preview ได้\n{payload}",
                        fill="#e05555", font=("Helvetica", 12),
                        justify="center",
                    )
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

