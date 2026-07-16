//! Spoken-word & jargon history, persisted to `history.json` in the app data dir.
//!
//! Records cumulative, **orderless** tallies — every spoken word ever heard,
//! and every time each jargon term was detected. All are plain frequency maps
//! (word/id -> count); nothing about *in what order* words were spoken is kept.
//! That's deliberate: a conversation is a sequence, so we store only the
//! bag-of-words frequencies and never a timeline. Past conversations cannot be
//! reconstructed from `history.json` — there is no order to read back out.
//!
//! v3 adds microphone-only filler tracking for the filler-reduction goals:
//! per-filler-word counts (mic only), a mic word total, and **per-day totals**
//! (words + filler heard via the mic that calendar day). The day buckets are the
//! one time-shaped datum we keep, and they are aggregates only — two counters per
//! day, no words, no order — so they chart progress without recording speech.

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::PathBuf;
use std::sync::Mutex;

use crate::dictionary::tokenize;

/// One calendar day's microphone totals — two counters, nothing else.
#[derive(Default, Clone, Serialize, Deserialize)]
pub struct DayTally {
    /// Words heard via the microphone that day.
    #[serde(default)]
    pub mic_words: u64,
    /// How many of them were filler words.
    #[serde(default)]
    pub mic_filler: u64,
}

#[derive(Default, Serialize, Deserialize)]
struct Stored {
    /// Spoken word (lowercased alphanumeric token) -> times heard (all sources).
    #[serde(default)]
    word_counts: HashMap<String, u64>,
    /// Jargon term id -> times detected.
    #[serde(default)]
    term_counts: HashMap<String, u64>,
    /// Filler word -> times heard **via the microphone only** (never system
    /// audio — the goals measure what the user says, not what they play).
    #[serde(default)]
    mic_filler_counts: HashMap<String, u64>,
    /// Total words heard via the microphone (denominator for the filler rate).
    #[serde(default)]
    mic_word_total: u64,
    /// "YYYY-MM-DD" (local) -> that day's mic totals, for the goal trend chart.
    #[serde(default)]
    mic_days: BTreeMap<String, DayTally>,
}

pub struct History {
    path: PathBuf,
    /// False when the on-disk file was unreadable and couldn't be backed up, so we
    /// must not overwrite it (see `paths::load_json_store`). New history isn't
    /// persisted in that state rather than destroying data we couldn't recover.
    savable: bool,
    inner: Mutex<Stored>,
}

/// A point-in-time copy used to build the frontend DTO without holding the lock.
pub struct Snapshot {
    pub word_counts: HashMap<String, u64>,
    pub term_counts: HashMap<String, u64>,
    pub mic_filler_counts: HashMap<String, u64>,
    pub mic_word_total: u64,
    pub mic_days: BTreeMap<String, DayTally>,
}

impl History {
    pub fn new(path: PathBuf) -> Self {
        // Loaded through the shared safe loader: a missing file is a fresh start, a
        // parseable file loads as-is, and an UNREADABLE file (corruption or a future
        // schema) is preserved as a backup rather than silently wiped. A pre-orderless
        // `history.json` still carrying a legacy `log` array parses fine (serde ignores
        // unknown fields) and drops the log on the next save. User data is never
        // deleted on load — only the History-tab "Clear" removes it.
        let loaded = crate::paths::load_json_store::<Stored>(&path);
        Self { path, savable: loaded.savable, inner: Mutex::new(loaded.value) }
    }

    fn save(&self, stored: &Stored) {
        if !self.savable {
            eprintln!(
                "[termscope] WARN: not persisting history — {} was unreadable and left untouched to avoid destroying unrecovered data",
                self.path.display()
            );
            return;
        }
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
    /// Words in `blocked` (user-deleted, see `removed.rs`) are never tallied.
    ///
    /// When `mic` is true (the utterance came from the microphone, i.e. the user
    /// speaking — never system audio), the mic-only filler tallies and the day's
    /// aggregate counters are updated too, feeding the filler-reduction goals.
    pub fn record_audio(
        &self,
        text: &str,
        jargon_ids: &[String],
        blocked: &HashSet<String>,
        mic: bool,
        filler: &HashSet<String>,
    ) {
        let mut g = self.inner.lock().unwrap();
        let mut mic_words = 0u64;
        let mut mic_filler = 0u64;
        for tok in tokenize(text) {
            if blocked.contains(&tok) {
                continue;
            }
            if mic {
                mic_words += 1;
                if filler.contains(&tok) {
                    mic_filler += 1;
                    *g.mic_filler_counts.entry(tok.clone()).or_insert(0) += 1;
                }
            }
            *g.word_counts.entry(tok).or_insert(0) += 1;
        }
        if mic_words > 0 {
            g.mic_word_total += mic_words;
            let day = g.mic_days.entry(local_date()).or_default();
            day.mic_words += mic_words;
            day.mic_filler += mic_filler;
        }
        for id in jargon_ids {
            *g.term_counts.entry(id.clone()).or_insert(0) += 1;
        }
        self.save(&g);
    }

    /// Purge one term's tally (user-invoked deletion via "remove term").
    pub fn remove_term(&self, id: &str) {
        let mut g = self.inner.lock().unwrap();
        if g.term_counts.remove(id).is_some() {
            self.save(&g);
        }
    }

    /// Purge one spoken word's tally (user-invoked deletion via "remove word").
    /// The per-word mic filler tally goes with it; the day aggregates stay — they
    /// are two anonymous counters per day and name no words.
    pub fn remove_word(&self, word: &str) {
        let mut g = self.inner.lock().unwrap();
        let a = g.word_counts.remove(word).is_some();
        let b = g.mic_filler_counts.remove(word).is_some();
        if a || b {
            self.save(&g);
        }
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
            mic_filler_counts: g.mic_filler_counts.clone(),
            mic_word_total: g.mic_word_total,
            mic_days: g.mic_days.clone(),
        }
    }

    /// Wipe all recorded history (user-invoked from the History tab).
    pub fn clear(&self) {
        let mut g = self.inner.lock().unwrap();
        g.word_counts.clear();
        g.term_counts.clear();
        g.mic_filler_counts.clear();
        g.mic_word_total = 0;
        g.mic_days.clear();
        self.save(&g);
    }
}

/// Local calendar date as "YYYY-MM-DD" — the key for the per-day aggregates.
fn local_date() -> String {
    chrono::Local::now().format("%Y-%m-%d").to_string()
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
        h.record_audio("the API talks to the API", &["334".into()], &HashSet::new(), false, &HashSet::new());
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
        h.record_audio("data data data", &["42".into()], &HashSet::new(), false, &HashSet::new());
        let s = h.snapshot();
        assert_eq!(s.term_counts.get("42"), Some(&151)); // cumulative, unbounded
        assert_eq!(s.word_counts.get("data"), Some(&3));
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn removed_words_are_purged_and_never_retallied() {
        let (h, path) = fresh("removed");
        h.record_audio("um the api um", &[], &HashSet::new(), false, &HashSet::new());
        assert_eq!(h.snapshot().word_counts.get("um"), Some(&2));

        h.remove_word("um"); // user deletes the word → tally purged
        assert_eq!(h.snapshot().word_counts.get("um"), None);
        assert_eq!(h.snapshot().word_counts.get("api"), Some(&1)); // others kept

        let blocked: HashSet<String> = ["um".to_string()].into();
        h.record_audio("um again um", &[], &blocked, false, &HashSet::new()); // spoken again → still not tallied
        assert_eq!(h.snapshot().word_counts.get("um"), None);
        assert_eq!(h.snapshot().word_counts.get("again"), Some(&1));

        h.record_selection(&["334".into()]);
        h.remove_term("334"); // deleted term's tally purged too
        assert_eq!(h.snapshot().term_counts.get("334"), None);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn mic_utterances_feed_filler_tallies_and_day_totals() {
        let (h, path) = fresh("mic");
        let filler: HashSet<String> = ["um".to_string(), "like".to_string()].into();

        // System audio: words tallied as always, but NO mic/filler/day tracking.
        h.record_audio("um the movie was like great", &[], &HashSet::new(), false, &filler);
        let s = h.snapshot();
        assert_eq!(s.word_counts.get("um"), Some(&1));
        assert_eq!(s.mic_word_total, 0);
        assert!(s.mic_filler_counts.is_empty());
        assert!(s.mic_days.is_empty());

        // Microphone: mic totals, per-filler counts, and today's bucket update.
        h.record_audio("um so like I um agree", &[], &HashSet::new(), true, &filler);
        let s = h.snapshot();
        assert_eq!(s.mic_word_total, 6);
        assert_eq!(s.mic_filler_counts.get("um"), Some(&2));
        assert_eq!(s.mic_filler_counts.get("like"), Some(&1));
        assert_eq!(s.mic_days.len(), 1); // one bucket: today
        let day = s.mic_days.values().next().unwrap();
        assert_eq!(day.mic_words, 6);
        assert_eq!(day.mic_filler, 3);

        // Same-day utterances accumulate into the same bucket.
        h.record_audio("um right", &[], &HashSet::new(), true, &filler);
        let s = h.snapshot();
        assert_eq!(s.mic_days.len(), 1);
        assert_eq!(s.mic_days.values().next().unwrap().mic_words, 8);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn removed_word_purges_its_mic_filler_tally() {
        let (h, path) = fresh("mic_removed");
        let filler: HashSet<String> = ["um".to_string()].into();
        h.record_audio("um um", &[], &HashSet::new(), true, &filler);
        assert_eq!(h.snapshot().mic_filler_counts.get("um"), Some(&2));

        h.remove_word("um");
        let s = h.snapshot();
        assert_eq!(s.mic_filler_counts.get("um"), None); // per-word tally purged
        assert_eq!(s.mic_days.values().next().unwrap().mic_filler, 2); // day totals are anonymous aggregates
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn v2_history_file_gains_mic_fields_without_losing_counts() {
        // A history.json written by TermScope 2.x (no mic fields) must load with
        // every existing count intact — additive schema, no data loss.
        let path = std::env::temp_dir().join("termscope_test_history_v2.json");
        std::fs::write(&path, r#"{"word_counts":{"api":3},"term_counts":{"334":2}}"#).unwrap();
        let s = History::new(path.clone()).snapshot();
        assert_eq!(s.word_counts.get("api"), Some(&3));
        assert_eq!(s.term_counts.get("334"), Some(&2));
        assert_eq!(s.mic_word_total, 0);
        assert!(s.mic_days.is_empty());
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn clear_wipes_everything() {
        let (h, path) = fresh("clear");
        let filler: HashSet<String> = ["um".to_string()].into();
        h.record_audio("API and um SDK", &["334".into(), "335".into()], &HashSet::new(), true, &filler);
        h.clear();
        let s = h.snapshot();
        assert!(s.word_counts.is_empty());
        assert!(s.term_counts.is_empty());
        assert!(s.mic_filler_counts.is_empty());
        assert_eq!(s.mic_word_total, 0);
        assert!(s.mic_days.is_empty());
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn persists_across_reload() {
        let path = std::env::temp_dir().join("termscope_test_history_reload.json");
        let _ = std::fs::remove_file(&path);
        {
            let h = History::new(path.clone());
            h.record_audio("vector database", &["999".into()], &HashSet::new(), false, &HashSet::new());
        }
        let s = History::new(path.clone()).snapshot(); // fresh instance, same file
        assert_eq!(s.term_counts.get("999"), Some(&1));
        assert_eq!(s.word_counts.get("vector"), Some(&1));
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn unreadable_file_is_preserved_never_wiped() {
        // A history.json this build can't parse (corruption, a partial write, or a
        // file from a future schema) must NOT be silently reset and overwritten —
        // the user's counts are their data and only they may delete them.
        let path = std::env::temp_dir().join("termscope_test_history_corrupt.json");
        let prefix = "termscope_test_history_corrupt.corrupt-";
        let clear_backups = || {
            for e in std::fs::read_dir(std::env::temp_dir()).unwrap().flatten() {
                if e.file_name().to_string_lossy().starts_with(prefix) {
                    let _ = std::fs::remove_file(e.path());
                }
            }
        };
        let _ = std::fs::remove_file(&path);
        clear_backups();

        std::fs::write(&path, "{ not valid json for Stored ]").unwrap();
        let h = History::new(path.clone());
        assert!(h.snapshot().word_counts.is_empty()); // couldn't parse → starts empty

        // The original bytes were preserved as a sibling backup, not deleted.
        let backups: Vec<_> = std::fs::read_dir(std::env::temp_dir())
            .unwrap()
            .flatten()
            .filter(|e| e.file_name().to_string_lossy().starts_with(prefix))
            .collect();
        assert_eq!(backups.len(), 1, "corrupt history must be preserved as a backup");

        // New activity now persists cleanly to the freed canonical path.
        h.record_audio("api", &[], &HashSet::new(), false, &HashSet::new());
        assert_eq!(
            History::new(path.clone()).snapshot().word_counts.get("api"),
            Some(&1)
        );

        let _ = std::fs::remove_file(&path);
        clear_backups();
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
