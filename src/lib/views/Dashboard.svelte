<script lang="ts">
  import { categoryColor } from "../api";
  import type { Entry } from "../types";

  let { entries, learned }: { entries: Entry[]; learned: Set<string> } =
    $props();

  const MILESTONES = [
    { thresh: 1, name: "First Word" },
    { thresh: 5, name: "Warming Up" },
    { thresh: 10, name: "Quick Study" },
    { thresh: 25, name: "Jargon Hunter" },
    { thresh: 50, name: "Buzzword Slayer" },
    { thresh: 100, name: "Corporate Fluent" },
    { thresh: 175, name: "Silver Tongue" },
    { thresh: 250, name: "Jargon Master" },
  ];

  let total = $derived(entries.length);
  let learnedCount = $derived(learned.size);
  let pct = $derived(total ? Math.round((learnedCount / total) * 100) : 0);

  let categories = $derived.by(() => {
    const m = new Map<string, { done: number; total: number }>();
    for (const e of entries) {
      const c = m.get(e.category) ?? { done: 0, total: 0 };
      c.total++;
      if (learned.has(e.id)) c.done++;
      m.set(e.category, c);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  });

  let nextIdx = $derived(MILESTONES.findIndex((m) => learnedCount < m.thresh));
  let nextGoal = $derived.by(() => {
    if (nextIdx < 0) return null;
    const m = MILESTONES[nextIdx];
    const prev = nextIdx > 0 ? MILESTONES[nextIdx - 1].thresh : 0;
    const span = m.thresh - prev || 1;
    return {
      name: m.name,
      thresh: m.thresh,
      remaining: m.thresh - learnedCount,
      progress: Math.max(0, Math.min(1, (learnedCount - prev) / span)),
    };
  });
</script>

<div class="scroll">
  <h1>Dashboard</h1>
  <p class="subtitle">Your jargon, decoded — and how much of it you've mastered.</p>

  <div class="stats">
    <div class="stat-card">
      <div class="stat-value" style="color: var(--green)">{learnedCount}</div>
      <div class="stat-label">Terms learned</div>
    </div>
    <div class="stat-card">
      <div class="stat-value" style="color: var(--accent)">{total}</div>
      <div class="stat-label">Terms tracked</div>
    </div>
    <div class="stat-card">
      <div class="stat-value" style="color: var(--purple)">{pct}%</div>
      <div class="stat-label">Mastery</div>
    </div>
  </div>

  <section class="panel">
    <h2>Milestones</h2>
    {#if nextGoal}
      <div class="next-goal">
        Next: learn {nextGoal.remaining} more to unlock “{nextGoal.name}” ({learnedCount}/{nextGoal.thresh})
      </div>
      <div class="bar"><div class="bar-fill gold" style="width: {nextGoal.progress * 100}%"></div></div>
    {:else}
      <div class="next-goal">Every milestone unlocked — you're a true jargon master!</div>
    {/if}
    <div class="badges">
      {#each MILESTONES as m}
        {@const got = learnedCount >= m.thresh}
        <div class="badge" class:got>
          <div class="badge-star">{got ? "★" : "☆"}</div>
          <div class="badge-name">{m.name}</div>
          <div class="badge-thresh">{m.thresh} terms</div>
        </div>
      {/each}
    </div>
  </section>

  <section class="panel">
    <h2>Progress by category</h2>
    {#each categories as [cat, c]}
      <div class="cat-row">
        <div class="cat-top">
          <span class="cat-name">{cat[0].toUpperCase() + cat.slice(1)}</span>
          <span class="cat-count">{c.done} / {c.total}</span>
        </div>
        <div class="bar">
          <div
            class="bar-fill"
            style="width: {c.total ? (c.done / c.total) * 100 : 0}%; background: {categoryColor(cat)}"
          ></div>
        </div>
      </div>
    {/each}
  </section>

  <p class="tip">
    Tip: click “✓ Learned” on a pop-up (or in the Library) to retire a term — it
    won't interrupt you again.
  </p>
</div>

<style>
  .scroll {
    height: 100vh;
    overflow-y: auto;
    padding: 20px 24px 40px;
  }
  h1 {
    font-size: 26px;
    font-weight: 600;
    margin: 0 0 2px;
  }
  .subtitle {
    color: var(--text-muted);
    margin: 0 0 18px;
  }
  .stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
  }
  .stat-card {
    background: var(--surface2);
    border-radius: var(--radius);
    padding: 16px 20px;
  }
  .stat-value {
    font-size: 34px;
    font-weight: 600;
  }
  .stat-label {
    color: var(--text-muted);
    font-size: 11px;
    margin-top: 2px;
  }
  .panel {
    background: var(--surface);
    border-radius: var(--radius);
    padding: 16px 20px;
    margin-top: 22px;
  }
  h2 {
    font-size: 16px;
    font-weight: 600;
    margin: 0 0 10px;
  }
  .next-goal {
    color: var(--text-muted);
    font-size: 11px;
    margin-bottom: 6px;
  }
  .bar {
    height: 8px;
    border-radius: 4px;
    background: var(--surface3);
    overflow: hidden;
  }
  .bar-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s;
  }
  .bar-fill.gold {
    background: var(--gold);
  }
  .badges {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    margin-top: 16px;
  }
  .badge {
    text-align: center;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 4px;
    color: var(--text-muted);
  }
  .badge.got {
    background: var(--surface2);
    border-color: var(--gold);
    color: var(--text);
  }
  .badge-star {
    font-size: 22px;
    color: var(--text-faint);
  }
  .badge.got .badge-star {
    color: var(--gold);
  }
  .badge-name {
    font-weight: 600;
    font-size: 11px;
    margin-top: 2px;
  }
  .badge-thresh {
    font-size: 10px;
    color: var(--text-faint);
  }
  .cat-row {
    margin: 10px 0;
  }
  .cat-top {
    display: flex;
    justify-content: space-between;
    margin-bottom: 4px;
  }
  .cat-name {
    font-weight: 600;
  }
  .cat-count {
    color: var(--text-muted);
    font-size: 11px;
  }
  .tip {
    color: var(--text-faint);
    font-size: 11px;
    margin-top: 16px;
  }
</style>
