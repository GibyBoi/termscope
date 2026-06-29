<script lang="ts">
  import { onMount, tick } from "svelte";
  import { flip } from "svelte/animate";
  import { fly } from "svelte/transition";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import {
    currentMonitor,
    getCurrentWindow,
    LogicalPosition,
    LogicalSize,
  } from "@tauri-apps/api/window";
  import Card from "./lib/components/Card.svelte";
  import { focusLibraryTerm, getConfig, markLearned } from "./lib/api";
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
  let timeout = 12;
  let seq = 0;
  let stackEl: HTMLDivElement;

  async function relayout() {
    await tick();
    const win = getCurrentWindow();
    if (items.length === 0) {
      await win.hide();
      return;
    }
    const rect = stackEl.getBoundingClientRect();
    const pad = 16;
    const w = Math.ceil(rect.width) + pad;
    const h = Math.ceil(rect.height) + pad;

    const mon = await currentMonitor();
    const sf = mon?.scaleFactor ?? 1;
    const sw = (mon?.size.width ?? 1920) / sf;
    const sh = (mon?.size.height ?? 1080) / sf;
    const margin = 10;
    const taskbar = 48;
    const right = position.includes("right");
    const top = position.includes("top");
    const x = right ? sw - w - margin : margin;
    const y = top ? margin : sh - h - taskbar;

    await win.setSize(new LogicalSize(w, h));
    await win.setPosition(new LogicalPosition(Math.round(x), Math.round(y)));
    await win.setAlwaysOnTop(true);
    await win.show();
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
        timeout = cfg.notification_timeout;
      } catch {}

      unlisteners.push(
        await listen<CardPayload>("ts://card", (e) => {
          maxCards = e.payload.maxCards;
          position = e.payload.position;
          timeout = e.payload.timeout;
          add(e.payload.entry, e.payload.timeout);
        }),
      );
      unlisteners.push(
        await listen<{ id: string }>("ts://card-remove", (e) =>
          removeById(e.payload.id),
        ),
      );
      unlisteners.push(
        await listen<{ timeout: number; maxCards: number; position: string }>(
          "ts://config",
          (e) => {
            maxCards = e.payload.maxCards;
            position = e.payload.position;
            timeout = e.payload.timeout;
            relayout();
          },
        ),
      );
    })();
    return () => unlisteners.forEach((u) => u());
  });
</script>

<div class="stack" bind:this={stackEl}>
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
</style>
