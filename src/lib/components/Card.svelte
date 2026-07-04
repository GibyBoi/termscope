<script lang="ts">
  import { onMount } from "svelte";
  import { categoryColor, removeTerm } from "../api";
  import type { Entry } from "../types";

  let {
    entry,
    timeout,
    onLearned,
    onLearnMore,
    onDismiss,
  }: {
    entry: Entry;
    timeout: number;
    onLearned: () => void;
    onLearnMore: () => void;
    onDismiss: () => void;
  } = $props();

  const total = Math.max(1, timeout) * 1000;
  let remaining = $state(total);
  let paused = $state(false);

  // Two-step "not jargon" delete: first click arms, second permanently removes
  // the term from TermScope for this user.
  let armedDelete = $state(false);
  let armTimer: ReturnType<typeof setTimeout> | undefined;

  async function requestDelete() {
    if (!armedDelete) {
      armedDelete = true;
      clearTimeout(armTimer);
      armTimer = setTimeout(() => (armedDelete = false), 4000);
      return;
    }
    clearTimeout(armTimer);
    await removeTerm(entry.id);
    onDismiss();
  }

  onMount(() => {
    const id = setInterval(() => {
      if (paused) return;
      remaining -= 100;
      if (remaining <= 0) {
        clearInterval(id);
        onDismiss();
      }
    }, 100);
    return () => clearInterval(id);
  });

  let progress = $derived(Math.max(0, remaining / total));
  let accent = $derived(categoryColor(entry.category));
</script>

<div
  class="card"
  style="--c: {accent}"
  role="dialog"
  tabindex="-1"
  aria-label={entry.term}
  onmouseenter={() => (paused = true)}
  onmouseleave={() => (paused = false)}
>
  <div class="stripe"></div>
  <div class="body">
    <div class="head">
      <span class="chip">{entry.category.toUpperCase()}</span>
      <span class="brand">TermScope</span>
    </div>
    <div class="term">{entry.term}</div>
    <div class="def">{entry.definition}</div>
    <div class="btns">
      <button class="learn-more" onclick={onLearnMore}>Learn more</button>
      <button class="learned" onclick={onLearned}>✓ Learned</button>
      <button
        class="not-jargon"
        class:armed={armedDelete}
        title={armedDelete
          ? "Click again to permanently delete this term"
          : "Just a normal word? Delete it from TermScope"}
        onclick={requestDelete}
      >
        {armedDelete ? "Sure?" : "🗑"}
      </button>
      <button class="dismiss" onclick={onDismiss} aria-label="Dismiss">✕</button>
    </div>
    <div class="cbar"><div class="cfill" style="width: {progress * 100}%"></div></div>
  </div>
</div>

<style>
  .card {
    width: 360px;
    display: flex;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.45);
    overflow: hidden;
  }
  .stripe {
    width: 4px;
    background: var(--c);
    margin: 12px 0 12px 7px;
    border-radius: 2px;
    flex-shrink: 0;
  }
  .body {
    flex: 1;
    padding: 12px 14px;
    min-width: 0;
  }
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .chip {
    font-size: 10px;
    font-weight: 600;
    color: var(--bg);
    background: var(--c);
    border-radius: 8px;
    padding: 2px 7px;
  }
  .brand {
    font-size: 10px;
    color: var(--text-faint);
  }
  .term {
    font-size: 20px;
    font-weight: 600;
    color: var(--c);
    margin: 8px 0 2px;
    word-wrap: break-word;
  }
  .def {
    color: var(--text);
    line-height: 1.45;
    margin-bottom: 10px;
  }
  .btns {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .btns button {
    height: 30px;
    border-radius: 8px;
    font-size: 11px;
    padding: 0 10px;
  }
  .learn-more {
    border: 1px solid var(--accent);
    color: var(--accent);
  }
  .learn-more:hover {
    background: var(--surface3);
  }
  .learned {
    background: var(--green);
    color: var(--bg);
    font-weight: 600;
  }
  .learned:hover {
    background: var(--green-hover);
  }
  .not-jargon {
    margin-left: auto;
    color: var(--text-muted);
    min-width: 30px;
    padding: 0 6px;
    border: 1px solid transparent;
  }
  .not-jargon:hover {
    color: var(--red);
    border-color: var(--red);
  }
  .not-jargon.armed {
    background: var(--red);
    border-color: var(--red);
    color: var(--bg);
    font-weight: 600;
  }
  .dismiss {
    color: var(--text-muted);
    width: 30px;
    padding: 0;
  }
  .dismiss:hover {
    background: var(--surface3);
  }
  .cbar {
    height: 3px;
    background: var(--surface3);
    border-radius: 2px;
    margin-top: 10px;
    overflow: hidden;
  }
  .cfill {
    height: 100%;
    background: var(--c);
  }
</style>
