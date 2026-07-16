<script lang="ts" module>
  /** One donut slice: identity + magnitude + the CSS color that follows it. */
  export interface Slice {
    label: string;
    value: number;
    color: string; // CSS color, e.g. "var(--cyan)"
  }
</script>

<script lang="ts">
  // Reusable SVG donut with a center figure and a direct-labeled legend.
  // Stroke-arc segments with a ~2px surface gap between slices; hovering a
  // slice (or its legend row) dims the others and shows an exact-count tooltip.
  let {
    slices,
    centerValue = "",
    centerLabel = "",
  }: { slices: Slice[]; centerValue?: string; centerLabel?: string } = $props();

  const SIZE = 148;
  const C = SIZE / 2;
  const R = 56;
  const THICK = 15;
  const PAD = 2.5 / R; // ≈2.5px gap between segments, in radians

  let total = $derived(slices.reduce((s, x) => s + x.value, 0));
  let visible = $derived(slices.filter((s) => s.value > 0));

  interface Arc extends Slice {
    start: number;
    end: number;
    pct: number;
  }
  let arcs = $derived.by<Arc[]>(() => {
    const tot = total || 1;
    let a = -Math.PI / 2; // start at 12 o'clock
    return visible.map((s) => {
      const span = (s.value / tot) * Math.PI * 2;
      const arc = { ...s, start: a, end: a + span, pct: s.value / tot };
      a += span;
      return arc;
    });
  });

  function pt(angle: number): string {
    return `${C + R * Math.cos(angle)} ${C + R * Math.sin(angle)}`;
  }
  /** Stroke-arc path for one segment, ends inset to leave the gap. */
  function arcPath(a: Arc): string {
    const s = a.start + PAD / 2;
    const e = Math.max(a.end - PAD / 2, s + 0.02); // keep slivers visible
    const large = e - s > Math.PI ? 1 : 0;
    return `M ${pt(s)} A ${R} ${R} 0 ${large} 1 ${pt(e)}`;
  }

  function pctLabel(pct: number): string {
    const p = Math.round(pct * 100);
    return p === 0 ? "<1%" : `${p}%`;
  }

  // ---- hover ----------------------------------------------------------------
  let hovered = $state<number | null>(null);
  let tip = $state<{ x: number; y: number; text: string } | null>(null);
  let wrap: HTMLDivElement;

  function showTip(i: number, ev: MouseEvent) {
    hovered = i;
    const a = arcs[i];
    const box = wrap.getBoundingClientRect();
    tip = {
      x: ev.clientX - box.left,
      y: ev.clientY - box.top,
      text: `${a.label}: ${a.value.toLocaleString()}× (${pctLabel(a.pct)})`,
    };
  }
  function hideTip() {
    hovered = null;
    tip = null;
  }
</script>

<div class="donut" bind:this={wrap}>
  <svg
    viewBox="0 0 {SIZE} {SIZE}"
    width={SIZE}
    height={SIZE}
    role="img"
    aria-label="{centerLabel}: {visible
      .map((s) => `${s.label} ${s.value}`)
      .join(', ')}"
  >
    {#if arcs.length === 1}
      <!-- hover-only targets; identity lives in the svg aria-label + legend -->
      <circle
        cx={C}
        cy={C}
        r={R}
        fill="none"
        stroke={arcs[0].color}
        stroke-width={THICK}
        role="presentation"
        onmousemove={(e) => showTip(0, e)}
        onmouseleave={hideTip}
      />
    {:else}
      {#each arcs as a, i}
        <path
          d={arcPath(a)}
          fill="none"
          stroke={a.color}
          stroke-width={THICK}
          class="seg"
          class:dim={hovered !== null && hovered !== i}
          role="presentation"
          onmousemove={(e) => showTip(i, e)}
          onmouseleave={hideTip}
        />
      {/each}
    {/if}
    <text x={C} y={C - 2} class="center-num">{centerValue}</text>
    <text x={C} y={C + 14} class="center-label">{centerLabel}</text>
  </svg>

  <div class="legend">
    {#each arcs as a, i}
      <div
        class="lrow"
        class:dim={hovered !== null && hovered !== i}
        onmouseenter={() => (hovered = i)}
        onmouseleave={hideTip}
        role="listitem"
      >
        <span class="swatch" style="background: {a.color}"></span>
        <span class="llabel">{a.label}</span>
        <span class="lcount">{a.value.toLocaleString()}×</span>
        <span class="lpct">{pctLabel(a.pct)}</span>
      </div>
    {/each}
  </div>

  {#if tip}
    <div class="tip" style="left: {tip.x + 12}px; top: {tip.y - 8}px">
      {tip.text}
    </div>
  {/if}
</div>

<style>
  .donut {
    position: relative;
    display: flex;
    align-items: center;
    gap: 18px;
    flex-wrap: wrap;
  }
  .seg,
  circle {
    transition: opacity 0.12s;
  }
  .seg.dim {
    opacity: 0.35;
  }
  .center-num {
    fill: var(--text);
    font-size: 24px;
    font-weight: 600;
    text-anchor: middle;
  }
  .center-label {
    fill: var(--text-muted);
    font-size: 9px;
    text-anchor: middle;
  }

  .legend {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 170px;
    flex: 1;
  }
  .lrow {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    padding: 3px 6px;
    border-radius: 6px;
    transition: opacity 0.12s;
  }
  .lrow:hover {
    background: var(--surface3);
  }
  .lrow.dim {
    opacity: 0.45;
  }
  .swatch {
    width: 10px;
    height: 10px;
    border-radius: 3px;
    flex-shrink: 0;
  }
  .llabel {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .lcount {
    color: var(--text-muted);
    font-weight: 600;
  }
  .lpct {
    color: var(--text-faint);
    min-width: 34px;
    text-align: right;
  }

  .tip {
    position: absolute;
    z-index: 5;
    pointer-events: none;
    background: var(--surface3);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 11px;
    color: var(--text);
    white-space: nowrap;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.4);
  }
</style>
