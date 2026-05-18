from __future__ import annotations

TEAL = "#00c896"
TEAL_DARK = "#00a87a"
THUMB_SIZE: tuple[int, int] = (90, 90)
PREVIEW_DEBOUNCE_MS = 350
TARGET_WIDTH = 1280
_QUEUE_GAP: int = 8

POSITION_THAI: dict[str, str] = {
    "top-left":      "มุมซ้ายบน",
    "top-center":    "กลางบน",
    "top-right":     "มุมขวาบน",
    "middle-left":   "กลางซ้าย",
    "center":        "ตรงกลาง",
    "middle-right":  "กลางขวา",
    "bottom-left":   "มุมซ้ายล่าง",
    "bottom-center": "กลางล่าง",
    "bottom-right":  "มุมขวาล่าง",
}
THAI_TO_POSITION: dict[str, str] = {v: k for k, v in POSITION_THAI.items()}

