#!/usr/bin/env python
"""Merge AI-generated terms into TermScope's dictionaries.

See tools/update_terms_prompt.md for the full workflow. In short:

    python tools/update_terms.py new_terms.json            # merge
    python tools/update_terms.py new_terms.json --enrich    # merge + fetch library defs

Input: a JSON list (or {"terms": [...]}) of objects:
    {"term", "definition", "category": "tech"|"business", "aliases"?, "strict"?}

Each valid, non-duplicate term is appended to data/terms_<category>.json.
Duplicates (by id) and invalid entries are reported and skipped.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from termscope import paths  # noqa: E402
from termscope.dictionary import _slug, load_entries  # noqa: E402

VALID_CATEGORIES = {"tech", "business"}


def _write_compact(path: Path, category: str, terms: list) -> None:
    """Write the dictionary one term per line (matches the hand-edited house style,
    which keeps diffs tiny when terms are added)."""
    lines = ["{", f'  "category": "{category}",', '  "terms": [']
    for i, term in enumerate(terms):
        tail = "," if i < len(terms) - 1 else ""
        lines.append("    " + json.dumps(term, ensure_ascii=False) + tail)
    lines += ["  ]", "}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_input(path: str) -> list:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "terms" in data:
        data = data["terms"]
    if not isinstance(data, list):
        raise SystemExit("Input must be a JSON list of term objects (or {\"terms\": [...]}).")
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Merge AI-generated terms into TermScope.")
    ap.add_argument("input", help="JSON file of new term objects")
    ap.add_argument("--enrich", action="store_true",
                    help="also fetch full library definitions for the new terms (online)")
    args = ap.parse_args(argv)

    incoming = _load_input(args.input)
    existing = load_entries(paths.bundled_term_files())
    existing_keys = {(e.category, _slug(e.term)) for e in existing}
    # Next free permanent id (ids are never reused, so progress is never reset).
    next_id = 1 + max((int(e.id) for e in existing if str(e.id).isdigit()), default=0)

    by_cat: dict[str, list] = {}
    added: list[tuple[str, str]] = []
    skipped: list[str] = []
    invalid = 0

    for item in incoming:
        if not isinstance(item, dict):
            invalid += 1
            continue
        term = str(item.get("term", "")).strip()
        definition = str(item.get("definition", "")).strip()
        category = str(item.get("category", "")).strip().lower()
        if not term or not definition or category not in VALID_CATEGORIES:
            invalid += 1
            continue
        key = (category, _slug(term))
        if key in existing_keys:
            skipped.append(term)
            continue
        existing_keys.add(key)
        entry = {"id": next_id, "term": term, "definition": definition}
        next_id += 1
        aliases = [str(a).strip() for a in item.get("aliases", []) if str(a).strip()]
        if aliases:
            entry["aliases"] = aliases
        if item.get("strict"):
            entry["strict"] = True
        by_cat.setdefault(category, []).append(entry)
        added.append((category, term))

    for category, entries in by_cat.items():
        path = ROOT / "data" / f"terms_{category}.json"
        if path.exists():
            doc = json.loads(path.read_text(encoding="utf-8"))
        else:
            doc = {"category": category, "terms": []}
        doc.setdefault("terms", []).extend(entries)
        _write_compact(path, doc.get("category", category), doc["terms"])

    print(f"Added {len(added)} term(s); skipped {len(skipped)} duplicate(s); {invalid} invalid.")
    for cat, term in added:
        print(f"  + [{cat}] {term}")
    if skipped:
        print("  duplicates skipped: " + ", ".join(skipped))

    if args.enrich and added:
        print("\nFetching library definitions for the new terms (online)...")
        from termscope.enrich_library import enrich
        enrich()  # resumes; only the new (unprocessed) terms are fetched
        print("Library updated.")
    elif added:
        print("\nTip: add --enrich to fetch full 'Learn more' definitions for the new terms.")

    print("\nRestart TermScope to load the new terms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
