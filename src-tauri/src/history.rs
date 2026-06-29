//! Spoken-word & jargon history, persisted to `%APPDATA%\TermScope\history.json`.
//!
//! Records two cumulative tallies — every spoken word ever heard, and every time
//! each jargon term was detected — plus a short rolling log of the most recent
//! jargon occurrences (so the History view can replay "what was just said").
//!
//! The log is hard-capped at `LOG_CAP`: the History slider tops out at 100
//! entries, so anything older can never be shown. We delete it rather than let it
//! accumulate forever (privacy — don't retain data past the point it's displayed).

use serde::{Deserialize, Serialize};
use std::collections::{HashMap, VecDeque};
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::dictionary::tokenize;

/// Most recent jargon occurrences kept on disk. Matches the History slider's max.
const LOG_CAP: usize = 100;

#[derive(Serialize, Deserialize, Clone)]
pub struct LogEntry {
    pub id: String,     // stable term id
    pub ts: f64,        // unix seconds
    pub source: String, // "audio" (spoken) | "selection" (highlighted)
}

#[derive(Default, Serialize, Deserialize)]
struct Stored {
    /// Spoken word (lowercased alphanumeric token) -> times heard.
    #[serde(default)]
    word_counts: HashMap<String, u64>,
    /// Jargon term id -> times detected.
    #[serde(default)]
    term_counts: HashMap<String, u64>,
    /// Recent jargon occurrences, newest at the back, capped at `LOG_CAP`.
    #[serde(default)]
    log: VecDeque<LogEntry>,
}

pub struct History {
    path: PathBuf,
    inner: Mutex<Stored>,
}

/// A point-in-time copy used to build the frontend DTO without holding the lock.
pub struct Snapshot {
    pub word_counts: HashMap<String, u64>,
    pub term_counts: HashMap<String, u64>,
    pub log: Vec<LogEntry>, // newest first
}

impl History {
    pub fn new(path: PathBuf) -> Self {
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

    /// Record a transcribed utterance: tally every spoken word, then log + tally
    /// each jargon term detected in it. One disk write for the whole utterance.
    ///
    /// `jargon_ids` are ALL terms found (independent of learned/cooldown) — the
    /// history reflects what was actually said, not what we chose to pop a card for.
    pub fn record_audio(&self, text: &str, jargon_ids: &[String]) {
        let mut g = self.inner.lock().unwrap();
        for tok in tokenize(text) {
            *g.word_counts.entry(tok).or_insert(0) += 1;
        }
        let ts = now_secs();
        for id in jargon_ids {
            *g.term_counts.entry(id.clone()).or_insert(0) += 1;
            g.log.push_back(LogEntry { id: id.clone(), ts, source: "audio".into() });
        }
        trim(&mut g.log);
        self.save(&g);
    }

    /// Record jargon surfaced from a highlighted text selection. No word tally —
    /// selected text wasn't "spoken", so it doesn't feed the spoken-word counts.
    pub fn record_selection(&self, jargon_ids: &[String]) {
        if jargon_ids.is_empty() {
            return;
        }
        let mut g = self.inner.lock().unwrap();
        let ts = now_secs();
        for id in jargon_ids {
            *g.term_counts.entry(id.clone()).or_insert(0) += 1;
            g.log.push_back(LogEntry { id: id.clone(), ts, source: "selection".into() });
        }
        trim(&mut g.log);
        self.save(&g);
    }

    pub fn snapshot(&self) -> Snapshot {
        let g = self.inner.lock().unwrap();
        Snapshot {
            word_counts: g.word_counts.clone(),
            term_counts: g.term_counts.clone(),
            log: g.log.iter().rev().cloned().collect(),
        }
    }

    /// Wipe all recorded history (user-invoked from the History tab).
    pub fn clear(&self) {
        let mut g = self.inner.lock().unwrap();
        g.word_counts.clear();
        g.term_counts.clear();
        g.log.clear();
        self.save(&g);
    }
}

fn trim(log: &mut VecDeque<LogEntry>) {
    while log.len() > LOG_CAP {
        log.pop_front();
    }
}

fn now_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
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
        assert_eq!(s.log.len(), 1);
        assert_eq!(s.log[0].id, "334");
        assert_eq!(s.log[0].source, "audio");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn selection_logs_jargon_without_word_tally() {
        let (h, path) = fresh("selection");
        h.record_selection(&["1".into(), "2".into()]);
        let s = h.snapshot();
        assert!(s.word_counts.is_empty()); // selected text isn't "spoken"
        assert_eq!(s.term_counts.get("1"), Some(&1));
        assert_eq!(s.log.len(), 2);
        assert_eq!(s.log[0].source, "selection");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn log_is_capped_newest_first_but_counts_are_complete() {
        let (h, path) = fresh("cap");
        for i in 0..150 {
            h.record_selection(&[i.to_string()]);
        }
        let s = h.snapshot();
        assert_eq!(s.log.len(), LOG_CAP); // never retains more than the slider can show
        assert_eq!(s.log[0].id, "149"); // newest first
        assert_eq!(s.log[LOG_CAP - 1].id, "50"); // 0..49 were trimmed
        assert_eq!(s.term_counts.len(), 150); // cumulative counts keep everything
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
        assert!(s.log.is_empty());
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
}
