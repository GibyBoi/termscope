"""User-editable settings, loaded from and saved to config.json."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import paths


@dataclass
class Config:
    # Which bundled categories to load.
    enabled_categories: list[str] = field(default_factory=lambda: ["tech", "business", "companies"])

    # Notifier backend: "card" (modern floating window, default), "win11toast"
    # (native Windows toast), "tk" (legacy popup) or "console" (headless).
    notifier: str = "card"

    # Don't re-show the same unlearned term more often than this (seconds).
    cooldown_seconds: int = 6 * 60 * 60
    # Hard cap on notifications surfaced per minute, to avoid flooding.
    max_per_minute: int = 6
    # How long each notification card stays on screen before auto-dismissing (seconds).
    notification_timeout: int = 12
    # Notification card ("always on top" window) layout options.
    card_position: str = "bottom-right"  # bottom-right | bottom-left | top-right | top-left
    card_max: int = 6                    # how many cards may stack on screen at once

    # Audio capture.
    listen_system_audio: bool = True
    listen_microphone: bool = True
    listen_on_startup: bool = False  # privacy-first: off until toggled
    # Local Vosk model directory; empty = auto-discover newest under models/.
    vosk_model_path: str = ""

    # Global hotkeys (parsed by the `keyboard` library).
    hotkey_explain_selection: str = "ctrl+alt+e"
    hotkey_mark_last_learned: str = "ctrl+alt+k"
    hotkey_toggle_listening: str = "ctrl+alt+space"

    # Window / app behavior.
    close_to_tray: bool = False  # X quits outright (clear). True = minimize to tray instead.
    appearance: str = "dark"     # "dark", "light" or "system"
    minimize_hint_shown: bool = False  # so the "still running in tray" hint shows only once

    def save(self, path: Path | None = None) -> None:
        path = path or paths.config_path()
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or paths.config_path()
        if not path.exists():
            cfg = cls()
            cfg.save(path)
            return cfg
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        known = {f for f in cls().__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})
