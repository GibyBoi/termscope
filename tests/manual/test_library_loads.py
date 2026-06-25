#!/usr/bin/env python
"""Verify the Library populates on first switch (via _show_view, not a direct populate)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from termscope.app import TermScopeApp
from termscope.ui.hub import TermScopeHub

app = TermScopeApp()
hub = TermScopeHub(app)
res = {}


def switch_to_library():
    hub._show_view("library")  # exactly what clicking the nav button does
    res["rows_right_after_show"] = len(hub._lib_list.winfo_children())


def check_later():
    res["rows_after_chunks"] = len(hub._lib_list.winfo_children())
    hub.destroy()


hub.after(300, switch_to_library)
hub.after(1800, check_later)
hub.after(6000, hub.destroy)
hub.mainloop()

print("rows right after show:", res.get("rows_right_after_show"))
print("rows after chunks:", res.get("rows_after_chunks"))
print("RESULT:", "FIXED" if res.get("rows_right_after_show", 0) > 0 else "STILL BROKEN")
