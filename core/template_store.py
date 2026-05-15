"""Persist watermark templates to a JSON file next to the app."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _get_store_path() -> Path:
    """Return path to templates.json — works for both script and onefile exe."""
    if getattr(sys, "frozen", False):
        # PyInstaller onefile: sys.executable = actual .exe path
        return Path(sys.executable).parent / "templates.json"
    # Normal Python run: store next to app.py
    return Path(__file__).parent.parent / "templates.json"


_STORE_PATH = _get_store_path()


def load_all() -> dict[str, Any]:
    """Return all saved templates as {name: data_dict}."""
    if not _STORE_PATH.exists():
        return {}
    try:
        data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_template(name: str, data: dict[str, Any]) -> None:
    """Upsert a template by name."""
    all_tpl = load_all()
    all_tpl[name] = data
    _STORE_PATH.write_text(
        json.dumps(all_tpl, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def delete_template(name: str) -> None:
    """Remove a template by name (no-op if not found)."""
    all_tpl = load_all()
    if name not in all_tpl:
        return
    del all_tpl[name]
    _STORE_PATH.write_text(
        json.dumps(all_tpl, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
