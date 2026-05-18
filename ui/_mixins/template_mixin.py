from __future__ import annotations
from pathlib import Path
from tkinter import messagebox
import customtkinter as ctk  # type: ignore[import-untyped]
from PIL import Image  # type: ignore[import-untyped]
from core import template_store
from ui._mixins._constants import TEAL,TEAL_DARK,POSITION_THAI,THAI_TO_POSITION


class TemplateMixin:

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

