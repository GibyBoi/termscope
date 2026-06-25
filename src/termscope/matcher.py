"""Find dictionary terms inside arbitrary text.

Uses a longest-match, left-to-right scan over tokens. Multi-word phrases such as
'low hanging fruit' are matched as a unit and win over shorter overlapping terms.
Tokens are compared after light plural normalization so 'APIs', 'OKRs' and
'stakeholders' match their singular dictionary entries. (Possessives like "API's"
already work, because the apostrophe splits off the trailing 's' as its own token.)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .dictionary import TermEntry

_WORD_RE = re.compile(r"[a-z0-9]+")


def _norm(tok: str) -> str:
    """Reduce a token to a plural-insensitive key.

    Conservative on purpose: only strips a trailing plural suffix when the word
    is long enough that doing so can't collide a short singular with its own
    plural (e.g. 'bus' stays 'bus' while 'buses' -> 'bus'). 'ss' endings are left
    alone so 'business' isn't mangled.
    """
    if len(tok) > 4 and tok.endswith("es"):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


@dataclass
class Match:
    entry: TermEntry
    start: int  # char offset into the original text
    end: int


def _tokens_with_spans(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in _WORD_RE.finditer(text.lower())]


class Matcher:
    """Indexes term token-sequences for fast scanning of input text."""

    def __init__(self, entries: list[TermEntry]):
        # normalized first token -> list of (normalized_token_tuple, entry), longest first
        self._by_first: dict[str, list[tuple[tuple[str, ...], TermEntry]]] = {}
        self._max_len = 1
        for entry in entries:
            for toks in entry.token_sets:
                key_tuple = tuple(_norm(t) for t in toks)
                self._by_first.setdefault(key_tuple[0], []).append((key_tuple, entry))
                self._max_len = max(self._max_len, len(key_tuple))
        for bucket in self._by_first.values():
            bucket.sort(key=lambda pair: len(pair[0]), reverse=True)

    def find(self, text: str, excluded_ids: set[str] | None = None) -> list[Match]:
        """Return matches in order of appearance, de-duplicated by entry id.

        `excluded_ids` (e.g. already-learned terms) are skipped entirely.
        """
        excluded = excluded_ids or set()
        spans = _tokens_with_spans(text)
        norm_toks = [_norm(t[0]) for t in spans]
        n = len(norm_toks)
        results: list[Match] = []
        seen_ids: set[str] = set()
        i = 0
        while i < n:
            bucket = self._by_first.get(norm_toks[i])
            chosen_len = 0
            chosen_entry: TermEntry | None = None
            if bucket:
                for phrase, entry in bucket:  # longest first
                    L = len(phrase)
                    if i + L <= n and tuple(norm_toks[i : i + L]) == phrase:
                        chosen_len, chosen_entry = L, entry
                        break
            if chosen_entry is not None:
                start, end = spans[i][1], spans[i + chosen_len - 1][2]
                if chosen_entry.strict and not _written_in_caps(text, start, end):
                    # Ambiguous acronym (e.g. REST/DRY) not capitalized in the
                    # source — treat as the ordinary word and move on one token.
                    i += 1
                    continue
                if chosen_entry.id not in excluded and chosen_entry.id not in seen_ids:
                    seen_ids.add(chosen_entry.id)
                    results.append(Match(chosen_entry, start, end))
                i += chosen_len  # consume the whole phrase
            else:
                i += 1
        return results


def _written_in_caps(text: str, start: int, end: int) -> bool:
    """True if the matched slice has letters and all of them are uppercase."""
    letters = [c for c in text[start:end] if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)
