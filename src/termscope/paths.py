"""Filesystem locations for bundled data and per-user state."""
from __future__ import annotations

import os
from pathlib import Path

from . import APP_NAME

# Repo layout: <root>/src/termscope/paths.py  ->  <root>
_PKG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _PKG_DIR.parent.parent
BUNDLED_DATA_DIR = PROJECT_ROOT / "data"


def user_data_dir() -> Path:
    """Per-user writable directory (e.g. %APPDATA%\\TermScope), created on demand."""
    base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else (Path.home() / ".config")
    d = root / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return user_data_dir() / "config.json"


def knowledge_path() -> Path:
    return user_data_dir() / "knowledge.json"


def models_dir() -> Path:
    d = user_data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundled_term_files() -> list[Path]:
    """All term dictionaries shipped with the app."""
    if not BUNDLED_DATA_DIR.exists():
        return []
    return sorted(BUNDLED_DATA_DIR.glob("terms_*.json"))
