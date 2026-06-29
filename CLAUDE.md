# TermScope (Tauri V2) — notes for Claude

Local-only Windows 11 desktop app that explains tech/business/company jargon. A
**Rust (Tauri V2) backend** + **Svelte 5 (Vite) frontend** rewrite of the original
Python/customtkinter app (which now lives under `legacy/` as reference).

Highlight any text and press the global hotkey → floating cards pop in front of all
windows explaining each unknown term (Learn more / ✓ Learned / Dismiss). A hub window
has a Dashboard (progress + milestones), a searchable Library (Wikipedia-enriched
definitions), and Settings. **Audio capture + offline STT is deferred to v2** — the
Listening UI is present but inert.

## Architecture
- **Rust core ports** (faithful 1:1 of the Python, in `src-tauri/src/`):
  `dictionary.rs` → `matcher.rs` (longest-match, plural-aware, `strict` acronyms; 11
  unit tests) → `knowledge.rs` (learned + cooldown, atomic save) ; `config.rs`,
  `library.rs`, `paths.rs`, `notifier.rs` (recent-stack + rate limit),
  `history.rs` (spoken-word + jargon tallies, see History tab below).
- **System glue**: `tray.rs` (Tauri tray), `startup.rs` (HKCU Run), `selection.rs`
  (clipboard + `enigo` Ctrl+C capture), `commands.rs` (all `#[tauri::command]`s +
  hotkey workers), `state.rs` (`AppState` = the old `TermScopeApp`).
- **lib.rs** wires plugins (single-instance, global-shortcut, opener, dialog), builds
  the tray, creates the transparent always-on-top **cards** window, registers hotkeys,
  and handles X-closes-to-tray-vs-quit.
- **Frontend** (`src/`): `App.svelte` (sidebar shell) + `lib/views/{Dashboard,Library,
  Settings}.svelte` for the hub; `Cards.svelte` + `lib/components/Card.svelte` for the
  floating overlay. `lib/api.ts` wraps every `invoke`; `lib/types.ts` mirrors the Rust
  structs; `app.css` holds the theme variables (ported from `legacy/.../ui/theme.py`).

## History tab
- `history.rs` records, to `%APPDATA%\TermScope\history.json` (atomic): a tally of
  **every spoken word** heard (`word_counts`), a tally of **every jargon detection**
  (`term_counts`), and a rolling **log** of recent jargon occurrences. The log is
  hard-capped at 100 (the slider's max) — older entries are dropped so we never
  retain data the UI can't show.
- Recording happens in `audio.rs::handle_heard_text` (all matches, ignoring
  learned/cooldown — history = what was *said*, not what we carded) and in
  `commands.rs::run_explain_selection` (selection jargon, no word tally). Each fires
  a `ts://history` event; `History.svelte` debounce-refetches on it.
- `commands::get_history` returns an enriched DTO (words sorted desc, jargon terms
  with counts, log newest-first); entries whose term id was retired are dropped.
  `commands::clear_history` wipes it (the tab's "Clear history" button).
- `History.svelte`: two-mode Counts view (jargon terms vs all spoken words) + a
  chronological log with a 20–100 slider and an All/Heard/Selected source filter.

## Growing the dictionary (discover-jargon skill)
- `.claude/skills/discover-jargon/` (SKILL.md + `jargon_tool.py`): the model generates
  candidate jargon, `jargon_tool.py check` reports which TermScope is missing (same
  normalization as `matcher.rs`), the model judges true-jargon-vs-ordinary-word, and
  `jargon_tool.py add` appends approved terms to `data/terms_<cat>.json` with stable
  global-max+1 ids, in the exact one-term-per-line format, atomically. `stats` shows
  per-category counts. Restart the app to load new terms.

## Two windows
- `main` (hub, defined in `tauri.conf.json`) and `cards` (created hidden in `lib.rs`:
  transparent, frameless, always-on-top, skip-taskbar, not focusable). The cards window
  **sizes/positions itself** to hug the card stack in the chosen corner (`Cards.svelte`
  `relayout()`), so it rarely covers anything but the cards.

## Data compatibility (do not break)
- `data/terms_*.json` + `data/library.json` keep the SAME format and **stable integer
  term ids**. `config.json` + `knowledge.json` stay in `%APPDATA%\TermScope`. So a user's
  learned-term progress carries over between the Python app and this rewrite untouched.
- Bundled data is wired via `tauri.conf.json` `bundle.resources`; `state.rs::resolve_data_dir`
  finds it in both packaged (resource dir) and dev (`../data`) builds.

## Events (Rust → JS)
- `ts://card` (to `cards`): `{ entry, timeout, maxCards, position }` — show a card.
- `ts://card-remove` (to `cards`): `{ id }`. `ts://config` (to `cards`): live card options.
- `ts://refresh` (to `main`): knowledge changed. `ts://open-term` (to `main`): `{ id }`
  from a card's "Learn more".

## Commands
`npm install` once. Then:
- `npm run tauri dev` — run the app (Vite on :1420 + the Rust shell).
- `npm run tauri build` — produce the NSIS installer.
- `npm run build` — frontend only (Vite → `dist/`).
- `cd src-tauri && cargo test` — matcher/dictionary unit tests.
- `cd src-tauri && cargo build` — compile the backend only.

## Build gotchas (Windows) — important
- **Never ship a raw `cargo build` exe.** A bare `cargo build`/`cargo build --release`
  produces a **dev-mode** binary that loads `devUrl` (localhost:1420) → the window shows
  `ERR_CONNECTION_REFUSED` with no dev server. Only `npm run tauri build` embeds the
  frontend (`frontendDist`/`../dist`) for a standalone app. Verify screen-free by checking
  the exe doesn't open a socket to 1420 (TcpListener probe).
- **EXE icon doesn't re-embed.** `tauri build`'s build-script icon embedding caches the
  old icon resource, so changing `icons/icon.ico` doesn't update the exe's Windows icon
  (it keeps shipping the stale placeholder). Fix the final exe with
  `npm run fix-icon` (rcedit, rewrites only the PE icon resource — frontend untouched),
  or use `npm run build:app` (= `tauri build` + fix-icon). The bundled NSIS installer's
  exe still carries the old icon unless you `cargo clean` before building.
- Regenerate the whole icon set from the source PNG: `python scripts/make_icon.py` then
  `npm run tauri icon assets/termscope.png`.
- Verify an exe's real embedded icon via `[System.Drawing.Icon]::ExtractAssociatedIcon`
  on a **fresh copy at a non-`%LOCALAPPDATA%` path** (the Claude sandbox virtualizes
  `%APPDATA%`/`%LOCALAPPDATA%`, so reads there can be stale).

## Toolchain (installed on this machine)
Rust (rustup, stable-msvc), VS 2022 Build Tools (VCTools), Node 24, npm, WebView2.
Add `~/.cargo/bin` to PATH in fresh shells (`export PATH="$HOME/.cargo/bin:$PATH"`).

## Environment gotchas (this machine)
- Tool subprocesses can't screen-capture (sandbox) — verify the GUI via the
  **computer-use MCP**, or a clean `npm run tauri dev` launch + logs.
- Selection capture (`selection.rs`) uses `enigo` to release modifiers then send Ctrl+C,
  mirroring the Python trick — unvalidated on hardware yet.

## Deferred to v2
WASAPI loopback + mic capture and offline Vosk STT (native Rust: `cpal` + `vosk-rs`).
The full pipeline still exists in `legacy/` if needed as a reference or sidecar.
