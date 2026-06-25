"""The TermScope jargon library: extensive, reference-style definitions.

Short definitions (in data/terms_*.json) are what fits on a notification. The
library augments each term with a fuller explanation sourced from an online
dictionary (Wikipedia) and cached offline in data/library.json, plus a source URL
for the "Learn more" action. If a term has no enriched entry yet, the library
falls back to its bundled short definition so callers always get something useful.

Run `python run.py enrich-library` to (re)build the cache from online sources.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import paths
from .dictionary import TermEntry


def library_path() -> Path:
    return paths.BUNDLED_DATA_DIR / "library.json"


class Library:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else library_path()
        self._data: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def __len__(self) -> int:
        return len(self._data)

    def has(self, term_id: str) -> bool:
        return term_id in self._data

    def extended(self, entry: TermEntry) -> str:
        """Full reference definition for a term, or the short one as a fallback."""
        rec = self._data.get(entry.id)
        if rec and rec.get("extended"):
            return rec["extended"]
        return entry.definition

    def source(self, entry: TermEntry) -> tuple[str | None, str | None]:
        """(source_name, url) for the term's online reference, if known."""
        rec = self._data.get(entry.id) or {}
        return rec.get("source"), rec.get("url")

    def coverage(self) -> int:
        """How many entries were enriched from an online source (not just fallback)."""
        return sum(1 for r in self._data.values() if r.get("source") and r.get("url"))
