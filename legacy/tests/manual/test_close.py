#!/usr/bin/env python
"""Verify the app is closeable: tray sets up, and the X / Quit path ends the mainloop."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from termscope.app import TermScopeApp
from termscope.ui.hub import TermScopeHub

app = TermScopeApp()
hub = TermScopeHub(app)
print("tray_active:", hub._tray_active, flush=True)

state = {"quit_called": False, "timed_out": False}

# Force the quit path (X button with close-to-tray disabled).
app.cfg.close_to_tray = False


def do_close():
    state["quit_called"] = True
    print("invoking _on_close (close_to_tray=False) -> expect quit", flush=True)
    hub._on_close()


def safety():
    state["timed_out"] = True
    print("TIMEOUT: window did not close on its own!", flush=True)
    hub.destroy()


hub.after(1200, do_close)
hub.after(7000, safety)
hub.mainloop()
print(f"MAINLOOP EXITED (quit_called={state['quit_called']} timed_out={state['timed_out']})", flush=True)
print("RESULT:", "CLOSEABLE" if state["quit_called"] and not state["timed_out"] else "PROBLEM", flush=True)
