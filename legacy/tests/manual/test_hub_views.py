#!/usr/bin/env python
"""Headless check that the hub's Library and Dashboard views render with real data."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from termscope.app import TermScopeApp
from termscope.ui.hub import TermScopeHub

app = TermScopeApp()
hub = TermScopeHub(app)
app.hub = hub

state = {}


def run_checks():
    try:
        hub._show_view("library")
        hub._populate_library()
        rows = len(hub._lib_list.winfo_children())
        # Pick a term that should have an extended definition and render its detail.
        entry = next(e for e in app.entries if e.term == "microservices")
        hub._select_term(entry)
        extended = app.library.extended(entry)
        source, url = app.library.source(entry)
        # Filter + search exercise
        hub._filter.set("Tech")
        hub._populate_library()
        tech_rows = len(hub._lib_list.winfo_children())
        hub._show_view("dashboard")
        hub.refresh()
        state.update(rows=rows, tech_rows=tech_rows,
                     extended_len=len(extended), source=source,
                     mastery=hub._stat_mastery.cget("text"),
                     learned=hub._stat_learned.cget("text"))
    except Exception as exc:  # noqa: BLE001
        import traceback
        state["error"] = traceback.format_exc()
    hub.destroy()


hub.after(500, run_checks)
hub.mainloop()

if "error" in state:
    print("FAIL\n" + state["error"])
    sys.exit(1)
print(f"OK library_rows={state['rows']} tech_rows={state['tech_rows']} "
      f"microservices_def_chars={state['extended_len']} source={state['source']} "
      f"dashboard(learned={state['learned']}, mastery={state['mastery']})")
