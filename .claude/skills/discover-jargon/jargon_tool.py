#!/usr/bin/env python
"""TermScope jargon dictionary tool — check candidates & add new terms.

Deterministic helper for the `discover-jargon` skill. The AI generates candidate
jargon; this tool does the dictionary-side bookkeeping the model can't be trusted
to do by hand: matching candidates against existing terms (same normalization the
Rust matcher uses), assigning stable unique ids, and writing the term files back
in TermScope's exact one-term-per-line format with an atomic replace.

Subcommands
-----------
  stats                          counts per category + the global max id
  check  [--in FILE]             which candidate words are already covered
  add    [--in FILE]             append approved new terms to the dictionaries

Input (check/add) is JSON read from --in or stdin:
  check : ["webhook", "idempotent", "the", ...]
  add   : [{"term": "...", "definition": "...", "category": "tech",
            "aliases": ["..."], "strict": false}, ...]
            (aliases & strict optional)

Output is JSON on stdout. The tool FAILS LOUDLY: malformed input or an unwritable
data dir is a non-zero exit with a message on stderr — it never silently drops a
requested term.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

WORD_RE = re.compile(r"[a-z0-9]+")

# Categories TermScope ships. New terms must target one of these (each maps to a
# data/terms_<category>.json file). We don't invent new category files here.
KNOWN_CATEGORIES = ("tech", "business", "companies")


# ---- text normalization (mirrors src-tauri/src/matcher.rs) -------------------

def tokenize(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def norm(tok: str) -> str:
    n = len(tok)
    if n > 4 and tok.endswith("es"):
        return tok[:-2]
    if n > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def canon(text: str) -> str:
    """Plural-insensitive canonical form used to compare surface forms."""
    return " ".join(norm(t) for t in tokenize(text))


# ---- dictionary I/O ----------------------------------------------------------

def resolve_data_dir(override: str | None) -> Path:
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    if os.environ.get("TERMSCOPE_DATA"):
        candidates.append(Path(os.environ["TERMSCOPE_DATA"]))
    # This script lives at <repo>/.claude/skills/discover-jargon/jargon_tool.py
    here = Path(__file__).resolve()
    candidates.append(here.parents[3] / "data")
    candidates.append(Path.cwd() / "data")
    for c in candidates:
        if c.is_dir() and any(c.glob("terms_*.json")):
            return c
    die(
        "could not locate TermScope's data/ dir (no terms_*.json found). "
        "Pass --data-dir <path> or set TERMSCOPE_DATA."
    )


def term_files(data_dir: Path) -> list[Path]:
    return sorted(data_dir.glob("terms_*.json"))


def load_file(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        die(f"failed to read {path.name}: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("terms"), list):
        die(f"{path.name} is not a valid term file (expected {{category, terms[]}})")
    return data


def write_terms_file(path: Path, category: str, terms: list[dict]) -> None:
    """Write a term file in TermScope's exact format (one term per line),
    atomically (tmp + os.replace) so a crash can't leave a half file."""
    lines = [
        "{",
        f'  "category": {json.dumps(category, ensure_ascii=False)},',
        '  "terms": [',
    ]
    for i, t in enumerate(terms):
        tail = "," if i < len(terms) - 1 else ""
        lines.append("    " + json.dumps(t, ensure_ascii=False) + tail)
    lines.append("  ]")
    lines.append("}")
    text = "\n".join(lines) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def build_index(data_dir: Path):
    """Return (canon_to_term, max_id, category_to_path)."""
    canon_to_term: dict[str, str] = {}
    max_id = 0
    cat_path: dict[str, Path] = {}
    for path in term_files(data_dir):
        data = load_file(path)
        category = data.get("category", "")
        if category:
            cat_path[category] = path
        for t in data["terms"]:
            term = (t.get("term") or "").strip()
            if not term:
                continue
            forms = [term] + [a for a in (t.get("aliases") or []) if isinstance(a, str)]
            for form in forms:
                key = canon(form)
                if key:
                    canon_to_term.setdefault(key, term)
            tid = t.get("id")
            if isinstance(tid, int):
                max_id = max(max_id, tid)
    return canon_to_term, max_id, cat_path


# ---- helpers -----------------------------------------------------------------

def die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    print(f"jargon_tool: error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def read_input(in_path: str | None):
    raw = ""
    if in_path:
        try:
            raw = Path(in_path).read_text(encoding="utf-8")
        except OSError as e:
            die(f"could not read --in {in_path}: {e}")
    else:
        raw = sys.stdin.read()
    raw = raw.strip()
    if not raw:
        die("no input provided (use --in FILE or pipe JSON on stdin)")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fall back to newline-delimited words (only useful for `check`).
        return [ln.strip() for ln in raw.splitlines() if ln.strip()]


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ---- subcommands -------------------------------------------------------------

def cmd_stats(args) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    _, max_id, _ = build_index(data_dir)
    out = {"data_dir": str(data_dir), "max_id": max_id, "categories": {}, "total": 0}
    for path in term_files(data_dir):
        data = load_file(path)
        n = len(data["terms"])
        out["categories"][data.get("category", path.stem)] = n
        out["total"] += n
    emit(out)
    return 0


def cmd_check(args) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    canon_to_term, _, _ = build_index(data_dir)
    words = read_input(args.infile)
    if not isinstance(words, list):
        die("check expects a JSON array of words")

    present, missing, seen = [], [], set()
    for w in words:
        if not isinstance(w, str) or not w.strip():
            continue
        key = canon(w)
        if not key or key in seen:
            continue
        seen.add(key)
        if key in canon_to_term:
            present.append({"word": w, "matched": canon_to_term[key]})
        else:
            missing.append({"word": w, "canon": key})

    emit({
        "summary": {"checked": len(seen), "present": len(present), "missing": len(missing)},
        "missing": missing,
        "present": present,
    })
    return 0


def cmd_add(args) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    canon_to_term, max_id, cat_path = build_index(data_dir)
    items = read_input(args.infile)
    if not isinstance(items, list):
        die("add expects a JSON array of term objects")

    # Validate the batch up front; structural problems are hard errors.
    cleaned = []
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            die(f"item {idx} is not an object")
        term = (it.get("term") or "").strip()
        definition = (it.get("definition") or "").strip()
        category = (it.get("category") or "").strip()
        if not term or not definition or not category:
            die(f"item {idx} missing required term/definition/category: {it!r}")
        aliases = [a.strip() for a in (it.get("aliases") or []) if isinstance(a, str) and a.strip()]
        strict = bool(it.get("strict", False))
        cleaned.append({"term": term, "definition": definition, "category": category,
                        "aliases": aliases, "strict": strict})

    added, skipped = [], []
    batch_canons: set[str] = set()
    next_id = max_id
    # Group accepted terms by destination file so we write each file once.
    pending: dict[str, list[dict]] = {}

    for it in cleaned:
        term, category = it["term"], it["category"]
        key = canon(term)
        if category not in KNOWN_CATEGORIES:
            skipped.append({"term": term, "reason": f"unknown category '{category}' "
                                                    f"(expected one of {', '.join(KNOWN_CATEGORIES)})"})
            continue
        if category not in cat_path:
            skipped.append({"term": term, "reason": f"no data file for category '{category}'"})
            continue
        if not key:
            skipped.append({"term": term, "reason": "term has no usable tokens"})
            continue
        if key in canon_to_term:
            skipped.append({"term": term, "reason": f"already in dictionary as '{canon_to_term[key]}'"})
            continue
        if key in batch_canons:
            skipped.append({"term": term, "reason": "duplicate within this batch"})
            continue

        batch_canons.add(key)
        next_id += 1
        entry: dict = {"id": next_id, "term": term, "definition": it["definition"]}
        if it["aliases"]:
            entry["aliases"] = it["aliases"]
        if it["strict"]:
            entry["strict"] = True
        pending.setdefault(category, []).append(entry)
        added.append({"id": next_id, "term": term, "category": category})

    if not args.dry_run:
        for category, new_entries in pending.items():
            path = cat_path[category]
            data = load_file(path)
            data["terms"].extend(new_entries)
            write_terms_file(path, data.get("category", category), data["terms"])

    emit({
        "summary": {"added": len(added), "skipped": len(skipped),
                    "dry_run": bool(args.dry_run), "next_id_after": next_id},
        "added": added,
        "skipped": skipped,
    })
    return 0


def main() -> int:
    # --data-dir is shared and may appear before OR after the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", default=None, help="path to TermScope's data/ dir")

    ap = argparse.ArgumentParser(description="TermScope jargon dictionary tool", parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats", parents=[common], help="counts per category + max id")

    c = sub.add_parser("check", parents=[common],
                       help="which candidate words are already in the dictionary")
    c.add_argument("--in", dest="infile", default=None, help="JSON array of words (else stdin)")

    a = sub.add_parser("add", parents=[common],
                       help="append approved new terms to the dictionaries")
    a.add_argument("--in", dest="infile", default=None, help="JSON array of term objects (else stdin)")
    a.add_argument("--dry-run", action="store_true", help="validate & report without writing")

    args = ap.parse_args()
    return {"stats": cmd_stats, "check": cmd_check, "add": cmd_add}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
