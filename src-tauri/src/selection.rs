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

/// Peek at the character immediately before the cursor in the focused field:
/// Shift+Left selects it, the sentinel/Ctrl+C trick reads it, and Right
/// collapses the selection back to the original caret position. Returns None
/// when there is nothing before the cursor (or no text field has focus).
/// The user's clipboard is stashed and restored exactly like a capture.
fn char_before_cursor() -> Option<char> {
    let mut clipboard = arboard::Clipboard::new().ok()?;
    let previous = match clipboard.get_text() {
        Ok(t) => Stash::Text(t),
        Err(_) => match clipboard.get_image() {
            Ok(img) => Stash::Image(img.to_owned_img()),
            Err(_) => Stash::None,
        },
    };
    let mut enigo = Enigo::new(&Settings::default()).ok()?;
    release_modifiers(&mut enigo);
    sleep(Duration::from_millis(30));
    let _ = clipboard.set_text(SENTINEL);

    let _ = enigo.key(Key::Shift, Press);
    let _ = enigo.key(Key::LeftArrow, Click);
    let _ = enigo.key(Key::Shift, Release);
    let _ = enigo.key(Key::Control, Press);
    let _ = enigo.key(Key::Unicode('c'), Click);
    let _ = enigo.key(Key::Control, Release);
    sleep(Duration::from_millis(90));
    let grabbed = clipboard.get_text().unwrap_or_default();
    // Collapse the probe selection back to where the caret was.
    let _ = enigo.key(Key::RightArrow, Click);
    sleep(Duration::from_millis(20));

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
    if grabbed == SENTINEL {
        return None; // nothing before the cursor / copy didn't take
    }
    grabbed.chars().next()
}

/// `paste_text`, but with a leading space added when the cursor sits directly
/// after a word or punctuation ("meet at 3." + dictation → "meet at 3. And…").
/// Used by dictation so pasted speech never fuses onto existing text.
pub fn paste_text_smart(text: &str) {
    let needs_space = char_before_cursor().is_some_and(|c| !c.is_whitespace());
    if needs_space {
        paste_text(&format!(" {text}"));
    } else {
        paste_text(text);
    }
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
