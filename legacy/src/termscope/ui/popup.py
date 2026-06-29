"""The floating notification card — a small modern window that pops in front of all
other windows (even when the hub isn't focused) to explain a piece of jargon.

Each card shows the term, its short definition and three actions: Learn more
(opens the full library entry), Mark learned (retires the term), and Dismiss.
Cards stack from one corner, slide smoothly as the stack changes, and auto-dismiss
after a timeout. A NotificationCenter marshals show requests from background (audio)
threads onto the Tk main thread and QUEUES any terms beyond the on-screen maximum,
showing each as a slot frees up.
"""
from __future__ import annotations

import collections
import queue
from typing import Callable

import customtkinter as ctk

from ..dictionary import TermEntry
from . import theme

CARD_W = 360
TEXT_W = CARD_W - 54   # wrap width for the term + definition labels
MARGIN = 20
GAP = 12
TASKBAR = 50           # px reserved above the taskbar / below the top edge

EntryCallback = Callable[[TermEntry], None]


class NotificationCard(ctk.CTkToplevel):
    def __init__(self, center: "NotificationCenter", entry: TermEntry, on_learned: EntryCallback,
                 timeout: int):
        super().__init__(center.root, fg_color=theme.SURFACE_2)
        self._center = center
        self._on_learned = on_learned
        self.entry = entry
        self._timeout_ms = max(1, timeout) * 1000
        self._remaining = self._timeout_ms
        self._paused = False
        self._placed = False
        self._x = self._y = self._ty = self._h = 0

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.0)  # fade in
        except Exception:  # noqa: BLE001
            pass

        self._build()
        self.update_idletasks()
        self._h = self.winfo_reqheight()
        self._fade_in()
        self._tick()

    # ---- layout ----------------------------------------------------------
    def _build(self) -> None:
        accent = theme.category_color(self.entry.category)
        outer = ctk.CTkFrame(self, fg_color=theme.SURFACE_2, corner_radius=theme.RADIUS,
                             border_width=1, border_color=theme.BORDER)
        outer.pack(fill="both", expand=True)

        stripe = ctk.CTkFrame(outer, fg_color=accent, width=4, corner_radius=2)
        stripe.pack(side="left", fill="y", padx=(7, 0), pady=12)

        body = ctk.CTkFrame(outer, fg_color="transparent")
        body.pack(side="left", fill="both", expand=True, padx=(12, 14), pady=12)

        header = ctk.CTkFrame(body, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(header, text=f" {self.entry.category.upper()} ",
                     font=(theme.FONT_SEMIBOLD, theme.SIZE_TINY), text_color=theme.BG,
                     fg_color=accent, corner_radius=8, height=18).pack(side="left")
        ctk.CTkLabel(header, text="TermScope", font=(theme.FONT, theme.SIZE_TINY),
                     text_color=theme.TEXT_FAINT).pack(side="right")

        ctk.CTkLabel(body, text=self.entry.term, font=(theme.FONT_SEMIBOLD, theme.SIZE_H1),
                     text_color=accent, anchor="w", justify="left",
                     wraplength=TEXT_W).pack(fill="x", pady=(8, 2))
        ctk.CTkLabel(body, text=self.entry.definition, font=(theme.FONT, theme.SIZE_BODY),
                     text_color=theme.TEXT, anchor="w", justify="left",
                     wraplength=TEXT_W).pack(fill="x", pady=(0, 10))

        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.pack(fill="x")
        ctk.CTkButton(btns, text="Learn more", width=88, height=30,
                      font=(theme.FONT, theme.SIZE_SMALL), fg_color="transparent",
                      border_width=1, border_color=theme.ACCENT, text_color=theme.ACCENT,
                      hover_color=theme.SURFACE_3, corner_radius=8,
                      command=self._learn_more).pack(side="left")
        ctk.CTkButton(btns, text="✓ Learned", width=86, height=30,
                      font=(theme.FONT, theme.SIZE_SMALL), fg_color=theme.GREEN,
                      text_color=theme.BG, hover_color=theme.GREEN_HOVER, corner_radius=8,
                      command=self._mark_learned).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="✕", width=30, height=30,
                      font=(theme.FONT, theme.SIZE_SMALL), fg_color="transparent",
                      text_color=theme.TEXT_MUTED, hover_color=theme.SURFACE_3, corner_radius=8,
                      command=self.close).pack(side="right")

        self._bar = ctk.CTkProgressBar(body, height=3, corner_radius=2,
                                       progress_color=accent, fg_color=theme.SURFACE_3)
        self._bar.set(1.0)
        self._bar.pack(fill="x", pady=(10, 0))

        self._bind_hover(outer)

    # ---- hover pause -----------------------------------------------------
    def _bind_hover(self, widget) -> None:
        widget.bind("<Enter>", lambda e: setattr(self, "_paused", True), add="+")
        widget.bind("<Leave>", lambda e: self._maybe_unpause(), add="+")
        for child in widget.winfo_children():
            self._bind_hover(child)

    def _maybe_unpause(self) -> None:
        # Only resume the countdown once the pointer has truly left the window
        # (child<->child moves fire spurious Leave events).
        def check() -> None:
            try:
                under = self.winfo_containing(self.winfo_pointerx(), self.winfo_pointery())
                if under is None or self.winfo_toplevel() not in (under, under.winfo_toplevel()):
                    self._paused = False
            except Exception:  # noqa: BLE001
                self._paused = False
        self.after(60, check)

    # ---- geometry --------------------------------------------------------
    def measure(self) -> int:
        self.update_idletasks()
        self._h = self.winfo_reqheight()
        return self._h

    def apply_geometry(self) -> None:
        try:
            self.geometry(f"{CARD_W}x{self._h}+{int(self._x)}+{int(round(self._y))}")
        except Exception:  # noqa: BLE001
            pass

    # ---- behavior --------------------------------------------------------
    def _fade_in(self, step: float = 0.14) -> None:
        try:
            a = self.attributes("-alpha")
            if a < 0.97:
                self.attributes("-alpha", min(0.97, a + step))
                self.after(16, self._fade_in)
        except Exception:  # noqa: BLE001
            pass

    def _tick(self) -> None:
        if not self.winfo_exists():
            return
        if not self._paused:
            self._remaining -= 100
            try:
                self._bar.set(max(0.0, self._remaining / self._timeout_ms))
            except Exception:  # noqa: BLE001
                pass
            if self._remaining <= 0:
                self.close()
                return
        self.after(100, self._tick)

    def _mark_learned(self) -> None:
        # The notifier's learned-callback takes the term id (like every backend),
        # while learn-more takes the entry itself (it opens the library view).
        self._on_learned(self.entry.id)
        self.close()

    def _learn_more(self) -> None:
        self._center.on_learn_more(self.entry)
        self.close()

    def close(self) -> None:
        if self.winfo_exists():
            self._center._remove(self)
            self.destroy()


class NotificationCenter:
    """Marshals notification cards onto the Tk main thread, stacks them with a slide
    animation, and queues overflow so nothing is dropped.

    `on_learn_more` (open the library entry) is stable and set here; the per-term
    `on_learned` handler is passed to show() so it flows from the notifier pipeline.
    """

    def __init__(self, root: ctk.CTk, on_learn_more: EntryCallback,
                 timeout: int = 14, max_cards: int = 6, position: str = "bottom-right"):
        self.root = root
        self.on_learn_more = on_learn_more
        self.timeout = timeout
        self.max_cards = max_cards
        self.position = position
        self._cards: list[NotificationCard] = []
        self._pending: "collections.deque[tuple[TermEntry, EntryCallback]]" = collections.deque()
        self._active_ids: set[str] = set()       # showing or queued (dedup)
        self._incoming: "queue.Queue[tuple[TermEntry, EntryCallback]]" = queue.Queue()
        self._anim_running = False
        self.root.after(120, self._drain)

    # ---- public API ------------------------------------------------------
    def show(self, entry: TermEntry, on_learned: EntryCallback) -> None:
        """Thread-safe: enqueue a term to be shown (or queued) on the UI thread."""
        self._incoming.put((entry, on_learned))

    def update_options(self, timeout: int | None = None, max_cards: int | None = None,
                       position: str | None = None) -> None:
        if timeout is not None:
            self.timeout = max(1, int(timeout))
        if max_cards is not None:
            self.max_cards = max(1, int(max_cards))
        if position is not None:
            self.position = position
        self._fill()
        self._reflow()

    def pending_count(self) -> int:
        return len(self._pending)

    # ---- internals -------------------------------------------------------
    def _drain(self) -> None:
        try:
            while True:
                entry, on_learned = self._incoming.get_nowait()
                if entry.id in self._active_ids:
                    continue  # already showing or queued — don't duplicate
                if len(self._pending) < 80:
                    self._pending.append((entry, on_learned))
                    self._active_ids.add(entry.id)
        except queue.Empty:
            pass
        self._fill()
        self.root.after(150, self._drain)

    def _live_cards(self) -> list[NotificationCard]:
        self._cards = [c for c in self._cards if c.winfo_exists()]
        return self._cards

    def _fill(self) -> None:
        spawned = False
        while self._pending and len(self._live_cards()) < self.max_cards:
            entry, on_learned = self._pending.popleft()
            self._cards.append(NotificationCard(self, entry, on_learned, self.timeout))
            spawned = True
        if spawned:
            self._reflow()

    def _remove(self, card: NotificationCard) -> None:
        if card in self._cards:
            self._cards.remove(card)
        self._active_ids.discard(card.entry.id)
        self._reflow()
        self._fill()  # let the next queued term take the freed slot

    def _reflow(self) -> None:
        cards = self._live_cards()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        right = "right" in self.position
        top = "top" in self.position
        offset = 0
        for card in reversed(cards):  # newest nearest the chosen corner
            card.measure()
            card._x = (sw - CARD_W - MARGIN) if right else MARGIN
            card._ty = (MARGIN + offset) if top else (sh - card._h - offset - TASKBAR)
            if not card._placed:
                card._placed = True
                card._y = card._ty + (-44 if top else 44)  # slide in from the corner edge
                card.apply_geometry()
            offset += card._h + GAP
        self._animate()

    def _animate(self) -> None:
        if self._anim_running:
            return
        self._anim_running = True
        self._anim_step()

    def _anim_step(self) -> None:
        moving = False
        for card in self._live_cards():
            dy = card._ty - card._y
            if abs(dy) > 1:
                card._y += dy * 0.35
                moving = True
            else:
                card._y = card._ty
            card.apply_geometry()
        if moving:
            self.root.after(16, self._anim_step)
        else:
            self._anim_running = False


def _self_test() -> None:
    """python -m termscope.ui.popup — show 4 cards with max 2 to exercise queueing."""
    from ..dictionary import TermEntry

    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.withdraw()
    center = NotificationCenter(root, on_learn_more=lambda e: print("learn more:", e.term),
                                timeout=5, max_cards=2)
    learned = lambda tid: print("learned:", tid)
    samples = [
        TermEntry("tech:microservices", "microservices",
                  "An architecture that splits an app into small, independently deployable services that each do one job.", "tech"),
        TermEntry("business:north-star", "north star",
                  "The single guiding metric or goal that aligns a team's efforts.", "business"),
        TermEntry("companies:stripe", "Stripe",
                  "A payments platform that lets businesses accept and manage online payments via simple APIs.", "companies"),
        TermEntry("tech:idempotent", "idempotent",
                  "An operation that has the same effect whether you run it once or many times.", "tech"),
    ]
    for i, e in enumerate(samples):
        root.after(400 + i * 800, lambda e=e: center.show(e, learned))
    root.after(14000, root.destroy)
    root.mainloop()
    print("self-test done; max queued:", center.pending_count())


if __name__ == "__main__":
    _self_test()
