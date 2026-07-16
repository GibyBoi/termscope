<script lang="ts">
  import { onMount } from "svelte";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import * as api from "../api";
  import type { AudioStatus } from "../types";

  // Dictation: microphone speech → text, with filler words cut as it arrives.
  // Everything here lives in RAM only — the dictated text is never written to
  // disk, matching the app's no-transcripts privacy design. (While Listening is
  // on, the orderless History tallies still count the words, as always.)

  let { audio }: { audio: AudioStatus } = $props();

  let active = $state(false); // are we currently appending dictation?
  let text = $state("");
  let fillersCut = $state(0);
  let fillerWords = $state<Set<string>>(new Set());
  let micEnabled = $state(true); // mirrors config.listen_microphone
  let startedListening = false; // we turned Listening on → turn it off after
  let copied = $state(false);
  let error = $state("");

  /** Same normalization as the Rust tokenizer: lowercase alphanumeric core. */
  function norm(word: string): string {
    return word.toLowerCase().replace(/[^a-z0-9]/g, "");
  }

  /** Cut filler words from an utterance; count what was dropped. */
  function clean(utterance: string): string {
    const kept: string[] = [];
    for (const w of utterance.split(/\s+/)) {
      if (!w) continue;
      if (fillerWords.has(norm(w))) {
        fillersCut += 1;
        continue;
      }
      kept.push(w);
    }
    return kept.join(" ");
  }

  function append(utterance: string) {
    const cleaned = clean(utterance);
    if (!cleaned) return;
    text = text ? `${text} ${cleaned}` : cleaned;
  }

  async function refreshMicEnabled() {
    try {
      micEnabled = (await api.getConfig()).listen_microphone;
    } catch {}
  }

  async function start() {
    error = "";
    await refreshMicEnabled();
    if (!micEnabled) return; // the inline warning shows the fix
    if (!audio.listening) {
      try {
        await api.toggleListening();
        startedListening = true;
      } catch (e) {
        error = String(e);
        return;
      }
    }
    active = true;
  }

  async function stop() {
    active = false;
    // If dictation turned Listening on, turn it back off — leave the app the
    // way the user had it.
    if (startedListening) {
      startedListening = false;
      try {
        if ((await api.isListening()) === true) await api.toggleListening();
      } catch {}
    }
  }

  async function enableMic() {
    try {
      await api.setConfigKey("listen_microphone", true);
      micEnabled = true;
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
  }

  let words = $derived(text.trim() ? text.trim().split(/\s+/).length : 0);

  onMount(() => {
    const unlisteners: UnlistenFn[] = [];
    (async () => {
      try {
        fillerWords = new Set(await api.getFillerWords());
      } catch {}
      await refreshMicEnabled();
      unlisteners.push(
        await listen<{ text: string; source?: string }>("ts://heard", (e) => {
          // Microphone only: dictation is what YOU say, never system audio.
          if (active && e.payload.source === "microphone") {
            append(e.payload.text);
          }
        }),
      );
    })();
    return () => {
      unlisteners.forEach((u) => u());
      if (startedListening) {
        // Leaving the view mid-dictation: release the mic we turned on.
        api.isListening().then((on) => {
          if (on) api.toggleListening().catch(() => {});
        });
      }
    };
  });
</script>

<div class="scroll">
  <header>
    <div>
      <h1>Dictation</h1>
      <p class="subtitle">
        Speak into your microphone — your words appear here with the filler cut
        out.
      </p>
    </div>
    <button
      class="rec-btn"
      class:active
      onclick={() => (active ? stop() : start())}
    >
      {active ? "■ Stop" : "● Start dictating"}
    </button>
  </header>

  {#if !micEnabled}
    <div class="warn">
      The microphone is disabled in Settings, so there's nothing to dictate
      from.
      <button class="warn-fix" onclick={enableMic}>Enable microphone</button>
    </div>
  {/if}
  {#if error}
    <div class="warn">{error}</div>
  {/if}
  {#if active && !audio.ready}
    <div class="note">
      {audio.reason || "Starting the transcriber…"} — dictation begins once
      audio is captured.
    </div>
  {/if}

  <textarea
    class="pad"
    bind:value={text}
    placeholder={active
      ? "Listening… start talking."
      : "Press “Start dictating”, then speak. Your cleaned-up words land here — edit them freely."}
  ></textarea>

  <div class="toolbar">
    <span class="stats">
      {words.toLocaleString()} word{words === 1 ? "" : "s"}
      {#if fillersCut > 0}
        &nbsp;·&nbsp; <span class="cut">{fillersCut} filler{fillersCut === 1 ? "" : "s"} cut ✂</span>
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
    🔒 Dictated text lives only in this window and is never saved to disk.
    Closing the app (or Clear) discards it — copy what you want to keep.
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
    margin: 0 0 14px;
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
  .rec-btn:hover {
    background: var(--accent);
    color: var(--bg);
  }
  .rec-btn.active {
    background: var(--red);
    color: var(--bg);
  }

  .warn {
    background: color-mix(in srgb, var(--red) 14%, transparent);
    border: 1px solid color-mix(in srgb, var(--red) 45%, transparent);
    color: var(--red);
    border-radius: var(--radius);
    padding: 10px 14px;
    font-size: 12px;
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 12px;
    justify-content: space-between;
  }
  .warn-fix {
    flex-shrink: 0;
    height: 28px;
    padding: 0 12px;
    border-radius: 8px;
    background: var(--red);
    color: var(--bg);
    font-size: 12px;
    font-weight: 600;
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
