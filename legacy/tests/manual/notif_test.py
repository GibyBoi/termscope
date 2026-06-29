#!/usr/bin/env python
"""Fire real notifications through NotificationManager to verify they appear on screen.

    python notif_test.py tk          # in-app corner popup (Tk)
    python notif_test.py win11toast  # native Windows toast
    python notif_test.py console     # stdout only

Keeps the process alive ~20s so the notification stays visible for a screenshot.
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from termscope.config import Config
from termscope.dictionary import TermEntry
from termscope.knowledge import Knowledge
from termscope.notifier import NotificationManager


def main() -> int:
    backend = sys.argv[1] if len(sys.argv) > 1 else "tk"
    cfg = Config.load()
    cfg.notifier = backend
    cfg.cooldown_seconds = 0
    cfg.max_per_minute = 100

    tmp = Path(tempfile.gettempdir()) / "termscope_notif_test_knowledge.json"
    knowledge = Knowledge(tmp)

    learned = []
    mgr = NotificationManager(cfg, knowledge, lambda tid: learned.append(tid))
    print(f"[notif_test] requested backend={backend!r}, active backend={mgr.backend_name!r}", flush=True)

    samples = [
        TermEntry(
            id="business:north-star",
            term="north star",
            definition="The single guiding metric or goal that aligns a team's efforts.",
            category="business",
        ),
        TermEntry(
            id="tech:idempotent",
            term="idempotent",
            definition="An operation that has the same effect whether you run it once or many times.",
            category="tech",
        ),
    ]

    for i, entry in enumerate(samples):
        ok = mgr.force(entry)
        print(f"[notif_test] fired {entry.term!r} -> shown={ok}", flush=True)
        time.sleep(2)

    print("[notif_test] holding 18s so the notification stays on screen...", flush=True)
    time.sleep(18)
    print(f"[notif_test] done. learned callbacks fired for: {learned}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
