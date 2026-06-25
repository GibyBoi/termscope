"""Read whatever text the user currently has highlighted.

There's no portable 'get selection' API on Windows, so we copy it: stash the
current clipboard, synthesize Ctrl+C, read the result, then restore the clipboard
so the user's copy buffer is left untouched.
"""
from __future__ import annotations

import threading
import time


def get_selection_text(restore: bool = True, settle: float = 0.12) -> str:
    """Return the highlighted text, or '' if nothing could be captured."""
    try:
        import keyboard
        import pyperclip
    except ImportError as exc:  # pragma: no cover - depends on optional deps
        print(f"[TermScope] selection capture unavailable ({exc}).")
        return ""

    try:
        previous = pyperclip.paste()
    except Exception:  # noqa: BLE001
        previous = None

    # The hotkey (e.g. Ctrl+Alt+E) leaves Ctrl/Alt physically held, so a raw
    # Ctrl+C would register as Ctrl+Alt+C and copy nothing. Release the modifiers
    # first so the synthesized copy is clean.
    for mod in ("ctrl", "alt", "shift", "left windows", "right windows"):
        try:
            keyboard.release(mod)
        except Exception:  # noqa: BLE001
            pass
    time.sleep(0.03)

    # Write a sentinel so we can tell "copied nothing" apart from "read the old
    # clipboard" — if the sentinel survives, the copy didn't take.
    sentinel = "\x00__termscope_no_selection__\x00"
    try:
        pyperclip.copy(sentinel)
    except Exception:  # noqa: BLE001
        pass

    keyboard.send("ctrl+c")
    time.sleep(settle)

    try:
        text = pyperclip.paste() or ""
    except Exception:  # noqa: BLE001
        text = ""
    if text == sentinel:
        text = ""  # nothing was actually selected/copied

    if restore and previous is not None:
        def _restore() -> None:
            time.sleep(settle)
            try:
                pyperclip.copy(previous)
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_restore, daemon=True).start()

    return text.strip()
