//! Find dictionary terms inside arbitrary text, ported from
//! `legacy/src/termscope/matcher.py`.
//!
//! Longest-match, left-to-right scan over tokens. Multi-word phrases win over
//! shorter overlapping terms. Tokens are compared after light plural normalization
//! so "APIs"/"OKRs"/"stakeholders" match their singular entries.

use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashMap;

use crate::dictionary::TermEntry;

static WORD_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[a-z0-9]+").unwrap());

/// Reduce a token to a plural-insensitive key (conservative; leaves "ss" alone).
fn norm(tok: &str) -> String {
    let len = tok.len(); // tokens are ascii [a-z0-9], so byte len == char count
    if len > 4 && tok.ends_with("es") {
        return tok[..len - 2].to_string();
    }
    if len > 3 && tok.ends_with('s') && !tok.ends_with("ss") {
        return tok[..len - 1].to_string();
    }
    tok.to_string()
}

#[derive(Debug, Clone)]
pub struct Match {
    pub entry_index: usize,
    // start/end byte offsets are kept for future text-highlighting; unused today.
    #[allow(dead_code)]
    pub start: usize,
    #[allow(dead_code)]
    pub end: usize,
}

/// (token, start, end) byte spans over the lowercased text.
fn tokens_with_spans(lower: &str) -> Vec<(String, usize, usize)> {
    WORD_RE
        .find_iter(lower)
        .map(|m| (m.as_str().to_string(), m.start(), m.end()))
        .collect()
}

pub struct Matcher {
    // normalized first token -> [(normalized token seq, entry index)], longest first
    by_first: HashMap<String, Vec<(Vec<String>, usize)>>,
    ids: Vec<String>,
    strict: Vec<bool>,
}

impl Matcher {
    pub fn new(entries: &[TermEntry]) -> Self {
        let mut by_first: HashMap<String, Vec<(Vec<String>, usize)>> = HashMap::new();
        let mut ids = Vec::with_capacity(entries.len());
        let mut strict = Vec::with_capacity(entries.len());
        for (idx, entry) in entries.iter().enumerate() {
            ids.push(entry.id.clone());
            strict.push(entry.strict);
            for toks in &entry.token_sets {
                let key: Vec<String> = toks.iter().map(|t| norm(t)).collect();
                if key.is_empty() {
                    continue;
                }
                by_first
                    .entry(key[0].clone())
                    .or_default()
                    .push((key, idx));
            }
        }
        for bucket in by_first.values_mut() {
            bucket.sort_by(|a, b| b.0.len().cmp(&a.0.len())); // longest first
        }
        Self { by_first, ids, strict }
    }

    /// Matches in order of appearance, de-duplicated by entry id. `excluded`
    /// (e.g. learned ids) are skipped entirely.
    pub fn find(&self, text: &str, excluded: &std::collections::HashSet<String>) -> Vec<Match> {
        let lower = text.to_lowercase();
        let spans = tokens_with_spans(&lower);
        let norm_toks: Vec<String> = spans.iter().map(|s| norm(&s.0)).collect();
        let n = norm_toks.len();
        let mut results: Vec<Match> = Vec::new();
        let mut seen_ids: std::collections::HashSet<String> = std::collections::HashSet::new();
        let mut i = 0usize;
        while i < n {
            let mut chosen_len = 0usize;
            let mut chosen_idx: Option<usize> = None;
            if let Some(bucket) = self.by_first.get(&norm_toks[i]) {
                for (phrase, idx) in bucket {
                    let l = phrase.len();
                    if i + l <= n && norm_toks[i..i + l] == phrase[..] {
                        chosen_len = l;
                        chosen_idx = Some(*idx);
                        break;
                    }
                }
            }
            match chosen_idx {
                Some(idx) => {
                    let start = spans[i].1;
                    let end = spans[i + chosen_len - 1].2;
                    if self.strict[idx] && !written_in_caps(text, start, end) {
                        i += 1;
                        continue;
                    }
                    let id = &self.ids[idx];
                    if !excluded.contains(id) && !seen_ids.contains(id) {
                        seen_ids.insert(id.clone());
                        results.push(Match { entry_index: idx, start, end });
                    }
                    i += chosen_len;
                }
                None => i += 1,
            }
        }
        results
    }
}

/// True if the matched slice has letters and all of them are uppercase.
fn written_in_caps(text: &str, start: usize, end: usize) -> bool {
    let slice = match text.get(start..end) {
        Some(s) => s,
        None => return false,
    };
    let letters: Vec<char> = slice.chars().filter(|c| c.is_alphabetic()).collect();
    !letters.is_empty() && letters.iter().all(|c| c.is_uppercase())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dictionary::{load_entries, tokenize, TermEntry};
    use std::collections::HashSet;
    use std::path::PathBuf;

    fn entry(term: &str, aliases: &[&str]) -> TermEntry {
        let mut token_sets: Vec<Vec<String>> = Vec::new();
        let aliases: Vec<String> = aliases.iter().map(|s| s.to_string()).collect();
        for form in std::iter::once(&term.to_string()).chain(aliases.iter()) {
            let toks = tokenize(form);
            if !toks.is_empty() && !token_sets.contains(&toks) {
                token_sets.push(toks);
            }
        }
        TermEntry {
            id: format!("tech:{}", term.to_lowercase().replace(' ', "-")),
            term: term.to_string(),
            definition: "def".into(),
            category: "tech".into(),
            aliases,
            strict: false,
            token_sets,
        }
    }

    fn none() -> HashSet<String> {
        HashSet::new()
    }

    fn terms<'a>(es: &'a [TermEntry], ms: &[Match]) -> Vec<&'a str> {
        ms.iter().map(|m| es[m.entry_index].term.as_str()).collect()
    }

    fn data_dir() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().join("data")
    }

    #[test]
    fn single_acronym_case_insensitive() {
        let es = vec![entry("API", &[])];
        let m = Matcher::new(&es);
        for text in ["Call the API now", "the api is down", "ApI failure"] {
            let found = m.find(text, &none());
            assert_eq!(found.len(), 1, "{}", text);
            assert_eq!(es[found[0].entry_index].term, "API");
        }
    }

    #[test]
    fn no_false_substring_match() {
        let es = vec![entry("API", &[])];
        let m = Matcher::new(&es);
        assert!(m.find("rapidly therapist apiary", &none()).is_empty());
    }

    #[test]
    fn multiword_phrase() {
        let es = vec![entry("low-hanging fruit", &["low hanging fruit"])];
        let m = Matcher::new(&es);
        let found = m.find("Let's grab the low hanging fruit first", &none());
        assert_eq!(found.len(), 1);
        assert_eq!(es[found[0].entry_index].term, "low-hanging fruit");
    }

    #[test]
    fn longest_match_wins() {
        let es = vec![entry("low hanging fruit", &[]), entry("fruit", &[])];
        let m = Matcher::new(&es);
        let found = m.find("the low hanging fruit", &none());
        assert_eq!(terms(&es, &found), vec!["low hanging fruit"]);
    }

    #[test]
    fn alias_match() {
        let es = vec![entry("CI/CD", &["ci cd", "cicd"])];
        let m = Matcher::new(&es);
        assert_eq!(m.find("our cicd pipeline", &none()).len(), 1);
        assert_eq!(m.find("the ci cd setup", &none()).len(), 1);
    }

    #[test]
    fn excluded_ids_skipped() {
        let es = vec![entry("API", &[])];
        let m = Matcher::new(&es);
        let mut ex = HashSet::new();
        ex.insert(es[0].id.clone());
        assert!(m.find("the API", &ex).is_empty());
    }

    #[test]
    fn dedupe_repeated_term() {
        let es = vec![entry("API", &[])];
        let m = Matcher::new(&es);
        assert_eq!(m.find("API talks to API which calls API", &none()).len(), 1);
    }

    #[test]
    fn spans_point_at_original_text() {
        let es = vec![entry("API", &[])];
        let m = Matcher::new(&es);
        let text = "use the API here";
        let mm = &m.find(text, &none())[0];
        assert_eq!(text[mm.start..mm.end].to_lowercase(), "api");
    }

    #[test]
    fn plural_forms_match() {
        let es = vec![entry("API", &[]), entry("stakeholder", &[]), entry("action item", &[])];
        let m = Matcher::new(&es);
        assert!(terms(&es, &m.find("we expose three APIs", &none())).contains(&"API"));
        assert!(terms(&es, &m.find("loop in the stakeholders", &none())).contains(&"stakeholder"));
        assert!(terms(&es, &m.find("two action items remain", &none())).contains(&"action item"));
    }

    #[test]
    fn business_word_not_mangled_by_plural_rule() {
        let es = vec![entry("business", &[])];
        let m = Matcher::new(&es);
        let found = m.find("the business plan", &none());
        assert_eq!(found.len(), 1);
        assert_eq!(es[found[0].entry_index].term, "business");
    }

    #[test]
    fn bundled_dictionaries_load() {
        let dir = data_dir();
        if !dir.exists() {
            return; // skip when data isn't alongside the crate
        }
        let files = crate::dictionary::bundled_term_files(&dir);
        assert!(!files.is_empty(), "no bundled term files found");
        let es = load_entries(&files, &HashSet::new());
        assert!(es.len() > 50);
        let ids: HashSet<_> = es.iter().map(|e| e.id.clone()).collect();
        assert_eq!(ids.len(), es.len(), "duplicate term ids in bundled data");
        let m = Matcher::new(&es);
        assert!(terms(&es, &m.find("what are our OKRs this quarter", &none())).contains(&"OKR"));
    }
}
