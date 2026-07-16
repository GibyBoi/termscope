<script lang="ts">
  import { onMount } from "svelte";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import * as api from "../api";
  import { categoryColor } from "../api";
  import type { History } from "../types";
  import {
    buildFilters,
    categoryLabel,
    collectItems,
    orderedCategories,
    type DisplayItem,
    type FilterDef,
  } from "../historyFilters";
  import DonutChart, {
    type Slice,
  } from "../components/DonutChart.svelte";
  import TrendChart, {
    type TrendPoint,
  } from "../components/TrendChart.svelte";

  let data: History | null = $state(null);
  let fillerWords = $state<Set<string>>(new Set());
  let categories = $state<string[]>([]); // config.enabled_categories, for filters
  let loaded = $state(false);
  let trackingOn = $state(true); // mirrors config.track_history, for the paused hint
  let fillerGoal = $state(0); // mirrors config.filler_goal_percent (0 = off)

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
      const cfg = await api.getConfig();
      trackingOn = cfg.track_history;
      categories = cfg.enabled_categories;
      fillerGoal = cfg.filler_goal_percent;
    } catch {}
    loaded = true;
  }

  async function saveGoal(value: number) {
    fillerGoal = Math.max(0, Math.min(100, value));
    await api.setConfigKey("filler_goal_percent", fillerGoal);
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
    data ? buildFilters({ data, fillerWords, categories }) : [],
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

  // ---- insights charts --------------------------------------------------------
  // All derived from the same orderless tallies as everything else — pure
  // frequency aggregates, so nothing here introduces a timeline either.

  // Jargon detections summed per category, in the stable category order so a
  // slice's position and color never depend on current counts.
  let catSlices = $derived.by<Slice[]>(() => {
    if (!data) return [];
    const sums = new Map<string, number>();
    for (const t of data.terms)
      sums.set(t.category, (sums.get(t.category) ?? 0) + t.count);
    return orderedCategories(new Set(sums.keys())).map((c) => ({
      label: categoryLabel(c),
      value: sums.get(c) ?? 0,
      color: categoryColor(c),
    }));
  });

  const TOP_N = 8;
  let topJargon = $derived(
    data
      ? [...data.terms]
          .sort((a, b) => b.count - a.count || a.term.localeCompare(b.term))
          .slice(0, TOP_N)
      : [],
  );
  let topMax = $derived(topJargon[0]?.count ?? 1);

  // Filler share: how much of everything heard was verbal filler.
  let fillerCount = $derived(
    data
      ? data.words.reduce(
          (s, w) => (fillerWords.has(w.word) ? s + w.count : s),
          0,
        )
      : 0,
  );
  let fillerPct = $derived(
    data && data.total_words > 0
      ? (fillerCount / data.total_words) * 100
      : 0,
  );

  // Learned coverage: of the unique jargon terms actually heard, how many are
  // already marked learned.
  let learnedHeard = $derived(
    data ? data.terms.filter((t) => t.learned).length : 0,
  );
  let learnedPct = $derived(
    data && data.terms.length > 0
      ? (learnedHeard / data.terms.length) * 100
      : 0,
  );

  function pct1(v: number): string {
    return v > 0 && v < 1 ? "<1" : v.toFixed(0);
  }

  // ---- filler-reduction goal (microphone only) --------------------------------

  const TREND_DAYS = 45; // most recent day-buckets plotted
  let trend = $derived.by<TrendPoint[]>(() => {
    if (!data) return [];
    return data.days.slice(-TREND_DAYS).map((d) => ({
      date: d.date,
      pct: d.mic_words > 0 ? (d.mic_filler / d.mic_words) * 100 : 0,
      words: d.mic_words,
      filler: d.mic_filler,
    }));
  });

  // "Recent" = the last 7 recorded days, so a quiet week doesn't blank the stat.
  let recent = $derived.by(() => {
    if (!data) return { pct: 0, words: 0, filler: 0 };
    const last = data.days.slice(-7);
    const words = last.reduce((s, d) => s + d.mic_words, 0);
    const filler = last.reduce((s, d) => s + d.mic_filler, 0);
    return { pct: words > 0 ? (filler / words) * 100 : 0, words, filler };
  });
  let allTimePct = $derived(
    data && data.mic_words > 0 ? (data.mic_filler / data.mic_words) * 100 : 0,
  );
  let onGoal = $derived(fillerGoal > 0 && recent.pct <= fillerGoal);
  let topFillers = $derived(data ? data.mic_fillers.slice(0, 5) : []);

  function toggleFilter(key: string) {
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    selected = next;
  }

  // ---- per-row deletion (two-step: first click arms, second confirms) --------

  let armedDelete = $state<string | null>(null);
  let armTimer: ReturnType<typeof setTimeout> | undefined;

  async function requestDelete(item: DisplayItem) {
    if (armedDelete !== item.key) {
      armedDelete = item.key; // step 1: arm — a second click confirms
      clearTimeout(armTimer);
      armTimer = setTimeout(() => (armedDelete = null), 4000);
      return;
    }
    clearTimeout(armTimer); // step 2: confirmed
    armedDelete = null;
    if (item.termId) await api.removeTerm(item.termId);
    else await api.removeWord(item.label);
    await load(); // ts://history also fires, but refresh immediately
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

    <!-- ---- insights charts ------------------------------------------------ -->
    <section class="block">
      <div class="block-head">
        <h2>At a glance</h2>
      </div>
      <p class="hint">
        Frequency breakdowns of the same tallies below — still counts only, no
        timeline.
      </p>

      <div class="charts">
        <div class="chart-cell">
          <h3>Jargon by category</h3>
          {#if data.total_jargon > 0}
            <DonutChart
              slices={catSlices}
              centerValue={data.total_jargon.toLocaleString()}
              centerLabel="jargon heard"
            />
          {:else}
            <p class="empty">No jargon detected yet.</p>
          {/if}
        </div>

        <div class="chart-cell">
          <h3>Top jargon</h3>
          {#if topJargon.length > 0}
            <div class="tj-list">
              {#each topJargon as t (t.id)}
                {@const accent = categoryColor(t.category)}
                <div class="tj-row" title="{t.term} — {t.definition}">
                  <span class="tj-label">{t.term}</span>
                  <div class="tj-bar">
                    <div
                      class="tj-fill"
                      style="width: {(t.count / topMax) * 100}%; background: {accent}"
                    ></div>
                  </div>
                  <span class="tj-count">{t.count}×</span>
                </div>
              {/each}
            </div>
          {:else}
            <p class="empty">No jargon detected yet.</p>
          {/if}
        </div>
      </div>

      <div class="meters">
        <div class="meter">
          <div class="meter-top">
            <span class="meter-name">Filler words (mic)</span>
            <span class="meter-val" style="color: var(--gold)"
              >{data.mic_words > 0 ? `${pct1(allTimePct)}%` : "—"}</span
            >
          </div>
          <div class="mbar">
            <div
              class="mbar-fill"
              style="width: {Math.min(allTimePct, 100)}%; background: var(--gold)"
            ></div>
          </div>
          <p class="meter-hint">
            {#if data.mic_words > 0}
              {data.mic_filler.toLocaleString()} of {data.mic_words.toLocaleString()}
              words <em>you spoke</em> were filler (um, like, basically…).
            {:else}
              Nothing heard from your microphone yet — this counts only what
              you say, never system audio.
            {/if}
            {#if fillerCount > 0}
              <span class="meter-extra"
                >Across all audio incl. system sounds: {pct1(fillerPct)}% ({fillerCount.toLocaleString()}
                of {data.total_words.toLocaleString()}).</span
              >
            {/if}
          </p>
        </div>
        <div class="meter">
          <div class="meter-top">
            <span class="meter-name">Learned coverage</span>
            <span class="meter-val" style="color: var(--green)"
              >{pct1(learnedPct)}%</span
            >
          </div>
          <div class="mbar">
            <div
              class="mbar-fill"
              style="width: {Math.min(learnedPct, 100)}%; background: var(--green)"
            ></div>
          </div>
          <p class="meter-hint">
            {learnedHeard.toLocaleString()} of {data.terms.length.toLocaleString()}
            unique jargon terms you've heard are marked learned.
          </p>
        </div>
      </div>
    </section>

    <!-- ---- filler-reduction goal (microphone only) ------------------------ -->
    <section class="block">
      <div class="block-head">
        <h2>Filler goal</h2>
        <label class="goal-set">
          <span>Target</span>
          <input
            class="goal-input"
            type="number"
            min="0"
            max="100"
            step="0.5"
            value={fillerGoal}
            onchange={(e) => saveGoal(Number(e.currentTarget.value))}
            title="Max % of your spoken words that may be filler. 0 turns the goal off."
          />
          <span>%</span>
        </label>
      </div>
      <p class="hint">
        How much of what <em>you say</em> is filler — counted from the
        microphone only, never from system audio.
      </p>

      {#if data.mic_words === 0}
        <p class="empty">
          Nothing heard from the microphone yet. Turn on <strong>Listening</strong>
          with the microphone enabled in Settings, and your filler rate will
          chart here day by day.
        </p>
      {:else}
        <div class="goal-stats">
          <div class="goal-stat">
            <span
              class="goal-num"
              style="color: {fillerGoal > 0
                ? onGoal
                  ? 'var(--green)'
                  : 'var(--red)'
                : 'var(--gold)'}">{recent.pct.toFixed(1)}%</span
            >
            <span class="goal-label"
              >last {Math.min(data.days.length, 7)} recorded day{data.days
                .length === 1
                ? ""
                : "s"}</span
            >
            {#if fillerGoal > 0}
              <span class="goal-verdict" class:ok={onGoal}>
                {onGoal
                  ? "✓ on goal"
                  : `${(recent.pct - fillerGoal).toFixed(1)}% over goal`}
              </span>
            {/if}
          </div>
          <div class="goal-stat">
            <span class="goal-num" style="color: var(--text-muted)"
              >{allTimePct.toFixed(1)}%</span
            >
            <span class="goal-label"
              >all time — {data.mic_filler.toLocaleString()} filler of
              {data.mic_words.toLocaleString()} words</span
            >
          </div>
        </div>

        {#if trend.length > 0}
          <TrendChart points={trend} goal={fillerGoal} />
        {/if}

        {#if topFillers.length > 0}
          <div class="top-fillers">
            <span class="tf-label">Your top fillers:</span>
            {#each topFillers as f (f.word)}
              <span class="tf-chip"
                >{f.word} <strong>{f.count.toLocaleString()}×</strong></span
              >
            {/each}
          </div>
        {/if}
      {/if}
    </section>

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
                <button
                  class="del"
                  class:armed={armedDelete === i.key}
                  title={armedDelete === i.key
                    ? "Click again to permanently delete"
                    : i.termId
                      ? "Not jargon? Delete this term from TermScope everywhere"
                      : "Delete this word and never count it again"}
                  onclick={() => requestDelete(i)}
                >
                  {armedDelete === i.key ? "Delete?" : "🗑"}
                </button>
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
      🔒 Only frequency counts are saved to disk — never the order or timing of
      what was said, so past conversations can't be reconstructed. The filler
      goal additionally keeps two anonymous totals per day (words and filler
      heard from the mic) to chart your progress — no words, no text.
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

  /* insights charts */
  h3 {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
    margin: 0 0 10px;
    text-transform: uppercase;
    letter-spacing: 0.4px;
  }
  .charts {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-top: 4px;
  }
  @media (max-width: 860px) {
    .charts {
      grid-template-columns: 1fr;
    }
  }
  .chart-cell {
    background: var(--surface2);
    border-radius: var(--radius);
    padding: 14px 16px;
    min-width: 0;
  }
  .tj-list {
    display: flex;
    flex-direction: column;
    gap: 7px;
  }
  .tj-row {
    display: grid;
    grid-template-columns: 110px 1fr 42px;
    align-items: center;
    gap: 10px;
    font-size: 12px;
  }
  .tj-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 600;
  }
  .tj-bar {
    height: 8px;
    border-radius: 4px;
    background: var(--surface3);
    overflow: hidden;
  }
  .tj-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s;
  }
  .tj-count {
    color: var(--text-muted);
    font-weight: 600;
    text-align: right;
  }

  .meters {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-top: 20px;
  }
  @media (max-width: 860px) {
    .meters {
      grid-template-columns: 1fr;
    }
  }
  .meter {
    background: var(--surface2);
    border-radius: var(--radius);
    padding: 14px 16px;
    min-width: 0;
  }
  .meter-top {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 8px;
  }
  .meter-name {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.4px;
  }
  .meter-val {
    font-size: 20px;
    font-weight: 600;
  }
  .mbar {
    height: 8px;
    border-radius: 4px;
    background: var(--surface3);
    overflow: hidden;
  }
  .mbar-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s;
  }
  .meter-hint {
    color: var(--text-faint);
    font-size: 11px;
    margin: 8px 0 0;
    line-height: 1.4;
  }
  .meter-extra {
    display: block;
    margin-top: 4px;
    color: var(--text-faint);
    opacity: 0.8;
  }

  /* filler goal */
  .goal-set {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--text-muted);
  }
  .goal-input {
    width: 64px;
    height: 30px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    padding: 0 8px;
    font-size: 13px;
  }
  .goal-input:focus {
    outline: none;
    border-color: var(--accent);
  }
  .goal-stats {
    display: flex;
    gap: 28px;
    align-items: baseline;
    flex-wrap: wrap;
    margin: 4px 0 14px;
  }
  .goal-stat {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }
  .goal-num {
    font-size: 30px;
    font-weight: 600;
  }
  .goal-label {
    color: var(--text-muted);
    font-size: 11px;
  }
  .goal-verdict {
    font-size: 11px;
    font-weight: 600;
    color: var(--red);
    background: color-mix(in srgb, var(--red) 14%, transparent);
    border-radius: 6px;
    padding: 2px 8px;
  }
  .goal-verdict.ok {
    color: var(--green);
    background: color-mix(in srgb, var(--green) 14%, transparent);
  }
  .top-fillers {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 14px;
  }
  .tf-label {
    color: var(--text-muted);
    font-size: 11px;
  }
  .tf-chip {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 3px 10px;
    font-size: 12px;
    color: var(--gold);
  }
  .tf-chip strong {
    color: var(--text-muted);
    font-weight: 600;
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
  .del {
    margin-left: 8px;
    height: 24px;
    min-width: 28px;
    padding: 0 6px;
    border-radius: 6px;
    font-size: 12px;
    color: var(--text-faint);
    background: transparent;
    border: 1px solid transparent;
    transition: color 0.12s, background 0.12s, border-color 0.12s;
  }
  .del:hover {
    color: var(--red);
    border-color: var(--red);
  }
  .del.armed {
    background: var(--red);
    border-color: var(--red);
    color: var(--bg);
    font-weight: 600;
    font-size: 11px;
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
