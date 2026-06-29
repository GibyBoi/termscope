//! Per-user knowledge state, ported from `legacy/src/termscope/knowledge.py`.
//!
//! Reads/writes the SAME `knowledge.json` the Python app used (keyed by stable
//! term ids), so a user's learned terms and anti-spam history carry straight over.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Default, Serialize, Deserialize)]
struct Stored {
    #[serde(default)]
    learned: HashMap<String, String>, // id -> ISO timestamp
    #[serde(default)]
    seen: HashMap<String, Seen>, // id -> {count, last}
}

#[derive(Default, Serialize, Deserialize, Clone)]
struct Seen {
    #[serde(default)]
    count: u64,
    #[serde(default)]
    last: f64, // unix seconds
}

pub struct Knowledge {
    path: PathBuf,
    inner: Mutex<Stored>,
}

impl Knowledge {
    pub fn new(path: PathBuf) -> Self {
        let inner = std::fs::read_to_string(&path)
            .ok()
            .and_then(|t| serde_json::from_str::<Stored>(&t).ok())
            .unwrap_or_default();
        Self { path, inner: Mutex::new(inner) }
    }

    fn save(&self, stored: &Stored) {
        if let Ok(text) = serde_json::to_string_pretty(stored) {
            let tmp = self.path.with_extension("tmp");
            if std::fs::write(&tmp, text).is_ok() {
                let _ = std::fs::rename(&tmp, &self.path);
            }
        }
    }

    pub fn is_learned(&self, id: &str) -> bool {
        self.inner.lock().unwrap().learned.contains_key(id)
    }

    pub fn learned_ids(&self) -> std::collections::HashSet<String> {
        self.inner.lock().unwrap().learned.keys().cloned().collect()
    }

    #[allow(dead_code)] // surfaced via get_knowledge today; kept for parity/future use
    pub fn learned_count(&self) -> usize {
        self.inner.lock().unwrap().learned.len()
    }

    pub fn mark_learned(&self, id: &str) {
        let mut g = self.inner.lock().unwrap();
        g.learned.insert(id.to_string(), now_iso());
        self.save(&g);
    }

    pub fn unlearn(&self, id: &str) {
        let mut g = self.inner.lock().unwrap();
        if g.learned.remove(id).is_some() {
            self.save(&g);
        }
    }

    pub fn reset(&self) {
        let mut g = self.inner.lock().unwrap();
        g.learned.clear();
        self.save(&g);
    }

    pub fn record_shown(&self, id: &str) {
        let mut g = self.inner.lock().unwrap();
        let rec = g.seen.entry(id.to_string()).or_default();
        rec.count += 1;
        rec.last = now_secs();
        self.save(&g);
    }

    /// True if the term has never been shown or its cooldown has elapsed.
    #[allow(dead_code)] // used by the audio-driven `offer` path (v2)
    pub fn can_show(&self, id: &str, cooldown_seconds: f64) -> bool {
        let g = self.inner.lock().unwrap();
        match g.seen.get(id) {
            None => true,
            Some(rec) => (now_secs() - rec.last) >= cooldown_seconds,
        }
    }
}

fn now_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

fn now_iso() -> String {
    // Local-ish ISO timestamp; format mirrors the Python "%Y-%m-%dT%H:%M:%S" shape.
    // We avoid pulling in chrono — a simple UTC stamp is sufficient for display.
    let secs = now_secs() as i64;
    let days = secs / 86_400;
    let rem = secs % 86_400;
    let (h, mi, s) = (rem / 3600, (rem % 3600) / 60, rem % 60);
    let (y, mo, d) = civil_from_days(days);
    format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}", y, mo, d, h, mi, s)
}

/// Howard Hinnant's days->civil date algorithm (proleptic Gregorian, UTC).
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = (if mp < 10 { mp + 3 } else { mp - 9 }) as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}
