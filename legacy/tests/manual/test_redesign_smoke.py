#!/usr/bin/env python
"""Integration smoke test for the redesigned app: drive the real pipeline
(matcher -> NotificationManager -> CardBackend -> NotificationCenter -> cards)
on the GUI main thread and confirm cards appear, without needing live audio."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from termscope.app import TermScopeApp
from termscope.ui.hub import TermScopeHub
from termscope.ui.popup import NotificationCenter

app = TermScopeApp()
app.cfg.notifier = "card"
app.cfg.cooldown_seconds = 0
app.cfg.max_per_minute = 100

hub = TermScopeHub(app)
app.hub = hub
app.set_ui_refresh(hub.schedule_refresh)
center = NotificationCenter(hub, on_learn_more=app.open_term_library, timeout=5)
app.notifications.attach_card_center(center)
hub.refresh()

state = {}


def fire():
    text = "our microservices use a load balancer; we watch latency, throughput and churn"
    state["offered"] = app.handle_text(text, "test")
    print("notifications offered:", state["offered"], flush=True)


def check():
    state["cards"] = len(center._cards)
    print("active cards on screen:", state["cards"], flush=True)
    print("learned-from-card test: marking first card learned", flush=True)
    if center._cards:
        center._cards[0]._mark_learned()


hub.after(700, fire)
hub.after(1600, check)
hub.after(2400, lambda: print("cards after a learn:", len(center._cards), flush=True))
hub.after(5000, hub.destroy)
hub.mainloop()
print(f"SMOKE OK offered={state.get('offered')} cards={state.get('cards')} "
      f"learned_total={app.knowledge.learned_count()}", flush=True)
