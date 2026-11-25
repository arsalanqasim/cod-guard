"""Fit a tenant-bound shadow artifact from that seller's own settled orders."""
import argparse
import hashlib
import json
from pathlib import Path
import pickle
import re
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
sys.path.insert(0, str(ROOT / "scripts/experiments"))

from evaluate_round9 import candidate_actions, pk_real, score, select_bands
from artifacts import atomic_write
from records import DEMO_TENANT
from risk_candidate import FEATURES, fit_model
from risk_shadow import SOURCE

SELLER_COLUMNS = ("order_id", "customer_id", "order_day", "amount_pkr", "items_count", "label_failed")


def read_seller_csv(path):
    frame = pd.read_csv(path, dtype="string")
    if set(frame.columns) != set(SELLER_COLUMNS) or frame.isna().any().any():
        raise ValueError("Use the documented seller CSV schema with complete records")
    for key in ("order_id", "customer_id"):
        frame[key] = frame[key].str.strip()
        if frame[key].eq("").any():
            raise ValueError("Order and customer identifiers must be nonblank")
    if not frame["order_id"].is_unique:
        raise ValueError("Use one row per order")
    frame["order_day"] = pd.to_datetime(frame["order_day"], format="%Y-%m-%d", errors="raise")
    for key in ("amount_pkr", "items_count", "label_failed"):
        frame[key] = pd.to_numeric(frame[key], errors="raise").astype(float)
    if (not np.isfinite(frame[["amount_pkr", "items_count", "label_failed"]]).all().all()
            or frame["amount_pkr"].lt(0).any() or frame["items_count"].lt(1).any()
            or frame["items_count"].mod(1).ne(0).any() or not frame["label_failed"].isin([0, 1]).all()):
        raise ValueError("Invalid amount, quantity or terminal label")
    frame["label_failed"] = frame["label_failed"].astype(int)
    previous = frame.groupby("customer_id")["order_day"].transform("min")
    frame["is_repeat_customer"] = frame["order_day"].gt(previous).astype(int)
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--seller-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-validation-false-hold-rate", type=float, default=0)
    args = parser.parse_args()
    if args.tenant == DEMO_TENANT or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.tenant):
        parser.error("Select the operator tenant for the seller who supplied the orders")
    if not 0 <= args.max_validation_false_hold_rate <= 1:
        parser.error("False hold rate must be a probability")
    source_hash = pk_real.sha256(args.seller_csv)
    frame = read_seller_csv(args.seller_csv)
    if pk_real.sha256(args.seller_csv) != source_hash:
        raise ValueError("Seller CSV changed during training setup")
    train, val, test = pk_real.split_customers_and_time(frame)
    calibration, validation = pk_real.validation_partitions(val)
    if any(group["label_failed"].nunique() != 2 for group in (calibration, validation)):
        raise ValueError("Both chronological validation halves require both terminal labels")
    estimator, brier = fit_model(train, calibration, validation)
    labels = validation["label_failed"].to_numpy()
    bands, _ = select_bands(labels, estimator.predict(validation[list(FEATURES)]),
                            np.zeros(len(labels), dtype=bool), args.max_validation_false_hold_rate)
    settings = {"verify_at": bands.verify_at, "hold_at": bands.hold_at}
    identity = f"seller-r9-v1:{args.tenant}:{source_hash}:{args.max_validation_false_hold_rate}"
    model_id = "seller-r9-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
    bundle = {"version": 1, "source": SOURCE, "tenant": args.tenant, "model_id": model_id,
              "estimator": estimator, "bands": settings}
    scores = estimator.predict(test[list(FEATURES)])
    metrics = score(test["label_failed"].to_numpy(), candidate_actions(
        scores, bands, np.zeros(len(scores), dtype=bool)), scores)
    atomic_write(args.output, pickle.dumps(bundle))
    print(json.dumps({"mode": "shadow", "source": SOURCE, "model_id": model_id,
                      "calibration_validation_brier": brier, "bands": settings, "holdout": metrics}, indent=2))


if __name__ == "__main__":
    main()
