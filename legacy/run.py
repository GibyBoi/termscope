#!/usr/bin/env python
"""Launcher for TermScope.

    python run.py                  # start the tray app
    python run.py download-model   # one-time: fetch the offline speech model
    python run.py demo "text..."   # headless: scan text and print matched terms
    python run.py terms            # list all loaded terms

The demo path uses the console notifier and needs no audio/GUI dependencies,
so it works on a bare Python install for quick verification.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def _demo(text: str) -> int:
    from termscope import paths
    from termscope.config import Config
    from termscope.dictionary import load_entries
    from termscope.matcher import Matcher
    from termscope.knowledge import Knowledge
    from termscope.notifier import NotificationManager

    cfg = Config.load()
    cfg.notifier = "console"
    cfg.cooldown_seconds = 0  # show every match in the demo
    cfg.max_per_minute = 1000
    entries = load_entries(paths.bundled_term_files(), set(cfg.enabled_categories))
    matcher = Matcher(entries)
    knowledge = Knowledge(paths.knowledge_path())
    mgr = NotificationManager(cfg, knowledge, lambda tid: knowledge.mark_learned(tid))

    matches = matcher.find(text, knowledge.learned_ids())
    if not matches:
        print("No tracked jargon found in that text.")
        return 0
    print(f"Found {len(matches)} term(s):")
    for match in matches:
        mgr.force(match.entry)
    return 0


def _list_terms() -> int:
    from termscope import paths
    from termscope.config import Config
    from termscope.dictionary import load_entries

    cfg = Config.load()
    entries = load_entries(paths.bundled_term_files(), set(cfg.enabled_categories))
    by_cat: dict[str, list] = {}
    for e in entries:
        by_cat.setdefault(e.category, []).append(e.term)
    for cat, terms in sorted(by_cat.items()):
        print(f"\n{cat} ({len(terms)}):")
        print("  " + ", ".join(sorted(terms)))
    print(f"\nTotal: {len(entries)} terms")
    return 0


def main() -> int:
    try:  # ensure em-dashes etc. render in the Windows console
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    args = sys.argv[1:]
    if args and args[0] == "demo":
        sample = " ".join(args[1:]) or (
            "Before EOD let's circle back on the API rate limits and our Q3 OKRs; "
            "the SaaS churn is hurting our ARR and the stakeholders want a deep dive."
        )
        return _demo(sample)
    if args and args[0] == "terms":
        return _list_terms()
    if args and args[0] in ("download-model", "download_model"):
        from termscope.download_model import main as dl_main

        return dl_main(args[1:])
    if args and args[0] in ("enrich-library", "enrich_library"):
        from termscope.enrich_library import main as enrich_main

        return enrich_main(args[1:])
    from termscope.app import run

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
