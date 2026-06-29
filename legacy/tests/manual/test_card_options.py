#!/usr/bin/env python
"""Verify the new card options update the live center, and library unlearn works."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from termscope.app import TermScopeApp
from termscope.ui.hub import TermScopeHub
from termscope.ui.popup import NotificationCenter

app = TermScopeApp()
hub = TermScopeHub(app)
center = NotificationCenter(hub, on_learn_more=app.open_term_library,
                           timeout=app.cfg.notification_timeout, max_cards=app.cfg.card_max,
                           position=app.cfg.card_position)
app.notification_center = center
res = {}


def checks():
    try:
        hub._set_card_duration(7)
        hub._set_card_max(2)
        hub._set_card_position("top-left")
        res["timeout"] = center.timeout
        res["max"] = center.max_cards
        res["pos"] = center.position

        e = app.entries[0]
        app.knowledge.mark_learned(e.id)
        res["before"] = app.knowledge.is_learned(e.id)
        hub._set_learned(e, False)  # the unlearn path used by the library
        res["after"] = app.knowledge.is_learned(e.id)
    except Exception as exc:  # noqa: BLE001
        import traceback
        res["error"] = traceback.format_exc()
    hub.destroy()


hub.after(400, checks)
hub.after(6000, hub.destroy)
hub.mainloop()

if "error" in res:
    print("FAIL\n" + res["error"]); sys.exit(1)
print(f"card options live: timeout={res['timeout']}s max={res['max']} position={res['pos']}")
print(f"unlearn: learned={res['before']} -> after_unlearn={res['after']} "
      f"({'OK' if res['before'] and not res['after'] else 'FAIL'})")
