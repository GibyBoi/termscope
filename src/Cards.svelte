<script lang="ts">
  import { onMount, tick } from "svelte";
  import { flip } from "svelte/animate";
  import { fly } from "svelte/transition";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import {
    currentMonitor,
    getCurrentWindow,
    LogicalPosition,
    PhysicalSize,
  } from "@tauri-apps/api/window";
  import Card from "./lib/components/Card.svelte";
  import {
    focusLibraryTerm,
    getConfig,
    markLearned,
    setConfigKey,
  } from "./lib/api";
  import type { CardPayload, Entry } from "./lib/types";

  interface Item {
    key: number;
    entry: Entry;
    timeout: number;
  }

  let items: Item[] = $state([]);
  let queue: Item[] = [];
  const activeIds = new Set<string>();
  let maxCards = 6;
  let position = "bottom-right";
  let customX = -1;
  let customY = -1;
  let timeout = 12;
  let seq = 0;
  let stackEl: HTMLDivElement;

  // Placement mode: the user drags a sample card to pick the custom popup spot.
  let placementMode = $state(false);
  let placeEl = $state<HTMLDivElement>();

  /// Size the window to fit `el`, in PHYSICAL pixels. Sizing with LogicalSize
  /// truncates on fractional display scaling (125%/150%), leaving the window a
  /// hair smaller than the content — the long-standing "text cut off at the
  /// card edge" bug. Measure in CSS px, convert with the webview's real
  /// devicePixelRatio, ceil, and add slack so nothing ever clips.
  async function fitWindowTo(el: HTMLElement): Promise<{ w: number; h: number }> {
    const win = getCurrentWindow();
    const rect = el.getBoundingClientRect();
    const pad = 16; // matches the 8px margin around the content
    const w = Math.ceil(rect.width) + pad;
    const h = Math.ceil(rect.height) + pad;
    const dpr = window.devicePixelRatio || 1;
    const slack = 2; // physical px, absorbs subpixel rounding
    await win.setSize(
      new PhysicalSize(Math.ceil(w * dpr) + slack, Math.ceil(h * dpr) + slack),
    );
    return { w, h }; // logical, for position math
  }

  async function relayout() {
    if (placementMode) return; // placement drives its own layout
    await tick();
    const win = getCurrentWindow();
    if (items.length === 0) {
      await win.hide();
      return;
    }
    const { w, h } = await fitWindowTo(stackEl);

    const mon = await currentMonitor();
    const sf = mon?.scaleFactor ?? 1;
    const sw = (mon?.size.width ?? 1920) / sf;
    const sh = (mon?.size.height ?? 1080) / sf;
    const margin = 10;
    const taskbar = 48;

    let x: number;
    let y: number;
    if (position === "custom" && customX >= 0 && customY >= 0) {
      // Anchor the stack's top-left at the saved custom spot, clamped on-screen.
      x = Math.min(Math.max(customX, margin), Math.max(margin, sw - w - margin));
      y = Math.min(Math.max(customY, margin), Math.max(margin, sh - h - margin));
    } else {
      const right = position.includes("right");
      const top = position.includes("top");
      x = right ? sw - w - margin : margin;
      y = top ? margin : sh - h - taskbar;
    }

    await win.setPosition(new LogicalPosition(Math.round(x), Math.round(y)));
    await win.setAlwaysOnTop(true);
    await win.show();
  }

  // ---- custom-location placement -------------------------------------------

  async function showPlacement() {
    await tick();
    if (!placeEl) return;
    const win = getCurrentWindow();
    await win.setFocusable(true); // so the sample card can be dragged & clicked
    const { w, h } = await fitWindowTo(placeEl);

    // Start from the existing custom spot, or centered on first use.
    let x = customX;
    let y = customY;
    if (x < 0 || y < 0) {
      const mon = await currentMonitor();
      const sf = mon?.scaleFactor ?? 1;
      const sw = (mon?.size.width ?? 1920) / sf;
      const sh = (mon?.size.height ?? 1080) / sf;
      x = Math.round((sw - w) / 2);
      y = Math.round((sh - h) / 2);
    }
    await win.setPosition(new LogicalPosition(Math.round(x), Math.round(y)));
    await win.setAlwaysOnTop(true);
    await win.show();
    await win.setFocus();
  }

  async function savePlacement() {
    const win = getCurrentWindow();
    const pos = await win.outerPosition(); // physical, virtual-screen coords
    const sf = await win.scaleFactor();
    customX = Math.round(pos.x / sf);
    customY = Math.round(pos.y / sf);
    position = "custom";
    await setConfigKey("card_custom_x", customX);
    await setConfigKey("card_custom_y", customY);
    await setConfigKey("card_position", "custom");
    await endPlacement();
  }

  async function endPlacement() {
    placementMode = false;
    const win = getCurrentWindow();
    await win.setFocusable(false); // restore the click-through-ish overlay behavior
    await relayout(); // no items → hides; otherwise re-anchors
  }

  function add(entry: Entry, t: number) {
    if (activeIds.has(entry.id)) return;
    activeIds.add(entry.id);
    const item: Item = { key: seq++, entry, timeout: t };
    if (items.length < maxCards) items = [...items, item];
    else queue.push(item);
    relayout();
  }

  function remove(key: number, id: string) {
    items = items.filter((i) => i.key !== key);
    activeIds.delete(id);
    if (queue.length && items.length < maxCards) {
      items = [...items, queue.shift()!];
    }
    relayout();
  }

  function removeById(id: string) {
    const it = items.find((i) => i.entry.id === id);
    if (it) {
      remove(it.key, id);
    } else {
      activeIds.delete(id);
      queue = queue.filter((q) => q.entry.id !== id);
    }
  }

  onMount(() => {
    const unlisteners: UnlistenFn[] = [];
    (async () => {
      try {
        const cfg = await getConfig();
        maxCards = cfg.card_max;
        position = cfg.card_position;
        customX = cfg.card_custom_x;
        customY = cfg.card_custom_y;
        timeout = cfg.notification_timeout;
      } catch {}

      unlisteners.push(
        await listen<CardPayload>("ts://card", (e) => {
          maxCards = e.payload.maxCards;
          position = e.payload.position;
          customX = e.payload.customX;
          customY = e.payload.customY;
          timeout = e.payload.timeout;
          if (placementMode) return; // don't stack cards over the placement box
          add(e.payload.entry, e.payload.timeout);
        }),
      );
      unlisteners.push(
        await listen("ts://place-mode", () => {
          placementMode = true;
          // Clear any live cards so only the sample box shows while placing.
          items = [];
          queue = [];
          activeIds.clear();
          showPlacement();
        }),
      );
      unlisteners.push(
        await listen<{ id: string }>("ts://card-remove", (e) =>
          removeById(e.payload.id),
        ),
      );
      unlisteners.push(
        await listen<{
          timeout: number;
          maxCards: number;
          position: string;
          customX: number;
          customY: number;
        }>("ts://config", (e) => {
          maxCards = e.payload.maxCards;
          position = e.payload.position;
          customX = e.payload.customX;
          customY = e.payload.customY;
          timeout = e.payload.timeout;
          relayout();
        }),
      );
    })();
    return () => unlisteners.forEach((u) => u());
  });
</script>

{#if placementMode}
  <div class="place" bind:this={placeEl}>
    <div class="place-grip" data-tauri-drag-region>
      <span class="place-dots">⠿</span>
      <span class="place-title">Drag me where you want popups to appear</span>
    </div>
    <div class="place-body">
      This is where your term cards will pop up. Position this box, then save.
    </div>
    <div class="place-actions">
      <button class="place-cancel" onclick={endPlacement}>Cancel</button>
      <button class="place-save" onclick={savePlacement}>Save location</button>
    </div>
  </div>
{/if}

<div class="stack" bind:this={stackEl} class:hidden={placementMode}>
  {#each items as item (item.key)}
    <div animate:flip={{ duration: 220 }} transition:fly={{ x: 60, duration: 200 }}>
      <Card
        entry={item.entry}
        timeout={item.timeout}
        onLearned={() => {
          markLearned(item.entry.id);
          remove(item.key, item.entry.id);
        }}
        onLearnMore={() => {
          focusLibraryTerm(item.entry.id);
          remove(item.key, item.entry.id);
        }}
        onDismiss={() => remove(item.key, item.entry.id)}
      />
    </div>
  {/each}
</div>

<style>
  .stack {
    display: inline-flex;
    flex-direction: column;
    gap: 12px;
    padding: 8px;
  }
  .stack.hidden {
    display: none;
  }

  /* placement sample card (custom-location picker) */
  .place {
    width: 300px;
    margin: 8px;
    border-radius: var(--radius, 12px);
    background: var(--surface, #1b1b22);
    border: 1px solid var(--accent, #7c5cff);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
    overflow: hidden;
    color: var(--text, #eee);
    font-family: system-ui, sans-serif;
  }
  .place-grip {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
    background: var(--accent, #7c5cff);
    color: #fff;
    font-size: 12px;
    font-weight: 600;
    cursor: grab;
    user-select: none;
  }
  .place-grip:active {
    cursor: grabbing;
  }
  .place-dots {
    font-size: 14px;
    opacity: 0.9;
    flex-shrink: 0;
    pointer-events: none; /* clicks land on the drag-region grip */
  }
  .place-title {
    flex: 1;
    min-width: 0; /* allow wrapping instead of overflowing the box */
    pointer-events: none; /* clicks land on the drag-region grip */
  }
  .place-body {
    padding: 14px 12px;
    font-size: 12px;
    line-height: 1.4;
    color: var(--text-muted, #aaa);
  }
  .place-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    padding: 0 12px 12px;
  }
  .place-actions button {
    padding: 6px 12px;
    border-radius: 8px;
    font-size: 12px;
    border: 1px solid var(--border, #333);
    cursor: pointer;
  }
  .place-cancel {
    background: var(--surface2, #26262f);
    color: var(--text-muted, #aaa);
  }
  .place-save {
    background: var(--accent, #7c5cff);
    border-color: var(--accent, #7c5cff);
    color: #fff;
    font-weight: 600;
  }
</style>
