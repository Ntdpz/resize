from __future__ import annotations
from pathlib import Path
from tkinter import filedialog
import customtkinter as ctk  # type: ignore[import-untyped]
from PIL import Image  # type: ignore[import-untyped]
from core.models import PlacementSettings
from ui._mixins._constants import TEAL,POSITION_THAI,THAI_TO_POSITION,_QUEUE_GAP


class LogoMixin:

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

