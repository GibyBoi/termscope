# Updating the TermScope term list with any AI

You can grow TermScope's dictionary using **any** AI assistant (ChatGPT, Claude,
Gemini, Copilot, a local model — whatever you have). The flow is:

1. Copy the **prompt below** into the AI, replacing `TOPIC` with what you want terms
   for (e.g. *"Kubernetes and cloud infra"*, *"venture-capital fundraising"*,
   *"data-science interviews"*).
2. Save the AI's JSON output to a file, e.g. `new_terms.json`.
3. Merge it in:

   ```powershell
   python tools/update_terms.py new_terms.json --enrich
   ```

   `--enrich` also fetches a full library definition for each new term (online,
   one-time). Drop it to merge instantly with just the short definitions.

4. Restart TermScope. The new terms are live (Library + notifications).

The merge script validates every entry, routes it to the right category file, and
**skips anything already in the dictionary**, so it's safe to run repeatedly.

---

## The prompt (copy from here)

You are expanding a jargon dictionary for **TermScope**, a tool that explains tech
and business terms people hear in meetings and interviews. Generate **new** terms
about: **TOPIC**.

Output **only** a JSON array — no prose, no markdown code fences. Each element:

```json
{
  "term": "the term as normally written (e.g. \"load balancer\", \"EBITDA\")",
  "definition": "one concise sentence: 'Expansion - what it means.', ~12-25 words, plain English",
  "category": "tech" or "business",
  "aliases": ["optional spoken/written variants, e.g. \"a p i\" for API, \"ci cd\" for CI/CD"],
  "strict": true ONLY if the term's lowercase form is a common English word or name
            (REST->rest, DRY->dry, SAM->sam) so it must NOT match casual speech; else omit
}
```

Rules:
- 15-30 genuinely useful terms someone might not already know. Prefer real jargon over basics.
- `definition`: exactly one sentence, in the style "Expansion - what it means."
- For acronyms, include spoken-letter `aliases` (e.g. `"a p i"`) so speech recognition can match them.
- `aliases` and `strict` are optional (defaults: none / false).
- Use only the two categories: `tech` and `business`.
- Valid JSON only. Double-check it parses.

Example elements:

```json
[
  {"term": "idempotent", "definition": "An operation that has the same effect whether you run it once or many times.", "category": "tech", "aliases": ["idempotency"]},
  {"term": "dry powder", "definition": "Cash reserves kept on hand to invest when the right opportunity appears.", "category": "business"},
  {"term": "REST", "definition": "Representational State Transfer - a common style for web APIs built on standard HTTP verbs.", "category": "tech", "strict": true}
]
```
