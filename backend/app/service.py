"""Shared application service for the API and exhibition dashboard.

Synthetic benchmark labels never replace marked outcomes. Dispatch decisions
are frozen when an outcome is first recorded, so later replies/model versions
cannot rewrite the historical confusion matrix.
"""
import os
import json
import pickle
from functools import lru_cache
from logging import getLogger
from pathlib import Path

import pandas as pd

from risk_engine import OPTIONAL_MODEL_FEATURES, assess as rule_assess
from verification import parse_reply, apply_reply, opening_message
from artifacts import active_version
from storage import queue_snapshot, read_state, transaction
from decision_events import append_event
from records import (DEMO_TENANT, ORDER_FIELDS, StateUnavailable, add_model_version, audit,
                     connect, ensure_seeded, select_orders, select_page, write)
from model_schema import probabilities, validate_bundle
from jobs import JobQueue

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("COD_GUARD_DATA_DIR", ROOT / "data"))
STATE_PATH = DATA_DIR / "state.json"
SEED_PATH = ROOT / "data/demo_orders.csv"
MODEL_PATH = Path(os.environ.get("COD_GUARD_MODEL_PATH", ROOT / "backend/app/model.pkl"))
OUTCOMES = ("delivered", "returned", "refused")
RETRAIN_JOBS = JobQueue(workers=1, capacity=1)


def _load_state(tenant_id=DEMO_TENANT, order_ids=None, *, messages=True):
    return read_state(STATE_PATH, tenant_id, order_ids, messages=messages)


@lru_cache(maxsize=2)
def _cached_bundle(path, modified_ns, size):
    with open(path, "rb") as handle:
        bundle = pickle.load(handle)
    return validate_bundle(bundle)


def _read_bundle(path):
    if not path.exists():
        return None
    stat = path.stat()
    return _cached_bundle(str(path), stat.st_mtime_ns, stat.st_size)


def _bundle():
    version = active_version(MODEL_PATH)
    return _read_bundle(version / "model.pkl" if version else MODEL_PATH)


def _available_model():
    try:
        bundle = _bundle()
    except Exception as exc:
        return None, {"available": False, "reason": f"Model unavailable: {type(exc).__name__}: {exc}", "threshold": 0.60}
    if bundle is None:
        return None, {"available": False, "reason": "No trained model; run backend/app/train_model.py", "threshold": 0.60}
    return bundle, {"available": True, "threshold": bundle["threshold"],
                    "model_id": bundle.get("model_id", "legacy-model"),
                    "model_name": bundle.get("model_name", "HistGradientBoostingClassifier"),
                    "trained_at": bundle.get("trained_at"), "version": bundle.get("version", 0),
                    "feedback": bundle.get("feedback", {}), "reason": None}


def model_status():
    return _available_model()[1]


def load_orders(tenant_id=DEMO_TENANT):
    if tenant_id == DEMO_TENANT:
        ensure_seeded(STATE_PATH, SEED_PATH)
    with connect(STATE_PATH) as connection:
        return pd.DataFrame(select_orders(connection, tenant_id), columns=("tenant_id", *ORDER_FIELDS))


def get_order(order_id, tenant_id=DEMO_TENANT):
    if tenant_id == DEMO_TENANT:
        ensure_seeded(STATE_PATH, SEED_PATH)
    with connect(STATE_PATH) as connection:
        matches = select_orders(connection, tenant_id, order_id=order_id)
    if not matches:
        raise KeyError(order_id)
    return matches[0]


def _ml_probability(order):
    try:
        bundle = _bundle()
    except Exception:
        return None  # model_status exposes the failure to the UI/API
    return _batch_probabilities(bundle, [order])[0]


def _model_row(order, columns):
    if not order.get("city") or any(order.get(key) is None for key in columns if not key.startswith("city_")):
        return None
    row = {column: order.get(column, 0) for column in columns}
    city_column = f"city_{order.get('city')}"
    if city_column in row:
        row[city_column] = 1
    return row


def _batch_probabilities(bundle, orders):
    results = [None] * len(orders)
    if bundle is None:
        return results
    rows = [(index, row) for index, order in enumerate(orders)
            if (row := _model_row(order, bundle["columns"])) is not None]
    if rows:
        try:
            values = probabilities(bundle, pd.DataFrame([row for _, row in rows], columns=bundle["columns"]))
        except Exception:
            return results
        for (index, _), probability in zip(rows, values):
            results[index] = float(probability)
    return results


def assess_order(order, *, state=None, tenant_id=DEMO_TENANT):
    if state is None:
        state = _load_state(tenant_id, (order["order_id"],), messages=False)
    return _assessment(order, state, model_status(), _ml_probability(order))


def _assessment(order, state, status, probability):
    order = {key: value for key, value in order.items() if value is not None}
    risk = rule_assess(order, ml_probability=probability, threshold=status["threshold"])
    missing_model_features = OPTIONAL_MODEL_FEATURES - order.keys()
    if not order.get("city") or missing_model_features:
        if risk["zone"] == "GREEN":
            risk["zone"] = "AMBER"
        risk["reasons"].append("Missing order features; request verification")
    saved = state["decisions"].get(order["order_id"])
    decision = saved or apply_reply(risk["zone"], "UNCLEAR")
    return {"order_id": order["order_id"], "rule_score": risk["risk_score"],
            "ml_probability": round(probability, 3) if probability is not None else None,
            "zone": risk["zone"], "reasons": risk["reasons"],
            "signal_count": risk["signal_count"], "signals": risk["signals"],
            "decision": decision["decision"], "decision_why": decision["why"],
            "verified": bool(saved), "intent": (saved or {}).get("intent"),
            "needs_review": bool((saved or {}).get("needs_review")),
            "outcome": state["outcomes"].get(order["order_id"]),
            "model_id": status.get("model_id"), "model_error": status["reason"]}


def order_page(tenant_id=DEMO_TENANT, *, limit=50, offset=0, search=""):
    if tenant_id == DEMO_TENANT:
        ensure_seeded(STATE_PATH, SEED_PATH)
    with connect(STATE_PATH) as connection:
        connection.execute("BEGIN")
        orders, total = select_page(connection, tenant_id, limit, offset, search)
        state = queue_snapshot(connection, tenant_id, tuple(order["order_id"] for order in orders))
    bundle, status = _available_model()
    scores = _batch_probabilities(bundle, orders)
    return orders, [_assessment(order, state, status, score) for order, score in zip(orders, scores)], total


def verify_reply(order, reply_text, source="text", *, actor="local-demo", tenant_id=DEMO_TENANT):
    with transaction(STATE_PATH, tenant_id, (order["order_id"],)) as state:
        return apply_verification(state, order, reply_text, parse_reply(reply_text), source, actor)


def apply_verification(state, order, reply_text, intent, source, actor):
    assessment = assess_order(order, state=state)
    result = apply_reply(assessment["zone"], intent)
    previous = state["decisions"].get(order["order_id"])
    effective_intent = intent
    if intent == "UNCLEAR":
        result["why"] += ". Please clarify with the customer."
    if intent == "UNCLEAR" and previous and previous.get("intent") in ("CONFIRM", "DENY"):
        effective_intent = previous["intent"]
        result = {"decision": previous["decision"],
                  "why": "Reply unclear; keeping the customer's previous explicit answer. Please clarify."}
    event = append_event(state, order["order_id"], "decision", actor, **result,
                         intent=effective_intent, zone=assessment["zone"], model_id=assessment["model_id"],
                         needs_review=intent == "UNCLEAR")
    state["decisions"][order["order_id"]] = event.copy()
    state["messages"].setdefault(order["order_id"], []).append({
        "text": reply_text, "source": source, "intent": intent, **result,
        "at": event["at"], "actor": actor, "decision_revision": event["revision"]})
    return {"intent": intent, "needs_review": intent == "UNCLEAR", **result}


def conversation(order_id, tenant_id=DEMO_TENANT):
    return _load_state(tenant_id, (order_id,))["messages"].get(order_id, [])


def mark_outcome(order_id, outcome, *, actor="local-demo", tenant_id=DEMO_TENANT):
    if outcome not in OUTCOMES:
        raise ValueError("Outcome must be delivered, returned, or refused")
    order = get_order(order_id, tenant_id)
    with transaction(STATE_PATH, tenant_id, (order_id,)) as state:
        return apply_outcome(state, order, outcome, actor)


def apply_outcome(state, order, outcome, actor):
    order_id = order["order_id"]
    snapshot = state["outcome_decisions"].get(order_id)
    if snapshot is None and order_id not in state["outcomes"]:
        assessment = assess_order(order, state=state)
        decision = state["decisions"].get(order_id)
        if not decision or "revision" not in decision:
            decision = append_event(state, order_id, "decision", actor,
                                    decision=assessment["decision"], why=assessment["decision_why"],
                                    zone=assessment["zone"], model_id=assessment["model_id"],
                                    intent=assessment["intent"], default_snapshot=True)
        snapshot = state["outcome_decisions"][order_id] = decision.copy()
    event = append_event(state, order_id, "outcome", actor, outcome=outcome,
                         decision_revision=(snapshot or {}).get("revision"),
                         correction=order_id in state["outcomes"])
    state["outcomes"][order_id] = outcome
    return event.copy()


def live_metrics(tenant_id=DEMO_TENANT):
    state = _load_state(tenant_id, messages=False)
    tp = fp = fn = tn = unscored = 0
    known_ids = set(load_orders(tenant_id)["order_id"])
    for order_id, outcome in state["outcomes"].items():
        if order_id not in known_ids or outcome not in OUTCOMES:
            continue
        decision = state["outcome_decisions"].get(order_id)
        if not decision:
            unscored += 1
            continue
        shipped = decision["decision"] == "SHIP"
        failed = outcome != "delivered"
        if shipped and failed:
            fn += 1
        elif shipped:
            tn += 1
        elif failed:
            tp += 1
        else:
            fp += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "unscored": unscored,
            "marked": tp + fp + fn + tn,
            "fp_rate": fp / (fp + tn) if fp + tn else None,
            "fn_rate": fn / (fn + tp) if fn + tp else None,
            "source": ("Marked demo outcomes; not real merchant performance" if tenant_id == DEMO_TENANT
                       else "Marked shadow outcomes; observational comparison only")}


def latest_evaluation():
    try:
        version = active_version(MODEL_PATH)
        if version is not None:
            bundle = _read_bundle(version / "model.pkl")
            report = json.loads((version / "evaluation.json").read_text(encoding="utf-8"))
            if bundle and isinstance(report, dict) and report.get("model_id") == bundle.get("model_id"):
                return report
            return None
    except Exception:
        return None
    status = model_status()
    for path in [STATE_PATH.parent / "latest_evaluation.json", ROOT / "data/evaluation.json"]:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(report, dict) and report.get("model_id") == status.get("model_id"):
            return report
    return None


def learning_status(tenant_id=DEMO_TENANT):
    if tenant_id != DEMO_TENANT:
        return {"recorded": 0, "trained_outcomes": 0, "pending": 0, "model_id": None, "version": 0}
    status = model_status()
    state = _load_state(messages=False)
    known = set(load_orders()["order_id"])
    outcomes = {key: value for key, value in state["outcomes"].items()
                if key in known and value in OUTCOMES}
    trained = status.get("feedback", {})
    return {"recorded": len(outcomes), "trained_outcomes": len(trained),
            "pending": sum(trained.get(key) != value for key, value in outcomes.items()),
            "model_id": status.get("model_id"), "version": status.get("version", 0)}


def retrain_model(*, actor="local-demo"):
    """Fit from a state snapshot. Feedback arriving later remains pending."""
    from train_model import fit_and_evaluate, publish, render_report
    record_access(DEMO_TENANT, actor, "retrain")
    orders = load_orders()
    known = set(orders["order_id"])
    state = _load_state(messages=False)
    feedback = {key: value for key, value in sorted(state["outcomes"].items())
                if key in known and value in OUTCOMES}
    version = active_version(MODEL_PATH)
    current = _read_bundle(version / "model.pkl" if version else MODEL_PATH) or {}
    if not feedback or feedback == current.get("feedback", {}):
        raise ValueError("No new or corrected demo outcomes to learn from")
    observed = orders[orders["order_id"].isin(feedback)].copy()
    observed["label_failed"] = observed["order_id"].map(lambda key: int(feedback[key] != "delivered"))
    benchmark = pd.read_csv(ROOT / "data/benchmark_orders.csv")
    bundle, report = fit_and_evaluate(benchmark, observed, feedback,
                                      previous_version=current.get("version", 0))
    publish(bundle, report, render_report(report), MODEL_PATH, expected=version)
    # The activated pair is authoritative. A secondary metadata write cannot
    # turn an already activated version into a failed serving job.
    try:
        with write(STATE_PATH) as connection:
            add_model_version(connection, DEMO_TENANT, bundle)
    except StateUnavailable:
        getLogger(__name__).exception("Could not update SQLite metadata for activated model %s", bundle["model_id"])
    return {"ok": True, "model_id": bundle["model_id"], "version": bundle["version"],
            "feedback_count": len(feedback), "training_rows": report["split"]["training"],
            "test": report["chosen"], "source": "Marked SYNTHETIC demo outcomes"}


def record_access(tenant_id, actor, action, *, order_id=None):
    with write(STATE_PATH) as connection:
        audit(connection, tenant_id, actor, action, order_id=order_id)


def check_state():
    ensure_seeded(STATE_PATH, SEED_PATH)
    with connect(STATE_PATH) as connection:
        connection.execute("SELECT order_id FROM orders LIMIT 1").fetchone()
        connection.execute("SELECT revision FROM decisions LIMIT 1").fetchone()
        connection.execute("SELECT revision FROM outcomes LIMIT 1").fetchone()


__all__ = ["load_orders", "get_order", "assess_order", "verify_reply", "mark_outcome",
           "live_metrics", "opening_message", "conversation", "model_status",
           "learning_status", "retrain_model", "latest_evaluation"]
