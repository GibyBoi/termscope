<script lang="ts">
  import { onMount } from "svelte";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import * as api from "../api";
  import { categoryColor } from "../api";
  import type { History } from "../types";

  let data: History | null = $state(null);
  let loaded = $state(false);
  let trackingOn = $state(true); // mirrors config.track_history, for the paused hint

  // "jargon" = how often each dictionary term was said; "words" = a tally of
  // every spoken word ever captured.
  let countMode: "jargon" | "words" = $state("jargon");
  let wordSearch = $state("");

  // Chronological log controls.
  let logCount = $state(30); // 20–100, driven by the slider
  let sourceFilter: "All" | "Heard" | "Selected" = $state("All");

  // The all-words tally can grow large; render a window of it (search narrows).
  const WORD_RENDER_CAP = 400;

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
        "Clear all history? This permanently deletes every word and jargon tally and the recent log.",
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
      unlisteners.push(await listen("ts://history", scheduleRefetch));
      unlisteners.push(await listen("ts://refresh", scheduleRefetch));
    })();
    return () => {
      clearTimeout(refetchTimer);
      unlisteners.forEach((u) => u());
    };
  });

  // ---- derived views --------------------------------------------------------

  let termMax = $derived(data && data.terms.length ? data.terms[0].count : 1);

  let filteredWords = $derived.by(() => {
    if (!data) return [];
    const q = wordSearch.trim().toLowerCase();
    return q ? data.words.filter((w) => w.word.includes(q)) : data.words;
  });
  let shownWords = $derived(filteredWords.slice(0, WORD_RENDER_CAP));
  let wordMax = $derived(shownWords.length ? shownWords[0].count : 1);

  let filteredLog = $derived.by(() => {
    if (!data) return [];
    if (sourceFilter === "Heard")
      return data.log.filter((e) => e.source === "audio");
    if (sourceFilter === "Selected")
      return data.log.filter((e) => e.source === "selection");
    return data.log;
  });
  let shownLog = $derived(filteredLog.slice(0, logCount));

  // Insert a day header whenever the calendar day changes (newest-first order).
  type LogRow = { header: string } | { it: (typeof shownLog)[number] };
  let shownLogRows = $derived.by<LogRow[]>(() => {
    const out: LogRow[] = [];
    let last = "";
    for (const it of shownLog) {
      const lbl = dayLabel(it.ts);
      if (lbl !== last) {
        out.push({ header: lbl });
        last = lbl;
      }
      out.push({ it });
    }
    return out;
  });

  const sourceMeta: Record<string, { label: string; icon: string }> = {
    audio: { label: "Heard", icon: "🔊" },
    selection: { label: "Selected", icon: "✎" },
  };

  function fmtTime(ts: number): string {
    const d = new Date(ts * 1000);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 45) return "just now";
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  function fmtClock(ts: number): string {
    return new Date(ts * 1000).toLocaleString();
  }
  function dayLabel(ts: number): string {
    const d = new Date(ts * 1000);
    const startOf = (x: Date) =>
      new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const days = Math.round((startOf(new Date()) - startOf(d)) / 86_400_000);
    if (days <= 0) return "Today";
    if (days === 1) return "Yesterday";
    return d.toLocaleDateString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  }
</script>

<div class="scroll">
  <header>
    <div>
      <h1>History</h1>
      <p class="subtitle">
        Every word TermScope has heard, and the jargon it caught — over time.
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
      ⏸ Recording is paused. Existing history is shown below — turn
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
        hotkey). As words are spoken, your tallies and a chronological jargon log
        build up here.
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
        <div class="segmented">
          <button
            class:active={countMode === "jargon"}
            onclick={() => (countMode = "jargon")}>Jargon terms</button
          >
          <button
            class:active={countMode === "words"}
            onclick={() => (countMode = "words")}>All words</button
          >
        </div>
      </div>

      {#if countMode === "jargon"}
        <p class="hint">How many times each dictionary term has been said.</p>
        {#if data.terms.length === 0}
          <p class="empty">No jargon caught yet.</p>
        {:else}
          <div class="list">
            {#each data.terms as t}
              {@const accent = categoryColor(t.category)}
              <div class="crow">
                <div class="crow-main">
                  <span class="term" style="color: {accent}">{t.term}</span>
                  <span class="chip" style="background: {accent}"
                    >{t.category.toUpperCase()}</span
                  >
                  {#if t.learned}<span class="learned">✓ learned</span>{/if}
                  <span class="spacer"></span>
                  <span class="count">{t.count}×</span>
                </div>
                <div class="cbar">
                  <div
                    class="cbar-fill"
                    style="width: {(t.count / termMax) * 100}%; background: {accent}"
                  ></div>
                </div>
                <div class="cdef">{t.definition}</div>
              </div>
            {/each}
          </div>
        {/if}
      {:else}
        <p class="hint">
          A complete tally of every spoken word captured by the microphone.
        </p>
        <input
          class="search"
          placeholder="Filter words…"
          bind:value={wordSearch}
        />
        {#if filteredWords.length === 0}
          <p class="empty">
            {wordSearch.trim()
              ? `No words match “${wordSearch}”.`
              : "No spoken words captured yet."}
          </p>
        {:else}
          <div class="wgrid">
            {#each shownWords as w}
              <div class="wrow">
                <span class="wword" title={w.word}>{w.word}</span>
                <div class="wbar">
                  <div
                    class="wbar-fill"
                    style="width: {(w.count / wordMax) * 100}%"
                  ></div>
                </div>
                <span class="wcount">{w.count}</span>
              </div>
            {/each}
          </div>
          {#if filteredWords.length > shownWords.length}
            <p class="more">
              +{(filteredWords.length - shownWords.length).toLocaleString()} more
              — type above to narrow.
            </p>
          {/if}
        {/if}
      {/if}
    </section>

    <!-- ---- chronological log -------------------------------------------- -->
    <section class="block">
      <div class="block-head">
        <h2>Recent jargon</h2>
        <div class="slider-wrap">
          <span class="slider-label">Last {logCount}</span>
          <input
            type="range"
            min="20"
            max="100"
            step="5"
            bind:value={logCount}
          />
        </div>
      </div>

      <div class="segmented small">
        {#each ["All", "Heard", "Selected"] as f}
          <button
            class:active={sourceFilter === f}
            onclick={() => (sourceFilter = f as typeof sourceFilter)}>{f}</button
          >
        {/each}
      </div>

      {#if shownLog.length === 0}
        <p class="empty">No jargon logged yet for this filter.</p>
      {:else}
        <div class="list">
          {#each shownLogRows as row}
            {#if "header" in row}
              <div class="day-sep">{row.header}</div>
            {:else}
              {@const it = row.it}
              {@const accent = categoryColor(it.category)}
              <div class="row">
                <div class="stripe" style="background: {accent}"></div>
                <div class="body">
                  <div class="row-top">
                    <span class="term" style="color: {accent}">{it.term}</span>
                    <span class="chip" style="background: {accent}"
                      >{it.category.toUpperCase()}</span
                    >
                    {#if it.learned}<span class="learned">✓ learned</span>{/if}
                    <span class="spacer"></span>
                    <span class="src">
                      {sourceMeta[it.source].icon}
                      {sourceMeta[it.source].label}
                    </span>
                    <span class="time" title={fmtClock(it.ts)}>{fmtTime(it.ts)}</span>
                  </div>
                  <div class="def">{it.definition}</div>
                </div>
              </div>
            {/if}
          {/each}
        </div>
        <p class="foot">
          Showing {shownLog.length} of {filteredLog.length} recent
          {filteredLog.length === 1 ? "entry" : "entries"} (TermScope keeps the
          last 100).
        </p>
      {/if}
    </section>
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
  .day-sep {
    color: var(--text-faint);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin: 10px 2px 2px;
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
  .segmented.small {
    margin-bottom: 14px;
  }
  .segmented.small button {
    padding: 5px 12px;
    font-size: 11px;
  }

  .slider-wrap {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .slider-label {
    color: var(--text-muted);
    font-size: 11px;
    min-width: 52px;
    text-align: right;
  }
  input[type="range"] {
    width: 140px;
    accent-color: var(--accent);
    cursor: pointer;
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

  /* all-words grid */
  .wgrid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 6px 18px;
  }
  .wrow {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .wword {
    width: 120px;
    flex-shrink: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 12px;
  }
  .wbar {
    flex: 1;
    height: 6px;
    border-radius: 3px;
    background: var(--surface3);
    overflow: hidden;
  }
  .wbar-fill {
    height: 100%;
    background: var(--cyan);
    border-radius: 3px;
  }
  .wcount {
    width: 44px;
    text-align: right;
    color: var(--text-muted);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
  }
  .more {
    color: var(--text-faint);
    font-size: 11px;
    margin-top: 12px;
  }

  /* chronological log rows */
  .row {
    display: flex;
    background: var(--surface2);
    border-radius: var(--radius);
    overflow: hidden;
  }
  .stripe {
    width: 4px;
    flex-shrink: 0;
  }
  .body {
    flex: 1;
    padding: 12px 14px;
    min-width: 0;
  }
  .row-top {
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
  .src {
    color: var(--text-muted);
    font-size: 11px;
    white-space: nowrap;
  }
  .time {
    color: var(--text-faint);
    font-size: 11px;
    min-width: 56px;
    text-align: right;
  }
  .def {
    color: var(--text-muted);
    font-size: 12px;
    margin-top: 4px;
    line-height: 1.45;
  }
  .foot {
    color: var(--text-faint);
    font-size: 11px;
    text-align: center;
    margin-top: 14px;
  }
</style>
