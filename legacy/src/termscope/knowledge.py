"""Per-user knowledge state: which terms are learned, and anti-spam bookkeeping."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class Knowledge:
    """Tracks learned terms and recent-show timestamps, persisted to JSON.

    The store starts empty — the user is assumed to know nothing — and grows as
    terms are marked learned. All mutations are thread-safe and saved immediately.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._learned: dict[str, str] = {}  # term id -> ISO timestamp learned
        self._seen: dict[str, dict] = {}  # term id -> {"count": int, "last": float}
        self._load()

    # ---- persistence -----------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._learned = dict(data.get("learned", {}))
            self._seen = dict(data.get("seen", {}))
        except (json.JSONDecodeError, OSError):
            # Corrupt or unreadable state should not crash startup.
            self._learned, self._seen = {}, {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        payload = {"learned": self._learned, "seen": self._seen}
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # ---- learned terms ---------------------------------------------------
    def is_learned(self, term_id: str) -> bool:
        with self._lock:
            return term_id in self._learned

    def learned_ids(self) -> set[str]:
        with self._lock:
            return set(self._learned)

    def mark_learned(self, term_id: str) -> None:
        with self._lock:
            self._learned[term_id] = _now_iso()
            self._save()

    def unlearn(self, term_id: str) -> None:
        with self._lock:
            if self._learned.pop(term_id, None) is not None:
                self._save()

    def learned_count(self) -> int:
        with self._lock:
            return len(self._learned)

    # ---- anti-spam -------------------------------------------------------
    def record_shown(self, term_id: str) -> None:
        with self._lock:
            rec = self._seen.setdefault(term_id, {"count": 0, "last": 0.0})
            rec["count"] += 1
            rec["last"] = time.time()
            self._save()

    def can_show(self, term_id: str, cooldown_seconds: float) -> bool:
        """True if the term has never been shown or its cooldown has elapsed."""
        with self._lock:
            rec = self._seen.get(term_id)
            if not rec:
                return True
            return (time.time() - rec["last"]) >= cooldown_seconds


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
