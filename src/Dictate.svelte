<script lang="ts">
  // The dictation indicator: a small always-on-top pill, centered just above
  // the bottom of the screen while transcription is live. A mic glyph plus a
  // row of bars whose lengths oscillate in a wave that travels end to end;
  // the wave's overall amplitude follows the real microphone level, so it
  // visibly reacts to the user speaking. Also surfaces dictation-start
  // failures in place of the wave for a few seconds.
  import { onMount, tick } from "svelte";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import {
    currentMonitor,
    getCurrentWindow,
    LogicalPosition,
    PhysicalSize,
  } from "@tauri-apps/api/window";

  const BARS = 9;
  const BOTTOM_MARGIN = 64; // logical px above the screen's bottom edge

  let active = $state(false);
  let error = $state("");
  let amp = $state(0.45); // 0.3–1, follows the mic level
  let pillEl = $state<HTMLDivElement>();
  let errTimer: ReturnType<typeof setTimeout> | undefined;
  let levelDecay: ReturnType<typeof setInterval> | undefined;
  let lastLevelAt = 0;

  async function reposition() {
    await tick();
    if (!pillEl) return;
    const win = getCurrentWindow();
    const rect = pillEl.getBoundingClientRect();
    const pad = 12;
    const w = Math.ceil(rect.width) + pad;
    const h = Math.ceil(rect.height) + pad;
    const dpr = window.devicePixelRatio || 1;
    await win.setSize(new PhysicalSize(Math.ceil(w * dpr) + 2, Math.ceil(h * dpr) + 2));
    const mon = await currentMonitor();
    const sf = mon?.scaleFactor ?? 1;
    const sw = (mon?.size.width ?? 1920) / sf;
    const sh = (mon?.size.height ?? 1080) / sf;
    await win.setPosition(
      new LogicalPosition(Math.round((sw - w) / 2), Math.round(sh - h - BOTTOM_MARGIN)),
    );
    await win.setAlwaysOnTop(true);
    await win.show();
  }

  async function refresh() {
    if (active || error) await reposition();
    else await getCurrentWindow().hide();
  }

  onMount(() => {
    const unlisteners: UnlistenFn[] = [];
    // Ease the wave down when level pings pause (silence or sidecar warm-up).
    levelDecay = setInterval(() => {
      if (Date.now() - lastLevelAt > 700) amp = Math.max(0.3, amp * 0.85);
    }, 250);
    (async () => {
      unlisteners.push(
        await listen<{ active: boolean; error?: string }>("ts://dictate", (e) => {
          active = e.payload.active;
          clearTimeout(errTimer);
          error = e.payload.error ?? "";
          if (error) {
            errTimer = setTimeout(() => {
              error = "";
              refresh();
            }, 6000);
          }
          refresh();
        }),
      );
      unlisteners.push(
        await listen<{ value: number; source: string }>("ts://level", (e) => {
          if (e.payload.source !== "microphone") return;
          lastLevelAt = Date.now();
          // 0-100 level → 0.3-1 amplitude, biased up so quiet speech still moves.
          amp = 0.3 + Math.min(1, Math.sqrt(e.payload.value / 100)) * 0.7;
        }),
      );
    })();
    return () => {
      clearInterval(levelDecay);
      clearTimeout(errTimer);
      unlisteners.forEach((u) => u());
    };
  });
</script>

<div class="wrap">
  {#if error}
    <div class="pill error" bind:this={pillEl}>
      <svg class="mic" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3Zm-6.5 8a.9.9 0 0 1 1.8 0 4.7 4.7 0 0 0 9.4 0 .9.9 0 0 1 1.8 0 6.5 6.5 0 0 1-5.6 6.42V20h2.2a.9.9 0 0 1 0 1.8H8.9a.9.9 0 0 1 0-1.8h2.2v-2.58A6.5 6.5 0 0 1 5.5 11Z"
        />
      </svg>
      <span class="err-text">Dictation failed: {error}</span>
    </div>
  {:else if active}
    <div class="pill" bind:this={pillEl} style="--amp: {amp}">
      <svg class="mic" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3Zm-6.5 8a.9.9 0 0 1 1.8 0 4.7 4.7 0 0 0 9.4 0 .9.9 0 0 1 1.8 0 6.5 6.5 0 0 1-5.6 6.42V20h2.2a.9.9 0 0 1 0 1.8H8.9a.9.9 0 0 1 0-1.8h2.2v-2.58A6.5 6.5 0 0 1 5.5 11Z"
        />
      </svg>
      <div class="bars" aria-label="Recording">
        {#each Array(BARS) as _, i}
          <span class="bar" style="animation-delay: {(i * 0.11).toFixed(2)}s"></span>
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  :global(html),
  :global(body),
  :global(.dictate-body) {
    margin: 0;
    background: transparent !important;
    overflow: hidden;
  }
  .wrap {
    padding: 6px;
    display: inline-block;
  }
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 9px 16px;
    border-radius: 999px;
    background: #1a1b26;
    border: 1.5px solid #e33b3b;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
    font-family: system-ui, sans-serif;
  }
  .mic {
    width: 18px;
    height: 18px;
    fill: #e33b3b;
    flex-shrink: 0;
  }
  .bars {
    display: flex;
    align-items: center;
    gap: 3px;
    height: 22px;
  }
  .bar {
    width: 3px;
    height: 20px;
    border-radius: 2px;
    background: #e33b3b;
    transform-origin: center;
    transform: scaleY(0.18);
    animation: wave 1s ease-in-out infinite;
  }
  /* Each bar runs the same oscillation; the staggered delays make the crest
     travel from one end of the row to the other. --amp (mic level) sets how
     tall the crest gets, so the wave breathes with the user's voice. */
  @keyframes wave {
    0%,
    100% {
      transform: scaleY(0.18);
    }
    50% {
      transform: scaleY(var(--amp, 0.5));
    }
  }
  .pill.error {
    border-radius: 14px;
    max-width: 380px;
  }
  .err-text {
    color: #ff8a8a;
    font-size: 12px;
    line-height: 1.35;
  }
</style>
