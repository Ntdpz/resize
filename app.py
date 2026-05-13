from __future__ import annotations

import customtkinter as ctk  # type: ignore[import-untyped]

from ui.main_window import AutoWatermarkWindow


def main() -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    window = AutoWatermarkWindow()
    window.mainloop()


if __name__ == "__main__":
    main()
