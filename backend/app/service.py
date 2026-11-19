"""Shared application service for the API and exhibition dashboard.

Synthetic benchmark labels never replace marked outcomes. Dispatch decisions
are frozen when an outcome is first recorded, so later replies/model versions
cannot rewrite the historical confusion matrix.
"""
import os
import pickle
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd

from risk_engine import assess as rule_assess
from verification import parse_reply, apply_reply, opening_message
from storage import read_state, transaction

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("COD_GUARD_DATA_DIR", ROOT / "data"))
STATE_PATH = DATA_DIR / "state.json"
MODEL_PATH = Path(os.environ.get("COD_GUARD_MODEL_PATH", ROOT / "backend/app/model.pkl"))
OUTCOMES = ("delivered", "returned", "refused")


def _load_state():
    return read_state(STATE_PATH)


@lru_cache(maxsize=2)
def _cached_bundle(path, modified_ns, size):
    with open(path, "rb") as handle:
        bundle = pickle.load(handle)
    if not all(key in bundle for key in ("model", "columns", "threshold")):
        raise ValueError("Model bundle is missing its schema or operating threshold")
    return bundle


def _bundle():
    if not MODEL_PATH.exists():
        return None
    stat = MODEL_PATH.stat()
    return _cached_bundle(str(MODEL_PATH), stat.st_mtime_ns, stat.st_size)


def model_status():
    try:
        bundle = _bundle()
        if bundle is None:
            return {"available": False, "reason": "No trained model; run backend/app/train_model.py", "threshold": 0.60}
        return {"available": True, "threshold": bundle["threshold"],
                "model_id": bundle.get("model_id", "legacy-model"),
                "model_name": bundle.get("model_name", "HistGradientBoostingClassifier"),
                "trained_at": bundle.get("trained_at"),
                "feedback": bundle.get("feedback", {}),
                "reason": None}
    except Exception as exc:
        return {"available": False, "reason": f"Model unavailable: {type(exc).__name__}: {exc}", "threshold": 0.60}


def load_orders():
    return pd.read_csv(ROOT / "data/demo_orders.csv", dtype={"order_id": str, "phone": str})


def get_order(order_id):
    rows = load_orders()
    matches = rows[rows["order_id"] == order_id]
    if matches.empty:
        raise KeyError(order_id)
    return matches.iloc[0].to_dict()


def _ml_probability(order):
    try:
        bundle = _bundle()
    except Exception:
        return None  # model_status exposes the failure to the UI/API
    if bundle is None:
        return None
    row = {column: order.get(column, 0) for column in bundle["columns"]}
    city_column = f"city_{order.get('city')}"
    if city_column in row:
        row[city_column] = 1
    return float(bundle["model"].predict_proba(pd.DataFrame([row], columns=bundle["columns"]))[0][1])


def assess_order(order):
    status = model_status()
    probability = _ml_probability(order)
    risk = rule_assess(order, ml_probability=probability, threshold=status["threshold"])
    state = _load_state()
    saved = state["decisions"].get(order["order_id"])
    decision = saved or apply_reply(risk["zone"], "UNCLEAR")
    return {"order_id": order["order_id"], "rule_score": risk["risk_score"],
            "ml_probability": round(probability, 3) if probability is not None else None,
            "zone": risk["zone"], "reasons": risk["reasons"],
            "signal_count": risk["signal_count"], "signals": risk["signals"],
            "decision": decision["decision"], "decision_why": decision["why"],
            "verified": bool(saved), "intent": (saved or {}).get("intent"),
            "outcome": state["outcomes"].get(order["order_id"]),
            "model_id": status.get("model_id"), "model_error": status["reason"]}


def verify_reply(order, reply_text, source="text"):
    assessment = assess_order(order)
    intent = parse_reply(reply_text)
    result = apply_reply(assessment["zone"], intent)
    with transaction(STATE_PATH) as state:
        state["decisions"][order["order_id"]] = {**result, "intent": intent}
        state["messages"].setdefault(order["order_id"], []).append({
            "text": reply_text, "source": source, "intent": intent, **result,
            "at": datetime.now(timezone.utc).isoformat()})
    return {"intent": intent, **result}


def conversation(order_id):
    return _load_state()["messages"].get(order_id, [])


def mark_outcome(order_id, outcome):
    if outcome not in OUTCOMES:
        raise ValueError("Outcome must be delivered, returned, or refused")
    assessment = assess_order(get_order(order_id))
    with transaction(STATE_PATH) as state:
        state["outcome_decisions"].setdefault(order_id, {
            "decision": assessment["decision"], "zone": assessment["zone"],
            "model_id": assessment["model_id"], "at": datetime.now(timezone.utc).isoformat()})
        state["outcomes"][order_id] = outcome


def live_metrics():
    state = _load_state()
    tp = fp = fn = tn = unscored = 0
    known_ids = set(load_orders()["order_id"])
    for order_id, outcome in state["outcomes"].items():
        if order_id not in known_ids or outcome not in OUTCOMES:
            continue
        decision = state["outcome_decisions"].get(order_id) or state["decisions"].get(order_id)
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
            "source": "Marked demo outcomes; not real merchant performance"}


__all__ = ["load_orders", "get_order", "assess_order", "verify_reply", "mark_outcome",
           "live_metrics", "opening_message", "conversation", "model_status"]
