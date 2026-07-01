<script lang="ts">
  import { onMount } from "svelte";
  import { ask, save as saveDialog } from "@tauri-apps/plugin-dialog";
  import {
    beginCardPlacement,
    exportProgress,
    getConfig,
    setConfigKey,
    setStartup,
    startupEnabled,
  } from "../api";
  import type { Config } from "../types";

  let { config, onReset }: { config: Config; onReset: () => void } = $props();

  let cfg = $state({ ...config });
  let startup = $state(false);

  onMount(async () => {
    try {
      cfg = await getConfig(); // show the latest saved values, not a stale prop
    } catch {}
    try {
      startup = await startupEnabled();
    } catch {}
  });

  async function save(key: keyof Config, value: unknown) {
    // Reassign (not mutate-by-dynamic-key) so Svelte reactively re-renders the control.
    cfg = { ...cfg, [key]: value };
    await setConfigKey(key as string, value);
  }

  async function placeCustomLocation() {
    // Ensure custom is the active mode, then hand off to the cards window's
    // drag-to-place overlay.
    if (cfg.card_position !== "custom") await save("card_position", "custom");
    await beginCardPlacement();
  }

  async function toggleStartup(v: boolean) {
    startup = v;
    try {
      await setStartup(v);
    } catch {}
  }

  async function doExport() {
    const path = await saveDialog({
      defaultPath: "termscope-progress.json",
      filters: [{ name: "JSON", extensions: ["json"] }],
    });
    if (path) await exportProgress(path);
  }

  async function doReset() {
    const ok = await ask(
      "Forget every term you've marked learned? This can't be undone.",
      { title: "Reset learned terms", kind: "warning" },
    );
    if (ok) onReset();
  }

  const POSITIONS = [
    { label: "Bottom-right", value: "bottom-right" },
    { label: "Bottom-left", value: "bottom-left" },
    { label: "Top-right", value: "top-right" },
    { label: "Top-left", value: "top-left" },
    { label: "Custom", value: "custom" },
  ];
  const STYLES = [
    { label: "Floating card", value: "card" },
    { label: "Windows toast", value: "win11toast" },
  ];

  const hotkeys = $derived([
    { label: "Explain selection", value: cfg.hotkey_explain_selection },
    { label: "Mark last term learned", value: cfg.hotkey_mark_last_learned },
    { label: "Toggle listening", value: cfg.hotkey_toggle_listening },
  ]);
</script>

<div class="scroll">
  <h1>Settings</h1>

  <section class="group">
    <h2>Listening</h2>
    <div class="note">
      Offline speech-to-text powered by OpenAI Whisper (base.en), running
      locally on your machine. Source changes apply the next time you switch
      Listening on from the sidebar.
    </div>
    <label class="switch">
      <input
        type="checkbox"
        checked={cfg.listen_system_audio}
        onchange={(e) => save("listen_system_audio", e.currentTarget.checked)}
      />
      <span class="track"></span>
      <span>Listen to system audio (the other person on a call)</span>
    </label>
    <label class="switch">
      <input
        type="checkbox"
        checked={cfg.listen_microphone}
        onchange={(e) => save("listen_microphone", e.currentTarget.checked)}
      />
      <span class="track"></span>
      <span>Listen to my microphone</span>
    </label>
    <label class="switch">
      <input
        type="checkbox"
        checked={cfg.listen_on_startup}
        onchange={(e) => save("listen_on_startup", e.currentTarget.checked)}
      />
      <span class="track"></span>
      <span>Start listening automatically on launch</span>
    </label>
  </section>

  <section class="group">
    <h2>Notifications</h2>
    <div class="field-label">Style</div>
    <div class="segmented">
      {#each STYLES as s}
        <button class:active={cfg.notifier === s.value} onclick={() => save("notifier", s.value)}>{s.label}</button>
      {/each}
    </div>

    <div class="slider">
      <div class="field-label">Don't repeat a term for: {Math.round(cfg.cooldown_seconds / 3600)}h</div>
      <input
        type="range"
        min="1"
        max="24"
        value={Math.round(cfg.cooldown_seconds / 3600)}
        oninput={(e) => save("cooldown_seconds", Number(e.currentTarget.value) * 3600)}
      />
    </div>
    <div class="slider">
      <div class="field-label">Max notifications per minute: {cfg.max_per_minute}</div>
      <input type="range" min="1" max="20" value={cfg.max_per_minute}
        oninput={(e) => save("max_per_minute", Number(e.currentTarget.value))} />
    </div>

    <div class="subhead">Floating-card window</div>
    <div class="slider">
      <div class="field-label">Each card stays on screen for: {cfg.notification_timeout}s</div>
      <input type="range" min="3" max="30" value={cfg.notification_timeout}
        oninput={(e) => save("notification_timeout", Number(e.currentTarget.value))} />
    </div>
    <div class="slider">
      <div class="field-label">Max cards on screen at once: {cfg.card_max}</div>
      <input type="range" min="1" max="6" value={cfg.card_max}
        oninput={(e) => save("card_max", Number(e.currentTarget.value))} />
    </div>
    <div class="field-label">Card position</div>
    <div class="segmented">
      {#each POSITIONS as p}
        <button class:active={cfg.card_position === p.value} onclick={() => save("card_position", p.value)}>{p.label}</button>
      {/each}
    </div>
    {#if cfg.card_position === "custom"}
      <div class="custom-place">
        <button class="place-btn" onclick={placeCustomLocation}>
          Drag to set location…
        </button>
        <span class="custom-hint">
          {cfg.card_custom_x >= 0 && cfg.card_custom_y >= 0
            ? `Saved at ${cfg.card_custom_x}, ${cfg.card_custom_y}. Click to reposition.`
            : "Not set yet — click, drag the box, then Save location."}
        </span>
      </div>
    {/if}
  </section>

  <section class="group">
    <h2>Global hotkeys</h2>
    {#each hotkeys as h}
      <div class="hotkey-row">
        <span>{h.label}</span>
        <span class="kbd">{h.value.toUpperCase()}</span>
      </div>
    {/each}
  </section>

  <section class="group">
    <h2>General</h2>
    <label class="switch">
      <input type="checkbox" checked={cfg.close_to_tray}
        onchange={(e) => save("close_to_tray", e.currentTarget.checked)} />
      <span class="track"></span>
      <span>Closing the window keeps TermScope running in the tray</span>
    </label>
    <label class="switch">
      <input type="checkbox" checked={startup}
        onchange={(e) => toggleStartup(e.currentTarget.checked)} />
      <span class="track"></span>
      <span>Start TermScope automatically when I sign in to Windows</span>
    </label>
  </section>

  <section class="group">
    <h2>History</h2>
    <div class="note">
      When on, TermScope tallies every spoken word it hears and logs the jargon it
      catches, for the History tab. All of it stays on this machine. Turn it off to
      stop recording — clear the stored history any time from the History tab.
    </div>
    <label class="switch">
      <input
        type="checkbox"
        checked={cfg.track_history}
        onchange={(e) => save("track_history", e.currentTarget.checked)}
      />
      <span class="track"></span>
      <span>Record spoken-word &amp; jargon history</span>
    </label>
  </section>

  <section class="group">
    <h2>Progress data</h2>
    <div class="note">Your learned-terms history lives in %APPDATA%\TermScope.</div>
    <div class="actions">
      <button class="btn-muted" onclick={doExport}>Export progress…</button>
      <button class="btn-danger" onclick={doReset}>Reset learned terms</button>
    </div>
  </section>

  <p class="note small">
    Toggles save instantly. Card options apply live; notification-style changes apply on restart.
  </p>
</div>

<style>
  .scroll {
    height: 100vh;
    overflow-y: auto;
    padding: 20px 28px 40px;
  }
  h1 {
    font-size: 26px;
    font-weight: 600;
    margin: 0 0 16px;
  }
  .group {
    background: var(--surface);
    border-radius: var(--radius);
    padding: 16px 20px;
    margin-bottom: 14px;
  }
  h2 {
    font-size: 16px;
    font-weight: 600;
    margin: 0 0 10px;
  }
  .subhead {
    color: var(--text-muted);
    font-weight: 600;
    font-size: 11px;
    margin: 14px 0 4px;
  }
  .field-label {
    margin: 8px 0 4px;
  }
  .note {
    color: var(--text-muted);
    font-size: 11px;
    margin-bottom: 8px;
  }
  .note.warn {
    color: var(--orange);
  }
  .note.small {
    color: var(--text-faint);
  }
  .switch {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 0;
    cursor: pointer;
  }
  .switch.disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
  .switch input {
    display: none;
  }
  .track {
    width: 38px;
    height: 20px;
    border-radius: 10px;
    background: var(--surface3);
    position: relative;
    flex-shrink: 0;
    transition: background 0.15s;
  }
  .track::after {
    content: "";
    position: absolute;
    top: 2px;
    left: 2px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--text-muted);
    transition: transform 0.15s, background 0.15s;
  }
  .switch input:checked + .track {
    background: var(--accent);
  }
  .switch input:checked + .track::after {
    transform: translateX(18px);
    background: white;
  }
  .segmented {
    display: inline-flex;
    background: var(--surface2);
    border-radius: 8px;
    padding: 2px;
    margin-bottom: 6px;
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
  .custom-place {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 10px;
    flex-wrap: wrap;
  }
  .place-btn {
    padding: 7px 14px;
    border-radius: 8px;
    background: var(--accent);
    color: #fff;
    font-size: 12px;
    font-weight: 600;
    border: none;
    cursor: pointer;
  }
  .place-btn:hover {
    filter: brightness(1.08);
  }
  .custom-hint {
    color: var(--text-muted);
    font-size: 11px;
  }
  .slider {
    margin: 10px 0;
  }
  .slider input[type="range"] {
    width: 100%;
    accent-color: var(--accent);
  }
  .hotkey-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px 0;
  }
  .kbd {
    font-weight: 600;
    font-size: 11px;
    color: var(--accent);
    background: var(--surface2);
    border-radius: 6px;
    padding: 4px 8px;
  }
  .actions {
    display: flex;
    gap: 8px;
  }
  .actions button {
    height: 32px;
    padding: 0 14px;
    border-radius: 8px;
    font-size: 12px;
  }
  .btn-muted {
    background: var(--surface3);
    color: var(--text);
  }
  .btn-muted:hover {
    background: var(--border);
  }
  .btn-danger {
    border: 1px solid var(--red);
    color: var(--red);
  }
  .btn-danger:hover {
    background: var(--surface3);
  }
</style>
