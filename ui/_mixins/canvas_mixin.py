from __future__ import annotations
import tkinter as tk
from pathlib import Path
from PIL import Image,ImageOps,ImageTk  # type: ignore[import-untyped]
from core.image_ops import calculate_position
from core.models import PlacementSettings
from ui._mixins._constants import TEAL,TARGET_WIDTH,THAI_TO_POSITION,PREVIEW_DEBOUNCE_MS


class CanvasMixin:

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

