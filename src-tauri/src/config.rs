//! User settings, ported from `legacy/src/termscope/config.py`.
//!
//! Same JSON shape and field names as the Python app, written to the same
//! `config.json`, so settings round-trip between the two implementations.

use serde::{Deserialize, Serialize};
use std::path::Path;

use crate::paths;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Config {
    /// Which bundled categories to load.
    pub enabled_categories: Vec<String>,
    /// Notifier backend: "card" (floating window, default) | "win11toast".
    pub notifier: String,
    /// Don't re-show the same unlearned term more often than this (seconds).
    pub cooldown_seconds: u64,
    /// Hard cap on notifications surfaced per minute.
    pub max_per_minute: u32,
    /// How long each notification card stays on screen (seconds).
    pub notification_timeout: u32,
    /// Card corner: bottom-right | bottom-left | top-right | top-left.
    pub card_position: String,
    /// How many cards may stack on screen at once.
    pub card_max: u32,

    // Audio capture (deferred to v2 — stored but inert in this build).
    pub listen_system_audio: bool,
    pub listen_microphone: bool,
    pub listen_on_startup: bool,
    pub vosk_model_path: String,

    // Global hotkeys.
    pub hotkey_explain_selection: String,
    pub hotkey_mark_last_learned: String,
    pub hotkey_toggle_listening: String,

    // Window / app behavior.
    pub close_to_tray: bool,
    pub appearance: String,
    pub minimize_hint_shown: bool,

    /// Record spoken-word and jargon history for the History tab. When off, no
    /// words or jargon occurrences are tallied or logged (existing history is
    /// kept until the user clears it).
    pub track_history: bool,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            enabled_categories: vec![
                "tech".into(),
                "business".into(),
                "companies".into(),
            ],
            notifier: "card".into(),
            cooldown_seconds: 6 * 60 * 60,
            max_per_minute: 6,
            notification_timeout: 12,
            card_position: "bottom-right".into(),
            card_max: 6,
            listen_system_audio: true,
            listen_microphone: true,
            listen_on_startup: false,
            vosk_model_path: String::new(),
            hotkey_explain_selection: "ctrl+alt+e".into(),
            hotkey_mark_last_learned: "ctrl+alt+k".into(),
            hotkey_toggle_listening: "ctrl+alt+space".into(),
            close_to_tray: false,
            appearance: "dark".into(),
            minimize_hint_shown: false,
            track_history: true,
        }
    }
}

impl Config {
    /// Load from `config.json`, writing defaults on first run. Unknown keys are
    /// ignored and missing keys fall back to defaults (matches the Python loader).
    /// Goes through the shared safe loader, so a corrupt config is preserved as a
    /// backup rather than silently overwritten (see `paths::load_json_store`).
    pub fn load() -> Self {
        let path = paths::config_path();
        let loaded = paths::load_json_store::<Config>(&path);
        // Write defaults only when there's no usable file yet — a genuine first run,
        // or right after a corrupt config was quarantined aside. Never over a file we
        // couldn't read or preserve (`savable == false`).
        if loaded.savable && !path.exists() {
            loaded.value.save_to(&path);
        }
        loaded.value
    }

    pub fn save(&self) {
        self.save_to(&paths::config_path());
    }

    pub fn save_to(&self, path: &Path) {
        if let Ok(text) = serde_json::to_string_pretty(self) {
            let _ = std::fs::write(path, text);
        }
    }
}
