//! Tauri commands invoked from the Svelte frontend, plus the shared workers the
//! global hotkeys call. Mirrors the wiring in `legacy/src/termscope/app.py`.

use serde::Serialize;
use serde_json::json;
use tauri::{AppHandle, Emitter, Manager, State};

use crate::config::Config;
use crate::dictionary::TermEntry;
use crate::library::Detail;
use crate::state::AppState;

#[derive(Serialize)]
pub struct KnowledgeDto {
    pub learned: Vec<String>,
    pub count: usize,
}

// ---- data -------------------------------------------------------------------

#[tauri::command]
pub fn get_entries(state: State<AppState>) -> Vec<TermEntry> {
    state
        .entries
        .iter()
        .filter(|e| !state.removed.is_term_removed(&e.id))
        .cloned()
        .collect()
}

#[tauri::command]
pub fn get_knowledge(state: State<AppState>) -> KnowledgeDto {
    let learned: Vec<String> = state.knowledge.learned_ids().into_iter().collect();
    let count = learned.len();
    KnowledgeDto { learned, count }
}

#[tauri::command]
pub fn get_library_detail(state: State<AppState>, id: String) -> Option<Detail> {
    state.entry(&id).map(|e| state.library.detail(e))
}

// ---- history ----------------------------------------------------------------

#[derive(Serialize)]
pub struct WordStat {
    pub word: String,
    pub count: u64,
}

#[derive(Serialize)]
pub struct TermStat {
    pub id: String,
    pub term: String,
    pub category: String,
    pub definition: String,
    pub learned: bool,
    pub count: u64,
}

/// One calendar day's microphone totals, for the filler-goal trend chart.
#[derive(Serialize)]
pub struct DayStat {
    pub date: String, // "YYYY-MM-DD" (local)
    pub mic_words: u64,
    pub mic_filler: u64,
}

#[derive(Serialize)]
pub struct HistoryDto {
    pub total_words: u64,
    pub unique_words: usize,
    pub total_jargon: u64,
    pub words: Vec<WordStat>, // every spoken word, sorted by count desc
    pub terms: Vec<TermStat>, // jargon detected at least once, sorted by count desc
    // Microphone-only filler tracking (the filler-reduction goals):
    pub mic_words: u64,             // total words heard via the microphone
    pub mic_filler: u64,            // how many of them were filler
    pub mic_fillers: Vec<WordStat>, // per-filler-word mic counts, sorted desc
    pub days: Vec<DayStat>,         // per-day mic totals, oldest → newest
}

#[tauri::command]
pub fn get_history(state: State<AppState>) -> HistoryDto {
    let snap = state.history.snapshot();
    let total_words: u64 = snap.word_counts.values().sum();
    let unique_words = snap.word_counts.len();
    let total_jargon: u64 = snap.term_counts.values().sum();

    let mut words: Vec<WordStat> = snap
        .word_counts
        .into_iter()
        .filter(|(word, _)| !state.removed.is_word_removed(word))
        .map(|(word, count)| WordStat { word, count })
        .collect();
    words.sort_by(|a, b| b.count.cmp(&a.count).then_with(|| a.word.cmp(&b.word)));

    // Only terms still present in the dictionary can be displayed; drop any whose
    // id was retired (delete data we can no longer show) or user-deleted.
    let mut terms: Vec<TermStat> = snap
        .term_counts
        .iter()
        .filter(|(id, _)| !state.removed.is_term_removed(id))
        .filter_map(|(id, &count)| {
            state.entry(id).map(|e| TermStat {
                id: id.clone(),
                term: e.term.clone(),
                category: e.category.clone(),
                definition: e.definition.clone(),
                learned: state.knowledge.is_learned(id),
                count,
            })
        })
        .collect();
    terms.sort_by(|a, b| {
        b.count
            .cmp(&a.count)
            .then_with(|| a.term.to_lowercase().cmp(&b.term.to_lowercase()))
    });

    let mut mic_fillers: Vec<WordStat> = snap
        .mic_filler_counts
        .into_iter()
        .filter(|(word, _)| !state.removed.is_word_removed(word))
        .map(|(word, count)| WordStat { word, count })
        .collect();
    mic_fillers.sort_by(|a, b| b.count.cmp(&a.count).then_with(|| a.word.cmp(&b.word)));
    let mic_filler: u64 = mic_fillers.iter().map(|w| w.count).sum();

    // BTreeMap iterates keys in order, and "YYYY-MM-DD" sorts chronologically.
    let days: Vec<DayStat> = snap
        .mic_days
        .into_iter()
        .map(|(date, d)| DayStat {
            date,
            mic_words: d.mic_words,
            mic_filler: d.mic_filler,
        })
        .collect();

    HistoryDto {
        total_words,
        unique_words,
        total_jargon,
        words,
        terms,
        mic_words: snap.mic_word_total,
        mic_filler,
        mic_fillers,
        days,
    }
}

/// The bundled filler-word tokens, for the History tab's "Filler words" filter.
/// Returned to the frontend so filter membership stays a pure client-side lookup
/// against the already-fetched spoken-word tallies (no extra per-word round-trip).
#[tauri::command]
pub fn get_filler_words(state: State<AppState>) -> Vec<String> {
    let mut words: Vec<String> = state.filler_words.iter().cloned().collect();
    words.sort();
    words
}

#[tauri::command]
pub fn clear_history(app: AppHandle, state: State<AppState>) {
    state.history.clear();
    let _ = app.emit_to("main", "ts://history", json!({}));
}

// ---- config -----------------------------------------------------------------

#[tauri::command]
pub fn get_config(state: State<AppState>) -> Config {
    state.config.lock().unwrap().clone()
}

/// Set a single config field by name (mirrors the hub's `_save`), persist, and
/// push live card options to the cards window.
#[tauri::command]
pub fn set_config_key(
    app: AppHandle,
    state: State<AppState>,
    key: String,
    value: serde_json::Value,
) -> Result<(), String> {
    let payload = {
        let mut cfg = state.config.lock().unwrap();
        let mut v = serde_json::to_value(&*cfg).map_err(|e| e.to_string())?;
        if let serde_json::Value::Object(ref mut map) = v {
            map.insert(key, value);
        }
        let new_cfg: Config = serde_json::from_value(v).map_err(|e| e.to_string())?;
        *cfg = new_cfg;
        cfg.save();
        json!({
            "timeout": cfg.notification_timeout,
            "maxCards": cfg.card_max,
            "position": cfg.card_position,
            "customX": cfg.card_custom_x,
            "customY": cfg.card_custom_y,
        })
    };
    let _ = app.emit_to("cards", "ts://config", payload);
    Ok(())
}

/// Enter "placement mode" on the cards window so the user can drag a sample card
/// to a spot and save it as the custom popup location (`card_position: custom`).
#[tauri::command]
pub fn begin_card_placement(app: AppHandle) {
    let _ = app.emit_to("cards", "ts://place-mode", json!({}));
}

#[derive(Serialize)]
pub struct PlacementResult {
    pub x: i32,
    pub y: i32,
}

/// Save the cards window's CURRENT position as the custom popup location.
/// Reads the position on the Rust side (no JS window-API permissions involved)
/// and persists it atomically with `card_position = "custom"`. Errors are
/// returned to the caller — never swallowed — so the placement UI can show them.
#[tauri::command]
pub fn save_card_placement(app: AppHandle, state: State<AppState>) -> Result<PlacementResult, String> {
    let win = app
        .get_webview_window("cards")
        .ok_or("cards window not found")?;
    let pos = win
        .outer_position()
        .map_err(|e| format!("could not read window position: {e}"))?;

    let payload = {
        let mut cfg = state.config.lock().unwrap();
        cfg.card_custom_x = pos.x;
        cfg.card_custom_y = pos.y;
        cfg.card_position = "custom".into();
        cfg.save();
        json!({
            "timeout": cfg.notification_timeout,
            "maxCards": cfg.card_max,
            "position": cfg.card_position,
            "customX": cfg.card_custom_x,
            "customY": cfg.card_custom_y,
        })
    };
    // Notify BOTH windows: cards re-anchors, the Settings page refetches so the
    // "Saved at x, y" hint reflects reality instead of staying stale.
    let _ = app.emit_to("cards", "ts://config", payload.clone());
    let _ = app.emit_to("main", "ts://config", payload);
    Ok(PlacementResult { x: pos.x, y: pos.y })
}

// ---- word/term deletion (user-invoked, the "not jargon" overlay) -------------

/// Permanently delete a dictionary term for this user: never matched, carded,
/// listed or tallied again, and its existing history counts are purged.
/// The UI double-confirms before calling this.
#[tauri::command]
pub fn remove_term(app: AppHandle, state: State<AppState>, id: String) {
    state.removed.remove_term(&id);
    state.history.remove_term(&id);
    // Yank any live card for it and refresh both the library and history views.
    let _ = app.emit_to("cards", "ts://card-remove", json!({ "id": id }));
    let _ = app.emit_to("main", "ts://refresh", json!({}));
    let _ = app.emit_to("main", "ts://history", json!({}));
}

/// Permanently delete a spoken word for this user: its tally is purged and the
/// word is never counted again. The UI double-confirms before calling this.
#[tauri::command]
pub fn remove_word(app: AppHandle, state: State<AppState>, word: String) {
    // Normalize to the same token form the tallies use.
    let tok = crate::dictionary::tokenize(&word)
        .into_iter()
        .next()
        .unwrap_or_else(|| word.to_lowercase());
    state.removed.remove_word(&tok);
    state.history.remove_word(&tok);
    let _ = app.emit_to("main", "ts://history", json!({}));
}

// ---- hotkeys ------------------------------------------------------------------

/// Read a hotkey field by its config key name.
fn hotkey_of(cfg: &Config, key: &str) -> Option<String> {
    match key {
        "hotkey_explain_selection" => Some(cfg.hotkey_explain_selection.clone()),
        "hotkey_mark_last_learned" => Some(cfg.hotkey_mark_last_learned.clone()),
        "hotkey_toggle_listening" => Some(cfg.hotkey_toggle_listening.clone()),
        "hotkey_dictate" => Some(cfg.hotkey_dictate.clone()),
        _ => None,
    }
}

/// Rebind a global hotkey. Validates and registers the new combo BEFORE saving:
/// on a bad/unavailable combo the old binding is restored and an error returned,
/// so the user is never left with a dead hotkey. An EMPTY combo unbinds the
/// action entirely — nothing registered, nothing listening for it.
#[tauri::command]
pub fn set_hotkey(
    app: AppHandle,
    state: State<AppState>,
    key: String,
    combo: String,
) -> Result<(), String> {
    use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut};

    let combo = combo.trim().to_lowercase();

    let (old, conflicts) = {
        let cfg = state.config.lock().unwrap();
        let old = hotkey_of(&cfg, &key).ok_or_else(|| format!("unknown hotkey \"{key}\""))?;
        let mut others = vec![
            ("Explain selection", cfg.hotkey_explain_selection.clone()),
            ("Mark last learned", cfg.hotkey_mark_last_learned.clone()),
            ("Toggle listening", cfg.hotkey_toggle_listening.clone()),
            ("Dictate", cfg.hotkey_dictate.clone()),
        ];
        // Unbound entries can't conflict; nor can the binding being replaced.
        others.retain(|(_, c)| !c.is_empty() && c.to_lowercase() != old.to_lowercase());
        (old, others)
    };

    let gs = app.global_shortcut();

    if combo.is_empty() {
        // Unbind: release the old registration and save the empty binding.
        if let Ok(old_sc) = old.parse::<Shortcut>() {
            let _ = gs.unregister(old_sc);
        }
    } else {
        let new_sc: Shortcut = combo
            .parse()
            .map_err(|_| format!("\"{combo}\" is not a usable shortcut"))?;
        if let Some((label, _)) = conflicts.iter().find(|(_, c)| c.to_lowercase() == combo) {
            return Err(format!("\"{combo}\" is already used by {label}"));
        }
        if let Ok(old_sc) = old.parse::<Shortcut>() {
            let _ = gs.unregister(old_sc);
        }
        if let Err(e) = gs.register(new_sc) {
            // Roll back so the previous binding keeps working.
            if let Ok(old_sc) = old.parse::<Shortcut>() {
                let _ = gs.register(old_sc);
            }
            return Err(format!("could not register \"{combo}\": {e}"));
        }
    }

    let payload = {
        let mut cfg = state.config.lock().unwrap();
        match key.as_str() {
            "hotkey_explain_selection" => cfg.hotkey_explain_selection = combo,
            "hotkey_mark_last_learned" => cfg.hotkey_mark_last_learned = combo,
            "hotkey_toggle_listening" => cfg.hotkey_toggle_listening = combo,
            "hotkey_dictate" => cfg.hotkey_dictate = combo,
            _ => unreachable!(),
        }
        cfg.save();
        json!({})
    };
    let _ = app.emit_to("main", "ts://config", payload);
    Ok(())
}

/// Restore a hotkey to this build's default combo and return it.
#[tauri::command]
pub fn reset_hotkey(
    app: AppHandle,
    state: State<AppState>,
    key: String,
) -> Result<String, String> {
    let default = hotkey_of(&Config::default(), &key)
        .ok_or_else(|| format!("unknown hotkey \"{key}\""))?;
    set_hotkey(app, state, key, default.clone())?;
    Ok(default)
}

/// Dictate-hotkey events, dispatched by mode:
/// - "toggle": press starts, next press stops (releases ignored). Key
///   autorepeat can deliver a burst of presses while held, so presses within a
///   short window of the last transition are ignored.
/// - "hold": press starts, release stops (push-to-talk).
///
/// The actual start/stop is heavyweight (may spawn the sidecar, pastes on
/// stop), so it runs off the shortcut handler's thread.
pub fn run_dictate_event(app: AppHandle, pressed: bool) {
    use std::sync::Mutex;
    use std::time::{Duration, Instant};
    static LAST_TOGGLE: Mutex<Option<Instant>> = Mutex::new(None);

    let hold = {
        let state = app.state::<AppState>();
        let mode = state.config.lock().unwrap().dictate_mode.clone();
        mode == "hold"
    };
    std::thread::spawn(move || {
        let state = app.state::<AppState>();
        // A failed start must be VISIBLE — a hotkey user gets no console. The
        // cards overlay shows the error where the speaking badge would be.
        let report = |e: String| {
            eprintln!("[termscope] dictate hotkey: {e}");
            let payload = json!({ "active": false, "error": e });
            let _ = app.emit_to("dictate", "ts://dictate", payload.clone());
            let _ = app.emit_to("main", "ts://dictate", payload);
        };
        if hold {
            if pressed && !state.audio.is_dictating() {
                if let Err(e) = state.audio.dictate_start(&app) {
                    report(e);
                }
            } else if !pressed && state.audio.is_dictating() {
                state.audio.dictate_stop(&app);
            }
            return;
        }
        if !pressed {
            return; // toggle mode acts on presses only
        }
        {
            let mut last = LAST_TOGGLE.lock().unwrap();
            if last.is_some_and(|t| t.elapsed() < Duration::from_millis(500)) {
                return; // autorepeat burst — not a deliberate second press
            }
            *last = Some(Instant::now());
        }
        if state.audio.is_dictating() {
            state.audio.dictate_stop(&app);
        } else if let Err(e) = state.audio.dictate_start(&app) {
            report(e);
        }
    });
}

/// Worker for the toggle-listening global hotkey.
pub fn run_toggle_listening(app: AppHandle) {
    let state = app.state::<AppState>();
    if state.audio.is_listening() {
        state.audio.stop();
        let _ = app.emit_to("main", "ts://audio-status", state.audio.status());
    } else if let Err(e) = state.audio.start(&app) {
        eprintln!("[termscope] toggle-listening hotkey: {e}");
    }
}

// ---- knowledge mutations ----------------------------------------------------

#[tauri::command]
pub fn mark_learned(app: AppHandle, state: State<AppState>, id: String) {
    state.knowledge.mark_learned(&id);
    let _ = app.emit_to("main", "ts://refresh", json!({}));
}

#[tauri::command]
pub fn unlearn(app: AppHandle, state: State<AppState>, id: String) {
    state.knowledge.unlearn(&id);
    let _ = app.emit_to("main", "ts://refresh", json!({}));
}

#[tauri::command]
pub fn reset_progress(app: AppHandle, state: State<AppState>) {
    state.knowledge.reset();
    let _ = app.emit_to("main", "ts://refresh", json!({}));
}

#[tauri::command]
pub fn export_progress(state: State<AppState>, path: String) -> Result<(), String> {
    let mut ids: Vec<String> = state.knowledge.learned_ids().into_iter().collect();
    ids.sort();
    let items: Vec<_> = ids
        .iter()
        .map(|id| {
            let term = state.entry(id).map(|e| e.term.clone()).unwrap_or_else(|| id.clone());
            json!({ "id": id, "term": term })
        })
        .collect();
    let payload = json!({ "learned_count": ids.len(), "learned": items });
    let text = serde_json::to_string_pretty(&payload).map_err(|e| e.to_string())?;
    std::fs::write(&path, text).map_err(|e| e.to_string())
}

// ---- selection / cards ------------------------------------------------------

#[tauri::command]
pub fn explain_selection(app: AppHandle) {
    run_explain_selection(app);
}

#[tauri::command]
pub fn mark_last_learned(app: AppHandle) {
    run_mark_last_learned(app);
}

/// Capture highlighted text, scan it, and surface unknown terms as cards.
/// Runs on its own thread because selection capture sleeps for the clipboard.
pub fn run_explain_selection(app: AppHandle) {
    std::thread::spawn(move || {
        let text = crate::selection::capture_selection();
        if text.trim().is_empty() {
            return;
        }
        let state = app.state::<AppState>();

        // History: tally every jargon term in the selection (what the user looked up),
        // independent of whether it's learned, so the frequency counts are complete.
        // User-deleted terms are excluded everywhere.
        let all = state.matcher.find(&text, &std::collections::HashSet::new());
        if state.config.lock().unwrap().track_history {
            let ids: Vec<String> = all
                .iter()
                .map(|m| state.entries[m.entry_index].id.clone())
                .filter(|id| !state.removed.is_term_removed(id))
                .collect();
            state.history.record_selection(&ids);
            let _ = app.emit_to("main", "ts://history", json!({}));
        }

        let learned = state.knowledge.learned_ids();
        let matches = state.matcher.find(&text, &learned);
        let (timeout, max_cards, position, custom_x, custom_y) = {
            let cfg = state.config.lock().unwrap();
            (
                cfg.notification_timeout,
                cfg.card_max,
                cfg.card_position.clone(),
                cfg.card_custom_x,
                cfg.card_custom_y,
            )
        };
        for m in matches.into_iter().take(5) {
            let entry = &state.entries[m.entry_index];
            if state.removed.is_term_removed(&entry.id) {
                continue; // user deleted this term — never card it
            }
            if state.knowledge.is_learned(&entry.id) {
                continue;
            }
            state.knowledge.record_shown(&entry.id);
            state.notifier.lock().unwrap().push_recent(entry.id.clone());
            let payload = json!({
                "entry": entry,
                "timeout": timeout,
                "maxCards": max_cards,
                "position": position,
                "customX": custom_x,
                "customY": custom_y,
            });
            let _ = app.emit_to("cards", "ts://card", payload);
        }
    });
}

/// Retire the most-recently-shown term that isn't already learned.
pub fn run_mark_last_learned(app: AppHandle) {
    let state = app.state::<AppState>();
    let id_opt = {
        let mut n = state.notifier.lock().unwrap();
        let mut found = None;
        while let Some(id) = n.pop_recent() {
            if !state.knowledge.is_learned(&id) {
                found = Some(id);
                break;
            }
        }
        found
    };
    if let Some(id) = id_opt {
        state.knowledge.mark_learned(&id);
        let _ = app.emit_to("cards", "ts://card-remove", json!({ "id": id }));
        let _ = app.emit_to("main", "ts://refresh", json!({}));
    }
}

// ---- window / system --------------------------------------------------------

#[tauri::command]
pub fn open_url(app: AppHandle, url: String) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    app.opener().open_url(url, None::<&str>).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn focus_library_term(app: AppHandle, id: String) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
    let _ = app.emit_to("main", "ts://open-term", json!({ "id": id }));
}

#[tauri::command]
pub fn show_main(app: AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

#[tauri::command]
pub fn quit_app(app: AppHandle) {
    app.exit(0);
}

#[tauri::command]
pub fn startup_enabled() -> bool {
    crate::startup::is_enabled()
}

#[tauri::command]
pub fn set_startup(enabled: bool) -> Result<(), String> {
    crate::startup::set_enabled(enabled)
}

// ---- audio listening --------------------------------------------------------

#[tauri::command]
pub fn is_listening(state: State<AppState>) -> bool {
    state.audio.is_listening()
}

#[tauri::command]
pub fn audio_status(state: State<AppState>) -> crate::audio::AudioStatus {
    state.audio.status()
}

#[tauri::command]
pub fn toggle_listening(app: AppHandle, state: State<AppState>) -> Result<bool, String> {
    if state.audio.is_listening() {
        state.audio.stop();
        Ok(false)
    } else {
        state.audio.start(&app)?;
        Ok(true)
    }
}
