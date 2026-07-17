//! Shared application state: the loaded dictionary, matcher, library, knowledge
//! store, config and notifier — the Rust analogue of `TermScopeApp` in
//! `legacy/src/termscope/app.py`.

use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::Mutex;

use tauri::{AppHandle, Manager};

use crate::audio::Audio;
use crate::config::Config;
use crate::corrections::Corrections;
use crate::dictionary::{self, TermEntry};
use crate::history::History;
use crate::knowledge::Knowledge;
use crate::library::Library;
use crate::matcher::Matcher;
use crate::notifier::Notifier;
use crate::paths;
use crate::removed::Removed;

pub struct AppState {
    pub config: Mutex<Config>,
    pub knowledge: Knowledge,
    pub history: History,
    pub entries: Vec<TermEntry>,
    pub entries_by_id: HashMap<String, usize>,
    pub matcher: Matcher,
    pub library: Library,
    pub notifier: Mutex<Notifier>,
    pub audio: Audio,
    /// Normalized filler-word tokens for the History tab's "Filler words" filter.
    pub filler_words: HashSet<String>,
    /// User-deleted terms/words (the "not jargon" overlay) — see `removed.rs`.
    pub removed: Removed,
    /// Dictation "hears X, write Y" dictionary — see `corrections.rs`.
    pub corrections: Corrections,
}

impl AppState {
    pub fn init(app: &AppHandle) -> Self {
        let config = Config::load();
        let data_dir = resolve_data_dir(app);

        let enabled: HashSet<String> = config.enabled_categories.iter().cloned().collect();
        let files = dictionary::bundled_term_files(&data_dir);
        let entries = dictionary::load_entries(&files, &enabled);
        let entries_by_id = entries
            .iter()
            .enumerate()
            .map(|(i, e)| (e.id.clone(), i))
            .collect();
        let matcher = Matcher::new(&entries);
        let filler_words = dictionary::load_filler_words(&data_dir);
        let library = Library::load(&data_dir.join("library.json"));
        let knowledge = Knowledge::new(paths::knowledge_path());
        let history = History::new(paths::history_path());
        let removed = Removed::new(paths::removed_path());
        let corrections = Corrections::new(paths::corrections_path());

        Self {
            config: Mutex::new(config),
            knowledge,
            history,
            entries,
            entries_by_id,
            matcher,
            library,
            notifier: Mutex::new(Notifier::new()),
            audio: Audio::new(),
            filler_words,
            removed,
            corrections,
        }
    }

    pub fn entry(&self, id: &str) -> Option<&TermEntry> {
        self.entries_by_id.get(id).map(|&i| &self.entries[i])
    }
}

/// Find the bundled `data/` directory in both packaged and dev builds.
fn resolve_data_dir(app: &AppHandle) -> PathBuf {
    if let Ok(res) = app.path().resource_dir() {
        let nested = res.join("data");
        if nested.join("library.json").exists() {
            return nested;
        }
        if res.join("library.json").exists() {
            return res;
        }
    }
    // Dev fallback: the repo's data dir sits next to the src-tauri crate.
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(|p| p.join("data"))
        .unwrap_or_else(|| PathBuf::from("data"))
}
