"""Transactional projections over normalized SQLite records."""
from contextlib import contextmanager

from records import (DEMO_TENANT, add_decision, add_message, add_model_version, add_outcome,
                     audit, connect, write)


def _where(tenant_id, order_ids):
    if order_ids is None:
        return "tenant_id=?", (tenant_id,)
    placeholders = ", ".join("?" for _ in order_ids)
    return f"tenant_id=? AND order_id IN ({placeholders})", (tenant_id, *order_ids)


def state_snapshot(connection, tenant_id=DEMO_TENANT, order_ids=None, *, messages=True):
    where, parameters = _where(tenant_id, order_ids)
    state = {key: {} for key in ("decisions", "outcomes", "outcome_decisions", "messages", "events")}
    revisions = {}
    for row in connection.execute(f"SELECT * FROM decisions WHERE {where} ORDER BY revision", parameters):
        decision = dict(row)
        decision.pop("tenant_id")
        order_id = decision.pop("order_id")
        default_snapshot = decision.pop("default_snapshot")
        decision["kind"] = "decision"
        state["events"].setdefault(order_id, []).append(decision)
        revisions[(order_id, decision["revision"])] = decision
        if not default_snapshot:
            state["decisions"][order_id] = decision
    for row in connection.execute(f"SELECT * FROM outcomes WHERE {where} ORDER BY revision", parameters):
        outcome = dict(row)
        outcome.pop("tenant_id")
        order_id = outcome.pop("order_id")
        outcome.update(kind="outcome", correction=bool(outcome["correction"]))
        state["events"].setdefault(order_id, []).append(outcome)
        state["outcomes"][order_id] = outcome["outcome"]
        if snapshot := revisions.get((order_id, outcome["decision_revision"])):
            state["outcome_decisions"][order_id] = snapshot
    for history in state["events"].values():
        history.sort(key=lambda event: event["revision"])
    if messages:
        for row in connection.execute(f"SELECT * FROM messages WHERE {where} ORDER BY id", parameters):
            message = dict(row)
            message.pop("tenant_id")
            message.pop("id")
            state["messages"].setdefault(message.pop("order_id"), []).append(message)
    return state


def read_state(path, tenant_id=DEMO_TENANT, order_ids=None, *, messages=True):
    with connect(path) as connection:
        connection.execute("BEGIN")
        return state_snapshot(connection, tenant_id, order_ids, messages=messages)


@contextmanager
def transaction(path, tenant_id=DEMO_TENANT, order_ids=None):
    with write(path) as connection:
        state = state_snapshot(connection, tenant_id, order_ids)
        event_counts = {key: len(events) for key, events in state["events"].items()}
        message_counts = {key: len(messages) for key, messages in state["messages"].items()}
        yield state
        for order_id, events in state["events"].items():
            for event in events[event_counts.get(order_id, 0):]:
                if event["kind"] == "decision":
                    add_decision(connection, tenant_id, order_id, event)
                else:
                    add_outcome(connection, tenant_id, order_id, event)
                audit(connection, tenant_id, event["actor"], event["kind"],
                      order_id=order_id, reference=str(event["revision"]))
        for order_id, messages in state["messages"].items():
            for message in messages[message_counts.get(order_id, 0):]:
                add_message(connection, tenant_id, order_id, message)
        if state.get("training"):
            add_model_version(connection, tenant_id, state["training"])
