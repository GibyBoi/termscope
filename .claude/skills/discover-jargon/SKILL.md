---
name: discover-jargon
description: >-
  Grow TermScope's jargon dictionary using the model's own knowledge. Use when
  the user wants to add jargon, expand the dictionary, find missing terms, or
  "discover jargon the online dictionaries don't have". The model generates
  candidate jargon, this skill checks which terms TermScope is already missing,
  the model judges which are TRUE jargon vs ordinary words, and the approved ones
  are written into data/terms_*.json with stable ids.
---

# Discover jargon

TermScope's dictionary is finite (~509 terms). An AI model knows far more domain
jargon than any one online glossary. This skill closes that gap: **generate
candidate jargon → check it against the dictionary → add the genuinely-missing,
genuinely-jargon terms.**

The companion script `jargon_tool.py` (next to this file) does the deterministic
dictionary work — normalized matching (same rules as the Rust matcher), stable
unique id assignment, and atomic writes in TermScope's exact file format. The
*judgment* (what counts as real jargon worth adding) stays with you, the model.

## When to use
- "Add more tech/business jargon to TermScope"
- "What jargon is TermScope missing?"
- "Expand the dictionary with [domain] terms"

## Categories
New terms must target one of: **tech**, **business**, **companies**
(→ `data/terms_tech.json`, `terms_business.json`, `terms_companies.json`).

## Workflow

### 1. Generate candidates
Brainstorm a broad list (aim for 40–150) of jargon for the relevant domain(s). If
the user named a focus ("DevOps", "VC funding", "fintech companies"), lean into
it; otherwise sweep across tech + business + companies. Cast a wide net here —
the check step is cheap and filters out anything already known.

### 2. Check against the dictionary
Write the candidates to a JSON array of strings and run:

```bash
python .claude/skills/discover-jargon/jargon_tool.py check --in candidates.json
```

(or pipe: `echo '["webhook","idempotent","synergy"]' | python .../jargon_tool.py check`)

Output reports `present` (already covered, including near-duplicates like plurals
/ aliases) and `missing`. **Only the `missing` list moves forward.**

### 3. Judge — true jargon vs ordinary word
This is the important step and it's *yours*. For each missing candidate, keep it
only if it is **genuinely jargon**: a domain-specific term, acronym, or phrase a
non-expert would plausibly not understand in a meeting/interview. Reject:
- ordinary English words ("strategy", "meeting", "fast"),
- overly niche/obscure terms unlikely to come up,
- anything ambiguous or that isn't really a defined term.

For each kept term write a TermScope-style definition: one clear sentence, plain
language, expand acronyms with an em dash (match the existing entries' voice — see
`data/terms_*.json`). Pick the right `category`. Add `aliases` for spoken/spelled
variants (e.g. `"a p i"` for API), and `strict: true` for acronyms that should
only match when written in capitals.

### 4. Add the approved terms
Write the approved objects to JSON and (optionally dry-run first):

```bash
python .claude/skills/discover-jargon/jargon_tool.py add --in approved.json --dry-run
python .claude/skills/discover-jargon/jargon_tool.py add --in approved.json
```

Approved-term shape:
```json
[
  {"term": "idempotent", "category": "tech",
   "definition": "Describes an operation that has the same effect whether run once or many times."},
  {"term": "ARR", "category": "business", "strict": true,
   "definition": "Annual Recurring Revenue — the yearly value of a company's subscription contracts."}
]
```

The tool assigns ids (global max + 1, never reused), skips anything that slipped
through as a duplicate, and writes the files atomically. It reports `added` and
`skipped` (with reasons) — relay that summary to the user.

### 5. Finish
- Report what was added (count + terms) and anything skipped and why.
- The running app loads the dictionary at startup, so tell the user to **restart
  TermScope** (or rebuild) to pick up new terms.
- Use scratch files for `candidates.json` / `approved.json` (the scratchpad dir),
  not the repo — they're throwaway working data, not something to retain.

## Notes
- `python .../jargon_tool.py stats` shows per-category counts and the current max id.
- The tool fails loudly: malformed input or a missing data dir is a non-zero exit
  with a message — it never silently drops a term you asked it to add.
- Stable ids mean adding terms never disturbs a user's learned-progress, which is
  keyed by id (see the repo CLAUDE.md / data-compat notes).
