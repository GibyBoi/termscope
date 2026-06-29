"""Discrete notifications with a 'Mark learned' action.

Three interchangeable backends, chosen by config.notifier:
  * "win11toast" — native Windows toast with an action button (default)
  * "tk"         — a small in-app popup in the screen corner (no extra deps)
  * "console"    — prints to stdout (used for headless testing)

A NotificationManager wraps the backend with rate limiting, cooldown enforcement
and a "most recently shown" stack so a global hotkey can retire the last term.
"""
from __future__ import annotations

import collections
import queue
import threading
import time
from typing import Callable

from .config import Config
from .dictionary import TermEntry
from .knowledge import Knowledge

LearnedCallback = Callable[[str], None]


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
class ConsoleBackend:
    name = "console"

    def show(self, entry: TermEntry, on_learned: LearnedCallback) -> None:
        print(f"\n[TermScope] {entry.term}  ({entry.category})\n  {entry.definition}")
        print(f"  -> mark learned with: knowledge id '{entry.id}'")


class Win11ToastBackend:
    name = "win11toast"

    def __init__(self) -> None:
        # Import eagerly so an unavailable backend fails fast and we can fall back.
        from win11toast import toast  # noqa: F401

        self._toast = toast

    def show(self, entry: TermEntry, on_learned: LearnedCallback) -> None:
        def handler(args) -> None:
            if isinstance(args, dict) and args.get("arguments") == "learned":
                on_learned(entry.id)

        def run() -> None:
            try:
                self._toast(
                    entry.term,
                    entry.definition,
                    buttons=[
                        {
                            "activationType": "background",
                            "arguments": "learned",
                            "content": "✓ Mark learned",
                        }
                    ],
                    on_click=handler,
                    duration="short",
                    app_id="TermScope",
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[TermScope] toast failed: {exc}")

        # toast() runs its own asyncio loop and blocks until dismissed.
        threading.Thread(target=run, daemon=True).start()


class TkBackend:
    """Corner popup hosted on a single persistent Tk thread."""

    name = "tk"

    def __init__(self, timeout_seconds: int = 12) -> None:
        import tkinter  # noqa: F401  (ensure availability before selecting this backend)

        self._timeout = timeout_seconds
        self._jobs: "queue.Queue[tuple[TermEntry, LearnedCallback]]" = queue.Queue()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._ui_loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _ui_loop(self) -> None:
        import tkinter as tk

        self._root = tk.Tk()
        self._root.withdraw()
        self._ready.set()
        self._root.after(150, self._drain)
        self._root.mainloop()

    def _drain(self) -> None:
        try:
            while True:
                entry, on_learned = self._jobs.get_nowait()
                self._popup(entry, on_learned)
        except queue.Empty:
            pass
        self._root.after(150, self._drain)

    def _popup(self, entry: TermEntry, on_learned: LearnedCallback) -> None:
        import tkinter as tk

        win = tk.Toplevel(self._root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.97)
        except tk.TclError:
            pass
        frame = tk.Frame(win, bg="#1f2430", padx=14, pady=12)
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame, text=entry.term, fg="#7aa2f7", bg="#1f2430",
            font=("Segoe UI Semibold", 12), anchor="w", justify="left",
        ).pack(anchor="w")
        tk.Label(
            frame, text=entry.definition, fg="#c0caf5", bg="#1f2430",
            font=("Segoe UI", 10), wraplength=320, anchor="w", justify="left",
        ).pack(anchor="w", pady=(4, 8))

        def learn() -> None:
            on_learned(entry.id)
            win.destroy()

        btns = tk.Frame(frame, bg="#1f2430")
        btns.pack(anchor="e")
        tk.Button(
            btns, text="✓ Mark learned", command=learn, relief="flat",
            bg="#3d59a1", fg="white", font=("Segoe UI", 9), padx=8, pady=2,
            activebackground="#4a6cc4", cursor="hand2",
        ).pack(side="left", padx=(0, 6))
        tk.Button(
            btns, text="Dismiss", command=win.destroy, relief="flat",
            bg="#2a2f3d", fg="#c0caf5", font=("Segoe UI", 9), padx=8, pady=2,
            cursor="hand2",
        ).pack(side="left")

        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        ww, wh = win.winfo_width(), win.winfo_height()
        win.geometry(f"+{sw - ww - 24}+{sh - wh - 64}")
        win.after(self._timeout * 1000, lambda: win.winfo_exists() and win.destroy())

    def show(self, entry: TermEntry, on_learned: LearnedCallback) -> None:
        self._jobs.put((entry, on_learned))


class CardBackend:
    """Delegates to the GUI's NotificationCenter (the modern floating card).

    Duck-typed: it just needs an object with `show(entry, on_learned)`. Kept free
    of any UI import so the notifier stays usable headlessly.
    """

    name = "card"

    def __init__(self, center) -> None:
        self._center = center

    def show(self, entry: TermEntry, on_learned: LearnedCallback) -> None:
        self._center.show(entry, on_learned)


def _build_backend(cfg: Config):
    """Build the initial backend. 'card'/'tk' are placeholders until the GUI calls
    attach_card_center(); they resolve to a no-op console backend here so we never
    spin up a second Tk root alongside the hub window."""
    if cfg.notifier == "win11toast":
        try:
            return Win11ToastBackend()
        except Exception as exc:  # noqa: BLE001
            print(f"[TermScope] win11toast unavailable ({exc}); using console until UI attaches.")
            return ConsoleBackend()
    return ConsoleBackend()


# --------------------------------------------------------------------------- #
# Manager
# --------------------------------------------------------------------------- #
class NotificationManager:
    def __init__(self, cfg: Config, knowledge: Knowledge, on_learned: LearnedCallback):
        self._cfg = cfg
        self._knowledge = knowledge
        self._on_learned = on_learned
        self._backend = _build_backend(cfg)
        self._recent: collections.deque[TermEntry] = collections.deque(maxlen=20)
        self._shown_times: collections.deque[float] = collections.deque()
        self._lock = threading.Lock()

    @property
    def backend_name(self) -> str:
        return self._backend.name

    def attach_card_center(self, center) -> None:
        """Once the GUI exists, route notifications through its floating cards."""
        if self._cfg.notifier in ("card", "tk"):
            self._backend = CardBackend(center)

    def _rate_ok(self) -> bool:
        now = time.time()
        with self._lock:
            while self._shown_times and now - self._shown_times[0] > 60:
                self._shown_times.popleft()
            if len(self._shown_times) >= self._cfg.max_per_minute:
                return False
            self._shown_times.append(now)
            return True

    def offer(self, entry: TermEntry) -> bool:
        """Show a notification for `entry` if it passes cooldown and rate limits."""
        if self._knowledge.is_learned(entry.id):
            return False
        if not self._knowledge.can_show(entry.id, self._cfg.cooldown_seconds):
            return False
        if not self._rate_ok():
            return False
        self._knowledge.record_shown(entry.id)
        self._recent.append(entry)
        self._backend.show(entry, self._handle_learned)
        return True

    def force(self, entry: TermEntry) -> bool:
        """Show `entry` regardless of cooldown/rate limit (explicit user request).

        Still skips terms already marked learned.
        """
        if self._knowledge.is_learned(entry.id):
            return False
        self._knowledge.record_shown(entry.id)
        self._recent.append(entry)
        self._backend.show(entry, self._handle_learned)
        return True

    def _handle_learned(self, term_id: str) -> None:
        self._on_learned(term_id)

    def mark_last_learned(self) -> TermEntry | None:
        """Retire the most recently shown term that isn't already learned."""
        while self._recent:
            entry = self._recent.pop()
            if not self._knowledge.is_learned(entry.id):
                self._handle_learned(entry.id)
                return entry
        return None
