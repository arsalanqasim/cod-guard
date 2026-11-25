"""Transactional projections over normalized SQLite records."""
from contextlib import contextmanager
import risk_shadow
from merchant_events import queue_order_event

from records import (DEMO_TENANT, add_decision, add_message, add_model_version, add_outcome,
                     audit, connect, reply_text, write)


def _where(tenant_id, order_ids):
    if order_ids is None:
        return "tenant_id=?", (tenant_id,)
    if not order_ids:
        return "tenant_id=? AND 1=0", (tenant_id,)
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
            message["text"] = reply_text(connection, tenant_id, row["order_id"], row["text"])
            message.pop("tenant_id")
            message.pop("id")
            state["messages"].setdefault(message.pop("order_id"), []).append(message)
    return state


def queue_snapshot(connection, tenant_id, order_ids):
    state = {"decisions": {}, "outcomes": {}}
    if not order_ids:
        return state
    where, parameters = _where(tenant_id, order_ids)
    for table, key in (("decisions", "decisions"), ("outcomes", "outcomes")):
        visible = " AND default_snapshot=0" if table == "decisions" else ""
        rows = connection.execute(f"""SELECT event.* FROM {table} AS event JOIN (
            SELECT order_id, MAX(revision) AS revision FROM {table}
            WHERE {where}{visible} GROUP BY order_id
            ) AS latest USING (order_id, revision) WHERE event.tenant_id=?""", (*parameters, tenant_id))
        for row in rows:
            state[key][row["order_id"]] = dict(row) if table == "decisions" else row["outcome"]
    return state


def read_state(path, tenant_id=DEMO_TENANT, order_ids=None, *, messages=True):
    with connect(path, tenant_id=tenant_id, snapshot=True) as connection:
        return state_snapshot(connection, tenant_id, order_ids, messages=messages)


@contextmanager
def transaction(path, tenant_id=DEMO_TENANT, order_ids=None):
    with write(path, tenant_id=tenant_id) as connection:
        with update_state(connection, tenant_id, order_ids) as state:
            yield state


@contextmanager
def update_state(connection, tenant_id, order_ids):
    state = state_snapshot(connection, tenant_id, order_ids)
    event_counts = {key: len(events) for key, events in state["events"].items()}
    message_counts = {key: len(messages) for key, messages in state["messages"].items()}
    yield state
    for order_id, events in state["events"].items():
        for event in events[event_counts.get(order_id, 0):]:
            if event["kind"] == "decision":
                add_decision(connection, tenant_id, order_id, event)
                risk_shadow.record(connection, tenant_id, order_id, event)
            else:
                add_outcome(connection, tenant_id, order_id, event)
                if event.get("correction"):
                    connection.execute("""DELETE FROM network_contributions
                        WHERE tenant_id=? AND order_id=? AND outcome<>?""",
                                       (tenant_id, order_id, event["outcome"]))
            audit(connection, tenant_id, event["actor"], event["kind"],
                  order_id=order_id, reference=str(event["revision"]))
            if getattr(connection, "encrypted", False):
                fields = {key: event[key] for key in ("revision", "at", "decision", "intent", "needs_review",
                                                     "outcome", "decision_revision") if key in event}
                kind = "order.outcome" if event["kind"] == "outcome" else "order.decision"
                if event.get("default_snapshot"):
                    continue
                queue_order_event(connection, tenant_id, order_id, kind, fields)
    for order_id, messages in state["messages"].items():
        for message in messages[message_counts.get(order_id, 0):]:
            add_message(connection, tenant_id, order_id, message)
    if state.get("training"):
        add_model_version(connection, tenant_id, state["training"])
