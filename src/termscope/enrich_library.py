"""Build data/library.json by fetching extensive definitions from online dictionaries.

Source: Wikipedia. For each term we run a fuzzy title search (opensearch API,
no key required), biased by the term's category, then fetch the REST summary of
the best matching page and keep its extract + URL — but only if the page is
actually about the term (a relevance gate, so "DRY" doesn't become "dryness").
Terms with no good page keep their bundled short definition (source: TermScope)
plus a Wiktionary lookup URL, so "Learn more" always goes somewhere useful.

    python run.py enrich-library            # enrich every term
    python run.py enrich-library --limit 20 # quick partial run
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from . import paths
from .dictionary import load_entries
from .library import library_path

_UA = "TermScope/1.0 (local jargon helper; educational use)"
_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
_API = "https://en.wikipedia.org/w/api.php"


def _get_json(url: str, retries: int = 3) -> dict | list | None:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries - 1:
                time.sleep(1.0 + attempt * 1.5)  # back off on rate limit
                continue
            return None
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            if attempt < retries - 1:
                time.sleep(0.6)
                continue
            return None
    return None


def _opensearch(query: str, limit: int = 3) -> list[str]:
    url = _API + "?" + urllib.parse.urlencode(
        {"action": "opensearch", "search": query, "limit": limit, "namespace": 0, "format": "json"}
    )
    data = _get_json(url)
    if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
        return [t for t in data[1] if t]
    return []


def _fetch_summary(title: str) -> dict | None:
    data = _get_json(_SUMMARY + urllib.parse.quote(title.replace(" ", "_"), safe=""))
    return data if isinstance(data, dict) else None


def _expansion(term: str, definition: str) -> str:
    """The acronym's spelled-out form, if the definition starts with one."""
    head = definition.split("—")[0].split("(")[0].strip().rstrip(".")
    words = head.split()
    if 1 < len(words) <= 7 and head[:1].isupper() and head.lower() != term.lower():
        return head
    return ""


def _good_extract(data: dict | None) -> bool:
    if not data or data.get("type") == "disambiguation":
        return False
    extract = (data.get("extract") or "").strip()
    if len(extract) < 80 or "may refer to" in extract.lower():
        return False
    return True


def _relevant(term: str, expansion: str, title: str, extract: str) -> bool:
    """Guard against wrong matches: the page must actually mention the term/expansion."""
    t, ti, ex = term.lower(), title.lower(), (extract or "").lower()[:400]
    if t in ti or t in ex:
        return True
    if expansion:
        e = expansion.lower()
        if e in ti or e in ex:
            return True
        # All expansion initials appearing as the acronym in the extract, e.g. "(API)".
        if f"({term.lower()})" in ex:
            return True
    return False


def _best_summary(term: str, definition: str, category: str) -> dict | None:
    expansion = _expansion(term, definition)
    hint = "computing" if category == "tech" else "business"
    queries = []
    if expansion:
        queries.append(expansion)
    queries.append(f"{term} {hint}")
    queries.append(term)

    tried: set[str] = set()
    for q in queries:
        for title in _opensearch(q):
            key = title.lower()
            if key in tried:
                continue
            tried.add(key)
            data = _fetch_summary(title)
            if _good_extract(data) and _relevant(term, expansion, title, data.get("extract", "")):
                return data
            time.sleep(0.15)
    return None


def _write(data: dict) -> None:
    path = library_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic, so concurrent/partial writes can't corrupt the cache


def enrich(limit: int | None = None) -> dict:
    """Enrich every term, checkpointing the cache so partial progress survives an
    interruption and reruns resume instead of refetching."""
    entries = load_entries(paths.bundled_term_files())
    if limit:
        entries = entries[:limit]
    try:
        out: dict[str, dict] = json.loads(library_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        out = {}
    hits = 0
    total = len(entries)
    for i, e in enumerate(entries, 1):
        if e.id in out:  # already processed on a previous run; resume past it
            if out[e.id].get("source") == "Wikipedia":
                hits += 1
            continue
        record = {
            "term": e.term,
            "category": e.category,
            "extended": e.definition,
            "source": "TermScope dictionary",
            "url": "https://en.wiktionary.org/wiki/Special:Search?search="
            + urllib.parse.quote(e.term),
        }
        data = _best_summary(e.term, e.definition, e.category)
        if data:
            record["extended"] = data["extract"].strip()
            record["source"] = "Wikipedia"
            record["url"] = data.get("content_urls", {}).get("desktop", {}).get("page", record["url"])
            hits += 1
        out[e.id] = record
        if i % 8 == 0 or i == total:
            _write(out)  # checkpoint
            print(f"  [{i}/{total}] {hits} from Wikipedia (saved)", flush=True)
        time.sleep(0.08)
    _write(out)
    return out


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    limit = None
    if "--limit" in argv:
        try:
            limit = int(argv[argv.index("--limit") + 1])
        except (IndexError, ValueError):
            limit = None
    print(f"Enriching library from online dictionaries (limit={limit or 'all'})...")
    data = enrich(limit)
    path = library_path()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    wiki = sum(1 for r in data.values() if r["source"] == "Wikipedia")
    print(f"Wrote {len(data)} entries to {path} ({wiki} from Wikipedia, {len(data) - wiki} fallback).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
