<script lang="ts">
  import { onMount } from "svelte";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import * as api from "../api";
  import type { AudioStatus } from "../types";

  // Dictation, the SpeakEasy way: press Start, speak, press Stop — the WHOLE
  // recording is transcribed in one pass (coherent punctuation, no seams),
  // filler words are cut, corrections applied, and the text lands here.
  // Everything stays in RAM; dictated text is never written to disk. The
  // backend owns the session (same flow as the dictate hotkey) and restores
  // Listening to however you had it afterwards.

  let { audio }: { audio: AudioStatus } = $props();

  type Phase = "idle" | "recording" | "computing";
  let phase = $state<Phase>("idle");
  let text = $state("");
  let fillersCut = $state(0);
  let polished = $state(false);
  let hotkey = $state(""); // config.hotkey_dictate, shown as a reference only
  let copied = $state(false);
  let error = $state("");

  async function start() {
    error = "";
    try {
      await api.dictationBegin();
      // phase flips via ts://dictate so hotkey + view sessions stay in sync
    } catch (e) {
      error = String(e);
    }
  }

  async function stop() {
    try {
      await api.dictationEnd();
    } catch (e) {
      error = String(e);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // WebView clipboard denied — fall back to a selection-based copy.
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    copied = true;
    setTimeout(() => (copied = false), 1600);
  }

  function clear() {
    text = "";
    fillersCut = 0;
    polished = false;
  }

  let words = $derived(text.trim() ? text.trim().split(/\s+/).length : 0);

  onMount(() => {
    const unlisteners: UnlistenFn[] = [];
    (async () => {
      try {
        hotkey = (await api.getConfig()).hotkey_dictate;
      } catch {}
      unlisteners.push(
        await listen<{ active: boolean; computing?: boolean; error?: string }>(
          "ts://dictate",
          (e) => {
            if (e.payload.error) {
              error = e.payload.error;
              phase = "idle";
            } else if (e.payload.active) {
              phase = "recording";
            } else if (e.payload.computing) {
              phase = "computing";
            } else {
              phase = "idle";
            }
          },
        ),
      );
      unlisteners.push(
        await listen<{ text: string; fillersCut: number; polished: boolean }>(
          "ts://dictation-result",
          (e) => {
            phase = "idle";
            if (e.payload.text) {
              text = text ? `${text}\n${e.payload.text}` : e.payload.text;
            }
            fillersCut += e.payload.fillersCut;
            polished = e.payload.polished;
          },
        ),
      );
    })();
    return () => {
      unlisteners.forEach((u) => u());
      // Leaving mid-recording ends the session (backend restores Listening).
      if (phase !== "idle") api.dictationEnd().catch(() => {});
    };
  });
</script>

<div class="scroll">
  <header>
    <div>
      <h1>Dictation</h1>
      <p class="subtitle">
        Speak, stop, and the whole recording is transcribed in one pass — with
        the filler cut out.
      </p>
      <p class="hotkey-ref">
        {#if hotkey}
          Anywhere on your PC: press <span class="kbd">{hotkey.toUpperCase()}</span>
          to dictate straight to your cursor. Change the binding in Settings.
        {:else}
          No dictation hotkey is set — bind one under Settings → Global hotkeys
          to dictate from anywhere.
        {/if}
      </p>
    </div>
    <button
      class="rec-btn"
      class:active={phase === "recording"}
      disabled={phase === "computing"}
      onclick={() => (phase === "recording" ? stop() : start())}
    >
      {#if phase === "recording"}■ Stop{:else if phase === "computing"}Computing…{:else}● Start dictating{/if}
    </button>
  </header>

  {#if error}
    <div class="warn">{error}</div>
  {/if}
  {#if phase === "recording" && !audio.ready}
    <div class="note">
      {audio.reason || "Starting the transcriber…"} — recording begins once
      audio is captured.
    </div>
  {/if}
  {#if phase === "computing"}
    <div class="note">Transcribing your recording…</div>
  {/if}

  <textarea
    class="pad"
    bind:value={text}
    placeholder={phase === "recording"
      ? "Recording… speak freely, then press Stop."
      : "Press “Start dictating”, speak, then Stop. The transcript lands here — edit it freely."}
  ></textarea>

  <div class="toolbar">
    <span class="stats">
      {words.toLocaleString()} word{words === 1 ? "" : "s"}
      {#if fillersCut > 0}
        &nbsp;·&nbsp; <span class="cut">{fillersCut} filler{fillersCut === 1 ? "" : "s"} cut ✂</span>
      {/if}
      {#if polished}
        &nbsp;·&nbsp; <span class="pol">polished ✦</span>
      {/if}
    </span>
    <div class="actions">
      <button class="act" onclick={clear} disabled={!text}>Clear</button>
      <button class="act primary" onclick={copy} disabled={!text}>
        {copied ? "✓ Copied" : "Copy"}
      </button>
    </div>
  </div>

  <p class="privacy">
    🔒 Recordings and dictated text live only in memory and are never saved to
    disk. Closing the app (or Clear) discards the text — copy what you want to
    keep.
  </p>
</div>

<style>
  .scroll {
    height: 100vh;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    padding: 20px 24px 24px;
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
    margin: 0 0 4px;
  }
  .hotkey-ref {
    color: var(--text-faint);
    font-size: 11px;
    margin: 0 0 14px;
  }
  .kbd {
    font-weight: 600;
    font-size: 10px;
    color: var(--accent);
    background: var(--surface2);
    border-radius: 5px;
    padding: 2px 6px;
  }
  .rec-btn {
    flex-shrink: 0;
    height: 36px;
    padding: 0 18px;
    border-radius: 10px;
    background: var(--accent-dim);
    color: var(--text);
    font-size: 13px;
    font-weight: 600;
    transition: background 0.12s;
  }
  .rec-btn:hover:not(:disabled) {
    background: var(--accent);
    color: var(--bg);
  }
  .rec-btn.active {
    background: var(--red);
    color: var(--bg);
  }
  .rec-btn:disabled {
    opacity: 0.6;
    cursor: default;
  }

  .warn {
    background: color-mix(in srgb, var(--red) 14%, transparent);
    border: 1px solid color-mix(in srgb, var(--red) 45%, transparent);
    color: var(--red);
    border-radius: var(--radius);
    padding: 10px 14px;
    font-size: 12px;
    margin-bottom: 12px;
  }
  .note {
    background: color-mix(in srgb, var(--gold) 14%, transparent);
    border: 1px solid color-mix(in srgb, var(--gold) 45%, transparent);
    color: var(--gold);
    border-radius: var(--radius);
    padding: 10px 14px;
    font-size: 12px;
    margin-bottom: 12px;
  }

  .pad {
    flex: 1;
    min-height: 200px;
    resize: none;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text);
    font-family: var(--font);
    font-size: 14px;
    line-height: 1.6;
    padding: 14px 16px;
    user-select: text;
    cursor: text;
  }
  .pad:focus {
    outline: none;
    border-color: var(--accent);
  }

  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 12px;
  }
  .stats {
    color: var(--text-muted);
    font-size: 12px;
  }
  .cut {
    color: var(--gold);
  }
  .pol {
    color: var(--purple);
  }
  .actions {
    display: flex;
    gap: 8px;
  }
  .act {
    height: 32px;
    padding: 0 16px;
    border-radius: 8px;
    background: var(--surface2);
    border: 1px solid var(--border);
    color: var(--text);
    font-size: 12px;
    transition: background 0.12s, border-color 0.12s;
  }
  .act:hover:not(:disabled) {
    border-color: var(--accent);
  }
  .act:disabled {
    opacity: 0.45;
    cursor: default;
  }
  .act.primary {
    background: var(--accent-dim);
    font-weight: 600;
  }
  .act.primary:hover:not(:disabled) {
    background: var(--accent);
    color: var(--bg);
  }

  .privacy {
    color: var(--text-faint);
    font-size: 11px;
    line-height: 1.5;
    margin: 12px 0 0;
  }
</style>
