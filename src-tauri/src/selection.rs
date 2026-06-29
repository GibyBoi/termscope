//! Read whatever text the user currently has highlighted, ported from
//! `legacy/src/termscope/selection.py`.
//!
//! There's no portable "get selection" API, so we copy it: stash the clipboard,
//! release any held modifiers (the hotkey leaves Ctrl/Alt down), synthesize
//! Ctrl+C, read the result, then restore the original clipboard.

use std::thread::sleep;
use std::time::Duration;

use enigo::{
    Direction::{Click, Press, Release},
    Enigo, Key, Keyboard, Settings,
};

const SENTINEL: &str = "\u{0}__termscope_no_selection__\u{0}";

/// Return the highlighted text, or an empty string if nothing could be captured.
pub fn capture_selection() -> String {
    let mut clipboard = match arboard::Clipboard::new() {
        Ok(c) => c,
        Err(_) => return String::new(),
    };
    let previous = clipboard.get_text().ok();

    let mut enigo = match Enigo::new(&Settings::default()) {
        Ok(e) => e,
        Err(_) => return String::new(),
    };

    // The hotkey (e.g. Ctrl+Alt+E) leaves Ctrl/Alt physically held, so a raw
    // Ctrl+C would register as Ctrl+Alt+C. Release the modifiers first.
    for key in [Key::Control, Key::Alt, Key::Shift, Key::Meta] {
        let _ = enigo.key(key, Release);
    }
    sleep(Duration::from_millis(30));

    // Sentinel lets us tell "copied nothing" apart from "read the old clipboard".
    let _ = clipboard.set_text(SENTINEL);

    let _ = enigo.key(Key::Control, Press);
    let _ = enigo.key(Key::Unicode('c'), Click);
    let _ = enigo.key(Key::Control, Release);
    sleep(Duration::from_millis(120));

    let mut text = clipboard.get_text().unwrap_or_default();
    if text == SENTINEL {
        text = String::new(); // nothing was actually selected/copied
    }

    // Restore the user's original clipboard.
    if let Some(prev) = previous {
        let _ = clipboard.set_text(prev);
    }

    text.trim().to_string()
}
