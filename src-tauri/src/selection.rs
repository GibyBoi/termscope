//! Read whatever text the user currently has highlighted, ported from
//! `legacy/src/termscope/selection.py`.
//!
//! There's no portable "get selection" API, so we copy it: stash the clipboard,
//! release any held modifiers (the hotkey leaves Ctrl/Alt down), synthesize
//! Ctrl+C, read the result, then restore the original clipboard. The stash
//! covers text AND images, and the restore runs on every path — a failed
//! capture must never leave the user's clipboard "broken".

use std::thread::sleep;
use std::time::Duration;

use enigo::{
    Direction::{Click, Press, Release},
    Enigo, Key, Keyboard, Settings,
};

/// Printable on purpose: if this ever survives in the clipboard despite the
/// guaranteed restore (say the process is killed mid-capture), a paste shows
/// obviously-TermScope text instead of a NUL-prefixed string that most apps
/// paste as *nothing* — which reads as "my clipboard is broken".
const SENTINEL: &str = "[TermScope capture in progress]";

/// What was on the clipboard before we touched it.
enum Stash {
    Text(String),
    Image(arboard::ImageData<'static>),
    None,
}

/// Return the highlighted text, or an empty string if nothing could be captured.
pub fn capture_selection() -> String {
    let mut clipboard = match arboard::Clipboard::new() {
        Ok(c) => c,
        Err(_) => return String::new(),
    };
    let previous = match clipboard.get_text() {
        Ok(t) => Stash::Text(t),
        // Not text — a copied screenshot/image is the common case; stash it too.
        Err(_) => match clipboard.get_image() {
            Ok(img) => Stash::Image(img.to_owned_img()),
            Err(_) => Stash::None,
        },
    };

    let mut enigo = match Enigo::new(&Settings::default()) {
        Ok(e) => e,
        Err(_) => return String::new(),
    };

    // The hotkey (e.g. Ctrl+Alt+E) leaves Ctrl/Alt physically held, so a raw
    // Ctrl+C would register as Ctrl+Alt+C. Release the modifiers first.
    release_modifiers(&mut enigo);
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

    // Restore the user's clipboard on EVERY path. When there was nothing to
    // restore, clear ours so the sentinel (or a stray capture) never lingers.
    match previous {
        Stash::Text(prev) => {
            let _ = clipboard.set_text(prev);
        }
        Stash::Image(img) => {
            let _ = clipboard.set_image(img);
        }
        Stash::None => {
            let _ = clipboard.clear();
        }
    }

    text.trim().to_string()
}

/// Put `text` on the clipboard and synthesize Ctrl+V so it lands at the cursor.
/// If no text field has focus the paste is a harmless no-op and the text simply
/// stays on the clipboard — used by hotkey dictation, where "it's on your
/// clipboard" is the intended fallback, so the clipboard is NOT restored.
pub fn paste_text(text: &str) {
    let mut clipboard = match arboard::Clipboard::new() {
        Ok(c) => c,
        Err(_) => return,
    };
    if clipboard.set_text(text).is_err() {
        return;
    }
    let mut enigo = match Enigo::new(&Settings::default()) {
        Ok(e) => e,
        Err(_) => return,
    };
    // The dictate hotkey may still be physically held (esp. in hold mode).
    release_modifiers(&mut enigo);
    sleep(Duration::from_millis(30));
    let _ = enigo.key(Key::Control, Press);
    let _ = enigo.key(Key::Unicode('v'), Click);
    let _ = enigo.key(Key::Control, Release);
}

fn release_modifiers(enigo: &mut Enigo) {
    for key in [Key::Control, Key::Alt, Key::Shift, Key::Meta] {
        let _ = enigo.key(key, Release);
    }
}
