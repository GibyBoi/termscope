//! Audio listening via a Python sidecar (`sidecar/listen.py`) that captures
//! system + mic audio and transcribes it offline with faster-whisper. The
//! sidecar emits recognized text as JSON lines on stdout; we feed each line
//! through the matcher and surface unknown terms as cards (cooldown + rate
//! limited, like the legacy `NotificationManager.offer`).

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use serde::Serialize;
use serde_json::json;
use tauri::{AppHandle, Emitter, Manager};

use crate::state::AppState;

#[derive(Default, Clone, Serialize)]
pub struct AudioStatus {
    pub listening: bool,
    pub ready: bool,
    pub reason: String,
    pub model: String,
}

/// What Listening looked like before hotkey dictation borrowed the sidecar,
/// so stopping dictation puts things back exactly as the user had them.
enum PriorAudio {
    /// Listening was off — dictation started the sidecar, so stop it after.
    Off,
    /// Listening was already capturing the microphone — nothing was touched.
    OnUntouched,
    /// Listening was on WITHOUT the mic — dictation restarted the sidecar with
    /// the mic added, so restart with the configured sources after.
    OnRestarted,
}

/// A live hotkey-dictation session: mic speech accumulating as cleaned text.
/// RAM only — the buffer is never persisted; on stop it goes to the clipboard.
struct Dictation {
    buffer: String,
    prior: PriorAudio,
}

pub struct Audio {
    child: Mutex<Option<Child>>,
    status: Mutex<AudioStatus>,
    dictation: Mutex<Option<Dictation>>,
}

impl Audio {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
            status: Mutex::new(AudioStatus::default()),
            dictation: Mutex::new(None),
        }
    }

    pub fn status(&self) -> AudioStatus {
        self.status.lock().unwrap().clone()
    }

    pub fn is_listening(&self) -> bool {
        self.status.lock().unwrap().listening
    }

    pub fn start(&self, app: &AppHandle) -> Result<(), String> {
        self.start_with(app, None)
    }

    /// Start the sidecar. `sources_override` (e.g. `["microphone"]` for hotkey
    /// dictation) wins over the configured sources when given.
    fn start_with(&self, app: &AppHandle, sources_override: Option<Vec<&str>>) -> Result<(), String> {
        let mut guard = self.child.lock().unwrap();
        if let Some(child) = guard.as_mut() {
            match child.try_wait() {
                Ok(Some(_)) => *guard = None, // previous sidecar exited; respawn
                _ => return Ok(()),           // still running
            }
        }
        let script = resolve_sidecar(app)?;
        let models_dir = crate::paths::user_data_dir().join("models");
        let sources = match sources_override {
            Some(s) => s,
            None => {
                let (sys, mic) = {
                    let state = app.state::<AppState>();
                    let cfg = state.config.lock().unwrap();
                    (cfg.listen_system_audio, cfg.listen_microphone)
                };
                let mut sources = Vec::new();
                if sys {
                    sources.push("system");
                }
                if mic {
                    sources.push("microphone");
                }
                sources
            }
        };
        if sources.is_empty() {
            return Err("Enable system audio and/or microphone in Settings first.".into());
        }

        // Capture the sidecar's stderr (Python/Whisper errors) to a log for diagnosis.
        let err_path = crate::paths::user_data_dir().join("audio.err.log");
        let err_out = std::fs::File::create(&err_path)
            .map(Stdio::from)
            .unwrap_or_else(|_| Stdio::null());

        let mut cmd = Command::new("python");
        cmd.arg(&script)
            .arg("--models-dir")
            .arg(&models_dir)
            .arg("--sources")
            .arg(sources.join(","))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(err_out);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        }

        let mut child = cmd
            .spawn()
            .map_err(|e| format!("could not start the audio sidecar (is Python installed?): {e}"))?;
        let stdout = child.stdout.take().ok_or("sidecar produced no stdout")?;

        {
            let mut st = self.status.lock().unwrap();
            st.listening = true;
            st.ready = false;
            st.reason = "starting…".into();
        }
        *guard = Some(child);
        drop(guard);

        let app2 = app.clone();
        std::thread::spawn(move || {
            // Mirror sidecar diagnostic lines (not transcribed speech) to a log so
            // audio issues are diagnosable without persisting what was said.
            let log_path = crate::paths::user_data_dir().join("audio.log");
            let mut logf = std::fs::OpenOptions::new()
                .create(true)
                .write(true)
                .truncate(true)
                .open(&log_path)
                .ok();
            let reader = BufReader::new(stdout);
            for line in reader.lines() {
                let line = match line {
                    Ok(l) => l,
                    Err(_) => break,
                };
                if line.trim().is_empty() {
                    continue;
                }
                let v: serde_json::Value = match serde_json::from_str(&line) {
                    Ok(v) => v,
                    Err(_) => continue,
                };
                let event = v.get("event").and_then(|e| e.as_str()).unwrap_or("");
                // Mirror only diagnostic events (status/errors). NEVER write the
                // transcribed `text` — a verbatim, in-order transcript on disk would
                // let past conversations be read straight back out, which the whole
                // orderless-history design exists to prevent. `level` pings are just
                // noise. Everything logged here is content-free.
                if event != "level" && event != "text" {
                    if let Some(f) = logf.as_mut() {
                        let _ = writeln!(f, "{}", line);
                    }
                }
                match event {
                    "status" => {
                        let ready = v.get("ready").and_then(|b| b.as_bool()).unwrap_or(false);
                        let reason = v.get("reason").and_then(|s| s.as_str()).unwrap_or("").to_string();
                        let model = v.get("model").and_then(|s| s.as_str()).unwrap_or("").to_string();
                        let state = app2.state::<AppState>();
                        let payload = {
                            let mut st = state.audio.status.lock().unwrap();
                            st.ready = ready;
                            st.reason = if ready {
                                format!("capturing audio ({model})")
                            } else {
                                reason
                            };
                            st.model = model;
                            st.clone()
                        };
                        let _ = app2.emit_to("main", "ts://audio-status", payload);
                    }
                    "text" => {
                        if let Some(text) = v.get("text").and_then(|s| s.as_str()) {
                            let source = v.get("source").and_then(|s| s.as_str()).unwrap_or("system");
                            // Live dictation taps the mic stream (filler cut here,
                            // RAM only) — and the normal pipeline still runs, so
                            // cards and history behave exactly as when listening.
                            if source == "microphone" {
                                let state = app2.state::<AppState>();
                                if state.audio.is_dictating() {
                                    let cleaned = clean_fillers(text, &state.filler_words);
                                    state.audio.dictation_append(&cleaned);
                                }
                            }
                            handle_heard_text(&app2, text, source);
                        }
                    }
                    "level" => {
                        let value = v.get("value").and_then(|x| x.as_i64()).unwrap_or(0);
                        let source = v.get("source").and_then(|s| s.as_str()).unwrap_or("system");
                        // The dictation pill scales its wave by the mic level.
                        broadcast(&app2, "ts://level", json!({ "value": value, "source": source }));
                    }
                    _ => {}
                }
            }
            // stdout closed → sidecar exited. Clear the dead child handle so a
            // later toggle re-spawns instead of no-op'ing on a stale process.
            let state = app2.state::<AppState>();
            if let Ok(mut g) = state.audio.child.lock() {
                *g = None;
            }
            let payload = {
                let mut st = state.audio.status.lock().unwrap();
                st.listening = false;
                if st.reason.is_empty() || st.reason == "starting…" {
                    st.reason = "stopped".into();
                }
                st.clone()
            };
            let _ = app2.emit_to("main", "ts://audio-status", payload);
        });
        Ok(())
    }

    pub fn stop(&self) {
        if let Some(mut child) = self.child.lock().unwrap().take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        let mut st = self.status.lock().unwrap();
        st.listening = false;
        st.reason = "off".into();
    }

    // ---- hotkey dictation -----------------------------------------------------

    pub fn is_dictating(&self) -> bool {
        self.dictation.lock().unwrap().is_some()
    }

    /// Begin a dictation session: make sure the microphone is being captured
    /// (borrowing or starting the sidecar as needed) and start accumulating.
    pub fn dictate_start(&self, app: &AppHandle) -> Result<(), String> {
        {
            let dict = self.dictation.lock().unwrap();
            if dict.is_some() {
                return Ok(()); // already dictating
            }
        }
        let mic_configured = {
            let state = app.state::<AppState>();
            let cfg = state.config.lock().unwrap();
            cfg.listen_microphone
        };
        let prior = if !self.is_listening() {
            self.start_with(app, Some(vec!["microphone"]))?;
            PriorAudio::Off
        } else if mic_configured {
            // The running sidecar already captures the mic; just tap the stream.
            PriorAudio::OnUntouched
        } else {
            // Listening is on but system-only: restart with the mic added.
            self.stop();
            self.start_with(app, Some(vec!["system", "microphone"]))?;
            PriorAudio::OnRestarted
        };
        *self.dictation.lock().unwrap() = Some(Dictation {
            buffer: String::new(),
            prior,
        });
        broadcast(app, "ts://dictate", json!({ "active": true }));
        let _ = app.emit_to("main", "ts://audio-status", self.status());
        Ok(())
    }

    /// End the dictation session: restore Listening to how the user had it,
    /// then deliver the cleaned text — pasted at the cursor via a synthesized
    /// Ctrl+V, and left on the clipboard either way.
    pub fn dictate_stop(&self, app: &AppHandle) {
        let session = match self.dictation.lock().unwrap().take() {
            Some(s) => s,
            None => return,
        };
        broadcast(app, "ts://dictate", json!({ "active": false }));
        match session.prior {
            PriorAudio::Off => self.stop(),
            PriorAudio::OnUntouched => {}
            PriorAudio::OnRestarted => {
                self.stop();
                if let Err(e) = self.start(app) {
                    eprintln!("[termscope] dictation: could not restore listening: {e}");
                }
            }
        }
        let _ = app.emit_to("main", "ts://audio-status", self.status());
        let text = session.buffer.trim().to_string();
        if !text.is_empty() {
            crate::selection::paste_text(&text);
        }
    }

    /// Feed a mic utterance into the live dictation buffer (filler already cut).
    fn dictation_append(&self, cleaned: &str) {
        if cleaned.is_empty() {
            return;
        }
        if let Some(d) = self.dictation.lock().unwrap().as_mut() {
            if !d.buffer.is_empty() {
                d.buffer.push(' ');
            }
            d.buffer.push_str(cleaned);
        }
    }
}

/// Emit to the indicator pill window and the hub.
fn broadcast(app: &AppHandle, event: &str, payload: serde_json::Value) {
    let _ = app.emit_to("dictate", event, payload.clone());
    let _ = app.emit_to("main", event, payload);
}

/// Remove filler words from an utterance, keeping everything else verbatim.
/// Tokens are matched by their normalized (lowercase alphanumeric) core, same
/// as the tallies, so "Um," and "um" both drop.
fn clean_fillers(text: &str, fillers: &std::collections::HashSet<String>) -> String {
    text.split_whitespace()
        .filter(|w| {
            let core: String = w
                .chars()
                .filter(|c| c.is_ascii_alphanumeric())
                .collect::<String>()
                .to_lowercase();
            core.is_empty() || !fillers.contains(&core)
        })
        .collect::<Vec<_>>()
        .join(" ")
}

impl Default for Audio {
    fn default() -> Self {
        Self::new()
    }
}

/// Scan heard text and surface unknown terms (cooldown + rate limited).
fn handle_heard_text(app: &AppHandle, text: &str, source: &str) {
    // Surface the raw transcription in the UI so listening is observable — lets the
    // user see it's hearing them even when a word isn't in the dictionary. The
    // source tag lets the Dictation view keep only what came from the microphone.
    let _ = app.emit_to("main", "ts://heard", json!({ "text": text, "source": source }));
    let state = app.state::<AppState>();

    // Find ALL jargon in the utterance (ignore learned/cooldown) — history records
    // what was actually said, not just what we decide to pop a card for. Terms and
    // words the user deleted (removed.rs) are excluded everywhere.
    let matches = state.matcher.find(text, &std::collections::HashSet::new());
    if state.config.lock().unwrap().track_history {
        let jargon_ids: Vec<String> = matches
            .iter()
            .map(|m| state.entries[m.entry_index].id.clone())
            .filter(|id| !state.removed.is_term_removed(id))
            .collect();
        let blocked = state.removed.removed_words();
        // Mic-only filler tracking: only the user's own speech counts toward the
        // filler-reduction goals, never words played through system audio.
        let mic = source == "microphone";
        state
            .history
            .record_audio(text, &jargon_ids, &blocked, mic, &state.filler_words);
        let _ = app.emit_to("main", "ts://history", json!({}));
    }

    if matches.is_empty() {
        return;
    }
    let (timeout, max_cards, position, custom_x, custom_y, cooldown, max_per_min) = {
        let cfg = state.config.lock().unwrap();
        (
            cfg.notification_timeout,
            cfg.card_max,
            cfg.card_position.clone(),
            cfg.card_custom_x,
            cfg.card_custom_y,
            cfg.cooldown_seconds as f64,
            cfg.max_per_minute,
        )
    };
    for m in matches {
        let entry = &state.entries[m.entry_index];
        if state.removed.is_term_removed(&entry.id) {
            continue; // user deleted this term — never card it
        }
        if state.knowledge.is_learned(&entry.id) {
            continue;
        }
        if !state.knowledge.can_show(&entry.id, cooldown) {
            continue;
        }
        if !state.notifier.lock().unwrap().rate_ok(max_per_min) {
            break; // hit the per-minute cap; stop this batch
        }
        state.knowledge.record_shown(&entry.id);
        state.notifier.lock().unwrap().push_recent(entry.id.clone());
        let payload = json!({
            "entry": entry,
            "timeout": timeout,
            "maxCards": max_cards,
            "position": position,
            "customX": custom_x,
            "customY": custom_y,
        });
        let _ = app.emit_to("cards", "ts://card", payload);
    }
}

#[cfg(test)]
mod tests {
    use super::clean_fillers;
    use std::collections::HashSet;

    #[test]
    fn clean_fillers_drops_normalized_tokens_keeps_rest() {
        let f: HashSet<String> = ["um".to_string(), "basically".to_string()].into();
        assert_eq!(
            clean_fillers("Um, so basically we ship Friday.", &f),
            "so we ship Friday."
        );
        assert_eq!(clean_fillers("um UM Um.", &f), "");
        assert_eq!(clean_fillers("", &f), "");
        // Punctuation-only tokens are never treated as filler.
        assert_eq!(clean_fillers("wait — um — what", &f), "wait — — what");
    }
}

/// Locate the bundled sidecar script in packaged and dev builds.
fn resolve_sidecar(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    if let Ok(res) = app.path().resource_dir() {
        let p = res.join("sidecar").join("listen.py");
        if p.exists() {
            return Ok(p);
        }
    }
    let dev = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(|p| p.join("sidecar").join("listen.py"))
        .unwrap_or_default();
    if dev.exists() {
        return Ok(dev);
    }
    Err("audio sidecar (sidecar/listen.py) not found".into())
}
