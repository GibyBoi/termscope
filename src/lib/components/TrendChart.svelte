<script lang="ts" module>
  /** One plotted day: the date, its filler %, and the underlying counts. */
  export interface TrendPoint {
    date: string; // "YYYY-MM-DD"
    pct: number; // filler % that day, 0-100
    words: number;
    filler: number;
  }
</script>

<script lang="ts">
  // SVG line chart of the daily mic filler %, with an optional dashed goal
  // line. One series, so no legend — the panel title names it. Hovering snaps
  // to the nearest day and shows its exact counts.
  let {
    points,
    goal = 0,
  }: { points: TrendPoint[]; goal?: number } = $props();

  const W = 560;
  const H = 150;
  const PAD_L = 34; // room for the y-axis % labels
  const PAD_R = 10;
  const PAD_T = 10;
  const PAD_B = 22; // room for the x-axis date labels

  let yMax = $derived.by(() => {
    const top = Math.max(
      5,
      goal > 0 ? goal * 1.3 : 0,
      ...points.map((p) => p.pct),
    );
    return Math.ceil((top * 1.15) / 5) * 5; // headroom, rounded to a 5% step
  });

  function x(i: number): number {
    const n = Math.max(points.length - 1, 1);
    return PAD_L + (i / n) * (W - PAD_L - PAD_R);
  }
  function y(pct: number): number {
    return PAD_T + (1 - pct / yMax) * (H - PAD_T - PAD_B);
  }

  let path = $derived(
    points
      .map((p, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(p.pct).toFixed(1)}`)
      .join(" "),
  );
  let yTicks = $derived([0, yMax / 2, yMax]);

  /** Short "Jul 16" label from "YYYY-MM-DD" without Date-object timezone traps. */
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function shortDate(d: string): string {
    const [, m, day] = d.split("-").map(Number);
    return `${MONTHS[(m ?? 1) - 1]} ${day ?? ""}`;
  }

  // ---- hover ------------------------------------------------------------------
  let hovered = $state<number | null>(null);
  let wrap: HTMLDivElement;
  let tipX = $state(0);

  function onMove(ev: MouseEvent) {
    if (points.length === 0) return;
    const box = wrap.getBoundingClientRect();
    const px = ((ev.clientX - box.left) / box.width) * W;
    let best = 0;
    for (let i = 1; i < points.length; i++) {
      if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i;
    }
    hovered = best;
    tipX = (x(best) / W) * box.width;
  }
</script>

<div
  class="wrap"
  bind:this={wrap}
  onmousemove={onMove}
  onmouseleave={() => (hovered = null)}
  role="img"
  aria-label="Daily filler percentage trend"
>
  <svg viewBox="0 0 {W} {H}" preserveAspectRatio="none">
    <!-- recessive grid + y labels -->
    {#each yTicks as t}
      <line x1={PAD_L} y1={y(t)} x2={W - PAD_R} y2={y(t)} class="grid" />
      <text x={PAD_L - 6} y={y(t) + 3} class="ylab">{t}%</text>
    {/each}

    <!-- goal: dashed line, labeled directly -->
    {#if goal > 0 && goal <= yMax}
      <line x1={PAD_L} y1={y(goal)} x2={W - PAD_R} y2={y(goal)} class="goal" />
      <text x={W - PAD_R} y={y(goal) - 4} class="goal-lab">goal {goal}%</text>
    {/if}

    <!-- the series -->
    {#if points.length > 1}
      <path d={path} class="line" />
    {/if}
    {#each points as p, i}
      <circle
        cx={x(i)}
        cy={y(p.pct)}
        r={hovered === i ? 5 : points.length > 40 ? 2 : 3.5}
        class="dot"
        class:over={goal > 0 && p.pct > goal}
      />
    {/each}

    <!-- x labels: first and last day only (selective, not one per point) -->
    {#if points.length > 0}
      <text x={x(0)} y={H - 6} class="xlab" text-anchor="start"
        >{shortDate(points[0].date)}</text
      >
      {#if points.length > 1}
        <text x={x(points.length - 1)} y={H - 6} class="xlab" text-anchor="end"
          >{shortDate(points[points.length - 1].date)}</text
        >
      {/if}
    {/if}

    <!-- hover crosshair -->
    {#if hovered !== null}
      <line
        x1={x(hovered)}
        y1={PAD_T}
        x2={x(hovered)}
        y2={H - PAD_B}
        class="crosshair"
      />
    {/if}
  </svg>

  {#if hovered !== null}
    {@const p = points[hovered]}
    <div class="tip" style="left: {tipX}px">
      <strong>{shortDate(p.date)}</strong> — {p.pct.toFixed(1)}% filler
      <span class="tip-sub">({p.filler.toLocaleString()} of {p.words.toLocaleString()} words)</span>
    </div>
  {/if}
</div>

<style>
  .wrap {
    position: relative;
    width: 100%;
  }
  svg {
    width: 100%;
    height: auto;
    display: block;
  }
  .grid {
    stroke: var(--surface3);
    stroke-width: 1;
  }
  .ylab {
    fill: var(--text-faint);
    font-size: 9px;
    text-anchor: end;
  }
  .xlab {
    fill: var(--text-faint);
    font-size: 9px;
  }
  .goal {
    stroke: var(--green);
    stroke-width: 1.5;
    stroke-dasharray: 5 4;
    opacity: 0.8;
  }
  .goal-lab {
    fill: var(--green);
    font-size: 9px;
    text-anchor: end;
  }
  .line {
    fill: none;
    stroke: var(--gold);
    stroke-width: 2;
    stroke-linejoin: round;
    stroke-linecap: round;
  }
  .dot {
    fill: var(--gold);
    stroke: var(--surface2);
    stroke-width: 2;
    transition: r 0.1s;
  }
  .dot.over {
    fill: var(--red);
  }
  .crosshair {
    stroke: var(--text-faint);
    stroke-width: 1;
    stroke-dasharray: 2 3;
  }
  .tip {
    position: absolute;
    top: -6px;
    transform: translateX(-50%);
    background: var(--surface3);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 11px;
    color: var(--text);
    white-space: nowrap;
    pointer-events: none;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.4);
  }
  .tip-sub {
    color: var(--text-muted);
  }
</style>
