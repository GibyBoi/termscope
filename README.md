# TermScope

A local-only Windows 11 desktop app that quietly explains the tech and business
jargon around you. It listens to what you hear (and what you highlight), and when
a term you haven't learned yet comes up it pops a **small card in front of all your
windows** with a short definition and **Dismiss / Mark learned / Learn more**.

It also doubles as a **jargon library** — a browsable reference of 200+ terms with
extensive definitions pulled from online dictionaries (cached offline) — and tracks
**how many technical terms you know** as you mark them learned.

Everything runs **offline** at runtime. Audio is transcribed on your machine (Vosk)
and never leaves it. The one online step is a one-time library enrichment.

## Highlights

- **Sleek hub window** (pin it to the taskbar) with three views: Dashboard, Library, Settings.
- **Floating notification cards** that appear over everything — even when the hub is
  minimized or another app is focused — with Dismiss, Mark learned and Learn more.
- **Jargon library** with extensive, reference-style definitions (Wikipedia-sourced
  where available, with a "Learn more" link), searchable and filterable.
- **"Terms you know" tracker** — per-category progress bars and a mastery percentage.
- **Two live inputs:** system audio (the other person on a call) + your mic, plus a
  highlight-and-explain hotkey.

## Install & launch

**Easiest — run the installer.** Double-click **`Install TermScope.bat`** (or run
`powershell -ExecutionPolicy Bypass -File install.ps1`). It installs dependencies,
downloads the offline speech model, builds the jargon library, and creates Start-menu
and Desktop shortcuts (stamped with the app's taskbar identity). It's safe to re-run.

**Manual steps** (same thing, by hand):

```powershell
python -m pip install -r requirements.txt   # includes customtkinter for the modern UI
python run.py download-model                 # one-time: offline speech model
python run.py enrich-library                 # one-time: fetch extensive definitions
powershell -ExecutionPolicy Bypass -File scripts\create_shortcuts.ps1   # shortcuts + taskbar identity
```

The shortcut step stamps the shortcuts (and any already-pinned taskbar shortcut) with
the app's **AppUserModelID**, matching the one the window sets itself at startup.
That's what makes the running window light up the **pinned TermScope icon** instead
of a generic "python (windowed)" button. If you pinned it before running this and
still see a stray button, unpin & re-pin once.

Then search **TermScope** in the Start menu (or use the Desktop shortcut), launch it,
and right-click its taskbar button → **Pin to taskbar**. You can also launch directly:

```powershell
python run.py            # with a console
pythonw TermScope.pyw    # no console (what the shortcut uses)
```

> The shortcut runs `pythonw.exe TermScope.pyw`, so there's no console window. The app
> keeps running (and keeps popping cards) while its window is minimized.

## Using it

- **Dashboard** — flip **Listening** on (bottom-left switch, or the `Ctrl+Alt+Space`
  hotkey) and watch your "terms learned / tracked / mastery" stats and per-category
  progress.
- **Library** — search and browse every term, read its full definition, hit
  **Learn more** to open the online source, or toggle a term **learned / un-learned**
  right from the list (the green ✓ / faint + on each row) or its detail panel.
- **Settings** — every toggle, saved live: which audio sources to listen to,
  start-on-launch, notification style (floating card / Windows toast), cooldown,
  rate cap, **how long each card stays on screen**, **how many cards stack at once**,
  **which corner they appear in**, speech model, and your hotkeys.
- **Notification card** — when a new term is heard or selected, a card slides in at
  the bottom-right:
  - **Learn more** opens its library entry.
  - **✓ Learned** retires it (you won't be shown it again).
  - **Dismiss** (or the auto-countdown) closes it.

| Hotkey | Default |
| --- | --- |
| Explain highlighted selection | `Ctrl+Alt+E` |
| Mark last shown term learned | `Ctrl+Alt+K` |
| Toggle audio listening | `Ctrl+Alt+Space` |

### Closing & running in the background

- The **X** button **quits** the app (clear and predictable). To keep it catching
  jargon while you work, **minimize** it instead — it keeps running.
- There's also a **Quit** button at the bottom of the sidebar and a **system-tray
  icon** (Open / Listening / Quit).
- Prefer X to minimize-to-tray? Turn on *"Closing the window keeps TermScope running
  in the tray"* in **Settings → General**.
- **Only one instance runs at a time** — launching it again just focuses the existing
  one, so you'll never end up with a stack of windows.

### More options (Settings → General)

Appearance (dark / light / system), **Start with Windows**, **Export progress**, and
**Reset learned terms**.

## Project layout

```
termscope/
  Install TermScope.bat / install.ps1       one-click installer
  run.py                                    CLI: run | download-model | enrich-library | demo | terms
  TermScope.pyw                             no-console launcher (what shortcuts use)
  requirements.txt
  data/
    terms_tech.json / terms_business.json   short dictionary definitions (238 terms)
    library.json                            extended definitions + source URLs (enriched)
  assets/termscope.ico                      app icon
  src/termscope/
    dictionary.py / matcher.py / knowledge.py   pure-stdlib core (terms, matching, learned state)
    library.py / enrich_library.py          extended definitions + online enrichment
    audio.py / selection.py                 system-audio + mic capture, highlight capture
    notifier.py                             card / win11toast / console backends + rate limiting
    hotkeys.py                              global hotkeys
    ui/
      hub.py                                the main window (Dashboard / Library / Settings)
      popup.py                              the floating notification card + center
      winident.py                           taskbar icon + AppUserModelID (pinned-icon grouping)
      theme.py                              colors / fonts
    app.py                                  wires the backend, hub and notifications together
  scripts/
    create_shortcuts.ps1                    Start-menu/Desktop shortcuts + taskbar identity
    make_icon.py                            regenerates assets/termscope.ico
  tools/
    update_terms.py                         merge AI-generated terms into the dictionary
    update_terms_prompt.md                  copy-paste prompt for any AI
  tests/
    test_matcher.py                         stdlib unit tests
    manual/                                 GUI/audio smoke + diagnostic scripts
```

## Configuration

Settings live in `%APPDATA%\TermScope\config.json` (edited live from the Settings tab).
Learned terms and anti-spam state live in `%APPDATA%\TermScope\knowledge.json`. The
offline speech model lives in `%APPDATA%\TermScope\models\` (the app auto-selects the
best installed model; a larger one transcribes fast jargon better — see below).

```powershell
# Optional: a larger, more accurate offline model (the app prefers it automatically)
python run.py download-model --url https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip
```

## Updating the term list (with any AI)

Grow the dictionary using **any** AI assistant — no special access needed:

1. Open **`tools/update_terms_prompt.md`**, copy the prompt, and paste it into ChatGPT,
   Claude, Gemini, etc. with your topic (e.g. *"cloud infra"*, *"VC fundraising"*).
2. Save the AI's JSON output to a file.
3. Merge it in (validates, dedupes, routes to the right category):

   ```powershell
   python tools/update_terms.py new_terms.json --enrich
   ```

   `--enrich` also fetches full "Learn more" definitions for the new terms. Restart
   TermScope and they're live.

You can also hand-edit `data/terms_*.json` directly — one entry per line:
`{"term": "ETL", "definition": "Extract, Transform, Load — moving data between systems.", "aliases": ["e t l"]}`.

## Privacy

- No network access at runtime. Transcription is fully local (Vosk).
- The only online step is the one-time `enrich-library` (Wikipedia); after it, the app
  is fully offline. "Learn more" opens a source link in your browser only if you click it.
- Listening is **opt-in** and off until you toggle it.

## Status

- **Validated:** the matcher (12 unit tests incl. strict acronyms), system-audio capture
  + live Vosk transcription, the full pipeline (heard term → rate-limited → floating card
  → Mark learned → progress update), the modern UI, the launcher and shortcuts.
- **Library coverage:** ~half the terms get a full Wikipedia extract; the rest keep a
  concise definition plus a Wiktionary "Learn more" link.
- **Not yet validated on hardware:** microphone-source capture and win11toast button
  clicks (the floating card is the default and is fully exercised).
```
