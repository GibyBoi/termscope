//! Filesystem locations for per-user state, ported from `legacy/src/termscope/paths.py`.
//!
//! Config and knowledge live in `%APPDATA%\TermScope` — the SAME location the Python
//! app used — so a user's learned-term progress carries straight over to this rewrite.
//! Bundled term data is resolved separately from the Tauri resource dir (see `state.rs`).

use serde::de::DeserializeOwned;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

pub const APP_NAME: &str = "TermScope";

/// Per-user writable directory (e.g. `%APPDATA%\TermScope`), created on demand.
pub fn user_data_dir() -> PathBuf {
    let base = std::env::var_os("APPDATA")
        .or_else(|| std::env::var_os("LOCALAPPDATA"))
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            dirs_home().join(".config")
        });
    let dir = base.join(APP_NAME);
    let _ = std::fs::create_dir_all(&dir);
    dir
}

pub fn config_path() -> PathBuf {
    user_data_dir().join("config.json")
}

pub fn knowledge_path() -> PathBuf {
    user_data_dir().join("knowledge.json")
}

pub fn history_path() -> PathBuf {
    user_data_dir().join("history.json")
}

pub fn removed_path() -> PathBuf {
    user_data_dir().join("removed.json")
}

fn dirs_home() -> PathBuf {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

/// Outcome of loading a JSON store that must never silently lose user data.
pub struct Loaded<T> {
    pub value: T,
    /// `false` when an existing file could not be read or safely preserved, so the
    /// caller must NOT persist over it — overwriting would destroy user data that
    /// was never recovered. Persisting is only ever safe once the original bytes
    /// are either parsed or set aside as a backup.
    pub savable: bool,
}

/// Load a JSON store **without ever silently discarding user data** — the single
/// safe entry point every per-user store (history, knowledge, config) loads through.
///
/// The contract, by case:
/// - **absent file** → `T::default()`, savable (a genuine first run).
/// - **present & parses** → the parsed value, savable.
/// - **present but unreadable/unparseable** (corruption, a partial write, or a file
///   from a future schema this build can't parse) → the file is *quarantined*: renamed
///   aside to `<name>.corrupt-<unix>.json`, a warning is logged, `T::default()` is
///   returned, and it's savable (the canonical path is now free for a fresh file).
///   The user's original bytes are preserved on disk — recoverable, never deleted.
/// - **unreadable AND un-preservable** (rename failed, or the file couldn't even be
///   read) → `T::default()`, **not** savable, so the caller leaves the file untouched
///   rather than overwriting data it could neither read nor back up.
///
/// The only paths that ever remove user data are an explicit user action (History
/// "Clear", knowledge "Reset") — never a load, and never an update.
pub fn load_json_store<T: DeserializeOwned + Default>(path: &Path) -> Loaded<T> {
    let text = match std::fs::read_to_string(path) {
        Ok(t) => t,
        Err(e) if e.kind() == ErrorKind::NotFound => {
            return Loaded { value: T::default(), savable: true };
        }
        Err(e) => {
            eprintln!(
                "[termscope] WARN: cannot read {} ({e}); starting empty and will NOT overwrite it",
                path.display()
            );
            return Loaded { value: T::default(), savable: false };
        }
    };
    match serde_json::from_str::<T>(&text) {
        Ok(value) => Loaded { value, savable: true },
        Err(e) => {
            let backup = path.with_extension(format!("corrupt-{}.json", unix_secs()));
            match std::fs::rename(path, &backup) {
                Ok(()) => {
                    eprintln!(
                        "[termscope] WARN: {} was unreadable ({e}); your data was preserved as {} and a fresh file will be started",
                        path.display(),
                        backup.display()
                    );
                    Loaded { value: T::default(), savable: true }
                }
                Err(re) => {
                    eprintln!(
                        "[termscope] ERROR: {} was unreadable ({e}) and could not be preserved ({re}); leaving it in place and will NOT overwrite it",
                        path.display()
                    );
                    Loaded { value: T::default(), savable: false }
                }
            }
        }
    }
}

fn unix_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}
