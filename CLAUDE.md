# TermScope (Tauri V2) — notes for Claude

## v3-dev branch: the red "TermScope 3 Dev" edition (this branch)
This branch is TermScope 3 **as a separate development app** that runs alongside
the user's installed TermScope 2.x — nothing here may touch the 2.x install or
its data. The separation knobs, and the checklist to revert when v3 ships:
- `tauri.conf.json`: productName **"TermScope 3 Dev"**, identifier
  `com.0xygenbreather.termscope.dev` (own single-instance mutex + install dir),
  window title. → On release: back to "TermScope" / `com.0xygenbreather.termscope`.
- `paths.rs`: `APP_NAME = "TermScope3Dev"` → data in `%APPDATA%\TermScope3Dev`
  (seeded once with COPIES of the real history/knowledge + synthetic `mic_days`
  for chart development — safe to wipe). → On release: `"TermScope"` again; the
  additive history schema needs no migration.
- `config.rs`: default hotkeys are `ctrl+shift+alt+…` so they don't collide with
  a running 2.x (`ctrl+alt+…`). → On release: revert defaults.
- Icon: all-red via `python scripts/make_icon.py --dev` (writes `assets/` +
  `src/assets/` PNGs) + `npm run tauri icon assets/termscope.png`. The sidebar
  badge ("x.y dev", red) is in `App.svelte`; tray labels in `tray.rs`.
  → On release: rerun `make_icon.py` WITHOUT `--dev`, regenerate icons,
  `cargo clean` (icon cache gotcha below), un-red the badge/tray.

### v3 features (this branch)
- **Mic-only filler tracking** (`history.rs`): the sidecar has always tagged text
  events with `source`; `audio.rs` now passes `mic = source=="microphone"` into
  `record_audio`, which additionally tallies `mic_filler_counts` (per filler
  word), `mic_word_total`, and `mic_days` — per-day `{mic_words, mic_filler}`
  aggregates (BTreeMap, local "YYYY-MM-DD" via chrono). The day buckets are the
  only time-shaped data in the app and hold two counters/day, no words — filler
  goals need a trend, conversations still can't be reconstructed. System audio
  NEVER feeds these (goals measure the user, not their speakers).
- **Filler goal** (History tab): `config.filler_goal_percent` (0 = off, default
  5.0), goal panel with recent (last 7 recorded days) vs all-time rate,
  `TrendChart.svelte` (SVG line, dashed goal line, hover crosshair), top-filler
  chips. DTO additions in `commands.rs::get_history` (`mic_words`, `mic_filler`,
  `mic_fillers`, `days`).
- **Dictation** (`views/Dictation.svelte`): mic-only speech-to-text pad that cuts
  filler words as utterances arrive (`ts://heard` now carries `source`; the view
  keeps only `microphone`). Start auto-enables Listening (and turns it back off
  if dictation turned it on); Copy/Clear; the text is RAM-only, never persisted.
- **Hotkey dictation** (`audio.rs::{dictate_start,dictate_stop}`): the
  `hotkey_dictate` global hotkey starts a backend dictation session — borrows or
  spawns the sidecar for the mic (`PriorAudio` records what to restore), cleans
  filler per utterance (`clean_fillers`, unit-tested), and on finish puts the
  text on the clipboard and synthesizes Ctrl+V (`selection::paste_text`) so it
  lands at the cursor; no focused field → it's simply on the clipboard. Finish
  is `config.dictate_mode`: "toggle" (second press, 500ms autorepeat debounce
  in `commands::run_dictate_event`) or "hold" (key release — `lib.rs` forwards
  BOTH shortcut edges for this hotkey only). While live, `ts://dictate
  {active}` drives the **dictation indicator pill**: a third window
  ("dictate" — `dictate.html` + `src/Dictate.svelte`, built hidden in
  `lib.rs`, `capabilities/dictate.json`), transparent/always-on-top/
  skip-taskbar, which its own frontend sizes and centers just above the
  screen's bottom edge while active. It shows a mic glyph + bars whose crest
  travels end to end (staggered CSS keyframes) with height following the real
  mic level (`ts://level` is broadcast to it). The Dictation VIEW emits the
  same event for its sessions (`emitTo` from JS), so the pill covers both
  flows; a failed hotkey start emits `{active:false, error}` and the pill
  shows the error for 6s — dictation failures are never silent. The view also
  displays the current `hotkey_dictate` as a read-only reference (binding is
  changed in Settings only).
- **Hotkeys are unbindable**: "" = unbound (skipped at registration; Esc in the
  Settings recorder unbinds; `set_hotkey` accepts empty; `reset_hotkey` restores
  the build default and returns it; per-row ↺ button in Settings).
- **Clipboard safety** (`selection.rs`): capture stashes text OR images and
  restores on every path (clears if there was nothing to restore); the sentinel
  is printable so a killed-mid-capture process can't leave an
  invisible-looking clipboard.

Local-only Windows 11 desktop app that explains tech/business/company jargon. A
**Rust (Tauri V2) backend** + **Svelte 5 (Vite) frontend** rewrite of the original
Python/customtkinter app (which now lives under `legacy/` as reference).

Highlight any text and press the global hotkey → floating cards pop in front of all
windows explaining each unknown term (Learn more / ✓ Learned / Dismiss). A hub window
has a Dashboard (progress + milestones), a searchable Library (Wikipedia-enriched
definitions), History, and Settings. **Listening** (system audio + mic → offline STT)
works through a Python sidecar (`sidecar/listen.py`, faster-whisper) — see the
"Audio sidecar" section below.

## Architecture
- **Rust core ports** (faithful 1:1 of the Python, in `src-tauri/src/`):
  `dictionary.rs` → `matcher.rs` (longest-match, plural-aware, `strict` acronyms; 11
  unit tests) → `knowledge.rs` (learned + cooldown, atomic save) ; `config.rs`,
  `library.rs`, `paths.rs`, `notifier.rs` (recent-stack + rate limit),
  `history.rs` (spoken-word + jargon tallies, see History tab below).
- **System glue**: `tray.rs` (Tauri tray), `startup.rs` (HKCU Run), `selection.rs`
  (clipboard + `enigo` Ctrl+C capture), `commands.rs` (all `#[tauri::command]`s +
  hotkey workers), `audio.rs` (spawns the Python sidecar, parses its JSON-line
  stdout, cards heard jargon), `state.rs` (`AppState` = the old `TermScopeApp`).
- **lib.rs** wires plugins (single-instance, global-shortcut, opener, dialog), builds
  the tray, creates the transparent always-on-top **cards** window, registers hotkeys,
  and handles X-closes-to-tray-vs-quit.
- **Frontend** (`src/`): `App.svelte` (sidebar shell) + `lib/views/{Dashboard,Library,
  Settings}.svelte` for the hub; `Cards.svelte` + `lib/components/Card.svelte` for the
  floating overlay. `lib/api.ts` wraps every `invoke`; `lib/types.ts` mirrors the Rust
  structs; `app.css` holds the theme variables (ported from `legacy/.../ui/theme.py`).

## History tab
- `history.rs` records, to `%APPDATA%\TermScope\history.json` (atomic), two
  **orderless** frequency tallies only: **every spoken word** heard (`word_counts`)
  and **every jargon detection** (`term_counts`). There is deliberately **no
  timeline** — no per-occurrence log, timestamps, or source. A conversation is a
  sequence; storing only bag-of-words counts means past conversations can't be
  reconstructed from the file. Old files that still carry a legacy `log` array load
  fine (serde ignores it) and drop it on the next save.
- Recording happens in `audio.rs::handle_heard_text` (all matches, ignoring
  learned/cooldown — history = what was *said*, not what we carded) and in
  `commands.rs::run_explain_selection` (selection jargon, no word tally). Each fires
  a `ts://history` event; `History.svelte` debounce-refetches on it.
- `commands::get_history` returns an enriched DTO (words sorted desc, jargon terms
  with counts + totals); entries whose term id was retired are dropped.
  `commands::clear_history` wipes it (the tab's "Clear history" button).
  `commands::get_filler_words` returns the bundled filler tokens (see below).
- `History.svelte`: a stats row + an **"At a glance" charts panel** + a Counts view
  driven by a **modular multi-select filter** (`src/lib/historyFilters.ts`). The
  charts are pure frequency aggregates of the same tallies (still no timeline):
  a jargon-by-category donut (`lib/components/DonutChart.svelte` — reusable SVG
  stroke-arc donut with center figure, direct-labeled legend, hover tooltip +
  dimming), a top-8 jargon bar list, and two meters (filler share of **mic**
  words — the all-audio share is a secondary line only — and learned share of
  unique jargon heard). **Filler is mic-first everywhere**: the Counts filters
  are "Filler (mic)" (from `mic_fillers`, the primary metric) and "Filler (all
  audio)" (words ∩ filler list, the bonus view). Slice order/colors come from
  `orderedCategories` + `categoryColor` so a category's position and color never
  depend on its counts. Each filter is a `FilterDef` producing a
  set of `DisplayItem` rows; the view unions the selected filters (de-duped by key),
  frequency-sorts them (asc/desc toggle) and search-narrows by label. Built-in
  filters: **Jargon** (all detected terms), **Filler words** (spoken words ∩ the
  filler list), one per jargon category (**Tech / Business / Company**, driven by
  config `enabled_categories` so they're always selectable — plus any extra category
  seen in `data.terms`), and **All words** (every spoken word, so any word's frequency
  stays searchable). Add a filter type = add one `FilterDef`. Still pure frequency
  bars, no chronological view.
- **Filler words** live in bundled `data/filler_words.json` (`{category, words:[…]}`),
  loaded by `dictionary::load_filler_words` into `AppState.filler_words` as normalized
  tokens and exposed via `get_filler_words`; membership is a client-side lookup against
  the already-fetched spoken-word tallies. Grow the list with the discover-jargon
  approach (judge true filler vs ordinary word). Entries must be single tokens — the
  orderless history is a bag of single words, so multi-word fillers can't match.

## User deletions (removed.rs) & custom hotkeys
- `removed.rs` → `%APPDATA%\TermScope\removed.json`: per-user overlay of deleted
  dictionary terms (`term_ids`) and spoken words (`words`). A removed term is never
  matched/carded/listed/tallied; a removed word's tally is purged and never recounted.
  Delete controls (two-step: click arms → click again confirms, 4s auto-disarm) live on
  History rows, the Library detail pane, and each popup card ("🗑"/"Sure?"). Bundled
  dictionaries stay read-only — deletions are this per-user overlay, so they survive
  updates. `remove_term`/`remove_word` commands purge history and emit refreshes.
- **Hotkeys are user-rebindable** in Settings (click binding → press combo → Esc
  cancels). `set_hotkey` validates + registers the new combo BEFORE saving, rolls back
  to the old combo on failure, and rejects duplicates across the three actions; the
  frontend requires a modifier (F-keys exempt). All three hotkeys (explain selection,
  mark last learned, toggle listening) are registered at startup and live-rebound.

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
- `data/terms_*.json` + `data/library.json` + `data/filler_words.json` keep the SAME format and **stable integer
  term ids**. `config.json` + `knowledge.json` stay in `%APPDATA%\TermScope`. So a user's
  learned-term progress carries over between the Python app and this rewrite untouched.
- Bundled data is wired via `tauri.conf.json` `bundle.resources`; `state.rs::resolve_data_dir`
  finds it in both packaged (resource dir) and dev (`../data`) builds.

## Storage safety — user data is never deleted except by the user (do not break)
Per-user data (`history.json` = spoken words + jargon tallies, `knowledge.json` = learned
terms, `config.json`) must survive every app update. The rules a future version MUST keep:
- **Load through `paths::load_json_store`** — the single safe loader. A missing file is a
  fresh start; a parseable file loads as-is; an **unreadable** file (corruption, a partial
  write, or a schema this build can't parse) is *quarantined* — renamed to
  `<name>.corrupt-<unix>.json` — and the store starts empty, `savable`. If it can't even be
  backed up, the store is **not** `savable` and refuses to write, so the original is left
  untouched. Never load with `serde_json::from_str(...).ok().unwrap_or_default()`: on a parse
  failure that silently returns empty and the next `save()` *overwrites the user's real data*.
  Regression test: `history::tests::unreadable_file_is_preserved_never_wiped`.
- **Keep persisted structs additively compatible**: every field `#[serde(default)]`, add
  fields (don't rename/retype existing ones), so old files keep parsing and no field is
  silently dropped. Renaming a field IS data loss — migrate it in the loader instead.
- **Config round-trips unknown settings**: `Config.extra` (`#[serde(flatten)]`) retains
  keys this build doesn't recognize (from a newer version or the legacy Python app) and
  writes them back on save, so a rollback never deletes settings a newer version added.
  Config saves are atomic (tmp + rename), like history. Regression tests:
  `config::tests::{unknown_settings_survive_resave, old_config_gains_new_fields_without_losing_values}`.
- **Deletion is user-only**: the sole code paths that remove user data are `History::clear`
  (History-tab "Clear") and `Knowledge::reset` (Reset learned). No load, migration, or update
  path may delete or blank a file.
- **The installer must not touch `%APPDATA%\TermScope`.** Data lives in Roaming `%APPDATA%`;
  the app installs to `%LOCALAPPDATA%`. The default NSIS bundle (no custom `bundle.windows.nsis`
  config) doesn't remove `%APPDATA%` on uninstall — and an *update* runs the old uninstaller
  first, so any future `deleteAppDataOnUninstall`-style behavior would wipe data on update.
  Never add it.

## Events (Rust → JS)
- To `cards`: `ts://card` `{ entry, timeout, maxCards, position, customX, customY }` —
  show a card; `ts://card-remove` `{ id }` — yank one; `ts://config` — live card
  options; `ts://place-mode` — enter drag-to-place mode.
- To `main`: `ts://refresh` — knowledge/dictionary changed; `ts://history` — tallies
  changed; `ts://open-term` `{ id }` — a card's "Learn more" deep-link;
  `ts://audio-status` — listening state; `ts://heard` `{ text }` — live transcription
  (RAM only, never persisted); `ts://level` `{ value, source }` — audio meter.
  `ts://config` also reaches `main` after hotkey/placement saves.

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
- **If `icons/icon.ico` changes, `cargo clean` before building.** Cargo caches the
  compiled Windows resource, so an incremental `tauri build` can ship an exe that
  still embeds the previous icon. A clean build always embeds the current one.
- The icon pipeline is: `python scripts/make_icon.py` redraws the logo →
  `assets/termscope.png` (single source image), then `npm run tauri icon
  assets/termscope.png` regenerates `src-tauri/icons/`. The app is Windows-only
  (NSIS), so only the Windows icons are kept — delete the android/ios/Square/Store/
  icns extras that `tauri icon` also emits.
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

## Audio sidecar (Listening)
`sidecar/listen.py` captures WASAPI loopback (system audio) + microphone with
`pyaudiowpatch` and transcribes offline with **faster-whisper** (base.en, int8, CPU).
Speech is segmented by the **`Endpointer`** (v3): whole utterances cut at natural
pauses (0.6s hang, 0.25s pre-roll, sub-0.3s blips dropped), with a forced SPLIT
(never an overlap) at the quietest recent stretch after 12s of pauseless speech —
the consumer de-dups one boundary word across forced cuts only. This replaced the
old fixed 3s windows + 0.4s overlap, which transcribed the overlap twice (doubled
words at every boundary) and let Whisper punctuate each slice as its own sentence
(stray mid-sentence periods). The Endpointer is a pure state machine —
`sidecar/test_endpointer.py` covers it with synthetic audio (`python
sidecar/test_endpointer.py`, needs numpy only).
It is bundled as a resource (`tauri.conf.json`) and spawned by `audio.rs` via the
system `python` on PATH — it is NOT compiled in. Requirements on the machine:
Python 3 + `pip install -r sidecar/requirements.txt`; the first listening session
downloads the Whisper model (~140 MB) into `%APPDATA%\TermScope\models`, after which
everything is offline. Missing Python/deps degrade gracefully: the sidecar emits a
`status ready:false` JSON line and Settings shows the reason — the rest of the app is
unaffected. A native Rust port (`cpal` + whisper) remains a possible future cleanup;
the original Vosk pipeline lives in `legacy/` as reference.
