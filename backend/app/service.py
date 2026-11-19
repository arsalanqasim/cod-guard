"""Shared COD-Guard service layer — used by both the FastAPI backend and
the Streamlit dashboard, so the demo behaves identically either way.

State (verification decisions + marked outcomes) lives in
data/state.json: the closed learning loop in its simplest form.
"""
import json, pickle
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "data/state.json"
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from risk_engine import assess as rule_assess          # noqa: E402
from verification import parse_reply, apply_reply, opening_message  # noqa: E402

def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"decisions": {}, "outcomes": {}}

def _save_state(s: dict) -> None:
    STATE_PATH.write_text(json.dumps(s, indent=1))

def load_orders() -> pd.DataFrame:
    return pd.read_csv(ROOT / "data/demo_orders.csv")

def _ml_probability(order: dict):
    pkl = ROOT / "backend/app/model.pkl"
    if not pkl.exists():
        return None
    try:
        with open(pkl, "rb") as f:
            bundle = pickle.load(f)
        row = {c: 0 for c in bundle["columns"]}
        for k, v in order.items():
            if k in row:
                row[k] = v
        city_col = f"city_{order.get('city')}"
        if city_col in row:
            row[city_col] = 1
        import pandas as pd
        return float(bundle["model"].predict_proba(pd.DataFrame([row]))[0][1])
    except Exception:
        return None

def assess_order(order: dict) -> dict:
    """Rules zone + ML probability, blended: ML can raise a zone, the
    rules' plain-words reasons always stay visible."""
    r = rule_assess(order)
    p = _ml_probability(order)
    zone = r["zone"]
    if p is not None:
        if p >= 0.60 and zone == "GREEN":
            zone = "AMBER"
        elif p >= 0.80 and zone == "AMBER":
            zone = "RED"
    state = _load_state()
    saved = state["decisions"].get(order["order_id"])
    return {"order_id": order["order_id"], "rule_score": r["risk_score"],
            "ml_probability": (round(p, 3) if p is not None else None),
            "zone": zone, "reasons": r["reasons"],
            "decision": (saved or {}).get("decision"),
            "decision_why": (saved or {}).get("why"),
            "outcome": state["outcomes"].get(order["order_id"])}

def verify_reply(order: dict, reply_text: str) -> dict:
    a = assess_order(order)
    intent = parse_reply(reply_text)
    result = apply_reply(a["zone"], intent)
    state = _load_state()
    state["decisions"][order["order_id"]] = result
    _save_state(state)
    return {"intent": intent, **result}

def mark_outcome(order_id: str, outcome: str) -> None:
    state = _load_state()
    state["outcomes"][order_id] = outcome   # delivered / returned / refused
    _save_state(state)

def live_metrics() -> dict:
    """Confusion of final decisions vs ground truth, over orders whose
    outcome has been marked — the demo's live FP/FN view.
    Decision SHIP vs not; truth failed (label 1) vs delivered (0)."""
    df = load_orders()
    state = _load_state()
    tp = fp = fn = tn = 0
    for _, row in df.iterrows():
        oid = row["order_id"]
        if oid not in state["outcomes"] or oid not in state["decisions"]:
            continue
        shipped = state["decisions"][oid]["decision"] == "SHIP"
        failed = int(row["label_failed"]) == 1
        if shipped and failed: fn += 1
        elif shipped and not failed: tn += 1
        elif not shipped and failed: tp += 1
        else: fp += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "marked": tp + fp + fn + tn,
            "fp_rate": (fp / (fp + tn)) if (fp + tn) else None,
            "fn_rate": (fn / (fn + tp)) if (fn + tp) else None}

__all__ = ["load_orders", "assess_order", "verify_reply", "mark_outcome",
           "live_metrics", "opening_message"]
