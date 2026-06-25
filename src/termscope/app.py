"""TermScope application: wires the dictionary, matcher, inputs and notifications."""
from __future__ import annotations

import threading
from typing import Callable

from . import paths
from .audio import AudioListener
from .config import Config
from .dictionary import load_entries
from .hotkeys import HotkeyManager
from .knowledge import Knowledge
from .library import Library
from .matcher import Matcher
from .notifier import NotificationManager
from .selection import get_selection_text


class TermScopeApp:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config.load()
        self.knowledge = Knowledge(paths.knowledge_path())
        self.library = Library()

        entries = load_entries(
            paths.bundled_term_files(), set(self.cfg.enabled_categories)
        )
        self.entries = entries
        self.entries_by_id = {e.id: e for e in entries}  # O(1) lookup by stable id
        self.matcher = Matcher(entries)

        self.notifications = NotificationManager(
            self.cfg, self.knowledge, self._on_learned
        )
        self.audio = AudioListener(self.cfg, self.handle_text)
        self.hotkeys = HotkeyManager(self.cfg)

        self.hub = None  # set by run() once the GUI exists
        self.notification_center = None  # set by run(); lets settings tune cards live
        self._stop = threading.Event()
        self._ui_refresh: Callable[[], None] | None = None

    # ---- entry lookup (used by the matcher callback wiring) --------------
    def entry_by_id(self, term_id: str):
        return self.entries_by_id.get(term_id)

    def open_term_library(self, entry) -> None:
        """'Learn more' from a notification card: surface the term in the hub."""
        if self.hub is not None:
            self.hub.open_library_term(entry)

    # ---- ui hookup -------------------------------------------------------
    def set_ui_refresh(self, callback: Callable[[], None]) -> None:
        self._ui_refresh = callback

    def _refresh_ui(self) -> None:
        if self._ui_refresh:
            try:
                self._ui_refresh()
            except Exception:  # noqa: BLE001
                pass

    # ---- status surfaces -------------------------------------------------
    @property
    def is_listening(self) -> bool:
        return self.audio.is_listening

    @property
    def listening_available(self) -> bool:
        return self.audio.available

    def listen_status_label(self) -> str:
        if self.audio.is_listening:
            return "Status: capturing audio"
        return f"Status: {self.audio.status_reason()}"

    def learned_count(self) -> int:
        return self.knowledge.learned_count()

    # ---- core flow -------------------------------------------------------
    def handle_text(self, text: str, source: str) -> int:
        """Scan transcribed/heard text and surface unknown terms (rate-limited)."""
        if not text:
            return 0
        shown = 0
        for match in self.matcher.find(text, self.knowledge.learned_ids()):
            if self.notifications.offer(match.entry):
                shown += 1
        return shown

    def explain_selection(self) -> int:
        """Explain jargon in the currently highlighted text (forced, ignores cooldown)."""
        text = get_selection_text()
        if not text:
            print("[TermScope] no text selected to explain.")
            return 0
        matches = self.matcher.find(text, self.knowledge.learned_ids())
        if not matches:
            print("[TermScope] no tracked jargon found in selection.")
            return 0
        shown = 0
        for match in matches[:5]:  # cap to avoid a burst from a long passage
            if self.notifications.force(match.entry):
                shown += 1
        return shown

    def mark_last_learned(self) -> None:
        entry = self.notifications.mark_last_learned()
        if entry:
            print(f"[TermScope] marked learned: {entry.term}")
        self._refresh_ui()

    def toggle_listening(self) -> None:
        if not self.audio.available:
            print(f"[TermScope] cannot listen: {self.audio.status_reason()}")
            return
        now_on = self.audio.toggle()
        print(f"[TermScope] listening {'started' if now_on else 'stopped'}.")
        self._refresh_ui()

    def _on_learned(self, term_id: str) -> None:
        self.knowledge.mark_learned(term_id)
        self._refresh_ui()

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        self.hotkeys.register(
            on_explain=lambda: threading.Thread(
                target=self.explain_selection, daemon=True
            ).start(),
            on_mark_last=self.mark_last_learned,
            on_toggle_listen=self.toggle_listening,
        )
        if self.cfg.listen_on_startup and self.audio.available:
            self.audio.start()
        self._print_banner()

    def _print_banner(self) -> None:
        print("=" * 58)
        print(f"  TermScope — {len(self.entries)} terms loaded "
              f"({', '.join(self.cfg.enabled_categories)})")
        print(f"  Notifier:  {self.notifications.backend_name}")
        print(f"  Listening: {self.audio.status_reason()}")
        print("  Hotkeys:")
        print(f"    explain selection   {self.cfg.hotkey_explain_selection}")
        print(f"    mark last learned   {self.cfg.hotkey_mark_last_learned}")
        print(f"    toggle listening    {self.cfg.hotkey_toggle_listening}")
        print("=" * 58)

    def shutdown(self) -> None:
        self.hotkeys.unregister()
        self.audio.stop()
        self._stop.set()

    def wait_until_stopped(self) -> None:
        try:
            self._stop.wait()
        except KeyboardInterrupt:
            self.shutdown()


_INSTANCE_MUTEX = None  # held for the process lifetime to enforce single-instance

# Stable Windows app identity. The taskbar groups our window under the pinned
# shortcut that carries this SAME id (set by install_shortcut.ps1), instead of a
# generic "python (windowed)" button. Keep this string in sync with that script.
APP_AUMID = "TermScope.App"


def _set_app_identity() -> None:
    """Tell Windows this process is 'TermScope' so the taskbar shows it as such."""
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_AUMID)
    except Exception:  # noqa: BLE001
        pass


def _already_running() -> bool:
    """True if another TermScope instance is already running this session.

    Uses a named mutex so a second launch (double-click, autostart + manual, etc.)
    bows out instead of piling up windows the user then can't tell apart.
    """
    global _INSTANCE_MUTEX
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        _INSTANCE_MUTEX = kernel32.CreateMutexW(None, False, "TermScope_SingleInstance_v1")
        if kernel32.GetLastError() != 183:  # ERROR_ALREADY_EXISTS
            return False
        # A copy is already running — bring its window to the front instead of
        # silently doing nothing, so re-launching feels like focusing the app.
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, "TermScope")
            if hwnd:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001
        return False  # never let the guard itself block startup


def run() -> None:
    """Launch the full GUI app: the hub window, the background listener and the
    floating notification cards."""
    import sys

    try:  # ensure Unicode definitions render in any attached console
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    _set_app_identity()  # must happen before the first window is created

    if _already_running():
        print("[TermScope] another instance is already running; exiting this duplicate.")
        return

    app = TermScopeApp()

    from .ui.hub import TermScopeHub
    from .ui.popup import NotificationCenter

    hub = TermScopeHub(app)
    app.hub = hub
    app.set_ui_refresh(hub.schedule_refresh)

    center = NotificationCenter(
        hub, on_learn_more=app.open_term_library,
        timeout=app.cfg.notification_timeout,
        max_cards=app.cfg.card_max,
        position=app.cfg.card_position,
    )
    app.notification_center = center
    app.notifications.attach_card_center(center)

    app.start()           # hotkeys + optional listen-on-startup
    hub.refresh()
    try:
        hub.mainloop()
    finally:
        app.shutdown()
