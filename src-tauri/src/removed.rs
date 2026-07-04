//! Per-user deleted words & terms, persisted to `%APPDATA%\TermScope\removed.json`.
//!
//! When the user decides a dictionary term "is just a normal word" (or wants a
//! spoken word gone), deleting it here removes it everywhere: the term stops
//! being matched, carded and listed, the word is never tallied again, and the
//! existing history counts for it are purged (user-invoked deletion — the one
//! kind the storage-safety rules allow). Bundled dictionaries are read-only app
//! resources, so user deletions live in this per-user overlay and survive updates.

use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::Mutex;

#[derive(Default, Serialize, Deserialize)]
struct Stored {
    /// Dictionary term ids the user deleted ("not jargon, just a normal word").
    #[serde(default)]
    term_ids: HashSet<String>,
    /// Spoken words (normalized lowercase tokens) the user deleted from history;
    /// they are also never tallied again.
    #[serde(default)]
    words: HashSet<String>,
}

pub struct Removed {
    path: PathBuf,
    /// False when the on-disk file was unreadable and couldn't be backed up —
    /// we then refuse to overwrite it (see `paths::load_json_store`).
    savable: bool,
    inner: Mutex<Stored>,
}

impl Removed {
    pub fn new(path: PathBuf) -> Self {
        let loaded = crate::paths::load_json_store::<Stored>(&path);
        Self { path, savable: loaded.savable, inner: Mutex::new(loaded.value) }
    }

    fn save(&self, stored: &Stored) {
        if !self.savable {
            eprintln!(
                "[termscope] WARN: not persisting removed-words list — {} was unreadable and left untouched",
                self.path.display()
            );
            return;
        }
        if let Ok(text) = serde_json::to_string_pretty(stored) {
            let tmp = self.path.with_extension("tmp");
            if std::fs::write(&tmp, text).is_ok() {
                let _ = std::fs::rename(&tmp, &self.path);
            }
        }
    }

    pub fn is_term_removed(&self, id: &str) -> bool {
        self.inner.lock().unwrap().term_ids.contains(id)
    }

    pub fn is_word_removed(&self, word: &str) -> bool {
        self.inner.lock().unwrap().words.contains(word)
    }

    /// Snapshot of the deleted spoken words, for filtering a whole utterance.
    pub fn removed_words(&self) -> HashSet<String> {
        self.inner.lock().unwrap().words.clone()
    }

    pub fn remove_term(&self, id: &str) {
        let mut g = self.inner.lock().unwrap();
        if g.term_ids.insert(id.to_string()) {
            self.save(&g);
        }
    }

    pub fn remove_word(&self, word: &str) {
        let mut g = self.inner.lock().unwrap();
        if g.words.insert(word.to_string()) {
            self.save(&g);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn removals_persist_across_reload() {
        let path = std::env::temp_dir().join("termscope_test_removed.json");
        let _ = std::fs::remove_file(&path);
        {
            let r = Removed::new(path.clone());
            r.remove_term("334");
            r.remove_word("basically");
        }
        let r = Removed::new(path.clone());
        assert!(r.is_term_removed("334"));
        assert!(r.is_word_removed("basically"));
        assert!(!r.is_term_removed("335"));
        let _ = std::fs::remove_file(&path);
    }
}
