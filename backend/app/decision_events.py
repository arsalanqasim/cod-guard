"""Append-only decision and outcome revisions for one order."""
from datetime import datetime, timezone


def append_event(state, order_id, kind, actor, **fields):
    events = state.setdefault("events", {}).setdefault(order_id, [])
    event = {"revision": events[-1]["revision"] + 1 if events else 1,
             "at": datetime.now(timezone.utc).isoformat(), "actor": actor,
             "kind": kind, **fields}
    events.append(event)
    return event
