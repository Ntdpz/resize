from __future__ import annotations
from pathlib import Path
from tkinter import filedialog
from core.models import SUPPORTED_EXTENSIONS
from ui._mixins._constants import TEAL


class InputMixin:

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

