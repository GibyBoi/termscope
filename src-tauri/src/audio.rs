//! Audio listening via a Python sidecar (`sidecar/listen.py`) that captures
//! system + mic audio and transcribes it offline with faster-whisper. The
//! sidecar emits recognized text as JSON lines on stdout; we feed each line
//! through the matcher and surface unknown terms as cards (cooldown + rate
//! limited, like the legacy `NotificationManager.offer`).

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
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

/// Where a finished dictation's text goes.
#[derive(Clone, Copy, PartialEq)]
pub enum Deliver {
    /// Clipboard + synthesized Ctrl+V at the cursor (the hotkey flow).
    Paste,
    /// `ts://dictation-result` to the hub's Dictation view.
    View,
}

/// A live dictation session. The AUDIO is buffered in the sidecar (RAM only);
/// this side tracks who gets the text and what Listening looked like before.
struct Dictation {
    prior: PriorAudio,
    deliver: Deliver,
    /// True while recording; false once stopped and waiting on the sidecar's
    /// one-pass transcription (the "Computing…" phase).
    recording: bool,
}

pub struct Audio {
    child: Mutex<Option<Child>>,
    /// The sidecar's stdin — commands go down as JSON lines; dropping it (on
    /// stop) is what tells the sidecar to shut down (EOF).
    stdin: Mutex<Option<ChildStdin>>,
    status: Mutex<AudioStatus>,
    dictation: Mutex<Option<Dictation>>,
    /// Bumped per dictation; lets the completion watchdog detect staleness.
    dictation_gen: AtomicU64,
    /// True once the sidecar reports the mic stream is genuinely open. Drives
    /// the pill's warm-up state: words spoken before this are lost, so the
    /// wave must not show until this flips.
    mic_capturing: AtomicBool,
}

impl Audio {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
            stdin: Mutex::new(None),
            status: Mutex::new(AudioStatus::default()),
            dictation: Mutex::new(None),
            dictation_gen: AtomicU64::new(0),
            mic_capturing: AtomicBool::new(false),
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

        let engine = {
            let state = app.state::<AppState>();
            let cfg = state.config.lock().unwrap();
            cfg.transcribe_engine.clone()
        };
        let mut cmd = Command::new("python");
        cmd.arg(&script)
            .arg("--models-dir")
            .arg(&models_dir)
            .arg("--sources")
            .arg(sources.join(","))
            .arg("--engine")
            .arg(&engine)
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
        *self.stdin.lock().unwrap() = child.stdin.take();
        // A fresh sidecar hasn't opened any stream yet.
        self.mic_capturing.store(false, Ordering::SeqCst);

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
                            handle_heard_text(&app2, text, source);
                        }
                    }
                    "dictation" => {
                        let text = v.get("text").and_then(|s| s.as_str()).unwrap_or("").to_string();
                        let state = app2.state::<AppState>();
                        state.audio.dictation_result(&app2, text);
                    }
                    "capturing" => {
                        let source = v.get("source").and_then(|s| s.as_str()).unwrap_or("");
                        if source == "microphone" {
                            let state = app2.state::<AppState>();
                            state.audio.mic_capturing.store(true, Ordering::SeqCst);
                            // Warm-up over: if a dictation is recording, flip
                            // the pill from "starting" to the live wave.
                            if state
                                .audio
                                .dictation
                                .lock()
                                .unwrap()
                                .as_ref()
                                .is_some_and(|d| d.recording)
                            {
                                broadcast(&app2, "ts://dictate", json!({ "active": true }));
                            }
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
            state.audio.mic_capturing.store(false, Ordering::SeqCst);
            // A dictation waiting on this sidecar can never complete now.
            state.audio.dictation_abort(&app2, "the transcriber exited");
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
        *self.stdin.lock().unwrap() = None; // EOF tells a live sidecar to exit
        self.mic_capturing.store(false, Ordering::SeqCst);
        if let Some(mut child) = self.child.lock().unwrap().take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        let mut st = self.status.lock().unwrap();
        st.listening = false;
        st.reason = "off".into();
    }

    /// Send one JSON command line down the sidecar's stdin.
    fn send_cmd(&self, cmd: serde_json::Value) -> Result<(), String> {
        let mut guard = self.stdin.lock().unwrap();
        let stdin = guard.as_mut().ok_or("transcriber is not running")?;
        writeln!(stdin, "{cmd}").and_then(|_| stdin.flush()).map_err(|e| e.to_string())
    }

    // ---- dictation ------------------------------------------------------------

    pub fn is_dictating(&self) -> bool {
        self.dictation.lock().unwrap().is_some()
    }

    /// Begin a dictation session: ensure the microphone is being captured
    /// (borrowing or starting the sidecar as needed) and tell the sidecar to
    /// start buffering the whole recording.
    pub fn dictate_start(&self, app: &AppHandle, deliver: Deliver) -> Result<(), String> {
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
            // The running sidecar already captures the mic.
            PriorAudio::OnUntouched
        } else {
            // Listening is on but system-only: restart with the mic added.
            self.stop();
            self.start_with(app, Some(vec!["system", "microphone"]))?;
            PriorAudio::OnRestarted
        };
        self.send_cmd(json!({ "cmd": "dictate", "on": true }))?;
        self.dictation_gen.fetch_add(1, Ordering::SeqCst);
        *self.dictation.lock().unwrap() = Some(Dictation {
            prior,
            deliver,
            recording: true,
        });
        // Until the mic stream is truly open (Windows lights its own mic
        // indicator at that moment), anything said is lost — show "starting"
        // rather than a wave that implies we're hearing them.
        let warming = !self.mic_capturing.load(Ordering::SeqCst);
        broadcast(app, "ts://dictate", json!({ "active": true, "warming": warming }));
        let _ = app.emit_to("main", "ts://audio-status", self.status());
        Ok(())
    }

    /// Stop recording: the sidecar transcribes the whole recording in one pass
    /// and answers with a `dictation` event (handled by `dictation_result`).
    /// Until then the session sits in the "Computing…" phase.
    pub fn dictate_stop(&self, app: &AppHandle) {
        {
            let mut guard = self.dictation.lock().unwrap();
            match guard.as_mut() {
                Some(d) if d.recording => d.recording = false,
                _ => return, // idle, or already computing
            }
        }
        // Keep capturing for a short tail so releasing the key never clips the
        // last word; the sidecar owns the actual tail timer.
        let tail = {
            let state = app.state::<AppState>();
            let cfg = state.config.lock().unwrap();
            cfg.dictate_tail_seconds.clamp(0.0, 5.0)
        };
        if self
            .send_cmd(json!({ "cmd": "dictate", "on": false, "tail": tail }))
            .is_err()
        {
            // Sidecar already gone — nothing will ever answer.
            self.dictation_abort(app, "the transcriber is not running");
            return;
        }
        let generation = self.dictation_gen.load(Ordering::SeqCst);
        let app2 = app.clone();
        std::thread::spawn(move || {
            // The pill keeps waving through the tail (still honestly
            // recording), then flips to Computing….
            std::thread::sleep(std::time::Duration::from_millis((tail * 1000.0) as u64));
            let state = app2.state::<AppState>();
            if state.audio.dictation_gen.load(Ordering::SeqCst) == generation
                && state.audio.is_dictating()
            {
                broadcast(&app2, "ts://dictate", json!({ "active": false, "computing": true }));
            }
            // Watchdog: a wedged sidecar must not leave the app stuck there.
            std::thread::sleep(std::time::Duration::from_secs(120));
            if state.audio.dictation_gen.load(Ordering::SeqCst) == generation
                && state.audio.is_dictating()
            {
                state.audio.dictation_abort(&app2, "transcription timed out");
            }
        });
    }

    /// A dictation completion arrived from the sidecar: clean the text,
    /// deliver it, and put Listening back the way the user had it. Runs the
    /// pipeline off the reader thread — polish may take seconds.
    fn dictation_result(&self, app: &AppHandle, raw: String) {
        let session = match self.dictation.lock().unwrap().take() {
            Some(s) => s,
            None => return, // aborted or never ours
        };
        self.dictation_gen.fetch_add(1, Ordering::SeqCst);
        self.restore_prior(app, session.prior);
        let app2 = app.clone();
        std::thread::spawn(move || {
            let state = app2.state::<AppState>();
            // History/cards see the RAW text — history counts what was SAID,
            // fillers included (the goals need them); cards may pop for jargon.
            if !raw.is_empty() {
                handle_heard_text(&app2, &raw, "microphone");
            }
            let (cleaned, fillers_cut) = clean_fillers(&raw, &state.filler_words);
            let corrected = state.corrections.apply(&cleaned);
            let mut text = finalize_dictation(&corrected);
            let mut polished = false;
            let (provider, model) = {
                let cfg = state.config.lock().unwrap();
                (cfg.polish_provider.clone(), cfg.polish_model.clone())
            };
            if provider == "ollama" && !text.is_empty() {
                match crate::polish::ollama_polish(&text, &model) {
                    Ok(p) => {
                        text = p;
                        polished = true;
                    }
                    Err(e) => eprintln!("[termscope] polish skipped: {e}"),
                }
            }
            match session.deliver {
                Deliver::Paste => {
                    if !text.is_empty() {
                        crate::selection::paste_text_smart(&text);
                    }
                }
                Deliver::View => {
                    let _ = app2.emit_to(
                        "main",
                        "ts://dictation-result",
                        json!({ "text": text, "fillersCut": fillers_cut, "polished": polished }),
                    );
                }
            }
            broadcast(&app2, "ts://dictate", json!({ "active": false }));
            let _ = app2.emit_to("main", "ts://audio-status", state.audio.status());
        });
    }

    /// Tear down a dictation session that can no longer complete.
    pub fn dictation_abort(&self, app: &AppHandle, reason: &str) {
        let session = match self.dictation.lock().unwrap().take() {
            Some(s) => s,
            None => return,
        };
        self.dictation_gen.fetch_add(1, Ordering::SeqCst);
        self.restore_prior(app, session.prior);
        broadcast(app, "ts://dictate", json!({ "active": false, "error": reason }));
        let _ = app.emit_to("main", "ts://audio-status", self.status());
    }

    fn restore_prior(&self, app: &AppHandle, prior: PriorAudio) {
        match prior {
            PriorAudio::Off => self.stop(),
            PriorAudio::OnUntouched => {}
            PriorAudio::OnRestarted => {
                self.stop();
                if let Err(e) = self.start(app) {
                    eprintln!("[termscope] dictation: could not restore listening: {e}");
                }
            }
        }
    }
}

/// Emit to the indicator pill window and the hub.
fn broadcast(app: &AppHandle, event: &str, payload: serde_json::Value) {
    let _ = app.emit_to("dictate", event, payload.clone());
    let _ = app.emit_to("main", event, payload);
}

/// Collapse every run of a repeated character down to at most `max` — so a
/// stretched "ummmmm" can be matched against the bundled "um"/"umm"/"ummm".
fn collapse_runs(s: &str, max: usize) -> String {
    let mut out = String::with_capacity(s.len());
    let mut last = '\0';
    let mut run = 0;
    for c in s.chars() {
        if c == last {
            run += 1;
        } else {
            last = c;
            run = 1;
        }
        if run <= max {
            out.push(c);
        }
    }
    out
}

/// Remove filler words from an utterance, keeping everything else verbatim.
/// Tokens are matched by their normalized (lowercase alphanumeric) core, same
/// as the tallies; stretched forms ("ummmmm") are collapsed before matching so
/// they drop too. Runs of identical punctuation-only tokens left behind by a
/// removal collapse to one. Returns the cleaned text and how many fillers fell.
fn clean_fillers(text: &str, fillers: &std::collections::HashSet<String>) -> (String, u64) {
    let mut kept: Vec<&str> = Vec::new();
    let mut cut = 0u64;
    for w in text.split_whitespace() {
        let core: String = w
            .chars()
            .filter(|c| c.is_ascii_alphanumeric())
            .collect::<String>()
            .to_lowercase();
        let is_filler = !core.is_empty()
            && (fillers.contains(&core)
                || fillers.contains(&collapse_runs(&core, 3))
                || fillers.contains(&collapse_runs(&core, 2))
                || fillers.contains(&collapse_runs(&core, 1)));
        if is_filler {
            cut += 1;
            continue;
        }
        if core.is_empty() && kept.last() == Some(&w) {
            continue; // "— —" after a removal → keep one
        }
        kept.push(w);
    }
    (kept.join(" "), cut)
}

/// Final polish for a finished dictation, SpeakEasy-style: collapse repeated
/// punctuation ("!!"/".." → one), then capitalize the first letter. Runs once
/// on the assembled session text, right before it is pasted.
fn finalize_dictation(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut last = '\0';
    for c in text.trim().chars() {
        if matches!(c, '.' | ',' | '!' | '?') && c == last {
            continue;
        }
        last = c;
        out.push(c);
    }
    let mut done = String::with_capacity(out.len());
    let mut chars = out.chars();
    if let Some(first) = chars.next() {
        done.extend(first.to_uppercase());
        done.push_str(chars.as_str());
    }
    done
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
    use super::{clean_fillers, finalize_dictation};
    use std::collections::HashSet;

    #[test]
    fn clean_fillers_drops_normalized_tokens_keeps_rest() {
        let f: HashSet<String> = ["um".to_string(), "basically".to_string()].into();
        assert_eq!(
            clean_fillers("Um, so basically we ship Friday.", &f).0,
            "so we ship Friday."
        );
        assert_eq!(clean_fillers("um UM Um.", &f), (String::new(), 3));
        assert_eq!(clean_fillers("", &f), (String::new(), 0));
        // Punctuation-only tokens left doubled by a removal collapse to one.
        assert_eq!(clean_fillers("wait — um — what", &f).0, "wait — what");
    }

    #[test]
    fn clean_fillers_catches_stretched_forms() {
        let f: HashSet<String> = ["um".to_string(), "hmm".to_string()].into();
        assert_eq!(clean_fillers("ummmmm right", &f), ("right".to_string(), 1));
        assert_eq!(clean_fillers("Hmmmmm, maybe.", &f).0, "maybe.");
        // A legitimately doubled letter is not a stretched filler.
        assert_eq!(clean_fillers("moon buggy", &f), ("moon buggy".to_string(), 0));
    }

    #[test]
    fn finalize_capitalizes_and_collapses_punctuation() {
        assert_eq!(
            finalize_dictation("so we ship friday.. yes!!"),
            "So we ship friday. yes!"
        );
        assert_eq!(finalize_dictation("  hello  "), "Hello");
        assert_eq!(finalize_dictation(""), "");
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
