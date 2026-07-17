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
    /// Card corner: bottom-right | bottom-left | top-right | top-left | custom.
    pub card_position: String,
    /// Custom card location — PHYSICAL virtual-screen coords of the cards
    /// window's top-left, used only when `card_position == "custom"`. Stored
    /// physical (not logical) so save/restore is an exact round-trip on
    /// fractionally-scaled displays. `-1` means unset, so custom falls back to
    /// the bottom-right corner until the user drags a location.
    pub card_custom_x: i32,
    pub card_custom_y: i32,
    /// How many cards may stack on screen at once.
    pub card_max: u32,

    // Audio capture (which sources the Listening sidecar opens).
    pub listen_system_audio: bool,
    pub listen_microphone: bool,
    pub listen_on_startup: bool,

    // Global hotkeys. An empty string means "unbound" — the action has no
    // hotkey and nothing is registered for it.
    pub hotkey_explain_selection: String,
    pub hotkey_mark_last_learned: String,
    pub hotkey_toggle_listening: String,
    /// Start/stop hotkey dictation (speech → cleaned text at the cursor).
    pub hotkey_dictate: String,
    /// How hotkey dictation ends: "toggle" (press again) | "hold" (key release).
    pub dictate_mode: String,

    // Window / app behavior.
    pub close_to_tray: bool,
    pub appearance: String,
    pub minimize_hint_shown: bool,

    /// Record spoken-word and jargon history for the History tab. When off, no
    /// words or jargon occurrences are tallied or logged (existing history is
    /// kept until the user clears it).
    pub track_history: bool,

    /// Filler-reduction goal: target percentage of microphone words that may be
    /// filler (e.g. 5.0 = "at most 5% filler"). 0 disables the goal display.
    pub filler_goal_percent: f64,

    /// Transcription engine: "whisper" | "moonshine" | "parakeet". Non-whisper
    /// engines need sherpa-onnx installed; the model downloads on first use.
    /// Applies the next time the sidecar starts.
    pub transcribe_engine: String,
    /// Optional LLM polish of dictation output: "off" | "ollama" (local only).
    pub polish_provider: String,
    /// Ollama model tag for polish (e.g. "llama3.2:1b").
    pub polish_model: String,

    /// Forward compatibility: settings this build doesn't know (written by a
    /// newer version, or by the legacy Python app) are retained here and
    /// round-tripped on save instead of being silently deleted. Rolling back a
    /// version must never cost the user the settings the newer version saved.
    #[serde(flatten)]
    pub extra: serde_json::Map<String, serde_json::Value>,
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
            card_custom_x: -1,
            card_custom_y: -1,
            card_max: 6,
            listen_system_audio: true,
            listen_microphone: true,
            listen_on_startup: false,
            // v3-dev branch: shifted defaults so the dev app's global hotkeys
            // don't collide with an installed TermScope 2.x running alongside
            // (its defaults are ctrl+alt+…). Revert on release — CLAUDE.md.
            hotkey_explain_selection: "ctrl+shift+alt+e".into(),
            hotkey_mark_last_learned: "ctrl+shift+alt+k".into(),
            hotkey_toggle_listening: "ctrl+shift+alt+space".into(),
            hotkey_dictate: "ctrl+shift+alt+d".into(),
            dictate_mode: "toggle".into(),
            close_to_tray: false,
            appearance: "dark".into(),
            minimize_hint_shown: false,
            track_history: true,
            filler_goal_percent: 5.0,
            transcribe_engine: "whisper".into(),
            polish_provider: "off".into(),
            polish_model: "llama3.2:1b".into(),
            extra: serde_json::Map::new(),
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
        // Atomic write (tmp + rename, like history.rs): a crash mid-write must
        // never leave a half-written config.json that costs the user their
        // settings on the next launch.
        if let Ok(text) = serde_json::to_string_pretty(self) {
            let tmp = path.with_extension("tmp");
            if std::fs::write(&tmp, text).is_ok() {
                let _ = std::fs::rename(&tmp, path);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Settings from a newer version (or the legacy Python app) that this build
    /// doesn't recognize must survive a load → save round-trip, so a version
    /// rollback never deletes them.
    #[test]
    fn unknown_settings_survive_resave() {
        let path = std::env::temp_dir().join("termscope_test_config_extra.json");
        let _ = std::fs::remove_file(&path);
        std::fs::write(
            &path,
            r#"{"notifier":"card","future_setting":42,"another_new_one":{"nested":true}}"#,
        )
        .unwrap();

        let loaded = crate::paths::load_json_store::<Config>(&path);
        assert!(loaded.savable);
        let cfg = loaded.value;
        assert_eq!(cfg.notifier, "card");
        assert_eq!(cfg.extra.get("future_setting"), Some(&serde_json::json!(42)));

        cfg.save_to(&path);
        let raw: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
        assert_eq!(raw.get("future_setting"), Some(&serde_json::json!(42)));
        assert_eq!(
            raw.get("another_new_one"),
            Some(&serde_json::json!({"nested": true}))
        );
        // Known fields were written too (missing ones filled with defaults).
        assert_eq!(raw.get("card_position"), Some(&serde_json::json!("bottom-right")));
        let _ = std::fs::remove_file(&path);
    }

    /// An old config missing newly-added fields loads with defaults and keeps
    /// every value it did have — adding settings in an update is always safe.
    #[test]
    fn old_config_gains_new_fields_without_losing_values() {
        let path = std::env::temp_dir().join("termscope_test_config_old.json");
        let _ = std::fs::remove_file(&path);
        // A config written before card_custom_x/y existed.
        std::fs::write(
            &path,
            r#"{"notifier":"win11toast","cooldown_seconds":99,"card_position":"top-left"}"#,
        )
        .unwrap();

        let cfg = crate::paths::load_json_store::<Config>(&path).value;
        assert_eq!(cfg.notifier, "win11toast"); // kept
        assert_eq!(cfg.cooldown_seconds, 99); // kept
        assert_eq!(cfg.card_position, "top-left"); // kept
        assert_eq!(cfg.card_custom_x, -1); // new field defaulted, not an error
        let _ = std::fs::remove_file(&path);
    }
}
