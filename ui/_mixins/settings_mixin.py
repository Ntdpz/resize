from __future__ import annotations
from pathlib import Path
from PIL import Image  # type: ignore[import-untyped]
from core.models import PlacementSettings,OUTPUT_SIZE_ORIGINAL
from ui._mixins._constants import TEAL,TARGET_WIDTH,THAI_TO_POSITION


class SettingsMixin:

    def _on_output_size_changed(self, _: str) -> None:
        self._save_current_image_settings()
        self._schedule_preview()


    def _on_position_changed(self, _: str) -> None:
        idx = self._selected_logo_idx
        if idx < len(self._logo_positions):
            self._logo_positions[idx] = self.position_thai_var.get()
        # Clear drag ratio for current image + selected logo
        if self.selected_preview_path is not None:
            self._per_image_pos_ratios.get(
                self.selected_preview_path, {}).pop(idx, None)
        self.custom_pos_label.grid_remove()
        self.reset_pos_button.grid_remove()
        self._save_current_image_settings()
        self._schedule_preview()


    def _reset_logo_position(self) -> None:
        idx = self._selected_logo_idx
        if self.selected_preview_path is not None:
            self._per_image_pos_ratios.get(
                self.selected_preview_path, {}).pop(idx, None)
        self.custom_pos_label.grid_remove()
        self.reset_pos_button.grid_remove()
        self._save_current_image_settings()
        self._schedule_preview()


    def _on_scale_changed(self, value: float) -> None:
        v = int(value)
        self.scale_display_var.set(f"{v}%")
        idx = self._selected_logo_idx
        if idx < len(self._logo_landscape_scales):
            self._logo_landscape_scales[idx] = v
        self._save_current_image_settings()
        self._schedule_preview()


    def _on_scale_portrait_changed(self, value: float) -> None:
        v = int(value)
        self.scale_portrait_display_var.set(f"{v}%")
        idx = self._selected_logo_idx
        if idx < len(self._logo_portrait_scales):
            self._logo_portrait_scales[idx] = v
        self._save_current_image_settings()
        self._schedule_preview()


    def _on_opacity_changed(self, value: float) -> None:
        v = int(value)
        self.opacity_display_var.set(f"{v}%")
        idx = self._selected_logo_idx
        if idx < len(self._logo_opacities):
            self._logo_opacities[idx] = value / 100.0
        self._save_current_image_settings()
        self._schedule_preview()


    def _toggle_per_image_mode(self) -> None:
        pass  # kept for compatibility


    def _reset_per_image_override(self) -> None:
        pass  # kept for compatibility


    def _save_current_settings_if_per_image(self, force: bool = False) -> None:
        self._save_current_image_settings()


    def _save_current_image_settings(self) -> None:
        """Persist current UI state as a per-image per-logo override."""
        if self.selected_preview_path is None:
            return
        idx = self._selected_logo_idx
        if idx >= len(self._logo_paths):
            return
        pos = THAI_TO_POSITION.get(self.position_thai_var.get(), "bottom-right")
        l_scale = self.logo_scale_var.get()
        p_scale = self.logo_scale_portrait_var.get()
        opacity = self.opacity_var.get() / 100.0
        self._per_image_overrides.setdefault(
            self.selected_preview_path, {}
        )[idx] = PlacementSettings(
            landscape_position=pos,
            portrait_position=pos,
            output_size_mode=self.output_size_var.get(),
            logo_scale_percent=l_scale,
            landscape_logo_scale_percent=l_scale,
            portrait_logo_scale_percent=p_scale,
            margin=0,
            opacity=opacity,
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
        """Copy the current image's per-logo overrides to all images of the given orientation."""
        if self.selected_preview_path is None:
            return
        self._save_current_image_settings()
        src_overrides = self._per_image_overrides.get(self.selected_preview_path, {})
        src_ratios = self._per_image_pos_ratios.get(self.selected_preview_path, {})
        for path in self.image_paths:
            if self._get_image_orientation(path) != orientation:
                continue
            self._per_image_overrides[path] = dict(src_overrides)
            if src_ratios:
                self._per_image_pos_ratios[path] = dict(src_ratios)
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
        """Copy the current image's per-logo overrides to every loaded image."""
        if self.selected_preview_path is None:
            return
        self._save_current_image_settings()
        src_overrides = self._per_image_overrides.get(self.selected_preview_path, {})
        src_ratios = self._per_image_pos_ratios.get(self.selected_preview_path, {})
        for path in self.image_paths:
            self._per_image_overrides[path] = dict(src_overrides)
            if src_ratios:
                self._per_image_pos_ratios[path] = dict(src_ratios)
            else:
                self._per_image_pos_ratios.pop(path, None)
        self._update_filmstrip_badges()


    def _reset_all_overrides(self) -> None:
        """Clear all per-image overrides; every image reverts to global defaults."""
        self._per_image_overrides.clear()
        self._per_image_pos_ratios.clear()
        self.custom_pos_label.grid_remove()
        self.reset_pos_button.grid_remove()
        if self.selected_preview_path is not None:
            self._load_logo_settings_into_ui(self._selected_logo_idx)
        self._update_filmstrip_badges()
        self._schedule_preview()


    def _update_filmstrip_badges(self) -> None:
        """Refresh thumbnail borders: teal=selected, default=others."""
        bg = self.filmstrip_inner.cget("bg")
        for p, container in self._thumb_containers.items():
            container.configure(bg=TEAL if p == self.selected_preview_path else bg)


    def _get_settings(self) -> PlacementSettings:
        """Return image-level settings (output_size, quality). Position/scale come per-logo."""
        return PlacementSettings(
            output_size_mode=self.output_size_var.get(),
            quality=95,
            margin=0,
        )


    def _build_logo_settings_by_path(
        self,
    ) -> dict[Path, dict[int, PlacementSettings]]:
        """Build per-image per-logo PlacementSettings, embedding drag positions."""
        result: dict[Path, dict[int, PlacementSettings]] = {}

        for path in self.image_paths:
            img_overrides = self._per_image_overrides.get(path, {})
            img_ratios = self._per_image_pos_ratios.get(path, {})

            if not img_overrides and not img_ratios:
                continue

            per_logo: dict[int, PlacementSettings] = {}

            for logo_idx, logo_pil in enumerate(self._logo_pils):
                if logo_pil is None:
                    continue
                override = img_overrides.get(logo_idx)
                ratio = img_ratios.get(logo_idx)

                if ratio is None:
                    if override is not None:
                        per_logo[logo_idx] = override
                    continue

                # Drag ratio → pixel offsets
                l_scale = (
                    override.effective_landscape_scale()
                    if override else self._logo_landscape_scales[logo_idx]
                )
                p_scale = (
                    override.effective_portrait_scale()
                    if override else self._logo_portrait_scales[logo_idx]
                )
                output_size = (
                    override.output_size_mode
                    if override else self.output_size_var.get()
                )
                opacity = (
                    override.opacity
                    if override else self._logo_opacities[logo_idx]
                )
                pos_key = (
                    override.landscape_position
                    if override else THAI_TO_POSITION.get(
                        self._logo_positions[logo_idx], "top-right")
                )

                try:
                    with Image.open(path) as img:
                        orig_w, orig_h = img.size
                    if output_size == OUTPUT_SIZE_ORIGINAL:
                        out_w, out_h = orig_w, orig_h
                    else:
                        out_w = TARGET_WIDTH
                        out_h = round(TARGET_WIDTH / orig_w * orig_h)

                    orientation = "landscape" if orig_w > orig_h else "portrait"
                    scale_pct = l_scale if orientation == "landscape" else p_scale

                    logo_w = max(1, round(out_w * scale_pct / 100))
                    logo_h = max(1, round(logo_w * logo_pil.height / logo_pil.width))
                    logo_x = max(0, min(round(ratio[0] * out_w), out_w - logo_w))
                    logo_y = max(0, min(round(ratio[1] * out_h), out_h - logo_h))

                    per_logo[logo_idx] = PlacementSettings(
                        landscape_position="top-left",
                        portrait_position="top-left",
                        output_size_mode=output_size,
                        margin=0,
                        offset_x=logo_x,
                        offset_y=logo_y,
                        logo_scale_percent=l_scale,
                        landscape_logo_scale_percent=l_scale,
                        portrait_logo_scale_percent=p_scale,
                        opacity=opacity,
                    )
                except Exception:
                    if override is not None:
                        per_logo[logo_idx] = override

            if per_logo:
                result[path] = per_logo

        return result

