"""Tests for the term matcher and dictionary loader.

Run from the project root with:  python -m pytest   (or)   python tests/test_matcher.py
Pure-stdlib: no third-party dependencies required.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from termscope.dictionary import TermEntry, load_entries, tokenize  # noqa: E402
from termscope.matcher import Matcher  # noqa: E402
from termscope import paths  # noqa: E402


def _entry(term, definition="def", category="tech", aliases=None):
    aliases = aliases or []
    token_sets = []
    for form in (term, *aliases):
        toks = tuple(tokenize(form))
        if toks and toks not in token_sets:
            token_sets.append(toks)
    return TermEntry(
        id=f"{category}:{term.lower().replace(' ', '-')}",
        term=term,
        definition=definition,
        category=category,
        aliases=aliases,
        token_sets=token_sets,
    )


def test_single_acronym_case_insensitive():
    m = Matcher([_entry("API")])
    for text in ["Call the API now", "the api is down", "ApI failure"]:
        found = m.find(text)
        assert len(found) == 1, text
        assert found[0].entry.term == "API"


def test_no_false_substring_match():
    # "API" should not match inside "rapidly" / "therapist".
    m = Matcher([_entry("API")])
    assert m.find("rapidly therapist apiary") == []


def test_multiword_phrase():
    m = Matcher([_entry("low-hanging fruit", aliases=["low hanging fruit"])])
    found = m.find("Let's grab the low hanging fruit first")
    assert len(found) == 1
    assert found[0].entry.term == "low-hanging fruit"


def test_longest_match_wins():
    # A standalone "fruit" term must not pre-empt the longer phrase.
    entries = [_entry("low hanging fruit"), _entry("fruit")]
    m = Matcher(entries)
    found = m.find("the low hanging fruit")
    assert [f.entry.term for f in found] == ["low hanging fruit"]


def test_alias_match():
    m = Matcher([_entry("CI/CD", aliases=["ci cd", "cicd"])])
    assert len(m.find("our cicd pipeline")) == 1
    assert len(m.find("the ci cd setup")) == 1


def test_excluded_ids_skipped():
    e = _entry("API")
    m = Matcher([e])
    assert m.find("the API", excluded_ids={e.id}) == []


def test_dedupe_repeated_term():
    m = Matcher([_entry("API")])
    found = m.find("API talks to API which calls API")
    assert len(found) == 1


def test_spans_point_at_original_text():
    m = Matcher([_entry("API")])
    text = "use the API here"
    match = m.find(text)[0]
    assert text[match.start : match.end].lower() == "api"


def test_bundled_dictionaries_load():
    files = paths.bundled_term_files()
    assert files, "no bundled term files found"
    entries = load_entries(files)
    assert len(entries) > 50
    ids = [e.id for e in entries]
    assert len(ids) == len(set(ids)), "duplicate term ids in bundled data"
    # Spot-check a known term resolves and matches in its plural form.
    m = Matcher(entries)
    assert any(f.entry.term == "OKR" for f in m.find("what are our OKRs this quarter"))


def test_plural_forms_match():
    entries = [_entry("API"), _entry("stakeholder"), _entry("action item")]
    m = Matcher(entries)
    assert any(f.entry.term == "API" for f in m.find("we expose three APIs"))
    assert any(f.entry.term == "stakeholder" for f in m.find("loop in the stakeholders"))
    assert any(f.entry.term == "action item" for f in m.find("two action items remain"))


def test_business_word_not_mangled_by_plural_rule():
    # 'business' ends in 'ss' and must not be stripped into a false match.
    m = Matcher([_entry("business")])
    found = m.find("the business plan")
    assert len(found) == 1 and found[0].entry.term == "business"


def test_learn_then_suppressed_integration():
    """End-to-end: a learned term is excluded from future scans and persists."""
    import tempfile
    from termscope.knowledge import Knowledge

    entries = load_entries(paths.bundled_term_files())
    m = Matcher(entries)
    text = "the API is down"

    with tempfile.TemporaryDirectory() as tmp:
        kpath = Path(tmp) / "knowledge.json"
        k = Knowledge(kpath)

        # Before learning, API is surfaced.
        assert any(f.entry.term == "API" for f in m.find(text, k.learned_ids()))

        # Mark it learned (mirrors what NotificationManager does on button click).
        api_id = next(f.entry.id for f in m.find(text) if f.entry.term == "API")
        k.mark_learned(api_id)

        # Now it's suppressed.
        assert not any(f.entry.term == "API" for f in m.find(text, k.learned_ids()))

        # And the decision persists across restarts.
        k2 = Knowledge(kpath)
        assert k2.is_learned(api_id)
        assert not any(f.entry.term == "API" for f in m.find(text, k2.learned_ids()))


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {exc!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
