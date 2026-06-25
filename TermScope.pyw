#!/usr/bin/env pythonw
"""No-console launcher for the TermScope desktop app.

Run with pythonw.exe (the windowless Python) so launching from the taskbar opens
the hub with no console window. The Start-menu/taskbar shortcut points here.

Under pythonw the console handles are invalid — writes to them buffer and then
fail when flushed, which would crash the app a few seconds in. We redirect
stdout/stderr to a line-buffered log file in %APPDATA%\\TermScope so every print
goes to a real file (and any fatal traceback is captured).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from termscope import paths

_log = open(paths.user_data_dir() / "termscope.log", "a", encoding="utf-8", buffering=1)
sys.stdout = _log
sys.stderr = _log

from termscope.app import run

if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        traceback.print_exc()
        raise
