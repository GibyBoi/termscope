//! Filesystem locations for per-user state, ported from `legacy/src/termscope/paths.py`.
//!
//! Config and knowledge live in `%APPDATA%\TermScope` — the SAME location the Python
//! app used — so a user's learned-term progress carries straight over to this rewrite.
//! Bundled term data is resolved separately from the Tauri resource dir (see `state.rs`).

use std::path::PathBuf;

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

fn dirs_home() -> PathBuf {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}
