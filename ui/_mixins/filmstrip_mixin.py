from __future__ import annotations
import threading
import tkinter as tk
from pathlib import Path
from PIL import Image,ImageOps,ImageTk  # type: ignore[import-untyped]
from ui._mixins._constants import THUMB_SIZE


class FilmstripMixin:

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

