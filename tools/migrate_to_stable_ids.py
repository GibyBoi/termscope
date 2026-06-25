#!/usr/bin/env python
"""One-time migration to permanent numeric term IDs.

Why: term ids used to be derived from "category:slug(term)", so renaming a term or
moving its category changed its id and lost the user's progress. This assigns every
definition a stable integer "id" (stored in the data files, never reused or changed)
and re-keys knowledge.json + library.json from the old slug ids to the new numeric
ids so existing learned/seen progress and enriched definitions carry over.

Idempotent: re-running only assigns ids to terms that don't have one yet, so future
term additions keep their ids forever.

    python tools/migrate_to_stable_ids.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from termscope import paths             # noqa: E402
from termscope.dictionary import _slug   # noqa: E402

DATA = ROOT / "data"


def _write_terms(path: Path, doc: dict) -> None:
    """One term per line, with "id" as the first field."""
    terms = doc["terms"]
    lines = ["{", f'  "category": "{doc["category"]}",', '  "terms": [']
    for i, t in enumerate(terms):
        ordered = {"id": t["id"]}
        for k, v in t.items():
            if k != "id":
                ordered[k] = v
        tail = "," if i < len(terms) - 1 else ""
        lines.append("    " + json.dumps(ordered, ensure_ascii=False) + tail)
    lines += ["  ]", "}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    files = sorted(DATA.glob("terms_*.json"))
    docs = {f: json.loads(f.read_text(encoding="utf-8")) for f in files}

    # Highest id already in use (so existing ids are never reassigned).
    max_id = 0
    for doc in docs.values():
        for t in doc["terms"]:
            if isinstance(t.get("id"), int):
                max_id = max(max_id, t["id"])

    slug_to_num: dict[str, int] = {}
    assigned = 0
    for f in files:
        doc = docs[f]
        cat = doc["category"]
        for t in doc["terms"]:
            if not isinstance(t.get("id"), int):
                max_id += 1
                t["id"] = max_id
                assigned += 1
            slug_to_num[f"{cat}:{_slug(t['term'])}"] = t["id"]
        _write_terms(f, doc)
    print(f"Assigned {assigned} new ids; {len(slug_to_num)} terms; highest id now {max_id}.")

    # Re-key knowledge.json (learned + seen) slug -> numeric.
    kp = paths.knowledge_path()
    if kp.exists():
        k = json.loads(kp.read_text(encoding="utf-8"))
        moved = 0
        for section in ("learned", "seen"):
            d = k.get(section)
            if isinstance(d, dict):
                nd = {}
                for key, val in d.items():
                    nk = str(slug_to_num.get(key, key))
                    moved += (nk != key)
                    nd[nk] = val
                k[section] = nd
        kp.write_text(json.dumps(k, indent=2), encoding="utf-8")
        print(f"Migrated knowledge.json: {moved} keys re-mapped "
              f"({len(k.get('learned', {}))} learned, {len(k.get('seen', {}))} seen).")
    else:
        print("No knowledge.json yet (nothing to migrate).")

    # Re-key library.json slug -> numeric.
    lp = DATA / "library.json"
    if lp.exists():
        lib = json.loads(lp.read_text(encoding="utf-8"))
        nlib = {str(slug_to_num.get(key, key)): rec for key, rec in lib.items()}
        lp.write_text(json.dumps(nlib, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Migrated library.json: {len(nlib)} entries re-keyed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
