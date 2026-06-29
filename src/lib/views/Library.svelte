<script lang="ts">
  import { categoryColor, getLibraryDetail, openUrl } from "../api";
  import type { Detail, Entry } from "../types";

  let {
    entries,
    learned,
    toggleLearned,
    selectId = $bindable(),
  }: {
    entries: Entry[];
    learned: Set<string>;
    toggleLearned: (id: string) => void;
    selectId: string | null;
  } = $props();

  type Filter = "All" | "Tech" | "Business" | "Companies" | "Learned";
  const FILTERS: Filter[] = ["All", "Tech", "Business", "Companies", "Learned"];
  const FILTER_CAT: Record<string, string> = {
    Tech: "tech",
    Business: "business",
    Companies: "companies",
  };

  let query = $state("");
  let filter: Filter = $state("All");
  let selected: Entry | null = $state(null);
  let detail: Detail | null = $state(null);

  let filtered = $derived.by(() => {
    const q = query.trim().toLowerCase();
    return entries
      .filter((e) => {
        if (FILTER_CAT[filter] && e.category !== FILTER_CAT[filter]) return false;
        if (filter === "Learned" && !learned.has(e.id)) return false;
        if (
          q &&
          !e.term.toLowerCase().includes(q) &&
          !e.definition.toLowerCase().includes(q)
        )
          return false;
        return true;
      })
      .sort((a, b) =>
        a.term.toLowerCase().localeCompare(b.term.toLowerCase()),
      );
  });

  async function select(e: Entry) {
    selected = e;
    detail = null;
    detail = await getLibraryDetail(e.id);
  }

  $effect(() => {
    if (selectId) {
      const e = entries.find((x) => x.id === selectId);
      if (e) select(e);
      selectId = null;
    }
  });
</script>

<div class="library">
  <header>
    <h1>Library</h1>
    <div class="controls">
      <div class="segmented">
        {#each FILTERS as f}
          <button class:active={filter === f} onclick={() => (filter = f)}>{f}</button>
        {/each}
      </div>
      <input class="search" placeholder="Search terms…" bind:value={query} />
    </div>
  </header>

  <div class="cols">
    <div class="list">
      {#if filtered.length === 0}
        <div class="empty">No terms match.</div>
      {:else}
        {#each filtered as e (e.id)}
          {@const isLearned = learned.has(e.id)}
          <button
            class="row"
            class:selected={selected?.id === e.id}
            onclick={() => select(e)}
          >
            <span class="dot" style="color: {categoryColor(e.category)}">●</span>
            <span class="row-term">{e.term}</span>
            <span
              class="toggle"
              class:on={isLearned}
              role="button"
              tabindex="0"
              onclick={(ev) => {
                ev.stopPropagation();
                toggleLearned(e.id);
              }}
              onkeydown={(ev) => {
                if (ev.key === "Enter") {
                  ev.stopPropagation();
                  toggleLearned(e.id);
                }
              }}
            >
              {isLearned ? "✓" : "+"}
            </span>
          </button>
        {/each}
      {/if}
    </div>

    <div class="detail">
      {#if !selected}
        <div class="empty">Select a term to read its full definition.</div>
      {:else}
        {@const accent = categoryColor(selected.category)}
        {@const isLearned = learned.has(selected.id)}
        <div class="detail-head">
          <span class="chip" style="background: {accent}">{selected.category.toUpperCase()}</span>
          {#if isLearned}<span class="learned-tag">✓ learned</span>{/if}
        </div>
        <h2 class="detail-term" style="color: {accent}">{selected.term}</h2>
        <p class="detail-def">{detail ? detail.extended : selected.definition}</p>
        {#if detail?.source}
          <div class="source">Source: {detail.source}</div>
        {/if}
        <div class="actions">
          {#if detail?.url}
            <button class="btn-outline" onclick={() => openUrl(detail!.url!)}>Learn more ↗</button>
          {/if}
          {#if isLearned}
            <button class="btn-muted" onclick={() => toggleLearned(selected!.id)}>Unlearn</button>
          {:else}
            <button class="btn-green" onclick={() => toggleLearned(selected!.id)}>✓ Mark learned</button>
          {/if}
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  .library {
    display: flex;
    flex-direction: column;
    height: 100vh;
    padding: 24px 24px 0;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
    gap: 16px;
    flex-wrap: wrap;
  }
  h1 {
    font-size: 26px;
    font-weight: 600;
    margin: 0;
  }
  .controls {
    display: flex;
    gap: 10px;
    align-items: center;
  }
  .segmented {
    display: flex;
    background: var(--surface2);
    border-radius: 8px;
    padding: 2px;
  }
  .segmented button {
    padding: 6px 12px;
    border-radius: 6px;
    color: var(--text-muted);
    font-size: 11px;
  }
  .segmented button.active {
    background: var(--accent-dim);
    color: var(--text);
  }
  .search {
    width: 220px;
    height: 34px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    padding: 0 12px;
    outline: none;
  }
  .search:focus {
    border-color: var(--accent);
  }
  .cols {
    display: grid;
    grid-template-columns: 3fr 4fr;
    gap: 16px;
    flex: 1;
    min-height: 0;
    padding-bottom: 24px;
  }
  .list,
  .detail {
    background: var(--surface);
    border-radius: var(--radius);
    overflow-y: auto;
  }
  .list {
    padding: 6px;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    height: 40px;
    padding: 0 8px;
    border-radius: 8px;
    color: var(--text);
    text-align: left;
  }
  .row:hover {
    background: var(--surface3);
  }
  .row.selected {
    background: var(--surface3);
  }
  .dot {
    font-size: 10px;
  }
  .row-term {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .toggle {
    width: 26px;
    height: 22px;
    border-radius: 6px;
    border: 1px solid var(--border);
    color: var(--text-faint);
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 600;
    flex-shrink: 0;
  }
  .toggle.on {
    background: var(--green);
    color: var(--bg);
    border-color: transparent;
  }
  .detail {
    padding: 20px;
  }
  .detail-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .chip {
    font-size: 10px;
    font-weight: 600;
    color: var(--bg);
    border-radius: 8px;
    padding: 3px 8px;
  }
  .learned-tag {
    color: var(--green);
    font-size: 11px;
  }
  .detail-term {
    font-size: 26px;
    font-weight: 600;
    margin: 8px 0;
  }
  .detail-def {
    line-height: 1.55;
    color: var(--text);
    margin: 0 0 12px;
  }
  .source {
    color: var(--text-faint);
    font-size: 11px;
    margin-bottom: 12px;
  }
  .actions {
    display: flex;
    gap: 8px;
  }
  .actions button {
    height: 34px;
    padding: 0 14px;
    border-radius: 8px;
    font-size: 12px;
  }
  .btn-outline {
    border: 1px solid var(--accent);
    color: var(--accent);
  }
  .btn-outline:hover {
    background: var(--surface3);
  }
  .btn-green {
    background: var(--green);
    color: var(--bg);
    font-weight: 600;
  }
  .btn-green:hover {
    background: var(--green-hover);
  }
  .btn-muted {
    background: var(--surface3);
    color: var(--text);
  }
  .btn-muted:hover {
    background: var(--border);
  }
  .empty {
    padding: 24px;
    color: var(--text-faint);
  }
</style>
