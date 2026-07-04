//! Notification bookkeeping, distilled from `legacy/src/termscope/notifier.py`.
//!
//! The actual card UI lives in the `cards` webview window; this just tracks the
//! "most recently shown" stack (so a hotkey can retire the last term) and the
//! per-minute rate limiter. Cooldown/learned checks are done by the command layer
//! against `Knowledge`. Display happens by emitting a `ts://card` event.

use std::collections::VecDeque;
use std::time::Instant;

pub struct Notifier {
    recent: VecDeque<String>, // entry ids, newest at the back
    shown_times: VecDeque<Instant>,
}

impl Notifier {
    pub fn new() -> Self {
        Self {
            recent: VecDeque::new(),
            shown_times: VecDeque::new(),
        }
    }

    /// Sliding-window rate limit: at most `max_per_minute` shows in any 60s.
    pub fn rate_ok(&mut self, max_per_minute: u32) -> bool {
        let now = Instant::now();
        while let Some(front) = self.shown_times.front() {
            if now.duration_since(*front).as_secs() > 60 {
                self.shown_times.pop_front();
            } else {
                break;
            }
        }
        if self.shown_times.len() as u32 >= max_per_minute {
            return false;
        }
        self.shown_times.push_back(now);
        true
    }

    pub fn push_recent(&mut self, id: String) {
        self.recent.push_back(id);
        while self.recent.len() > 20 {
            self.recent.pop_front();
        }
    }

    pub fn pop_recent(&mut self) -> Option<String> {
        self.recent.pop_back()
    }
}

impl Default for Notifier {
    fn default() -> Self {
        Self::new()
    }
}
