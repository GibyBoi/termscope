# TermScope

A local-only Windows desktop app that explains the tech, business and company
**jargon** you run into — highlight any text, hit a global hotkey, and a floating card
pops up in front of everything with a plain-English definition. It also keeps a
searchable library (with fuller, Wikipedia-sourced definitions) and tracks which terms
you've learned. Everything runs offline.

Built with **Rust (Tauri v2)**, **Svelte 5 + TypeScript**, and a small Python audio
sidecar running **Whisper** locally. Current release: **3.4**. The original
Python/customtkinter app lives under [`legacy/`](legacy/) for reference.

## How it works

```
 system audio (WASAPI loopback) ─┐
 microphone ─────────────────────┤  Python sidecar            Rust core (Tauri v2)             Svelte 5 UI
                                 └─▶ Endpointer ─▶ Whisper ─▶ matcher ─▶ knowledge ─▶ notifier ─▶ floating cards
 highlighted text + hotkey ────────────────────────────────▶  (JSON lines over stdin/stdout)      hub · dictation pill
```

- **Utterance endpointing, not fixed windows.** Audio is cut into whole utterances by a pure
  state machine (0.6 s hang, 0.25 s pre-roll, forced split at the quietest point after 12 s
  of unbroken speech). It replaced fixed 3 s overlapping windows, which transcribed every
  overlap twice and doubled words at each boundary. Covered by synthetic-audio tests.
- **No LLM in the hot path.** Terms are found by a longest-match, plural-aware token scan
  with strict rules for acronyms, so detection is instant, deterministic and offline.
  Cooldowns and a rate limiter keep cards from spamming you.
- **Three windows.** The hub, a transparent click-through always-on-top overlay that
  resizes itself to hug the card stack, and a dictation pill with a live waveform.
- **Privacy by construction.** Audio is never written to disk. History keeps only
  orderless word counts, so a conversation cannot be reconstructed from it. The only
  network use is the one-time model download.
- **User data is never lost.** Atomic saves, unreadable files are quarantined rather than
  overwritten, and unknown config keys survive a round trip between versions.
- 34 Tauri commands, 34 Rust unit tests (`cargo test`) plus Python endpointer tests.

> The project (and this repository) is named **TermScope**. An earlier release carried
> the codename “WhisperOfHistory” — that's when TermScope started using the **Whisper**
> offline voice-detection model to hear spoken jargon and added the **History** tab.
> History is stored as **orderless frequency counts only** (how often each word/term
> came up), never a timeline, so past conversations can't be reconstructed from disk.

## Features

- **Explain selection** — highlight text anywhere, press `Ctrl+Alt+E`, and unknown terms
  surface as floating cards (Learn more / ✓ Learned / Dismiss), stacked in a corner.
- **Listening (Whisper STT)** — optionally transcribe system audio + mic offline with the
  **Whisper** model to catch jargon as it's spoken and surface the same floating cards.
- **Dictation** — hold or toggle a hotkey, speak, and the text is pasted at your cursor
  with filler words removed. The whole recording is transcribed in one pass for coherent
  punctuation; an optional polish pass can run through a local model only (never cloud).
  Whisper is the default engine; Moonshine and Parakeet are selectable.
- **History** — a tally of how often each spoken word and each detected jargon term has
  come up. Stored as **orderless frequency counts only** (no order, timestamps, or log),
  so the file can't be replayed as a conversation.
- **Hub window** — Dashboard (progress, milestones, per-category bars), Library (search +
  filter ~785 terms with extended definitions), and Settings (all saved live).
- **Learned tracker** — mark terms learned so they stop interrupting you; progress lives
  in `%APPDATA%\TermScope` and survives updates (stable term ids).
- **Tray + autostart** — runs from the system tray; optional start-with-Windows.

| Hotkey | Default |
| --- | --- |
| Explain highlighted selection | `Ctrl+Alt+E` |
| Mark last shown term learned | `Ctrl+Alt+K` |
| Toggle listening | `Ctrl+Alt+Space` |

Hotkeys are rebindable in Settings — the table above shows the defaults.

### Listening requirements

Listening runs through a small Python sidecar bundled with the app
([`sidecar/listen.py`](sidecar/listen.py)). It needs **Python 3 on your PATH** with the
dependencies from [`sidecar/requirements.txt`](sidecar/requirements.txt):

```sh
python -m pip install --user -r sidecar/requirements.txt
```

The first listening session downloads the Whisper model (base.en, ~140 MB) into
`%APPDATA%\TermScope\models`; after that transcription is fully offline. Without
Python (or the packages) the rest of the app works normally — Settings simply shows
why Listening is unavailable. (The original app used Vosk; see [`legacy/`](legacy/).)

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
    lib/views/         Dashboard / Library / History / Settings
    Cards.svelte       floating-card overlay window
    lib/components/Card.svelte
    lib/api.ts         invoke() wrappers   lib/types.ts   app.css (theme)
  src-tauri/           Rust backend
    src/dictionary.rs matcher.rs knowledge.rs config.rs library.rs
        history.rs removed.rs paths.rs                    (pure-logic core)
    src/selection.rs startup.rs notifier.rs tray.rs audio.rs
        commands.rs state.rs lib.rs                       (system glue)
    tauri.conf.json    capabilities/   icons/
  sidecar/             Python audio sidecar (WASAPI capture + faster-whisper STT)
  data/                bundled term dictionaries + enriched library (stable ids)
  assets/              logo source image (regenerate: scripts/make_icon.py)
  legacy/              the original Python app, kept as reference
```

## Configuration & privacy

Settings live in `%APPDATA%\TermScope\config.json`; learned terms + anti-spam state in
`knowledge.json` — both shared with the legacy app's format. Listening history lives in
`history.json` as **orderless frequency counts only** — just how many times each word and
jargon term came up, with no order, timestamps, or per-utterance log, so it can never be
read back as a conversation (and transcribed speech is never written to any log). The app
makes no network requests, with two exceptions: the one-time Whisper model download when
Listening is first enabled, and "Learn more", which opens a source link in your browser
only when you click it.

See [CLAUDE.md](CLAUDE.md) for architecture notes.

## Attribution

Extended definitions in [`data/library.json`](data/library.json) are adapted from
[Wikipedia](https://www.wikipedia.org/) and are available under the
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) license; each entry links
its source article. Speech recognition uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
