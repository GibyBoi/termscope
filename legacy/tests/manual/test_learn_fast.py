#!/usr/bin/env python
"""Verify marking a term learned updates only the button + db, with no full reload."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from termscope.app import TermScopeApp
from termscope.ui.hub import TermScopeHub

app = TermScopeApp()
for tid in list(app.knowledge.learned_ids()):
    app.knowledge.unlearn(tid)
hub = TermScopeHub(app)
res = {}


def go():
    hub._show_view("library")
    hub.after(1600, test_click)


def test_click():
    eid = next(iter(hub._row_toggles))
    entry = next(e for e in app.entries if e.id == eid)
    gen_before = hub._render_gen
    rows_before = len(hub._lib_list.winfo_children())
    t0 = time.perf_counter()
    hub._apply_learned(entry, True)
    res["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    res["db_learned"] = app.knowledge.is_learned(eid)
    res["toggle_text"] = hub._row_toggles[eid].cget("text")
    res["no_repopulate"] = (hub._render_gen == gen_before)
    res["rows_unchanged"] = (len(hub._lib_list.winfo_children()) == rows_before)
    hub.destroy()


hub.after(300, go)
hub.after(7000, hub.destroy)
hub.mainloop()
print(res)
ok = (res.get("db_learned") and res.get("toggle_text") == "✓"
      and res.get("no_repopulate") and res.get("rows_unchanged"))
print("RESULT:", "FAST + IN-PLACE" if ok else "PROBLEM")
