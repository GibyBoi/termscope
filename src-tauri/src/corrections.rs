//! Dictation corrections — the user's "it hears X, write Y" dictionary,
//! persisted to `corrections.json` in the app data dir. Applied to dictation
//! output after filler removal: misspelling entries rewrite what the model
//! heard; entries with an empty `hears` enforce the saved casing of `write`
//! wherever it appears ("github" -> "GitHub").

use regex::Regex;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Mutex;

#[derive(Clone, Serialize, Deserialize)]
pub struct Correction {
    /// What the transcriber tends to produce. Empty = casing-only entry.
    #[serde(default)]
    pub hears: String,
    /// What should be written instead.
    #[serde(default)]
    pub write: String,
}

#[derive(Default, Serialize, Deserialize)]
struct Stored {
    #[serde(default)]
    entries: Vec<Correction>,
}

pub struct Corrections {
    path: PathBuf,
    savable: bool,
    inner: Mutex<Stored>,
}

impl Corrections {
    pub fn new(path: PathBuf) -> Self {
        let loaded = crate::paths::load_json_store::<Stored>(&path);
        Self { path, savable: loaded.savable, inner: Mutex::new(loaded.value) }
    }

    fn save(&self, stored: &Stored) {
        if !self.savable {
            eprintln!(
                "[termscope] WARN: not persisting corrections — {} was unreadable and left untouched",
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

    pub fn list(&self) -> Vec<Correction> {
        self.inner.lock().unwrap().entries.clone()
    }

    pub fn add(&self, hears: String, write: String) {
        let mut g = self.inner.lock().unwrap();
        g.entries.push(Correction { hears, write });
        self.save(&g);
    }

    pub fn remove(&self, index: usize) {
        let mut g = self.inner.lock().unwrap();
        if index < g.entries.len() {
            g.entries.remove(index);
            self.save(&g);
        }
    }

    /// Apply every correction to `text`, whole-word, case-insensitive.
    pub fn apply(&self, text: &str) -> String {
        let entries = self.list();
        let mut out = text.to_string();
        for e in &entries {
            let write = e.write.trim();
            if write.is_empty() {
                continue;
            }
            let hears = if e.hears.trim().is_empty() { write } else { e.hears.trim() };
            out = replace_word(&out, hears, write);
        }
        out
    }
}

/// Whole-word, case-insensitive replacement. Terms edged by word characters
/// use `\b`; terms like "C++" or ".NET" get whitespace/edge boundaries via
/// capture groups (the regex crate has no lookaround).
fn replace_word(text: &str, term: &str, write: &str) -> String {
    let esc = regex::escape(term);
    let word_edged = term
        .chars()
        .next()
        .map(|c| c.is_alphanumeric() || c == '_')
        .unwrap_or(false)
        && term
            .chars()
            .last()
            .map(|c| c.is_alphanumeric() || c == '_')
            .unwrap_or(false);
    if word_edged {
        match Regex::new(&format!(r"(?i)\b{esc}\b")) {
            Ok(re) => re.replace_all(text, write).into_owned(),
            Err(_) => text.to_string(),
        }
    } else {
        match Regex::new(&format!(r"(?i)(^|\s)({esc})($|\s|[.,!?;:])")) {
            Ok(re) => re
                .replace_all(text, |caps: &regex::Captures| {
                    format!("{}{}{}", &caps[1], write, &caps[3])
                })
                .into_owned(),
            Err(_) => text.to_string(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fresh(name: &str) -> (Corrections, PathBuf) {
        let path = std::env::temp_dir().join(format!("termscope_test_corrections_{name}.json"));
        let _ = std::fs::remove_file(&path);
        (Corrections::new(path.clone()), path)
    }

    #[test]
    fn misspelling_rewrites_whole_words_only() {
        let (c, path) = fresh("misspell");
        c.add("term scope".into(), "TermScope".into());
        c.add("jason".into(), "JSON".into());
        assert_eq!(
            c.apply("I opened term scope and read the jason file."),
            "I opened TermScope and read the JSON file."
        );
        // No partial-word hits: "jasonville" is left alone.
        assert_eq!(c.apply("visiting jasonville"), "visiting jasonville");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn empty_hears_enforces_casing() {
        let (c, path) = fresh("casing");
        c.add("".into(), "GitHub".into());
        assert_eq!(c.apply("push it to github now"), "push it to GitHub now");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn non_word_edged_terms_match_with_boundaries() {
        let (c, path) = fresh("symbols");
        c.add("c plus plus".into(), "C++".into());
        c.add("".into(), ".NET".into());
        assert_eq!(c.apply("I write c plus plus daily."), "I write C++ daily.");
        assert_eq!(c.apply("the .net runtime"), "the .NET runtime");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn entries_persist_and_remove() {
        let path = std::env::temp_dir().join("termscope_test_corrections_persist.json");
        let _ = std::fs::remove_file(&path);
        {
            let c = Corrections::new(path.clone());
            c.add("a".into(), "b".into());
            c.add("x".into(), "y".into());
            c.remove(0);
        }
        let c = Corrections::new(path.clone());
        let list = c.list();
        assert_eq!(list.len(), 1);
        assert_eq!(list[0].hears, "x");
        let _ = std::fs::remove_file(&path);
    }
}
