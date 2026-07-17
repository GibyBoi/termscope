<script lang="ts">
  import { onMount } from "svelte";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import * as api from "./lib/api";
  import type { AudioStatus, Config, Entry } from "./lib/types";
  import Dashboard from "./lib/views/Dashboard.svelte";
  import Library from "./lib/views/Library.svelte";
  import Settings from "./lib/views/Settings.svelte";
  import History from "./lib/views/History.svelte";
  import Dictation from "./lib/views/Dictation.svelte";
  import logoUrl from "./assets/termscope.png";

  // Injected from package.json by Vite (see vite.config.ts) — bump it there for
  // future versions. Shown inside the app as e.g. "2.0".
  declare const __APP_VERSION__: string;
  const version = __APP_VERSION__.split(".").slice(0, 2).join(".");

  let view: "dashboard" | "library" | "history" | "dictation" | "settings" =
    $state("dashboard");
  let entries: Entry[] = $state([]);
  let learned: Set<string> = $state(new Set());
  let config: Config | null = $state(null);
  let pendingTermId: string | null = $state(null);
  let audio: AudioStatus = $state({
    listening: false,
    ready: false,
    reason: "off",
    model: "",
  });
  let heard = $state(""); // most recent transcription, for live feedback
  let levelSys = $state(0);
  let levelMic = $state(0);
  let level = $derived(Math.max(levelSys, levelMic)); // 0-100 audio meter
  let lastLevelAt = 0;

  async function refreshAudio() {
    try {
      audio = await api.audioStatus();
    } catch {}
  }

  async function toggleListening() {
    try {
      await api.toggleListening();
    } catch (e) {
      audio = { ...audio, reason: String(e) };
    }
    await refreshAudio();
  }

  async function refreshKnowledge() {
    const k = await api.getKnowledge();
    learned = new Set(k.learned);
  }

  async function toggleLearned(id: string) {
    if (learned.has(id)) await api.unlearn(id);
    else await api.markLearned(id);
    await refreshKnowledge();
  }

  async function resetAll() {
    await api.resetProgress();
    await refreshKnowledge();
  }

  onMount(() => {
    const unlisteners: UnlistenFn[] = [];
    // Decay the meter to zero when level pings stop (e.g. system audio silent).
    const decay = setInterval(() => {
      if (Date.now() - lastLevelAt > 500) {
        levelSys = 0;
        levelMic = 0;
      }
    }, 200);
    (async () => {
      entries = await api.getEntries();
      await refreshKnowledge();
      config = await api.getConfig();
      await refreshAudio();
      unlisteners.push(
        await listen<AudioStatus>(
          "ts://audio-status",
          (e) => (audio = e.payload),
        ),
      );
      unlisteners.push(
        await listen<{ text: string }>(
          "ts://heard",
          (e) => (heard = e.payload.text),
        ),
      );
      unlisteners.push(
        await listen<{ value: number; source: string }>("ts://level", (e) => {
          lastLevelAt = Date.now();
          if (e.payload.source === "microphone") levelMic = e.payload.value;
          else levelSys = e.payload.value;
        }),
      );
      unlisteners.push(
        await listen("ts://refresh", async () => {
          await refreshKnowledge();
          // Entries can change too (e.g. a term the user deleted) — refetch so
          // the Library and Dashboard drop it immediately.
          entries = await api.getEntries();
        }),
      );
      unlisteners.push(
        await listen<{ id: string }>("ts://open-term", (e) => {
          pendingTermId = e.payload.id;
          view = "library";
        }),
      );
    })();
    return () => {
      clearInterval(decay);
      unlisteners.forEach((u) => u());
    };
  });

  const nav = [
    { key: "dashboard", label: "Dashboard", icon: "▣" },
    { key: "library", label: "Library", icon: "▤" },
    { key: "history", label: "History", icon: "↺" },
    { key: "dictation", label: "Dictation", icon: "✎" },
    { key: "settings", label: "Settings", icon: "⚙" },
  ] as const;
</script>

<div class="shell">
  <aside class="sidebar">
    <div class="brand">
      <img class="logo" src={logoUrl} alt="TermScope" />
      <span class="brand-name">TermScope</span>
      <span class="brand-ver">{version}</span>
    </div>

    <nav>
      {#each nav as item}
        <button
          class="nav-btn"
          class:active={view === item.key}
          onclick={() => (view = item.key)}
        >
          <span class="nav-icon">{item.icon}</span>
          <span>{item.label}</span>
        </button>
      {/each}
    </nav>

    <div class="sidebar-foot">
      <div class="listen-box">
        <label class="listen-row">
          <span class="listen-label">Listening</span>
          <span class="switch-sm">
            <input
              type="checkbox"
              checked={audio.listening}
              onchange={toggleListening}
            />
            <span class="track-sm"></span>
          </span>
        </label>
        <div class="listen-status">{audio.reason || "off"}</div>
        {#if audio.listening}
          <div class="meter-row">
            <div class="meter" title="audio level">
              <div class="meter-fill" style="width: {level}%"></div>
            </div>
            <span class="meter-val">{level}</span>
          </div>
        {/if}
        {#if audio.listening && heard}
          <div class="listen-heard" title={heard}>“{heard}”</div>
        {/if}
      </div>
      <button class="quit-btn" onclick={() => api.quitApp()}>⏻&nbsp;&nbsp;Quit</button>
    </div>
  </aside>

  <main class="content">
    {#if view === "dashboard"}
      <Dashboard {entries} {learned} />
    {:else if view === "library"}
      <Library
        {entries}
        {learned}
        {toggleLearned}
        bind:selectId={pendingTermId}
      />
    {:else if view === "history"}
      <History />
    {:else if view === "dictation"}
      <Dictation {audio} />
    {:else if config}
      <Settings {config} onReset={resetAll} />
    {/if}
  </main>
</div>

<style>
  .shell {
    display: flex;
    height: 100vh;
    width: 100vw;
  }
  .sidebar {
    width: 210px;
    flex-shrink: 0;
    background: var(--surface);
    display: flex;
    flex-direction: column;
    padding: 0 12px;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 24px 8px 28px;
  }
  .logo {
    width: 26px;
    height: 26px;
    border-radius: 6px;
    display: block;
  }
  .brand-name {
    font-weight: 600;
    font-size: 20px;
    color: var(--text);
  }
  .brand-ver {
    font-size: 11px;
    font-weight: 600;
    color: var(--accent);
    background: var(--surface3);
    border-radius: 6px;
    padding: 1px 6px;
    align-self: flex-start;
    margin-top: 3px;
  }
  nav {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .nav-btn {
    display: flex;
    align-items: center;
    gap: 12px;
    height: 44px;
    padding: 0 14px;
    border-radius: 8px;
    color: var(--text-muted);
    font-size: 16px;
    text-align: left;
    transition: background 0.12s, color 0.12s;
  }
  .nav-btn:hover {
    background: var(--surface3);
  }
  .nav-btn.active {
    background: var(--surface3);
    color: var(--text);
  }
  .nav-icon {
    width: 18px;
    text-align: center;
  }
  .sidebar-foot {
    margin-top: auto;
    padding-bottom: 14px;
  }
  .listen-box {
    background: var(--surface2);
    border-radius: var(--radius);
    padding: 12px 14px;
    margin-bottom: 8px;
  }
  .listen-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    cursor: pointer;
  }
  .listen-label {
    font-weight: 600;
  }
  .switch-sm input {
    display: none;
  }
  .track-sm {
    display: inline-block;
    width: 34px;
    height: 18px;
    border-radius: 9px;
    background: var(--surface3);
    position: relative;
    transition: background 0.15s;
  }
  .track-sm::after {
    content: "";
    position: absolute;
    top: 2px;
    left: 2px;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--text-muted);
    transition: transform 0.15s, background 0.15s;
  }
  .switch-sm input:checked + .track-sm {
    background: var(--green);
  }
  .switch-sm input:checked + .track-sm::after {
    transform: translateX(16px);
    background: white;
  }
  .listen-status {
    margin-top: 6px;
    font-size: 10px;
    color: var(--text-faint);
    line-height: 1.3;
  }
  .meter-row {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 6px;
  }
  .meter {
    flex: 1;
    height: 6px;
    border-radius: 3px;
    background: var(--surface3);
    overflow: hidden;
  }
  .meter-fill {
    height: 100%;
    background: var(--green);
    transition: width 0.12s ease-out;
  }
  .meter-val {
    font-size: 9px;
    color: var(--text-faint);
    width: 18px;
    text-align: right;
  }
  .listen-heard {
    margin-top: 4px;
    font-size: 10px;
    font-style: italic;
    color: var(--cyan);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .quit-btn {
    width: 100%;
    height: 34px;
    border-radius: 8px;
    color: var(--text-muted);
    text-align: left;
    padding: 0 14px;
    transition: background 0.12s, color 0.12s;
  }
  .quit-btn:hover {
    background: var(--red);
    color: var(--bg);
  }
  .content {
    flex: 1;
    overflow: hidden;
    background: var(--bg);
  }
</style>
