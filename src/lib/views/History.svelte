<script lang="ts">
  import { onMount } from "svelte";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import * as api from "../api";
  import { categoryColor } from "../api";
  import type { History } from "../types";
  import {
    buildFilters,
    collectItems,
    type DisplayItem,
    type FilterDef,
  } from "../historyFilters";

  let data: History | null = $state(null);
  let fillerWords = $state<Set<string>>(new Set());
  let loaded = $state(false);
  let trackingOn = $state(true); // mirrors config.track_history, for the paused hint

  // The Counts view is driven by a modular multi-select filter (see
  // historyFilters.ts): each selected filter contributes a set of rows, unioned
  // and shown by frequency. Everything shown is a pure count — TermScope never
  // stores the order or timing of what was said, so nothing here can be read
  // back as a conversation.
  let selected = $state<Set<string>>(new Set(["jargon"]));
  let sortDir: "desc" | "asc" = $state("desc");
  let search = $state("");
  let dropdownOpen = $state(false);

  // The union (esp. all filler/spoken words) can grow large; render a window of
  // it, which the search narrows.
  const RENDER_CAP = 500;

  async function load() {
    data = await api.getHistory();
    try {
      trackingOn = (await api.getConfig()).track_history;
    } catch {}
    loaded = true;
  }

  async function clearAll() {
    if (
      !confirm(
        "Clear all history? This permanently deletes every word and jargon tally.",
      )
    )
      return;
    await api.clearHistory();
    await load();
  }

  // Live-refresh while listening, debounced so a burst of transcriptions doesn't
  // hammer the backend.
  let refetchTimer: ReturnType<typeof setTimeout> | undefined;
  function scheduleRefetch() {
    clearTimeout(refetchTimer);
    refetchTimer = setTimeout(load, 400);
  }

  onMount(() => {
    const unlisteners: UnlistenFn[] = [];
    (async () => {
      await load();
      try {
        fillerWords = new Set(await api.getFillerWords());
      } catch {}
      unlisteners.push(await listen("ts://history", scheduleRefetch));
      unlisteners.push(await listen("ts://refresh", scheduleRefetch));
    })();
    return () => {
      clearTimeout(refetchTimer);
      unlisteners.forEach((u) => u());
    };
  });

  // ---- derived views --------------------------------------------------------

  let filters = $derived<FilterDef[]>(
    data ? buildFilters({ data, fillerWords }) : [],
  );
  let selectedLabels = $derived(
    filters.filter((f) => selected.has(f.key)).map((f) => f.label),
  );
  let filterSummary = $derived(
    selectedLabels.length === 0
      ? "Select filters…"
      : selectedLabels.join(", "),
  );

  // Union of the selected filters, then search-narrowed and frequency-sorted.
  let items = $derived.by<DisplayItem[]>(() => {
    if (!data) return [];
    let out = collectItems(filters, selected);
    const q = search.trim().toLowerCase();
    if (q) out = out.filter((i) => i.label.toLowerCase().includes(q));
    out.sort((a, b) =>
      sortDir === "desc"
        ? b.count - a.count || a.label.localeCompare(b.label)
        : a.count - b.count || a.label.localeCompare(b.label),
    );
    return out;
  });
  let shown = $derived(items.slice(0, RENDER_CAP));
  // Bar scale is the largest count in the whole selection so bars stay
  // comparable regardless of sort direction or the render window.
  let countMax = $derived(
    items.reduce((m, i) => (i.count > m ? i.count : m), 1),
  );

  function toggleFilter(key: string) {
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    selected = next;
  }
</script>

<div class="scroll">
  <header>
    <div>
      <h1>History</h1>
      <p class="subtitle">
        How often each word and piece of jargon has come up — counts only.
      </p>
    </div>
    {#if data && (data.total_words > 0 || data.terms.length > 0)}
      <button class="clear-btn" onclick={clearAll} title="Delete all history">
        Clear history
      </button>
    {/if}
  </header>

  {#if loaded && !trackingOn}
    <div class="paused">
      ⏸ Recording is paused. Existing tallies are shown below — turn
      <strong>Record history</strong> back on in Settings to resume.
    </div>
  {/if}

  {#if !loaded}
    <p class="empty">Loading…</p>
  {:else if data && data.total_words === 0 && data.terms.length === 0}
    <div class="empty-state">
      <div class="empty-emoji">🎧</div>
      <h2>Nothing heard yet</h2>
      <p>
        Turn on <strong>Listening</strong> in the sidebar (or use the explain-selection
        hotkey). As words are spoken, TermScope tallies how often each one comes up
        — never what was said or when.
      </p>
    </div>
  {:else if data}
    <div class="stats">
      <div class="stat">
        <span class="stat-num" style="color: var(--accent)"
          >{data.total_words.toLocaleString()}</span
        ><span class="stat-label">Words heard</span>
      </div>
      <div class="stat">
        <span class="stat-num" style="color: var(--cyan)"
          >{data.unique_words.toLocaleString()}</span
        ><span class="stat-label">Unique words</span>
      </div>
      <div class="stat">
        <span class="stat-num" style="color: var(--gold)"
          >{data.total_jargon.toLocaleString()}</span
        ><span class="stat-label">Jargon said</span>
      </div>
      <div class="stat">
        <span class="stat-num" style="color: var(--purple)"
          >{data.terms.length.toLocaleString()}</span
        ><span class="stat-label">Unique jargon</span>
      </div>
    </div>

    <!-- ---- counts -------------------------------------------------------- -->
    <section class="block">
      <div class="block-head">
        <h2>Counts</h2>
        <div class="controls">
          <!-- multi-select filter dropdown -->
          <div class="dropdown">
            <button
              class="dd-btn"
              class:open={dropdownOpen}
              onclick={() => (dropdownOpen = !dropdownOpen)}
              title="Choose which words to show"
            >
              <span class="dd-label">{filterSummary}</span>
              <span class="dd-caret">▾</span>
            </button>
            {#if dropdownOpen}
              <!-- click-away backdrop -->
              <button
                class="dd-backdrop"
                aria-label="Close filter menu"
                onclick={() => (dropdownOpen = false)}
              ></button>
              <div class="dd-menu">
                {#each filters as f}
                  <label class="dd-opt" title={f.hint}>
                    <input
                      type="checkbox"
                      checked={selected.has(f.key)}
                      onchange={() => toggleFilter(f.key)}
                    />
                    <span>{f.label}</span>
                  </label>
                {/each}
              </div>
            {/if}
          </div>

          <!-- sort direction -->
          <div class="segmented">
            <button
              class:active={sortDir === "desc"}
              onclick={() => (sortDir = "desc")}
              title="Most frequent first">Most</button
            >
            <button
              class:active={sortDir === "asc"}
              onclick={() => (sortDir = "asc")}
              title="Least frequent first">Least</button
            >
          </div>
        </div>
      </div>

      <p class="hint">
        Word usage by frequency for the selected filter{selectedLabels.length ===
        1
          ? ""
          : "s"}, {sortDir === "desc" ? "most" : "least"} frequent first.
      </p>

      <input
        class="search"
        placeholder="Search for a word…"
        bind:value={search}
      />

      {#if selected.size === 0}
        <p class="empty">Pick at least one filter above.</p>
      {:else if items.length === 0}
        <p class="empty">
          {search.trim()
            ? `No matches for “${search}”.`
            : "Nothing tallied for the selected filters yet."}
        </p>
      {:else}
        <div class="list">
          {#each shown as i (i.key)}
            {@const accent = categoryColor(i.category ?? "")}
            <div class="crow">
              <div class="crow-main">
                <span class="term" style="color: {accent}">{i.label}</span>
                {#if i.category}
                  <span class="chip" style="background: {accent}"
                    >{i.category.toUpperCase()}</span
                  >
                {/if}
                {#if i.learned}<span class="learned">✓ learned</span>{/if}
                <span class="spacer"></span>
                <span class="count">{i.count}×</span>
              </div>
              <div class="cbar">
                <div
                  class="cbar-fill"
                  style="width: {(i.count / countMax) * 100}%; background: {accent}"
                ></div>
              </div>
              {#if i.definition}<div class="cdef">{i.definition}</div>{/if}
            </div>
          {/each}
        </div>
        {#if items.length > shown.length}
          <p class="more">
            +{(items.length - shown.length).toLocaleString()} more — search above
            to narrow.
          </p>
        {/if}
      {/if}
    </section>

    <p class="privacy">
      🔒 Only these frequency counts are saved to disk — never the order or timing
      of what was said, so past conversations can't be reconstructed.
    </p>
  {/if}
</div>

<style>
  .scroll {
    height: 100vh;
    overflow-y: auto;
    padding: 20px 24px 40px;
  }
  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
  }
  h1 {
    font-size: 26px;
    font-weight: 600;
    margin: 0 0 2px;
  }
  .subtitle {
    color: var(--text-muted);
    margin: 0 0 14px;
  }
  .clear-btn {
    flex-shrink: 0;
    height: 32px;
    padding: 0 14px;
    border-radius: 8px;
    background: var(--surface2);
    border: 1px solid var(--border);
    color: var(--text-muted);
    font-size: 12px;
    transition: background 0.12s, color 0.12s, border-color 0.12s;
  }
  .clear-btn:hover {
    background: var(--red);
    border-color: var(--red);
    color: var(--bg);
  }

  .paused {
    background: color-mix(in srgb, var(--gold) 14%, transparent);
    border: 1px solid color-mix(in srgb, var(--gold) 45%, transparent);
    color: var(--gold);
    border-radius: var(--radius);
    padding: 10px 14px;
    font-size: 12px;
    margin-bottom: 16px;
  }
  .empty {
    color: var(--text-faint);
    font-size: 12px;
    padding: 6px 2px;
  }
  .empty-state {
    text-align: center;
    color: var(--text-muted);
    padding: 60px 20px;
  }
  .empty-emoji {
    font-size: 44px;
  }
  .empty-state h2 {
    margin: 10px 0 6px;
    color: var(--text);
    font-size: 18px;
  }
  .empty-state p {
    max-width: 420px;
    margin: 0 auto;
    line-height: 1.5;
    font-size: 13px;
  }

  .stats {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 8px;
  }
  .stat {
    background: var(--surface2);
    border-radius: var(--radius);
    padding: 14px 18px;
    display: flex;
    flex-direction: column;
  }
  .stat-num {
    font-size: 26px;
    font-weight: 600;
  }
  .stat-label {
    color: var(--text-muted);
    font-size: 11px;
  }

  .block {
    background: var(--surface);
    border-radius: var(--radius);
    padding: 16px 20px;
    margin-top: 18px;
  }
  .block-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 4px;
  }
  h2 {
    font-size: 16px;
    font-weight: 600;
    margin: 0;
  }
  .hint {
    color: var(--text-muted);
    font-size: 11px;
    margin: 4px 0 12px;
  }

  .controls {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  /* multi-select filter dropdown */
  .dropdown {
    position: relative;
  }
  .dd-btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    max-width: 260px;
    height: 30px;
    padding: 0 10px;
    border-radius: 8px;
    background: var(--surface2);
    border: 1px solid var(--border);
    color: var(--text);
    font-size: 12px;
  }
  .dd-btn.open,
  .dd-btn:hover {
    border-color: var(--accent);
  }
  .dd-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .dd-caret {
    color: var(--text-muted);
    font-size: 10px;
  }
  .dd-backdrop {
    position: fixed;
    inset: 0;
    background: transparent;
    border: none;
    z-index: 10;
  }
  .dd-menu {
    position: absolute;
    top: calc(100% + 4px);
    right: 0;
    z-index: 11;
    min-width: 180px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 4px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  }
  .dd-opt {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 8px;
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
  }
  .dd-opt:hover {
    background: var(--surface3);
  }
  .dd-opt input {
    accent-color: var(--accent);
  }

  .segmented {
    display: inline-flex;
    background: var(--surface2);
    border-radius: 8px;
    padding: 2px;
  }
  .segmented button {
    padding: 6px 14px;
    border-radius: 6px;
    color: var(--text-muted);
    font-size: 12px;
  }
  .segmented button.active {
    background: var(--accent-dim);
    color: var(--text);
  }

  .search {
    width: 100%;
    height: 34px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    padding: 0 12px;
    margin-bottom: 12px;
  }
  .search:focus {
    outline: none;
    border-color: var(--accent);
  }

  .list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  /* jargon-count rows */
  .crow {
    background: var(--surface2);
    border-radius: var(--radius);
    padding: 12px 14px;
  }
  .crow-main {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .term {
    font-weight: 600;
    font-size: 15px;
  }
  .chip {
    font-size: 9px;
    font-weight: 600;
    color: var(--bg);
    border-radius: 6px;
    padding: 2px 6px;
  }
  .learned {
    color: var(--green);
    font-size: 11px;
  }
  .spacer {
    flex: 1;
  }
  .cbar {
    height: 5px;
    border-radius: 3px;
    background: var(--surface3);
    overflow: hidden;
    margin: 8px 0 6px;
  }
  .cbar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.3s;
  }
  .cdef {
    color: var(--text-muted);
    font-size: 12px;
    line-height: 1.45;
  }
  .count {
    color: var(--text);
    font-weight: 600;
    font-size: 13px;
  }

  .more {
    color: var(--text-faint);
    font-size: 11px;
    margin-top: 12px;
  }

  .privacy {
    color: var(--text-faint);
    font-size: 11px;
    line-height: 1.5;
    margin-top: 18px;
  }
</style>
