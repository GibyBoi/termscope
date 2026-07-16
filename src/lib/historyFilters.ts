// Modular filter registry for the History tab.
//
// The History tab shows orderless frequency tallies (see `history.rs`): every
// spoken word (`words`) and every jargon detection (`terms`). A *filter* is just
// a named way to pick a subset of those tallies to display. Each filter is a
// self-contained `FilterDef` — to add a new filter type (e.g. "Slang", another
// jargon category) you add one entry to `buildFilters` and nothing else changes:
// the dropdown, union, sorting, search and rendering all key off `DisplayItem`.

import type { History, TermStat, WordStat } from "./types";

/** A single row shown in the Counts list, from any filter, unified. */
export interface DisplayItem {
  /** Stable de-dup key so the same term/word selected via two filters shows once. */
  key: string;
  label: string;
  count: number;
  /** True for a dictionary/jargon term (carries a definition), false for a spoken word. */
  isTerm: boolean;
  /** Dictionary term id, set only when isTerm — used by the row's delete action. */
  termId?: string;
  category?: string;
  definition?: string;
  learned?: boolean;
}

/** One filter option in the multi-select dropdown. */
export interface FilterDef {
  key: string;
  label: string;
  hint: string;
  /** Produce the items this filter contributes from the current history data. */
  build: () => DisplayItem[];
}

/** Everything a filter needs to build its items. */
export interface FilterContext {
  data: History;
  /** Normalized filler-word tokens (from `get_filler_words`). */
  fillerWords: Set<string>;
  /** All jargon categories available (from config `enabled_categories`), so the
   * per-category filters are always offered — even before any such jargon has
   * been detected. Categories seen in the data but not listed here are appended. */
  categories: string[];
}

function termItem(t: TermStat): DisplayItem {
  return {
    key: `term:${t.id}`,
    label: t.term,
    count: t.count,
    isTerm: true,
    termId: t.id,
    category: t.category,
    definition: t.definition,
    learned: t.learned,
  };
}

function wordItem(w: WordStat, category?: string): DisplayItem {
  return { key: `word:${w.word}`, label: w.word, count: w.count, isTerm: false, category };
}

/** Human label for a dictionary category id (the data uses "companies" → "Company"). */
const CATEGORY_LABELS: Record<string, string> = {
  tech: "Tech",
  business: "Business",
  companies: "Company",
};

export function categoryLabel(cat: string): string {
  return CATEGORY_LABELS[cat] ?? cat.charAt(0).toUpperCase() + cat.slice(1);
}

/** Stable preferred category order (tech, business, companies, then the rest
 * alphabetically) — keeps filter lists and chart slices in a fixed order so a
 * category's position (and color) never depends on its current counts. */
export function orderedCategories(all: Set<string>): string[] {
  const order = ["tech", "business", "companies"];
  return [
    ...order.filter((c) => all.has(c)),
    ...[...all].filter((c) => !order.includes(c)).sort(),
  ];
}

/**
 * Build the ordered list of available filters for the current data.
 *
 * Base filters (Jargon, Filler words) are always present; one filter per jargon
 * category actually seen in the data is appended, so new dictionary categories
 * surface here automatically without code changes.
 */
export function buildFilters(ctx: FilterContext): FilterDef[] {
  const { data, fillerWords, categories } = ctx;

  const filters: FilterDef[] = [
    {
      key: "jargon",
      label: "Jargon",
      hint: "Every dictionary term detected, across all categories.",
      build: () => data.terms.map(termItem),
    },
    {
      key: "filler",
      label: "Filler words",
      hint: "Spoken words that are common verbal filler (um, like, basically…).",
      build: () =>
        data.words
          .filter((w) => fillerWords.has(w.word))
          .map((w) => wordItem(w, "filler")),
    },
  ];

  // One filter per jargon category, in a stable preferred order. Driven by the
  // configured categories so Tech/Business/Company are always selectable, plus
  // any extra category actually seen in the data.
  const present = new Set(data.terms.map((t) => t.category));
  const cats = orderedCategories(new Set([...categories, ...present]));
  for (const cat of cats) {
    filters.push({
      key: `cat:${cat}`,
      label: categoryLabel(cat),
      hint: `${categoryLabel(cat)} jargon only.`,
      build: () => data.terms.filter((t) => t.category === cat).map(termItem),
    });
  }

  // Every spoken word captured, unfiltered — so any individual word's frequency
  // is always searchable, not just jargon and filler.
  filters.push({
    key: "words",
    label: "All words",
    hint: "Every spoken word captured, by frequency.",
    build: () => data.words.map((w) => wordItem(w)),
  });

  return filters;
}

/**
 * Union the items contributed by the selected filters, de-duplicated by key.
 * (A jargon term matched by both "Jargon" and "Tech" appears once.)
 */
export function collectItems(filters: FilterDef[], selected: Set<string>): DisplayItem[] {
  const byKey = new Map<string, DisplayItem>();
  for (const f of filters) {
    if (!selected.has(f.key)) continue;
    for (const item of f.build()) {
      if (!byKey.has(item.key)) byKey.set(item.key, item);
    }
  }
  return [...byKey.values()];
}
