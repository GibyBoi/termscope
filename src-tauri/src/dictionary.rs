//! Loading the bundled term dictionaries, ported from
//! `legacy/src/termscope/dictionary.py`.
//!
//! The id is the term's permanent numeric "id" (stable across app revisions so
//! progress is never lost); terms without one fall back to "category:slug".

use once_cell::sync::Lazy;
use regex::Regex;
use serde::Serialize;
use std::collections::HashSet;
use std::path::Path;

static WORD_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[a-z0-9]+").unwrap());
static SLUG_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[^a-z0-9]+").unwrap());

/// Lowercase alphanumeric tokens (punctuation and case discarded).
pub fn tokenize(text: &str) -> Vec<String> {
    WORD_RE
        .find_iter(&text.to_lowercase())
        .map(|m| m.as_str().to_string())
        .collect()
}

fn slug(text: &str) -> String {
    SLUG_RE
        .replace_all(&text.to_lowercase(), "-")
        .trim_matches('-')
        .to_string()
}

#[derive(Debug, Clone, Serialize)]
pub struct TermEntry {
    pub id: String,
    pub term: String,
    pub definition: String,
    pub category: String,
    pub aliases: Vec<String>,
    /// When true, only match if the source wrote the term in capitals (e.g. "REST").
    pub strict: bool,
    /// Each surface form (term + aliases) reduced to a token sequence.
    #[serde(skip)]
    pub token_sets: Vec<Vec<String>>,
}

/// Parse term files into entries. Duplicates are skipped by both id and category+slug.
pub fn load_entries(files: &[std::path::PathBuf], enabled: &HashSet<String>) -> Vec<TermEntry> {
    let mut entries: Vec<TermEntry> = Vec::new();
    let mut seen_ids: HashSet<String> = HashSet::new();
    let mut seen_slugs: HashSet<String> = HashSet::new();

    for path in files {
        let data: serde_json::Value = match std::fs::read_to_string(path)
            .ok()
            .and_then(|t| serde_json::from_str(&t).ok())
        {
            Some(v) => v,
            None => continue,
        };
        let category = data
            .get("category")
            .and_then(|v| v.as_str())
            .unwrap_or("general")
            .to_string();
        if !enabled.is_empty() && !enabled.contains(&category) {
            continue;
        }
        let terms = match data.get("terms").and_then(|v| v.as_array()) {
            Some(t) => t,
            None => continue,
        };
        for item in terms {
            let term = match item.get("term").and_then(|v| v.as_str()) {
                Some(t) => t.trim().to_string(),
                None => continue,
            };
            let slug_key = format!("{}:{}", category, slug(&term));
            let tid = match item.get("id") {
                Some(serde_json::Value::Number(n)) => n.to_string(),
                Some(serde_json::Value::String(s)) => s.clone(),
                _ => slug_key.clone(),
            };
            if seen_ids.contains(&tid) || seen_slugs.contains(&slug_key) {
                continue;
            }
            seen_ids.insert(tid.clone());
            seen_slugs.insert(slug_key.clone());

            let aliases: Vec<String> = item
                .get("aliases")
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|a| a.as_str())
                        .map(|s| s.trim().to_string())
                        .filter(|s| !s.is_empty())
                        .collect()
                })
                .unwrap_or_default();

            let mut token_sets: Vec<Vec<String>> = Vec::new();
            for form in std::iter::once(&term).chain(aliases.iter()) {
                let toks = tokenize(form);
                if !toks.is_empty() && !token_sets.contains(&toks) {
                    token_sets.push(toks);
                }
            }

            let definition = item
                .get("definition")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim()
                .to_string();
            let strict = item.get("strict").and_then(|v| v.as_bool()).unwrap_or(false);

            entries.push(TermEntry {
                id: tid,
                term,
                definition,
                category: category.clone(),
                aliases,
                strict,
                token_sets,
            });
        }
    }
    entries
}

/// All term dictionaries (`terms_*.json`) in a data directory.
pub fn bundled_term_files(data_dir: &Path) -> Vec<std::path::PathBuf> {
    let mut files: Vec<_> = std::fs::read_dir(data_dir)
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| e.path())
        .filter(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.starts_with("terms_") && n.ends_with(".json"))
                .unwrap_or(false)
        })
        .collect();
    files.sort();
    files
}
