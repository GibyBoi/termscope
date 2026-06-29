//! The TermScope jargon library — extended reference definitions, ported from
//! `legacy/src/termscope/library.py`. Reads the bundled `data/library.json`
//! (keyed by stable term id), falling back to the short definition when a term
//! has no enriched entry yet.

use serde::Serialize;
use std::collections::HashMap;
use std::path::Path;

use crate::dictionary::TermEntry;

#[derive(Default)]
pub struct Library {
    data: HashMap<String, serde_json::Value>,
}

#[derive(Serialize)]
pub struct Detail {
    pub extended: String,
    pub source: Option<String>,
    pub url: Option<String>,
}

impl Library {
    pub fn load(path: &Path) -> Self {
        let data = std::fs::read_to_string(path)
            .ok()
            .and_then(|t| serde_json::from_str::<HashMap<String, serde_json::Value>>(&t).ok())
            .unwrap_or_default();
        Self { data }
    }

    /// Full reference detail for a term, or the short definition as a fallback.
    pub fn detail(&self, entry: &TermEntry) -> Detail {
        let rec = self.data.get(&entry.id);
        let extended = rec
            .and_then(|r| r.get("extended"))
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(|s| s.to_string())
            .unwrap_or_else(|| entry.definition.clone());
        let source = rec
            .and_then(|r| r.get("source"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let url = rec
            .and_then(|r| r.get("url"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        Detail { extended, source, url }
    }
}
