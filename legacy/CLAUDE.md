# TermScope — notes for Claude

Local-only Windows 11 **desktop app** (customtkinter) that explains tech/business
jargon heard in audio or found in highlighted text. A floating card pops in front of
all windows with Dismiss / Mark learned / Learn more. Also a browsable jargon library
with extended (Wikipedia-sourced) definitions and a "terms you know" tracker.

## Architecture
- Pure-stdlib core: `dictionary.py` → `matcher.py` (longest-match, plural-aware,
  `strict` acronyms) → `knowledge.py` (learned + cooldown). Fully unit-tested, no deps.
- `library.py` + `enrich_library.py`: extended definitions cached in `data/library.json`,
  enriched from Wikipedia (opensearch + REST summary, relevance-gated, checkpointed).
- Runtime layer (optional deps): `audio.py` (Vosk + PyAudioWPatch + numpy),
  `selection.py`, `hotkeys.py`, `notifier.py`.
- GUI: `ui/hub.py` (the CTk main window — Dashboard/Library/Settings), `ui/popup.py`
  (floating `NotificationCard` + `NotificationCenter`), `ui/theme.py`.
- `app.py` wires it together; `run()` builds the hub (single CTk root), the
  NotificationCenter, attaches it to the notifier, starts the listener, runs mainloop.

## Key conventions
- Notifier backends expose `show(entry, on_learned)`; `on_learned` takes the term **id**
  (string), `on_learn_more` takes the **entry**. The `card` backend delegates to the
  GUI's NotificationCenter, attached at runtime via `notifications.attach_card_center()`
  (so no second Tk root is ever created — `_build_backend` returns a console placeholder
  for `card`/`tk` until the GUI attaches).
- Only one CTk root (the hub). Background (audio) threads marshal onto it via
  `root.after` (NotificationCenter queue, `hub.schedule_refresh`).
- `find_model_dir` prefers full models over "small", then higher version.
- Default notifier is `card`; default `close_to_tray=False` (X quits). Single-instance
  guard (named mutex) in `app.run()`.

## Layout
- `src/termscope/` package; `ui/` has hub/popup/winident/theme.
- `data/` dicts + library; `assets/` icon.
- `scripts/` create_shortcuts.ps1 + make_icon.py. `tools/` update_terms.py + prompt.
- `tests/test_matcher.py` (unit) + `tests/manual/` (GUI/audio smoke + diagnostics).
- Root: `install.ps1` / `Install TermScope.bat`, `run.py`, `TermScope.pyw`.

## Commands
- `python run.py` (or `pythonw TermScope.pyw`) — the app.
- `python run.py download-model` / `enrich-library` / `demo "..."` / `terms`.
- `python tests/test_matcher.py` — stdlib unit tests (12).
- `install.ps1` — full installer; `scripts/create_shortcuts.ps1` — just shortcuts.
- `python tools/update_terms.py FILE [--enrich]` — merge AI-generated terms (see prompt).
- Manual smoke: scripts in `tests/manual/` (need `parents[2]/src` on path), `python -m termscope.ui.popup`.

## Environment gotchas (this machine)
- Microsoft Store Python: `python -m termscope.*` fails (package is under `src/`); use
  `run.py` subcommands or `PYTHONPATH=src`.
- Tool subprocesses can't screen-capture (sandbox), so GUI is verified via clean
  launch + headless pipeline smoke tests, not screenshots.
- Long background tasks can be reaped by the harness — `enrich_library` checkpoints
  `data/library.json` every 8 terms and resumes, so rerun it until it reports all 238.

## Not yet validated on hardware
Microphone-source capture, win11toast button-click callbacks. The floating card path
is fully exercised end-to-end.
