"""Freeze the real order cohorts and compare the current and model-first policies."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
import pk_real
from risk_candidate import Bands, FEATURES, fit_model
import service
from train_model import fit_and_evaluate, split_benchmark

LOCK = ROOT / "data/pk_real.v1.lock.json"
FALSE_SHIP_PKR = 650
FALSE_HOLD_PKR = 450
VERIFY_PKR = 50
VERIFY_RESOLUTION = .60
SHIP, VERIFY, HOLD = 0, 1, 2


def candidate_actions(scores, bands, unreachable):
    return np.where(unreachable, VERIFY, np.where(scores >= bands.hold_at, HOLD,
                                                 np.where(scores >= bands.verify_at, VERIFY, SHIP)))


def incumbent_actions(frame, bundle=None):
    state = {"decisions": {}, "outcomes": {}}
    rows = frame.to_dict("records")
    if bundle:
        probabilities = service._batch_probabilities(bundle, rows)
    else:
        probabilities = [None] * len(rows)
    dispatch = {"SHIP": SHIP, "HOLD": HOLD, "VERIFY_FIRST": VERIFY}
    status = {"threshold": bundle["threshold"] if bundle else .50, "reason": None}
    actions = [dispatch[service._assessment(row, state, status, score)["decision"]]
               for row, score in zip(rows, probabilities)]
    return np.array(actions), None if bundle is None else np.array(probabilities, dtype=float)


def score(labels, actions, probabilities=None):
    good = labels == 0
    failed = ~good
    verified = actions == VERIFY
    held, shipped = actions == HOLD, actions == SHIP
    fp, fn = int((good & held).sum()), int((failed & shipped).sum())
    committed = int(held.sum() + shipped.sum())
    cost = FALSE_SHIP_PKR * fn + FALSE_HOLD_PKR * fp + VERIFY_PKR * verified.sum()
    cost += (1 - VERIFY_RESOLUTION) * FALSE_HOLD_PKR * (good & verified).sum()
    result = {"orders": len(labels), "failed": int(failed.sum()), "ship": int(shipped.sum()),
              "verify": int(verified.sum()), "hold": int(held.sum()), "committed": committed,
              "committed_error_rate": (fp + fn) / committed if committed else None,
              "false_holds": fp, "false_hold_rate": fp / int(good.sum()),
              "false_ships": fn, "false_ship_rate": fn / int(failed.sum()),
              "expected_pkr_per_1000": float(1000 * cost / len(labels)),
              "ece": None, "brier": None, "score_near_08": None}
    if probabilities is not None:
        bins = np.minimum((10 * probabilities).astype(int), 9)
        result["ece"] = float(sum(mask.mean() * abs(labels[mask].mean() - probabilities[mask].mean())
                                  for index in range(10) if (mask := bins == index).any()))
        result["brier"] = float(np.mean((probabilities - labels) ** 2))
        near = (probabilities >= .75) & (probabilities < .85)
        if near.any():
            result["score_near_08"] = {"n": int(near.sum()), "mean_score": float(probabilities[near].mean()),
                                       "observed_failed": float(labels[near].mean())}
    return result


def select_bands(labels, probabilities, unreachable, bound):
    grid = np.linspace(0, 1, 41)
    alternatives = []
    for index, low in enumerate(grid[:-1]):
        for high in grid[index + 1:]:
            bands = Bands(float(low), float(high))
            result = score(labels, candidate_actions(probabilities, bands, unreachable))
            if result["false_hold_rate"] <= bound:
                alternatives.append(((result["expected_pkr_per_1000"], result["false_holds"],
                                      result["false_ships"], bands.verify_at, bands.hold_at), bands, result))
    _, selected, result = min(alternatives, key=lambda candidate: candidate[0])
    return selected, result


def evaluate(real_splits):
    train, val, real_test = real_splits
    calibration, policy_val = pk_real.validation_partitions(val)
    candidate, calibration_errors = fit_model(train, calibration, policy_val)
    labels = policy_val["label_failed"].to_numpy()
    # The existing system only receives purchase-time fields actually in the source.
    incumbent, _ = incumbent_actions(policy_val[["order_id", *FEATURES]])
    bound = score(labels, incumbent)["false_hold_rate"]
    bands, validation = select_bands(labels, candidate.predict(policy_val[list(FEATURES)]),
                                     np.zeros(len(labels), dtype=bool), bound)

    synthetic = pd.read_csv(ROOT / "data/benchmark_orders.csv")
    _, _, synth_test, _ = split_benchmark(synthetic)
    served, _ = fit_and_evaluate(synthetic)
    all_metrics = {}
    for tag, test, old_bundle in (("[PK-REAL]", real_test, None), ("[PK-SYNTH]", synth_test, served)):
        observed = test["label_failed"].to_numpy()
        incumbent_input = test if old_bundle is not None else test[["order_id", *FEATURES]]
        base_actions, base_scores = incumbent_actions(incumbent_input, old_bundle)
        probabilities = candidate.predict(test[list(FEATURES)])
        unreachable = test["phone_valid"].eq(0).to_numpy() if "phone_valid" in test else np.zeros(len(test), dtype=bool)
        base = score(observed, base_actions, base_scores)
        flip = score(observed, candidate_actions(probabilities, bands, unreachable), probabilities)
        all_metrics[tag] = {"incumbent": base, "candidate": flip,
                            "cost_decreased": flip["expected_pkr_per_1000"] < base["expected_pkr_per_1000"],
                            "false_holds_within_bound": flip["false_hold_rate"] <= bound}
    gate = all(result["cost_decreased"] and result["false_holds_within_bound"] for result in all_metrics.values())
    return {"mode": "development evaluation", "training_dataset": "[PK-REAL]",
            "licence": "Unstated; development and evaluation only", "calibration": candidate.method,
            "calibration_validation_brier": calibration_errors,
            "validation": {"calibration_rows": len(calibration), "policy_rows": len(policy_val),
                           "false_hold_bound": bound, "policy_metrics": validation},
            "bands": {"verify_at": bands.verify_at, "hold_at": bands.hold_at},
            "cost_assumptions_pkr": {"false_ship": FALSE_SHIP_PKR, "false_hold": FALSE_HOLD_PKR,
                                     "verification": VERIFY_PKR, "correct_resolution_rate": VERIFY_RESOLUTION},
            "holdouts": all_metrics, "gate_passed": gate}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument("--freeze", action="store_true")
    command.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.freeze and LOCK.exists():
        parser.error("The cohort lock already exists")
    orders, source = pk_real.load_orders(args.archive)
    splits = pk_real.split_customers_and_time(orders)
    manifest = pk_real.frozen_manifest(args.archive, orders, source, splits)
    if args.freeze:
        with LOCK.open("x", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(manifest, indent=2) + "\n")
    else:
        if json.loads(LOCK.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Kaggle source or projected cohorts differ from the frozen lock")
        report = evaluate(splits)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(args.report)


if __name__ == "__main__":
    main()
