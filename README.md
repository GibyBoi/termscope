# TermScope

A local-only Windows desktop app that explains the tech, business and company
**jargon** you run into — highlight any text, hit a global hotkey, and a floating card
pops up in front of everything with a plain-English definition. It also keeps a
searchable library (with fuller, Wikipedia-sourced definitions) and tracks which terms
you've learned. Everything runs offline.

This is the **Tauri V2 rewrite** (Rust + Svelte 5). The original Python/customtkinter
app lives under [`legacy/`](legacy/) for reference.

> **Release: “WhisperOfHistory.”** The project is still called **TermScope** — this is
> just the name of the current release, which is where TermScope started using the
> **Whisper** offline voice-detection model to hear spoken jargon and added the
> **History** tab. History is stored as **orderless frequency counts only** (how often
> each word/term came up), never a timeline, so past conversations can't be
> reconstructed from disk.

## Features

- **Explain selection** — highlight text anywhere, press `Ctrl+Alt+E`, and unknown terms
  surface as floating cards (Learn more / ✓ Learned / Dismiss), stacked in a corner.
- **Listening (Whisper STT)** — optionally transcribe system audio + mic offline with the
  **Whisper** model to catch jargon as it's spoken and surface the same floating cards.
- **History** — a tally of how often each spoken word and each detected jargon term has
  come up. Stored as **orderless frequency counts only** (no order, timestamps, or log),
  so the file can't be replayed as a conversation.
- **Hub window** — Dashboard (progress, milestones, per-category bars), Library (search +
  filter ~500 terms with extended definitions), and Settings (all saved live).
- **Learned tracker** — mark terms learned so they stop interrupting you; progress lives
  in `%APPDATA%\TermScope` and survives updates (stable term ids).
- **Tray + autostart** — runs from the system tray; optional start-with-Windows.

| Hotkey | Default |
| --- | --- |
| Explain highlighted selection | `Ctrl+Alt+E` |
| Mark last shown term learned | `Ctrl+Alt+K` |
| Toggle listening | `Ctrl+Alt+Space` |

As of the **WhisperOfHistory** release, the Listening controls are live: enable system
audio and/or microphone in Settings and TermScope transcribes offline with **Whisper**,
catching spoken jargon and feeding the History tallies. (The original app used Vosk; see
[`legacy/`](legacy/).)

## Develop

Prerequisites: Rust (stable-msvc), VS Build Tools (C++ workload), Node 18+, WebView2.

```sh
npm install
npm run tauri dev      # run the app (Vite dev server + Rust shell)
npm run tauri build    # build the Windows installer (NSIS)
cd src-tauri && cargo test   # matcher / dictionary unit tests
```

## Project layout

```
termscope/
  src/                 Svelte 5 frontend
    App.svelte         hub shell (sidebar + views)
    lib/views/         Dashboard / Library / Settings
    Cards.svelte       floating-card overlay window
    lib/components/Card.svelte
    lib/api.ts         invoke() wrappers   lib/types.ts   app.css (theme)
  src-tauri/           Rust backend
    src/dictionary.rs matcher.rs knowledge.rs config.rs library.rs   (pure-logic ports)
    src/selection.rs startup.rs notifier.rs tray.rs commands.rs state.rs lib.rs
    tauri.conf.json    capabilities/   icons/
  data/                bundled term dictionaries + enriched library (stable ids)
  legacy/              the original Python app
```

## Configuration & privacy

Settings live in `%APPDATA%\TermScope\config.json`; learned terms + anti-spam state in
`knowledge.json` — both shared with the legacy app's format. Listening history lives in
`history.json` as **orderless frequency counts only** — just how many times each word and
jargon term came up, with no order, timestamps, or per-utterance log, so it can never be
read back as a conversation (and transcribed speech is never written to any log). No
network access at runtime; "Learn more" opens a source link in your browser only when you
click it.

See [CLAUDE.md](CLAUDE.md) for architecture notes.
