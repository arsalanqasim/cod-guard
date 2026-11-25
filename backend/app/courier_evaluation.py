"""Host-only, non-publishing evaluation of consented tenant outcome feedback."""

import argparse
import json

import numpy as np
import pandas as pd

import service
from records import DEMO_TENANT, connect, select_orders
from storage import state_snapshot
from train_model import FEATURES, fit_and_evaluate


def run(tenant_id):
    if tenant_id == DEMO_TENANT:
        raise ValueError("Use a separately authorized shadow tenant")
    with connect(service.STATE_PATH, tenant_id=tenant_id) as db:
        db.execute("BEGIN")
        evidence = {row["order_id"]: row["outcome"] for row in db.execute(
            "SELECT order_id, outcome FROM courier_outcome_evidence WHERE tenant_id=?", (tenant_id,))}
        if not evidence:
            raise ValueError("No eligible courier evidence")
        outcomes = state_snapshot(db, tenant_id, messages=False)["outcomes"]
        orders = select_orders(db, tenant_id)
    rows, feedback = [], {}
    for order in orders:
        order_id = order["order_id"]
        outcome = evidence.get(order_id)
        if outcome is None or outcomes.get(order_id) != outcome or order["data_source"].casefold() == "synthetic":
            continue
        features = {key: order[key] for key in FEATURES}
        if any(value is None or not np.isfinite(value) for value in features.values()) or not order["city"]:
            continue
        masked_id = f"courier-shadow-{len(rows):08d}"
        feedback[masked_id] = outcome
        rows.append({**features, "city": order["city"], "order_id": masked_id, "label_failed": int(outcome != "delivered")})
    if not rows:
        raise ValueError("No complete, unconflicted courier outcomes for shadow evaluation")
    benchmark = pd.read_csv(service.ROOT / "data/benchmark_orders.csv")
    _, baseline = fit_and_evaluate(benchmark)
    _, candidate = fit_and_evaluate(benchmark, pd.DataFrame(rows), feedback)
    reference, result = baseline["chosen"], candidate["chosen"]
    keys = ("fp_rate", "fn_rate", "total_cost")
    return {"mode": "shadow-only", "test_source": "SYNTHETIC", "eligible_training_rows": len(rows),
            "excluded_evidence_rows": len(evidence) - len(rows), "baseline": reference, "candidate": result,
            "locked_non_regression": all(result[key] <= reference[key] for key in keys),
            "holdout_sha256": candidate["split"]["test_labels_sha256"], "published": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--authorized-training", action="store_true", required=True)
    arguments = parser.parse_args()
    try:
        print(json.dumps(run(arguments.tenant), indent=2))
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
