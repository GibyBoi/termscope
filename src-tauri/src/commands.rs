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
    state.entries.clone()
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

#[derive(Serialize)]
pub struct LogStat {
    pub id: String,
    pub term: String,
    pub category: String,
    pub definition: String,
    pub source: String,
    pub ts: f64,
    pub learned: bool,
}

#[derive(Serialize)]
pub struct HistoryDto {
    pub total_words: u64,
    pub unique_words: usize,
    pub total_jargon: u64,
    pub words: Vec<WordStat>, // every spoken word, sorted by count desc
    pub terms: Vec<TermStat>, // jargon detected at least once, sorted by count desc
    pub log: Vec<LogStat>,    // most-recent jargon occurrences, newest first
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
        .map(|(word, count)| WordStat { word, count })
        .collect();
    words.sort_by(|a, b| b.count.cmp(&a.count).then_with(|| a.word.cmp(&b.word)));

    // Only terms still present in the dictionary can be displayed; drop any whose
    // id was retired (delete data we can no longer show).
    let mut terms: Vec<TermStat> = snap
        .term_counts
        .iter()
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

    let log: Vec<LogStat> = snap
        .log
        .into_iter()
        .filter_map(|le| {
            state.entry(&le.id).map(|e| LogStat {
                id: le.id.clone(),
                term: e.term.clone(),
                category: e.category.clone(),
                definition: e.definition.clone(),
                source: le.source,
                ts: le.ts,
                learned: state.knowledge.is_learned(&le.id),
            })
        })
        .collect();

    HistoryDto {
        total_words,
        unique_words,
        total_jargon,
        words,
        terms,
        log,
    }
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
        })
    };
    let _ = app.emit_to("cards", "ts://config", payload);
    Ok(())
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

        // History: log every jargon term in the selection (what the user looked up),
        // independent of whether it's learned, so the chronological log is complete.
        let all = state.matcher.find(&text, &std::collections::HashSet::new());
        if state.config.lock().unwrap().track_history {
            let ids: Vec<String> = all
                .iter()
                .map(|m| state.entries[m.entry_index].id.clone())
                .collect();
            state.history.record_selection(&ids);
            let _ = app.emit_to("main", "ts://history", json!({}));
        }

        let learned = state.knowledge.learned_ids();
        let matches = state.matcher.find(&text, &learned);
        let (timeout, max_cards, position) = {
            let cfg = state.config.lock().unwrap();
            (cfg.notification_timeout, cfg.card_max, cfg.card_position.clone())
        };
        for m in matches.into_iter().take(5) {
            let entry = &state.entries[m.entry_index];
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
