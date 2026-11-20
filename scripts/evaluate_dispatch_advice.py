"""Run Round 8 synthetic prepaid, courier and address assessments."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from random import Random
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
from address_quality import classify_address
from dispatch_advice import courier_rates, prepaid_offer, recommend_courier
import service
from train_model import split_benchmark

ADDRESS_CORPUS = ROOT / "data/address_quality.v1.jsonl"
ADDRESS_LOCK = ROOT / "data/address_quality.v1.lock.json"
COURIER_PROBABILITIES = {
    "Lahore": {"leopards": .12, "tcs": .21, "postex": .18},
    "Karachi": {"leopards": .24, "tcs": .16, "postex": .11},
    "Multan": {"leopards": .16, "tcs": .12, "postex": .22},
}


def rate(value):
    number = float(value)
    if not 0 <= number <= 1:
        raise argparse.ArgumentTypeError("Provide a probability between 0 and 1")
    return number


def prepaid_simulation(reply_rate, acceptance_given_reply, paid_given_acceptance):
    _, _, test, _ = split_benchmark(pd.read_csv(ROOT / "data/benchmark_orders.csv"))
    bundle, status = service._available_model()
    baseline = service.latest_evaluation()
    if bundle is None or baseline is None or baseline["split"]["feedback"]:
        raise ValueError("Build the synthetic baseline model before running the prepaid simulation")
    orders = test.to_dict("records")
    probabilities = service._batch_probabilities(bundle, orders)
    state = {"decisions": {}, "outcomes": {}}
    eligible = sum(prepaid_offer(service._assessment(order, state, status, prob), (5, "JazzCash")) is not None
                   for order, prob in zip(orders, probabilities))
    replies = eligible * reply_rate
    accepted = replies * acceptance_given_reply
    paid = accepted * paid_given_acceptance
    return {"mode": "synthetic simulation", "test_orders": len(orders), "offers": eligible,
            "assumptions": {"reply_rate": reply_rate, "acceptance_given_reply": acceptance_given_reply,
                            "paid_given_acceptance": paid_given_acceptance, "discount_pct": 5},
            "expected_replies": replies, "expected_accepted": accepted, "expected_prepaid": paid,
            "expected_share_of_eligible": paid / eligible if eligible else 0,
            "expected_share_of_holdout": paid / len(orders)}


def courier_replay():
    rng = Random(8800)
    history = []
    for city, couriers in COURIER_PROBABILITIES.items():
        for courier, probability in couriers.items():
            history.append({"city": city, "courier": courier, "n": 100,
                            "returns": sum(rng.random() < probability for _ in range(100))})
    rates = courier_rates(history)
    delivered = matched = considered = 0
    observed = expected_actual = expected_recommended = 0.0
    by_city = {}
    for city, couriers in COURIER_PROBABILITIES.items():
        recommendation = recommend_courier(rates, city)
        by_city[city] = recommendation
        for _ in range(120):
            chosen = rng.choice(tuple(couriers))
            returned = rng.random() < couriers[chosen]
            if not recommendation:
                continue
            recommended = recommendation["courier"]
            considered += 1
            observed += returned
            expected_actual += couriers[chosen]
            expected_recommended += couriers[recommended]
            if not returned:
                delivered += 1
                matched += chosen == recommended
    return {"mode": "synthetic replay", "history": 900, "test": 360, "recommended": considered,
            "matched_delivered": matched, "delivered": delivered,
            "accuracy_among_delivered": matched / delivered if delivered else None,
            "observed_return_rate": observed / considered if considered else None,
            "expected_assigned_rate": expected_actual / considered if considered else None,
            "expected_recommended_rate": expected_recommended / considered if considered else None,
            "counterfactual_return_rate_change": (expected_recommended - expected_actual) / considered
            if considered else None, "by_city": by_city}


def address_evaluation():
    corpus = ADDRESS_CORPUS.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in corpus.splitlines()]
    lock = json.loads(ADDRESS_LOCK.read_text(encoding="utf-8"))
    if len(rows) != lock["n"] or hashlib.sha256(corpus.encode()).hexdigest() != lock["sha256"]:
        raise ValueError("Address benchmark differs from its frozen version")
    exact, cases = 0, Counter()
    reasons = {}
    failures = []
    for row in rows:
        expected = set(row["issues"])
        predicted = set(classify_address(row["address"], row["city"]))
        cases[("flagged" if expected else "clear") + ("_flagged" if predicted else "_clear")] += 1
        for reason in expected | predicted:
            score = reasons.setdefault(reason, Counter())
            score["tp" if reason in expected and reason in predicted else "fn" if reason in expected else "fp"] += 1
        exact += expected == predicted
        if expected != predicted:
            failures.append({"id": row["id"], "expected": sorted(expected), "predicted": sorted(predicted)})
    return {"mode": "synthetic labelled corpus", "n": len(rows), "exact": exact,
            "accuracy": (cases["flagged_flagged"] + cases["clear_clear"]) / len(rows),
            "confusion": dict(cases), "reasons": reasons, "failures": failures}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reply-rate", type=rate, default=.60)
    parser.add_argument("--accept-rate", type=rate, default=.30)
    parser.add_argument("--payment-rate", type=rate, default=.80)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"prepaid": prepaid_simulation(args.reply_rate, args.accept_rate, args.payment_rate),
              "courier": courier_replay(), "address": address_evaluation()}
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
