"""System-tray icon and menu (pystray). Runs the app's main loop.

If pystray/Pillow aren't installed, `run_headless` keeps the process alive so
hotkeys and (optionally) listening still work without a tray icon.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import TermScopeApp


def _make_icon_image(listening: bool):
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    accent = (122, 162, 247, 255)  # blue
    on = (124, 207, 130, 255)  # green when listening
    d.ellipse((6, 6, size - 6, size - 6), fill=(31, 36, 48, 255), outline=accent, width=3)
    # A speech-bubble-ish glyph; dot turns green while listening.
    d.text((22, 16), "T", fill=accent)
    d.ellipse((40, 40, 52, 52), fill=on if listening else (90, 96, 110, 255))
    return img


class Tray:
    def __init__(self, app: "TermScopeApp"):
        self._app = app
        self._icon = None

    def run(self) -> None:
        try:
            import pystray
        except ImportError as exc:
            print(f"[TermScope] tray unavailable ({exc}); running headless.")
            self.run_headless()
            return

        self._pystray = pystray
        self._icon = pystray.Icon(
            "TermScope",
            icon=_make_icon_image(self._app.is_listening),
            title="TermScope",
            menu=self._build_menu(),
        )
        self._icon.run()

    def _build_menu(self):
        import pystray

        m = pystray.MenuItem
        return pystray.Menu(
            m(
                lambda item: f"Listening: {'ON' if self._app.is_listening else 'OFF'}",
                self._on_toggle_listen,
                checked=lambda item: self._app.is_listening,
                enabled=lambda item: self._app.listening_available,
            ),
            m(
                lambda item: self._app.listen_status_label(),
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            m("Explain selection", self._on_explain),
            m("Mark last term as learned", self._on_mark_last),
            pystray.Menu.SEPARATOR,
            m(lambda item: f"Learned: {self._app.learned_count()} terms", None, enabled=False),
            m("Open data folder", self._on_open_data),
            pystray.Menu.SEPARATOR,
            m("Quit", self._on_quit),
        )

    def refresh(self) -> None:
        if self._icon is not None:
            self._icon.icon = _make_icon_image(self._app.is_listening)
            self._icon.update_menu()

    # ---- menu callbacks (run on the tray thread) -------------------------
    def _on_toggle_listen(self, icon, item) -> None:
        self._app.toggle_listening()
        self.refresh()

    def _on_explain(self, icon, item) -> None:
        threading.Thread(target=self._app.explain_selection, daemon=True).start()

    def _on_mark_last(self, icon, item) -> None:
        self._app.mark_last_learned()

    def _on_open_data(self, icon, item) -> None:
        import os

        from . import paths

        os.startfile(str(paths.user_data_dir()))  # noqa: S606 (Windows-only convenience)

    def _on_quit(self, icon, item) -> None:
        self._app.shutdown()
        if self._icon is not None:
            self._icon.stop()

    def run_headless(self) -> None:
        """No tray icon: block until the app is asked to stop."""
        self._app.wait_until_stopped()
