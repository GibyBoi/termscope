"""The TermScope hub — the main application window shown in the taskbar.

Three views in a sidebar shell:
  * Dashboard — listening toggle + "technical terms you know" progress.
  * Library   — searchable, browsable terms with their extensive definitions.
  * Settings  — every toggle and option, saved live to config.json.

The hub owns the single CTk root; the audio listener and notification cards run
against it. Built to keep running (and firing notifications) while minimized.
"""
from __future__ import annotations

import threading
import webbrowser
from typing import TYPE_CHECKING

import customtkinter as ctk

from . import theme

if TYPE_CHECKING:
    from ..app import TermScopeApp


ctk.set_appearance_mode("dark")

# Fun learning milestones: (terms-learned threshold, badge name).
_MILESTONES = [
    (1, "First Word"),
    (5, "Warming Up"),
    (10, "Quick Study"),
    (25, "Jargon Hunter"),
    (50, "Buzzword Slayer"),
    (100, "Corporate Fluent"),
    (175, "Silver Tongue"),
    (250, "Jargon Master"),
]


class TermScopeHub(ctk.CTk):
    def __init__(self, app: "TermScopeApp"):
        super().__init__(fg_color=theme.BG)
        self.app = app
        try:
            ctk.set_appearance_mode(getattr(app.cfg, "appearance", "dark"))
        except Exception:  # noqa: BLE001
            pass
        self.title("TermScope")
        self.geometry("960x620")
        self.minsize(860, 560)
        self._apply_icon()
        self._tray = None
        self._tray_active = False

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._views: dict[str, ctk.CTkFrame] = {}
        self._selected_term = None
        self._library_rows: list = []

        self._build_sidebar()
        self._views["dashboard"] = self._build_dashboard()
        self._views["library"] = self._build_library()
        self._views["settings"] = self._build_settings()
        self._show_view("dashboard")

        self._setup_tray()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Stamp icon + AUMID before the window first maps, so its taskbar button is
        # created already grouped under the pinned shortcut (not a python button).
        self.update_idletasks()
        self._force_taskbar_icon()

    # ===================================================================== #
    # Sidebar
    # ===================================================================== #
    def _build_sidebar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0, width=210)
        bar.grid(row=0, column=0, sticky="nsw")
        bar.grid_propagate(False)

        brand = ctk.CTkFrame(bar, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(24, 28))
        ctk.CTkLabel(brand, text="◆", font=(theme.FONT, 22), text_color=theme.ACCENT).pack(side="left")
        ctk.CTkLabel(brand, text="TermScope", font=(theme.FONT_SEMIBOLD, theme.SIZE_H1),
                     text_color=theme.TEXT).pack(side="left", padx=(8, 0))

        for key, label, icon in [("dashboard", "Dashboard", "▣"),
                                  ("library", "Library", "▤"),
                                  ("settings", "Settings", "⚙")]:
            b = ctk.CTkButton(bar, text=f"  {icon}   {label}", anchor="w",
                              font=(theme.FONT, theme.SIZE_H2), height=44,
                              fg_color="transparent", text_color=theme.TEXT_MUTED,
                              hover_color=theme.SURFACE_3, corner_radius=8,
                              command=lambda k=key: self._show_view(k))
            b.pack(fill="x", padx=12, pady=2)
            self._nav_buttons[key] = b

        # Quit pinned to the very bottom — always reachable, no trap.
        ctk.CTkButton(bar, text="⏻   Quit", height=34, anchor="w",
                      font=(theme.FONT, theme.SIZE_BODY), fg_color="transparent",
                      text_color=theme.TEXT_MUTED, hover_color=theme.RED, corner_radius=8,
                      command=self.quit_app).pack(side="bottom", fill="x", padx=12, pady=(0, 14))

        # Listening control above the Quit button.
        foot = ctk.CTkFrame(bar, fg_color=theme.SURFACE_2, corner_radius=theme.RADIUS)
        foot.pack(side="bottom", fill="x", padx=12, pady=(8, 6))
        self._listen_switch = ctk.CTkSwitch(
            foot, text="Listening", font=(theme.FONT_SEMIBOLD, theme.SIZE_BODY),
            text_color=theme.TEXT, progress_color=theme.GREEN, command=self._toggle_listen)
        self._listen_switch.pack(anchor="w", padx=14, pady=(12, 2))
        self._listen_status = ctk.CTkLabel(foot, text="", font=(theme.FONT, theme.SIZE_TINY),
                                           text_color=theme.TEXT_FAINT, anchor="w", justify="left",
                                           wraplength=160)
        self._listen_status.pack(anchor="w", padx=14, pady=(0, 12))

    def _apply_icon(self) -> None:
        from .. import paths
        self._ico_path = str(paths.PROJECT_ROOT / "assets" / "termscope.ico")
        try:
            self.iconbitmap(self._ico_path)  # title-bar icon
        except Exception:  # noqa: BLE001
            pass
        # Tk's iconbitmap doesn't reliably set the *taskbar* icon under pythonw, so
        # also push it via Win32 WM_SETICON once the OS window exists (and again
        # later in case customtkinter re-sets it).
        self.after(200, self._force_taskbar_icon)
        self.after(1500, self._force_taskbar_icon)

    def _force_taskbar_icon(self) -> None:
        try:
            import ctypes

            u = ctypes.windll.user32
            u.GetAncestor.restype = ctypes.c_void_p
            u.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            u.LoadImageW.restype = ctypes.c_void_p
            u.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            u.SendMessageW.restype = ctypes.c_void_p
            u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p,
                                       ctypes.c_void_p]
            hwnd = u.GetAncestor(self.winfo_id(), 2) or self.winfo_id()  # GA_ROOT
            big, small = u.GetSystemMetrics(11), u.GetSystemMetrics(49)  # SM_CXICON, SM_CXSMICON
            for size, which in ((small, 0), (big, 1)):  # ICON_SMALL=0, ICON_BIG=1
                h = u.LoadImageW(None, self._ico_path, 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
                if h:
                    u.SendMessageW(hwnd, 0x0080, which, h)  # WM_SETICON
            # Stamp the window's AppUserModelID so the taskbar groups it under the
            # pinned TermScope shortcut (the process-level AUMID didn't propagate).
            from ..app import APP_AUMID
            from . import winident
            winident.set_window_aumid(int(hwnd), APP_AUMID)
        except Exception:  # noqa: BLE001
            pass

    def _show_view(self, name: str) -> None:
        for key, frame in self._views.items():
            if key == name:
                frame.grid(row=0, column=1, sticky="nsew")
            else:
                frame.grid_remove()
        for key, btn in self._nav_buttons.items():
            active = key == name
            btn.configure(fg_color=theme.SURFACE_3 if active else "transparent",
                          text_color=theme.TEXT if active else theme.TEXT_MUTED)
        self._active_view = name
        if name == "dashboard":
            self.refresh()
        elif name == "library" and (self._lib_dirty or not self._lib_list.winfo_children()):
            self._populate_library()
            self._lib_dirty = False

    # ===================================================================== #
    # Dashboard
    # ===================================================================== #
    def _build_dashboard(self) -> ctk.CTkFrame:
        v = ctk.CTkScrollableFrame(self, fg_color=theme.BG)
        v.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(v, text="Dashboard", font=(theme.FONT_SEMIBOLD, theme.SIZE_TITLE),
                     text_color=theme.TEXT).grid(row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(v, text="Your jargon, decoded — and how much of it you've mastered.",
                     font=(theme.FONT, theme.SIZE_BODY), text_color=theme.TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 18))

        # Stat cards row
        stats = ctk.CTkFrame(v, fg_color="transparent")
        stats.grid(row=2, column=0, sticky="ew", padx=14)
        for i in range(3):
            stats.grid_columnconfigure(i, weight=1)
        self._stat_learned = self._stat_card(stats, 0, "Terms learned", theme.GREEN)
        self._stat_total = self._stat_card(stats, 1, "Terms tracked", theme.ACCENT)
        self._stat_mastery = self._stat_card(stats, 2, "Mastery", theme.PURPLE)

        # Milestones / achievements
        mile = ctk.CTkFrame(v, fg_color=theme.SURFACE, corner_radius=theme.RADIUS)
        mile.grid(row=3, column=0, sticky="ew", padx=20, pady=(22, 0))
        mile.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(mile, text="Milestones", font=(theme.FONT_SEMIBOLD, theme.SIZE_H2),
                     text_color=theme.TEXT).grid(row=0, column=0, sticky="w", padx=20, pady=(16, 4))
        self._next_goal = ctk.CTkLabel(mile, text="", font=(theme.FONT, theme.SIZE_SMALL),
                                       text_color=theme.TEXT_MUTED, anchor="w")
        self._next_goal.grid(row=1, column=0, sticky="ew", padx=20)
        self._next_bar = ctk.CTkProgressBar(mile, height=8, corner_radius=4,
                                            progress_color=theme.GOLD, fg_color=theme.SURFACE_3)
        self._next_bar.grid(row=2, column=0, sticky="ew", padx=20, pady=(4, 10))
        self._badges = ctk.CTkFrame(mile, fg_color="transparent")
        self._badges.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))
        for i in range(4):
            self._badges.grid_columnconfigure(i, weight=1, uniform="badge")

        # Per-category progress
        prog = ctk.CTkFrame(v, fg_color=theme.SURFACE, corner_radius=theme.RADIUS)
        prog.grid(row=4, column=0, sticky="ew", padx=20, pady=22)
        prog.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(prog, text="Progress by category", font=(theme.FONT_SEMIBOLD, theme.SIZE_H2),
                     text_color=theme.TEXT).grid(row=0, column=0, sticky="w", padx=20, pady=(16, 8))
        self._cat_container = ctk.CTkFrame(prog, fg_color="transparent")
        self._cat_container.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 16))
        self._cat_container.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(v, text="Tip: click “✓ Learned” on a pop-up (or in the Library) to retire a "
                     "term — it won't interrupt you again.", font=(theme.FONT, theme.SIZE_SMALL),
                     text_color=theme.TEXT_FAINT, anchor="w", justify="left").grid(
            row=5, column=0, sticky="w", padx=20, pady=(0, 16))
        return v

    def _stat_card(self, parent, col: int, label: str, accent: str) -> ctk.CTkLabel:
        card = ctk.CTkFrame(parent, fg_color=theme.SURFACE_2, corner_radius=theme.RADIUS)
        card.grid(row=0, column=col, sticky="ew", padx=6)
        value = ctk.CTkLabel(card, text="—", font=(theme.FONT_SEMIBOLD, 34), text_color=accent)
        value.pack(anchor="w", padx=20, pady=(16, 0))
        ctk.CTkLabel(card, text=label, font=(theme.FONT, theme.SIZE_SMALL),
                     text_color=theme.TEXT_MUTED).pack(anchor="w", padx=20, pady=(0, 16))
        return value

    # ===================================================================== #
    # Library
    # ===================================================================== #
    def _build_library(self) -> ctk.CTkFrame:
        v = ctk.CTkFrame(self, fg_color=theme.BG)
        v.grid_columnconfigure(0, weight=3, uniform="lib")
        v.grid_columnconfigure(1, weight=4, uniform="lib")
        v.grid_rowconfigure(2, weight=1)
        self._render_gen = 0
        self._lib_dirty = True
        self._row_toggles: dict = {}
        self._row_frames: dict = {}

        header = ctk.CTkFrame(v, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(24, 10))
        ctk.CTkLabel(header, text="Library", font=(theme.FONT_SEMIBOLD, theme.SIZE_TITLE),
                     text_color=theme.TEXT).pack(side="left")
        self._search = ctk.CTkEntry(header, placeholder_text="Search terms…", width=220, height=34,
                                    fg_color=theme.SURFACE_2, border_color=theme.BORDER,
                                    text_color=theme.TEXT)
        self._search.pack(side="right")
        self._search.bind("<KeyRelease>", lambda e: self._populate_library())
        self._filter = ctk.CTkSegmentedButton(
            header, values=["All", "Tech", "Business", "Companies", "Learned"],
            font=(theme.FONT, theme.SIZE_SMALL), command=lambda _=None: self._populate_library(),
            fg_color=theme.SURFACE_2, selected_color=theme.ACCENT_DIM,
            unselected_color=theme.SURFACE_2, text_color=theme.TEXT)
        self._filter.set("All")
        self._filter.pack(side="right", padx=10)

        # Thin loading bar shown while a big list renders in chunks.
        self._lib_loading = ctk.CTkProgressBar(v, height=4, corner_radius=2,
                                               progress_color=theme.ACCENT, fg_color=theme.SURFACE_2)
        self._lib_loading.grid(row=1, column=0, sticky="ew", padx=(24, 8), pady=(0, 4))
        self._lib_loading.grid_remove()

        self._lib_list = ctk.CTkScrollableFrame(v, fg_color=theme.SURFACE, corner_radius=theme.RADIUS)
        self._lib_list.grid(row=2, column=0, sticky="nsew", padx=(24, 8), pady=(0, 24))
        self._lib_list.grid_columnconfigure(0, weight=1)

        self._detail = ctk.CTkScrollableFrame(v, fg_color=theme.SURFACE, corner_radius=theme.RADIUS)
        self._detail.grid(row=2, column=1, sticky="nsew", padx=(8, 24), pady=(0, 24))
        self._detail.grid_columnconfigure(0, weight=1)
        self._def_label = None
        self._detail.bind("<Configure>", self._on_detail_resize)
        self._render_detail(None)
        return v

    def _filtered_entries(self) -> list:
        q = (self._search.get() if hasattr(self, "_search") else "").strip().lower()
        mode = self._filter.get() if hasattr(self, "_filter") else "All"
        learned = self.app.knowledge.learned_ids()
        cat_for = {"Tech": "tech", "Business": "business", "Companies": "companies"}
        out = []
        for e in sorted(self.app.entries, key=lambda x: x.term.lower()):
            if mode in cat_for and e.category != cat_for[mode]:
                continue
            if mode == "Learned" and e.id not in learned:
                continue
            if q and q not in e.term.lower() and q not in e.definition.lower():
                continue
            out.append(e)
        return out

    def _make_row(self, entry, learned_ids) -> None:
        accent = theme.category_color(entry.category)
        row = ctk.CTkButton(
            self._lib_list, text=f"  {entry.term}", anchor="w", height=40,
            font=(theme.FONT, theme.SIZE_BODY), fg_color="transparent",
            text_color=theme.TEXT, hover_color=theme.SURFACE_3, corner_radius=8,
            command=lambda e=entry: self._select_term(e))
        row.grid(sticky="ew", padx=6, pady=1)
        ctk.CTkLabel(row, text="●", font=(theme.FONT, theme.SIZE_SMALL),
                     text_color=accent).place(relx=0.0, rely=0.5, x=4, anchor="w")
        toggle = ctk.CTkButton(row, width=30, height=24, corner_radius=6,
                               font=(theme.FONT_SEMIBOLD, theme.SIZE_SMALL))
        toggle.configure(command=lambda e=entry, t=toggle: self._toggle_row(e, t))
        self._style_toggle(toggle, entry.id in learned_ids)
        toggle.place(relx=1.0, rely=0.5, x=-8, anchor="e")
        self._row_toggles[entry.id] = toggle
        self._row_frames[entry.id] = row

    def _style_toggle(self, toggle, is_learned: bool) -> None:
        toggle.configure(
            text="✓" if is_learned else "+",
            fg_color=theme.GREEN if is_learned else "transparent",
            text_color=theme.BG if is_learned else theme.TEXT_FAINT,
            hover_color=theme.GREEN_HOVER if is_learned else theme.SURFACE_3,
            border_width=0 if is_learned else 1, border_color=theme.BORDER)

    def _toggle_row(self, entry, toggle) -> None:
        self._apply_learned(entry, not self.app.knowledge.is_learned(entry.id))

    def _apply_learned(self, entry, now_learned: bool) -> None:
        """Mark/unlearn a term and update ONLY the affected widgets — no full reload."""
        if now_learned:
            self.app.knowledge.mark_learned(entry.id)
        else:
            self.app.knowledge.unlearn(entry.id)
        toggle = self._row_toggles.get(entry.id)
        if toggle is not None and toggle.winfo_exists():
            self._style_toggle(toggle, now_learned)
            # Under the "Learned" filter an unlearned term no longer belongs: drop its row.
            if not now_learned and self._filter.get() == "Learned":
                frame = self._row_frames.pop(entry.id, None)
                self._row_toggles.pop(entry.id, None)
                if frame is not None and frame.winfo_exists():
                    frame.destroy()
        else:
            self._lib_dirty = True  # not visible in the current list; refresh on next show
        if getattr(self, "_selected_term", None) is not None and self._selected_term.id == entry.id:
            self._render_detail(entry)
        self.refresh()

    def _populate_library(self) -> None:
        self._render_gen += 1
        gen = self._render_gen
        for w in self._lib_list.winfo_children():
            w.destroy()
        self._row_toggles = {}
        self._row_frames = {}
        learned = self.app.knowledge.learned_ids()
        entries = self._filtered_entries()
        if not entries:
            self._lib_loading.grid_remove()
            ctk.CTkLabel(self._lib_list, text="No terms match.", font=(theme.FONT, theme.SIZE_BODY),
                         text_color=theme.TEXT_FAINT).grid(pady=20)
            return
        if len(entries) <= 60:  # fast enough to render in one go
            self._lib_loading.grid_remove()
            for e in entries:
                self._make_row(e, learned)
            return
        # Big list: render in chunks with a loading bar so the UI stays responsive.
        self._lib_loading.set(0.0)
        self._lib_loading.grid()
        self._render_chunk(entries, 0, gen, learned)

    def _render_chunk(self, entries, index: int, gen: int, learned) -> None:
        if gen != self._render_gen:
            return  # superseded by a newer search/filter
        chunk = 30
        for e in entries[index:index + chunk]:
            self._make_row(e, learned)
        done = index + chunk
        self._lib_loading.set(min(1.0, done / len(entries)))
        if done < len(entries):
            self.after(1, lambda: self._render_chunk(entries, done, gen, learned))
        else:
            self._lib_loading.grid_remove()

    def _on_detail_resize(self, event) -> None:
        if self._def_label is not None and self._def_label.winfo_exists():
            self._def_label.configure(wraplength=max(220, event.width - 56))

    def _select_term(self, entry) -> None:
        self._selected_term = entry
        self._render_detail(entry)

    def _render_detail(self, entry) -> None:
        for w in self._detail.winfo_children():
            w.destroy()
        self._def_label = None
        if entry is None:
            ctk.CTkLabel(self._detail, text="Select a term to read its full definition.",
                         font=(theme.FONT, theme.SIZE_BODY), text_color=theme.TEXT_FAINT).grid(
                row=0, column=0, padx=20, pady=24, sticky="w")
            return
        accent = theme.category_color(entry.category)
        learned = self.app.knowledge.is_learned(entry.id)

        head = ctk.CTkFrame(self._detail, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 4))
        ctk.CTkLabel(head, text=f"  {entry.category.upper()}  ",
                     font=(theme.FONT_SEMIBOLD, theme.SIZE_TINY), text_color=theme.BG,
                     fg_color=accent, corner_radius=8, height=18).pack(side="left")
        if learned:
            ctk.CTkLabel(head, text="✓ learned", font=(theme.FONT, theme.SIZE_SMALL),
                         text_color=theme.GREEN).pack(side="right")
        wl = max(220, self._detail.winfo_width() - 56)
        ctk.CTkLabel(self._detail, text=entry.term, font=(theme.FONT_SEMIBOLD, theme.SIZE_TITLE),
                     text_color=accent, anchor="w", justify="left", wraplength=wl).grid(
            row=1, column=0, sticky="w", padx=20, pady=(2, 8))

        extended = self.app.library.extended(entry)
        self._def_label = ctk.CTkLabel(self._detail, text=extended, font=(theme.FONT, theme.SIZE_BODY),
                                       text_color=theme.TEXT, anchor="w", justify="left", wraplength=wl)
        self._def_label.grid(row=2, column=0, sticky="w", padx=20, pady=(0, 12))

        source, url = self.app.library.source(entry)
        if source:
            ctk.CTkLabel(self._detail, text=f"Source: {source}", font=(theme.FONT, theme.SIZE_SMALL),
                         text_color=theme.TEXT_FAINT, anchor="w").grid(row=3, column=0, sticky="w",
                                                                       padx=20, pady=(0, 12))

        actions = ctk.CTkFrame(self._detail, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="w", padx=20, pady=(4, 20))
        if url:
            ctk.CTkButton(actions, text="Learn more ↗", width=110, height=34,
                          font=(theme.FONT, theme.SIZE_SMALL), fg_color="transparent",
                          border_width=1, border_color=theme.ACCENT, text_color=theme.ACCENT,
                          hover_color=theme.SURFACE_3, corner_radius=8,
                          command=lambda u=url: webbrowser.open(u)).pack(side="left", padx=(0, 8))
        if learned:
            ctk.CTkButton(actions, text="Unlearn", width=110, height=34,
                          font=(theme.FONT, theme.SIZE_SMALL), fg_color=theme.SURFACE_3,
                          text_color=theme.TEXT, hover_color=theme.BORDER, corner_radius=8,
                          command=lambda e=entry: self._apply_learned(e, False)).pack(side="left")
        else:
            ctk.CTkButton(actions, text="✓ Mark learned", width=140, height=34,
                          font=(theme.FONT_SEMIBOLD, theme.SIZE_SMALL), fg_color=theme.GREEN,
                          text_color=theme.BG, hover_color=theme.GREEN_HOVER, corner_radius=8,
                          command=lambda e=entry: self._apply_learned(e, True)).pack(side="left")

    # ===================================================================== #
    # Settings
    # ===================================================================== #
    def _build_settings(self) -> ctk.CTkFrame:
        v = ctk.CTkScrollableFrame(self, fg_color=theme.BG)
        v.grid_columnconfigure(0, weight=1)
        cfg = self.app.cfg

        ctk.CTkLabel(v, text="Settings", font=(theme.FONT_SEMIBOLD, theme.SIZE_TITLE),
                     text_color=theme.TEXT).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 16))

        audio = self._settings_group(v, 1, "Listening")
        self._switch(audio, "Listen to system audio (the other person on a call)",
                     cfg.listen_system_audio, lambda val: self._save("listen_system_audio", val))
        self._switch(audio, "Listen to my microphone", cfg.listen_microphone,
                     lambda val: self._save("listen_microphone", val))
        self._switch(audio, "Start listening automatically on launch", cfg.listen_on_startup,
                     lambda val: self._save("listen_on_startup", val))

        notif = self._settings_group(v, 2, "Notifications")
        ctk.CTkLabel(notif, text="Style", font=(theme.FONT, theme.SIZE_BODY),
                     text_color=theme.TEXT).pack(anchor="w", pady=(4, 4))
        style_map = {"Floating card (recommended)": "card", "Windows toast": "win11toast"}
        rev = {v2: k for k, v2 in style_map.items()}
        seg = ctk.CTkSegmentedButton(notif, values=list(style_map.keys()),
                                     font=(theme.FONT, theme.SIZE_SMALL),
                                     command=lambda label: self._save("notifier", style_map[label]),
                                     fg_color=theme.SURFACE_2, selected_color=theme.ACCENT_DIM,
                                     unselected_color=theme.SURFACE_2, text_color=theme.TEXT)
        seg.set(rev.get(cfg.notifier, "Floating card (recommended)"))
        seg.pack(anchor="w", pady=(0, 10))
        self._slider(notif, "Don't repeat a term for", cfg.cooldown_seconds // 3600, 1, 24, "h",
                     lambda val: self._save("cooldown_seconds", int(val) * 3600))
        self._slider(notif, "Max notifications per minute", cfg.max_per_minute, 1, 20, "",
                     lambda val: self._save("max_per_minute", int(val)))

        ctk.CTkLabel(notif, text="Floating-card window", font=(theme.FONT_SEMIBOLD, theme.SIZE_SMALL),
                     text_color=theme.TEXT_MUTED).pack(anchor="w", pady=(12, 2))
        self._slider(notif, "Each card stays on screen for", cfg.notification_timeout, 3, 30, "s",
                     self._set_card_duration)
        self._slider(notif, "Max cards on screen at once", cfg.card_max, 1, 6, "",
                     self._set_card_max)
        ctk.CTkLabel(notif, text="Card position", font=(theme.FONT, theme.SIZE_BODY),
                     text_color=theme.TEXT).pack(anchor="w", pady=(8, 4))
        posmap = {"Bottom-right": "bottom-right", "Bottom-left": "bottom-left",
                  "Top-right": "top-right", "Top-left": "top-left"}
        pos_rev = {v2: k for k, v2 in posmap.items()}
        pseg = ctk.CTkSegmentedButton(notif, values=list(posmap.keys()),
                                      font=(theme.FONT, theme.SIZE_SMALL),
                                      command=lambda label: self._set_card_position(posmap[label]),
                                      fg_color=theme.SURFACE_2, selected_color=theme.ACCENT_DIM,
                                      unselected_color=theme.SURFACE_2, text_color=theme.TEXT)
        pseg.set(pos_rev.get(cfg.card_position, "Bottom-right"))
        pseg.pack(anchor="w", pady=(0, 4))

        model = self._settings_group(v, 3, "Speech model")
        from ..audio import find_model_dir
        from .. import paths
        models = [d.name for d in paths.models_dir().iterdir() if d.is_dir() and (d / "am").exists()]
        current = find_model_dir(cfg)
        ctk.CTkLabel(model, text="Offline Vosk model used for transcription",
                     font=(theme.FONT, theme.SIZE_SMALL), text_color=theme.TEXT_MUTED).pack(
            anchor="w", pady=(2, 4))
        if models:
            menu = ctk.CTkOptionMenu(model, values=models, font=(theme.FONT, theme.SIZE_SMALL),
                                     fg_color=theme.SURFACE_2, button_color=theme.ACCENT_DIM,
                                     command=lambda name: self._save("vosk_model_path",
                                                                      str(paths.models_dir() / name)))
            menu.set(current.name if current else models[-1])
            menu.pack(anchor="w")
        else:
            ctk.CTkLabel(model, text="No model installed — run: python run.py download-model",
                         font=(theme.FONT, theme.SIZE_SMALL), text_color=theme.ORANGE).pack(anchor="w")

        hot = self._settings_group(v, 4, "Global hotkeys")
        for label, val in [("Explain selection", cfg.hotkey_explain_selection),
                           ("Mark last term learned", cfg.hotkey_mark_last_learned),
                           ("Toggle listening", cfg.hotkey_toggle_listening)]:
            row = ctk.CTkFrame(hot, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=label, font=(theme.FONT, theme.SIZE_BODY),
                         text_color=theme.TEXT).pack(side="left")
            ctk.CTkLabel(row, text=val.upper(), font=(theme.FONT_SEMIBOLD, theme.SIZE_SMALL),
                         text_color=theme.ACCENT, fg_color=theme.SURFACE_2, corner_radius=6,
                         padx=8).pack(side="right")

        gen = self._settings_group(v, 5, "General")
        self._switch(gen, "Closing the window keeps TermScope running in the tray",
                     cfg.close_to_tray, lambda val: self._save("close_to_tray", val))
        self._switch(gen, "Start TermScope automatically when I sign in to Windows",
                     self._is_startup_enabled(), self._set_startup)

        data = self._settings_group(v, 6, "Progress data")
        ctk.CTkLabel(data, text="Your learned-terms history lives in %APPDATA%\\TermScope.",
                     font=(theme.FONT, theme.SIZE_SMALL), text_color=theme.TEXT_MUTED).pack(
            anchor="w", pady=(2, 6))
        rowd = ctk.CTkFrame(data, fg_color="transparent")
        rowd.pack(anchor="w")
        ctk.CTkButton(rowd, text="Export progress…", width=140, height=32,
                      font=(theme.FONT, theme.SIZE_SMALL), fg_color=theme.SURFACE_3,
                      text_color=theme.TEXT, hover_color=theme.BORDER, corner_radius=8,
                      command=self._export_progress).pack(side="left", padx=(0, 8))
        ctk.CTkButton(rowd, text="Reset learned terms", width=160, height=32,
                      font=(theme.FONT, theme.SIZE_SMALL), fg_color="transparent",
                      border_width=1, border_color=theme.RED, text_color=theme.RED,
                      hover_color=theme.SURFACE_3, corner_radius=8,
                      command=self._reset_progress).pack(side="left")

        self._settings_note = ctk.CTkLabel(
            v, text="Toggles save instantly. Audio & model changes apply next time you toggle "
            "Listening on; notification-style changes apply on restart.",
            font=(theme.FONT, theme.SIZE_SMALL), text_color=theme.TEXT_FAINT, anchor="w", justify="left")
        self._settings_note.grid(row=7, column=0, sticky="w", padx=8, pady=14)
        return v

    # ---- notification-card options --------------------------------------
    def _set_card_duration(self, val) -> None:
        self._save("notification_timeout", int(val))
        if self.app.notification_center is not None:
            self.app.notification_center.update_options(timeout=int(val))

    def _set_card_max(self, val) -> None:
        self._save("card_max", int(val))
        if self.app.notification_center is not None:
            self.app.notification_center.update_options(max_cards=int(val))

    def _set_card_position(self, pos: str) -> None:
        self._save("card_position", pos)
        if self.app.notification_center is not None:
            self.app.notification_center.update_options(position=pos)

    # ---- general-options helpers ----------------------------------------
    def _set_appearance(self, label: str) -> None:
        mode = {"Dark": "dark", "Light": "light", "System": "system"}.get(label, "dark")
        self._save("appearance", mode)
        try:
            ctk.set_appearance_mode(mode)
        except Exception:  # noqa: BLE001
            pass

    def _startup_command(self) -> str:
        import os
        import sys
        from .. import paths
        pyw = paths.PROJECT_ROOT / "TermScope.pyw"
        exe = sys.executable
        if exe.lower().endswith("python.exe"):
            cand = exe[:-len("python.exe")] + "pythonw.exe"
            if os.path.exists(cand):
                exe = cand
        return f'"{exe}" "{pyw}"'

    def _is_startup_enabled(self) -> bool:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, "TermScope")
                return True
        except OSError:
            return False

    def _set_startup(self, enabled: bool) -> None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                                winreg.KEY_SET_VALUE) as k:
                if enabled:
                    winreg.SetValueEx(k, "TermScope", 0, winreg.REG_SZ, self._startup_command())
                else:
                    try:
                        winreg.DeleteValue(k, "TermScope")
                    except OSError:
                        pass
        except OSError as exc:  # noqa: BLE001
            print(f"[TermScope] could not change startup setting: {exc}")

    def _export_progress(self) -> None:
        import json
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".json", initialfile="termscope-progress.json",
            filetypes=[("JSON", "*.json")])
        if not path:
            return
        learned = sorted(self.app.knowledge.learned_ids())
        by_term = {e.id: e.term for e in self.app.entries}
        payload = {"learned_count": len(learned),
                   "learned": [{"id": i, "term": by_term.get(i, i)} for i in learned]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _reset_progress(self) -> None:
        from tkinter import messagebox
        if not messagebox.askyesno("Reset learned terms",
                                   "Forget every term you've marked learned? This can't be undone."):
            return
        for tid in list(self.app.knowledge.learned_ids()):
            self.app.knowledge.unlearn(tid)
        self._lib_dirty = True
        if getattr(self, "_active_view", None) == "library":
            self._populate_library()
            self._lib_dirty = False
        self.refresh()

    def _settings_group(self, parent, row: int, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=theme.SURFACE, corner_radius=theme.RADIUS)
        card.grid(row=row, column=0, sticky="ew", padx=8, pady=8)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=title, font=(theme.FONT_SEMIBOLD, theme.SIZE_H2),
                     text_color=theme.TEXT).pack(anchor="w", padx=18, pady=(14, 6))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=(0, 14))
        return inner

    def _switch(self, parent, label: str, value: bool, on_change) -> None:
        sw = ctk.CTkSwitch(parent, text=label, font=(theme.FONT, theme.SIZE_BODY),
                           text_color=theme.TEXT, progress_color=theme.ACCENT,
                           command=lambda: on_change(bool(sw.get())))
        sw.pack(anchor="w", pady=5)
        if value:
            sw.select()

    def _slider(self, parent, label: str, value: int, lo: int, hi: int, suffix: str, on_change) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(8, 2))
        cap = ctk.CTkLabel(row, text=f"{label}: {value}{suffix}", font=(theme.FONT, theme.SIZE_BODY),
                           text_color=theme.TEXT)
        cap.pack(anchor="w")
        s = ctk.CTkSlider(row, from_=lo, to=hi, number_of_steps=hi - lo, progress_color=theme.ACCENT,
                          button_color=theme.ACCENT, button_hover_color=theme.ACCENT_HOVER)
        s.set(value)

        def _changed(val):
            cap.configure(text=f"{label}: {int(val)}{suffix}")
            on_change(val)

        s.configure(command=_changed)
        s.pack(fill="x", pady=(2, 0))

    def _save(self, key: str, value) -> None:
        setattr(self.app.cfg, key, value)
        self.app.cfg.save()

    # ===================================================================== #
    # Listening + refresh
    # ===================================================================== #
    def _toggle_listen(self) -> None:
        self.app.toggle_listening()
        self.after(80, self.refresh)

    def schedule_refresh(self) -> None:
        """Thread-safe refresh request (callbacks may come from audio threads)."""
        try:
            self.after(0, self.refresh)
        except Exception:  # noqa: BLE001
            pass

    def _render_milestones(self, learned: int) -> None:
        for w in self._badges.winfo_children():
            w.destroy()
        next_idx = None
        for i, (thresh, name) in enumerate(_MILESTONES):
            got = learned >= thresh
            if not got and next_idx is None:
                next_idx = i
            r, c = divmod(i, 4)
            badge = ctk.CTkFrame(self._badges, corner_radius=10,
                                 fg_color=theme.SURFACE_2 if got else "transparent",
                                 border_width=1, border_color=theme.GOLD if got else theme.BORDER)
            badge.grid(row=r, column=c, padx=5, pady=5, sticky="ew")
            ctk.CTkLabel(badge, text="★" if got else "☆", font=(theme.FONT, 22),
                         text_color=theme.GOLD if got else theme.TEXT_FAINT).pack(pady=(10, 0))
            ctk.CTkLabel(badge, text=name, font=(theme.FONT_SEMIBOLD, theme.SIZE_SMALL),
                         text_color=theme.TEXT if got else theme.TEXT_MUTED).pack()
            ctk.CTkLabel(badge, text=f"{thresh} terms", font=(theme.FONT, theme.SIZE_TINY),
                         text_color=theme.TEXT_FAINT).pack(pady=(0, 10))
        if next_idx is not None:
            thresh, name = _MILESTONES[next_idx]
            prev = _MILESTONES[next_idx - 1][0] if next_idx > 0 else 0
            span = thresh - prev
            self._next_goal.configure(
                text=f"Next: learn {thresh - learned} more to unlock “{name}”  ({learned}/{thresh})")
            self._next_bar.set(max(0.0, min(1.0, (learned - prev) / span if span else 1.0)))
        else:
            self._next_goal.configure(text="Every milestone unlocked — you're a true jargon master!")
            self._next_bar.set(1.0)

    def refresh(self) -> None:
        total = len(self.app.entries)
        learned_ids = self.app.knowledge.learned_ids()
        learned = len(learned_ids)
        pct = round(learned / total * 100) if total else 0
        self._stat_learned.configure(text=str(learned))
        self._stat_total.configure(text=str(total))
        self._stat_mastery.configure(text=f"{pct}%")

        # Listening control lives in the always-visible sidebar — update it every time.
        if self.app.is_listening:
            self._listen_switch.select()
        else:
            self._listen_switch.deselect()
        self._listen_status.configure(text=self.app.listen_status_label())

        # The milestone badges + category bars are relatively expensive to rebuild, so
        # only do it while the dashboard is actually visible. This keeps learn-clicks
        # on the Library snappy (they call refresh() too, just to update the stats).
        if getattr(self, "_active_view", "dashboard") != "dashboard":
            return
        self._render_milestones(learned)
        cats: dict[str, list[int]] = {}
        for e in self.app.entries:
            c = cats.setdefault(e.category, [0, 0])
            c[1] += 1
            if e.id in learned_ids:
                c[0] += 1
        for w in self._cat_container.winfo_children():
            w.destroy()
        for cat in sorted(cats):
            done, tot = cats[cat]
            accent = theme.category_color(cat)
            row = ctk.CTkFrame(self._cat_container, fg_color="transparent")
            row.pack(fill="x", pady=6)
            top = ctk.CTkFrame(row, fg_color="transparent")
            top.pack(fill="x")
            ctk.CTkLabel(top, text=cat.capitalize(), font=(theme.FONT_SEMIBOLD, theme.SIZE_BODY),
                         text_color=theme.TEXT).pack(side="left")
            ctk.CTkLabel(top, text=f"{done} / {tot}", font=(theme.FONT, theme.SIZE_SMALL),
                         text_color=theme.TEXT_MUTED).pack(side="right")
            bar = ctk.CTkProgressBar(row, height=8, corner_radius=4, progress_color=accent,
                                     fg_color=theme.SURFACE_3)
            bar.set(done / tot if tot else 0)
            bar.pack(fill="x", pady=(4, 0))

    def open_library_term(self, entry) -> None:
        """Bring the hub forward and show a term (used by the 'Learn more' action)."""
        self.deiconify()
        self.lift()
        self.focus_force()
        self._show_view("library")
        self._select_term(entry)

    # ===================================================================== #
    # Tray + lifecycle (always closeable; optional background running)
    # ===================================================================== #
    def _setup_tray(self) -> None:
        try:
            import pystray
            from PIL import Image

            from .. import paths
            ico = paths.PROJECT_ROOT / "assets" / "termscope.ico"
            image = Image.open(str(ico)) if ico.exists() else None
            menu = pystray.Menu(
                pystray.MenuItem("Open TermScope", self._tray_open, default=True),
                pystray.MenuItem(
                    lambda item: f"Listening: {'ON' if self.app.is_listening else 'OFF'}",
                    self._tray_toggle_listen),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit TermScope", self._tray_quit),
            )
            self._tray = pystray.Icon("TermScope", icon=image, title="TermScope", menu=menu)
            threading.Thread(target=self._tray.run, daemon=True).start()
            self._tray_active = True
        except Exception as exc:  # noqa: BLE001
            print(f"[TermScope] tray unavailable ({exc}); the X button will quit the app.")
            self._tray, self._tray_active = None, False

    def _tray_open(self, icon=None, item=None) -> None:
        self.after(0, self._restore_window)

    def _tray_toggle_listen(self, icon=None, item=None) -> None:
        self.after(0, self._toggle_listen)
        if self._tray is not None:
            try:
                self._tray.update_menu()
            except Exception:  # noqa: BLE001
                pass

    def _tray_quit(self, icon=None, item=None) -> None:
        self.after(0, self.quit_app)

    def _restore_window(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_close(self) -> None:
        # X button: minimize to tray if the user opted in AND the tray is live;
        # otherwise quit outright. Never silently trap the window.
        if getattr(self.app.cfg, "close_to_tray", True) and self._tray_active:
            self.withdraw()
            if not getattr(self.app.cfg, "minimize_hint_shown", False):
                self.app.cfg.minimize_hint_shown = True
                self.app.cfg.save()
                if self._tray is not None:
                    try:
                        self._tray.notify("Still running in the tray — right-click its icon to "
                                          "Quit, or change this in Settings.", "TermScope")
                    except Exception:  # noqa: BLE001
                        pass
        else:
            self.quit_app()

    def quit_app(self) -> None:
        """Fully exit: stop the tray, shut the backend down, end the UI."""
        for step in (
            lambda: self._tray.stop() if self._tray is not None else None,
            self.app.shutdown,
            self.destroy,
        ):
            try:
                step()
            except Exception:  # noqa: BLE001
                pass
