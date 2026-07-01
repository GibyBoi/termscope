//! Spoken-word & jargon history, persisted to `%APPDATA%\TermScope\history.json`.
//!
//! Records two cumulative, **orderless** tallies — every spoken word ever heard,
//! and every time each jargon term was detected. Both are plain frequency maps
//! (word/id -> count); nothing about *when* or *in what order* words were spoken
//! is kept. That's deliberate: a conversation is a sequence, so we store only the
//! bag-of-words frequencies and never a timeline. Past conversations cannot be
//! reconstructed from `history.json` — there is no order to read back out.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Mutex;

use crate::dictionary::tokenize;

#[derive(Default, Serialize, Deserialize)]
struct Stored {
    /// Spoken word (lowercased alphanumeric token) -> times heard.
    #[serde(default)]
    word_counts: HashMap<String, u64>,
    /// Jargon term id -> times detected.
    #[serde(default)]
    term_counts: HashMap<String, u64>,
}

pub struct History {
    path: PathBuf,
    inner: Mutex<Stored>,
}

/// A point-in-time copy used to build the frontend DTO without holding the lock.
pub struct Snapshot {
    pub word_counts: HashMap<String, u64>,
    pub term_counts: HashMap<String, u64>,
}

impl History {
    pub fn new(path: PathBuf) -> Self {
        // A pre-orderless `history.json` may still carry a legacy `log` array; serde
        // ignores unknown fields, so old files load fine and the log is dropped on
        // the next save (never re-serialized).
        let inner = std::fs::read_to_string(&path)
            .ok()
            .and_then(|t| serde_json::from_str::<Stored>(&t).ok())
            .unwrap_or_default();
        Self { path, inner: Mutex::new(inner) }
    }

    fn save(&self, stored: &Stored) {
        if let Ok(text) = serde_json::to_string(stored) {
            let tmp = self.path.with_extension("tmp");
            if std::fs::write(&tmp, text).is_ok() {
                let _ = std::fs::rename(&tmp, &self.path);
            }
        }
    }

    /// Record a transcribed utterance: tally every spoken word, then tally each
    /// jargon term detected in it. One disk write for the whole utterance. Only
    /// counts are updated — the utterance text and its word order are discarded.
    ///
    /// `jargon_ids` are ALL terms found (independent of learned/cooldown) — the
    /// history reflects what was actually said, not what we chose to pop a card for.
    pub fn record_audio(&self, text: &str, jargon_ids: &[String]) {
        let mut g = self.inner.lock().unwrap();
        for tok in tokenize(text) {
            *g.word_counts.entry(tok).or_insert(0) += 1;
        }
        for id in jargon_ids {
            *g.term_counts.entry(id.clone()).or_insert(0) += 1;
        }
        self.save(&g);
    }

    /// Record jargon surfaced from a highlighted text selection. No word tally —
    /// selected text wasn't "spoken", so it doesn't feed the spoken-word counts.
    pub fn record_selection(&self, jargon_ids: &[String]) {
        if jargon_ids.is_empty() {
            return;
        }
        let mut g = self.inner.lock().unwrap();
        for id in jargon_ids {
            *g.term_counts.entry(id.clone()).or_insert(0) += 1;
        }
        self.save(&g);
    }

    pub fn snapshot(&self) -> Snapshot {
        let g = self.inner.lock().unwrap();
        Snapshot {
            word_counts: g.word_counts.clone(),
            term_counts: g.term_counts.clone(),
        }
    }

    /// Wipe all recorded history (user-invoked from the History tab).
    pub fn clear(&self) {
        let mut g = self.inner.lock().unwrap();
        g.word_counts.clear();
        g.term_counts.clear();
        self.save(&g);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A History backed by a unique, freshly-removed temp file.
    fn fresh(name: &str) -> (History, PathBuf) {
        let path = std::env::temp_dir().join(format!("termscope_test_history_{name}.json"));
        let _ = std::fs::remove_file(&path);
        (History::new(path.clone()), path)
    }

    #[test]
    fn tallies_spoken_words_and_jargon() {
        let (h, path) = fresh("words");
        h.record_audio("the API talks to the API", &["334".into()]);
        let s = h.snapshot();
        assert_eq!(s.word_counts.get("the"), Some(&2)); // every spoken word counted
        assert_eq!(s.word_counts.get("api"), Some(&2));
        assert_eq!(s.word_counts.get("talks"), Some(&1));
        assert_eq!(s.term_counts.get("334"), Some(&1)); // jargon tallied once
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn selection_tallies_jargon_without_word_tally() {
        let (h, path) = fresh("selection");
        h.record_selection(&["1".into(), "2".into()]);
        let s = h.snapshot();
        assert!(s.word_counts.is_empty()); // selected text isn't "spoken"
        assert_eq!(s.term_counts.get("1"), Some(&1));
        assert_eq!(s.term_counts.get("2"), Some(&1));
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn counts_accumulate_across_calls() {
        let (h, path) = fresh("accumulate");
        for _ in 0..150 {
            h.record_selection(&["42".into()]);
        }
        h.record_audio("data data data", &["42".into()]);
        let s = h.snapshot();
        assert_eq!(s.term_counts.get("42"), Some(&151)); // cumulative, unbounded
        assert_eq!(s.word_counts.get("data"), Some(&3));
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn clear_wipes_everything() {
        let (h, path) = fresh("clear");
        h.record_audio("API and SDK", &["334".into(), "335".into()]);
        h.clear();
        let s = h.snapshot();
        assert!(s.word_counts.is_empty());
        assert!(s.term_counts.is_empty());
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn persists_across_reload() {
        let path = std::env::temp_dir().join("termscope_test_history_reload.json");
        let _ = std::fs::remove_file(&path);
        {
            let h = History::new(path.clone());
            h.record_audio("vector database", &["999".into()]);
        }
        let s = History::new(path.clone()).snapshot(); // fresh instance, same file
        assert_eq!(s.term_counts.get("999"), Some(&1));
        assert_eq!(s.word_counts.get("vector"), Some(&1));
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn legacy_log_field_is_ignored_on_load() {
        // Files written by the old timeline-keeping version still load; the `log`
        // array is silently discarded so no ordered data survives.
        let path = std::env::temp_dir().join("termscope_test_history_legacy.json");
        let legacy = r#"{"word_counts":{"api":3},"term_counts":{"334":2},
            "log":[{"id":"334","ts":1700000000.0,"source":"audio"}]}"#;
        std::fs::write(&path, legacy).unwrap();
        let s = History::new(path.clone()).snapshot();
        assert_eq!(s.word_counts.get("api"), Some(&3));
        assert_eq!(s.term_counts.get("334"), Some(&2));
        let _ = std::fs::remove_file(&path);
    }
}
