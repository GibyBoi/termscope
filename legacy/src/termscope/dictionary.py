"""Loading the bundled term dictionaries into matchable entries."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_WORD_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens. Punctuation and case are discarded so that
    'CI/CD', 'ci cd' and 'cicd' all reduce to comparable token streams."""
    return _WORD_RE.findall(text.lower())


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


@dataclass
class TermEntry:
    id: str
    term: str
    definition: str
    category: str
    aliases: list[str] = field(default_factory=list)
    # When True, only match if the source text wrote the term in capitals (e.g.
    # "REST", "DRY"). Stops short acronyms from false-firing on the common English
    # word they spell ("rest", "dry"). Audio transcripts are lowercase, so strict
    # terms simply won't surface from speech — the right trade for ambiguous ones.
    strict: bool = False
    # Each surface form (the term plus every alias) reduced to a token tuple.
    token_sets: list[tuple[str, ...]] = field(default_factory=list)

    @property
    def display(self) -> str:
        return self.term


def load_entries(
    files: list[Path], enabled_categories: set[str] | None = None
) -> list[TermEntry]:
    """Parse term files into TermEntry objects.

    The id is the term's permanent numeric "id" (stable across app revisions so
    progress is never lost); terms without one fall back to the legacy
    "category:slug" id. Duplicates are skipped by both id and category+slug.
    """
    entries: list[TermEntry] = []
    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()
    for path in files:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        category = data.get("category", "general")
        if enabled_categories is not None and category not in enabled_categories:
            continue
        for item in data.get("terms", []):
            term = item["term"].strip()
            slug_key = f"{category}:{_slug(term)}"
            raw_id = item.get("id")
            tid = str(raw_id) if raw_id is not None else slug_key
            if tid in seen_ids or slug_key in seen_slugs:
                continue
            seen_ids.add(tid)
            seen_slugs.add(slug_key)
            aliases = [a.strip() for a in item.get("aliases", []) if a.strip()]
            token_sets: list[tuple[str, ...]] = []
            for form in (term, *aliases):
                toks = tuple(tokenize(form))
                if toks and toks not in token_sets:
                    token_sets.append(toks)
            entries.append(
                TermEntry(
                    id=tid,
                    term=term,
                    definition=item["definition"].strip(),
                    category=category,
                    aliases=aliases,
                    strict=bool(item.get("strict", False)),
                    token_sets=token_sets,
                )
            )
    return entries
