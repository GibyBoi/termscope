"""Global hotkey registration via the `keyboard` library.

Bindings (configurable in config.json):
  * explain selection      — read the highlighted text and explain any terms
  * mark last learned      — retire the most recently shown term, hands-free
  * toggle listening       — start/stop audio capture
"""
from __future__ import annotations

from .config import Config


class HotkeyManager:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._keyboard = None
        self._registered: list = []

    @property
    def available(self) -> bool:
        try:
            import keyboard  # noqa: F401
        except ImportError:
            return False
        return True

    def register(self, *, on_explain, on_mark_last, on_toggle_listen) -> bool:
        try:
            import keyboard
        except ImportError as exc:
            print(f"[TermScope] global hotkeys unavailable ({exc}).")
            return False
        self._keyboard = keyboard
        bindings = [
            (self._cfg.hotkey_explain_selection, on_explain),
            (self._cfg.hotkey_mark_last_learned, on_mark_last),
            (self._cfg.hotkey_toggle_listening, on_toggle_listen),
        ]
        for combo, callback in bindings:
            try:
                handle = keyboard.add_hotkey(combo, callback)
                self._registered.append(handle)
            except Exception as exc:  # noqa: BLE001
                print(f"[TermScope] could not bind '{combo}': {exc}")
        return bool(self._registered)

    def unregister(self) -> None:
        if not self._keyboard:
            return
        for handle in self._registered:
            try:
                self._keyboard.remove_hotkey(handle)
            except Exception:  # noqa: BLE001
                pass
        self._registered.clear()
