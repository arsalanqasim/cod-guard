"""Evaluate point-in-time purchase history and selective verification on the frozen holdouts."""
import argparse
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from threadpoolctl import threadpool_limits

import pk_real
from evaluate_round9 import (
    FALSE_HOLD_PKR, FALSE_SHIP_PKR, LOCK, ROOT, SHIP, VERIFY, VERIFY_PKR,
    VERIFY_RESOLUTION, incumbent_actions, score,
)
from train_model import feature_frame, fit_and_evaluate, split_benchmark, verify_test_lock

PURCHASE_FEATURES = ("prior_orders", "prior_orders_30d", "prior_orders_90d", "prior_order_days",
                     "days_since_purchase", "relative_amount")
OUTCOME_FEATURES = ("prior_label_count", "smoothed_failure_rate", "last_proxy_failed")
BASKET_FEATURES = ("lines", "distinct_skus", "max_line_discount", "amount_per_item", "purchase_weekday")
SYNTH_OUTCOMES = ("customer_past_delivered", "customer_past_refusals")
OUTCOME_LAGS = (30, 90)
SHIP_THRESHOLDS = np.arange(5, 28) / 100
RESOLUTION_SCENARIOS = (.20, .40, VERIFY_RESOLUTION, .80)
BOOTSTRAP_REPETITIONS = 2000
MIN_RELEASE_CLUSTERS = 40


def lookup_history(targets, daily, cutoff):
    """Find the most recent cumulative row at or before each order's cutoff."""
    queries = targets[["customer_id"]].assign(history_day=cutoff, position=np.arange(len(targets)))
    matched = pd.merge_asof(
        queries.sort_values("history_day"), daily.sort_values("history_day"),
        on="history_day", by="customer_id", direction="backward",
    ).sort_values("position")
    matched.index = targets.index
    return matched


def purchase_features(targets, purchases):
    history = purchases.groupby(["customer_id", "order_day"], as_index=False).agg(
        orders=("amount_pkr", "size"), amount=("amount_pkr", "sum"),
    ).sort_values("order_day")
    groups = history.groupby("customer_id")
    history["prior_order_days"] = groups.cumcount() + 1
    history[["orders", "amount"]] = groups[["orders", "amount"]].cumsum()
    history = history.assign(last_purchase=history["order_day"]).rename(columns={"order_day": "history_day"})
    day = targets["order_day"]
    prior = lookup_history(targets, history, day - pd.Timedelta(days=1))
    count = prior["orders"].fillna(0)
    return pd.DataFrame({
        "prior_orders": count,
        "prior_orders_30d": count - lookup_history(targets, history, day - pd.Timedelta(days=31))["orders"].fillna(0),
        "prior_orders_90d": count - lookup_history(targets, history, day - pd.Timedelta(days=91))["orders"].fillna(0),
        "prior_order_days": prior["prior_order_days"].fillna(0),
        "days_since_purchase": (day - prior["last_purchase"]).dt.days,
        "relative_amount": np.log1p(targets["amount_pkr"]) - np.log1p(prior["amount"] / prior["orders"]),
    })


def lagged_outcome_features(targets, labeled_orders, days, *, observed_through=None):
    """Proxy-only sensitivity. The archive lacks actual outcome availability dates."""
    history = labeled_orders.groupby(["customer_id", "order_day"], as_index=False).agg(
        prior_label_count=("label_failed", "size"), failed=("label_failed", "sum"),
    ).sort_values("order_day")
    history["last_proxy_failed"] = history["failed"] / history["prior_label_count"]
    totals = ["prior_label_count", "failed"]
    history[totals] = history.groupby("customer_id")[totals].cumsum()
    cutoff = targets["order_day"] - pd.Timedelta(days=days)
    if observed_through is not None:
        cutoff = cutoff.clip(upper=observed_through)
    prior = lookup_history(targets, history.rename(columns={"order_day": "history_day"}), cutoff)
    count = prior["prior_label_count"].fillna(0)
    return pd.DataFrame({
        "prior_label_count": count,
        "smoothed_failure_rate": (prior["failed"].fillna(0) + 1) / (count + 2),
        "last_proxy_failed": prior["last_proxy_failed"],
    })


@dataclass(frozen=True)
class FittedRisk:
    model: HistGradientBoostingClassifier
    calibrator: LogisticRegression

    def predict(self, features):
        return self.calibrator.predict_proba(self.model.decision_function(features).reshape(-1, 1))[:, 1]


def fit_risk(train, labels, calibration, calibration_labels):
    model = HistGradientBoostingClassifier(
        max_iter=120, max_leaf_nodes=7, min_samples_leaf=40, learning_rate=.05,
        l2_regularization=15, early_stopping=False, random_state=10,
    ).fit(train, labels)
    raw = model.decision_function(calibration).reshape(-1, 1)
    calibrator = LogisticRegression().fit(raw, calibration_labels)
    return FittedRisk(model, calibrator)


def order_cost(labels, actions, resolution=VERIFY_RESOLUTION):
    return np.choose(actions, (FALSE_SHIP_PKR * labels,
                               VERIFY_PKR + (1 - resolution) * FALSE_HOLD_PKR * (1 - labels),
                               FALSE_HOLD_PKR * (1 - labels)))


def release_actions(base, probabilities, eligible, threshold):
    if threshold is None:
        return base.copy()
    return np.where((base == VERIFY) & eligible & (probabilities <= threshold), SHIP, base)


def select_release(base, probabilities, eligible, labels, groups):
    """Choose a cost-reducing cutoff using the policy-validation cohort only."""
    best_cost_delta = 0
    chosen = {"threshold": None, "released": 0, "cost_delta_pkr_per_1000": 0.0,
              "one_sided_cluster_upper_pkr_per_release": None}
    baseline_cost = order_cost(labels, base)
    largest = (base == VERIFY) & eligible & (probabilities <= SHIP_THRESHOLDS[-1])
    for threshold in SHIP_THRESHOLDS:
        actions = release_actions(base, probabilities, eligible, threshold)
        released = actions != base
        effects = (order_cost(labels, actions) - baseline_cost)[released]
        totals = pd.DataFrame({"effect": effects, "group": groups[released]}).groupby("group")["effect"].agg(
            ["sum", "size"],
        )
        n_clusters = len(totals)
        if n_clusters < MIN_RELEASE_CLUSTERS:
            continue
        centered = totals["sum"] - effects.mean() * totals["size"]
        standard_error = np.sqrt((centered ** 2).sum() * n_clusters / (n_clusters - 1)) / len(effects)
        upper = float(effects.mean() + 1.645 * standard_error)
        delta = float(effects.sum())
        if upper < 0 and delta < best_cost_delta:
            best_cost_delta = delta
            chosen = {"threshold": float(threshold), "released": int(released.sum()),
                      "cost_delta_pkr_per_1000": 1000 * delta / len(labels),
                      "one_sided_cluster_upper_pkr_per_release": upper}
    return {**chosen, "at_largest_tested_cutoff": {"orders": int(largest.sum()),
                                                 "clusters": len(np.unique(groups[largest])),
                                                 "failed": int(labels[largest].sum())}}


def reallocate_verification(base, probabilities, has_valid_phone):
    """Rank reachable SHIP and VERIFY orders within the incumbent's exact verification budget."""
    candidates = np.flatnonzero(np.isin(base, (SHIP, VERIFY)) & has_valid_phone)
    budget = int((base[candidates] == VERIFY).sum())
    # When estimated risk is tied, keep the incumbent queue allocation.
    ranked = candidates[np.lexsort((base[candidates] != VERIFY, -probabilities[candidates]))]
    result = base.copy()
    result[candidates] = SHIP
    result[ranked[:budget]] = VERIFY
    return result


def paired_interval(effects, groups):
    cluster = pd.DataFrame({"effect": effects, "group": groups}).groupby("group")["effect"].agg(["sum", "size"])
    totals, sizes = cluster["sum"].to_numpy(), cluster["size"].to_numpy()
    draws = np.random.default_rng(10).integers(len(cluster), size=(BOOTSTRAP_REPETITIONS, len(cluster)))
    means = 1000 * totals[draws].sum(axis=1) / sizes[draws].sum(axis=1)
    return np.quantile(means, [.025, .975]).tolist()


def ranking(labels, probabilities):
    result = {"orders": len(labels), "failed": int(labels.sum())}
    if len(np.unique(labels)) < 2:
        return result
    n_screened = int(np.ceil(.20 * len(labels)))
    threshold = np.partition(probabilities, -n_screened)[-n_screened]
    above = probabilities > threshold
    tied = probabilities == threshold
    captured = labels[above].sum() + labels[tied].mean() * (n_screened - above.sum())
    return {**result, "auprc": float(average_precision_score(labels, probabilities)),
            "auroc": float(roc_auc_score(labels, probabilities)),
            "brier": float(np.mean((probabilities - labels) ** 2)),
            "recall_at_top_20_percent": float(captured / labels.sum())}


def policy_metrics(labels, base, actions, groups, probabilities=None):
    effects = order_cost(labels, actions) - order_cost(labels, base)
    released = (base == VERIFY) & (actions == SHIP)
    return {**score(labels, actions, probabilities),
            "verify_to_ship": int(released.sum()), "failed_verify_to_ship": int(labels[released].sum()),
            "ship_to_verify": int(((base == SHIP) & (actions == VERIFY)).sum()),
            "delta_pkr_per_1000": float(1000 * effects.mean()),
            "delta_paired_95_interval": paired_interval(effects, groups),
            "delta_at_resolution": {
                str(rate): float(1000 * (order_cost(labels, actions, rate) - order_cost(labels, base, rate)).mean())
                for rate in RESOLUTION_SCENARIOS}}


def real_data(splits, orders, purchases):
    train, validation, test = splits
    cutoff = train["order_day"].max()
    final_cutoff = validation["order_day"].max()
    basket = purchases.set_index("order_id")[["lines", "distinct_skus", "max_line_discount"]]
    for frame, observed_through in ((train, None), (validation, cutoff), (test, final_cutoff)):
        features = frame.join(basket, on="order_id", validate="one_to_one").assign(
            amount_per_item=frame["amount_pkr"] / frame["items_count"],
            purchase_weekday=frame["order_day"].dt.day_of_week,
        ).join(purchase_features(frame, purchases))
        for days in OUTCOME_LAGS:
            lagged = lagged_outcome_features(frame, orders, days, observed_through=observed_through)
            features = features.join(lagged.add_suffix(f"_{days}d"))
        yield features


def synthetic_inputs(frame, columns=None):
    full = feature_frame(frame, columns)
    baseline = full.drop(columns=list(SYNTH_OUTCOMES))
    return {"synthetic_without_customer_outcomes": baseline, "synthetic_with_customer_outcomes": full}


def run(archive, output):
    orders, source, purchases = pk_real.load_orders(archive, include_purchase_history=True)
    splits = pk_real.split_customers_and_time(orders)
    manifest = pk_real.frozen_manifest(archive, orders, source, splits)
    if json.loads(LOCK.read_text(encoding="utf-8")) != manifest:
        raise ValueError("Kaggle source or projected cohorts differ from the frozen lock")
    synthetic = pd.read_csv(ROOT / "data/benchmark_orders.csv")
    synth_train, synth_val, synth_test, _ = split_benchmark(synthetic)
    synth_lock = verify_test_lock(synth_test)

    features = {"order_slip": pk_real.FEATURES, "purchase_history": (*pk_real.FEATURES, *PURCHASE_FEATURES)}
    features["basket_details"] = (*pk_real.FEATURES, *BASKET_FEATURES)
    features["basket_and_purchase_history"] = (*features["purchase_history"], *BASKET_FEATURES)
    for days in OUTCOME_LAGS:
        features[f"lagged_outcomes_{days}d"] = (*features["purchase_history"],
                                             *(f"{key}_{days}d" for key in OUTCOME_FEATURES))
    real_train, real_val, real_test = real_data(splits, orders, purchases)
    calibration, policy_val = pk_real.validation_partitions(real_val)
    y_policy = policy_val["label_failed"].to_numpy()
    real_base_val, _ = incumbent_actions(policy_val[["order_id", *pk_real.FEATURES]])
    all_eligible = np.ones(len(policy_val), dtype=bool)
    groups = policy_val["customer_id"].to_numpy()
    real_models, selection, real_validation_ranking = {}, {}, {}
    for name, columns in features.items():
        keys = list(columns)
        fitted = fit_risk(real_train[keys], real_train["label_failed"], calibration[keys], calibration["label_failed"])
        real_models[name] = fitted
        probabilities = fitted.predict(policy_val[keys])
        selection[name] = select_release(real_base_val, probabilities, all_eligible, y_policy, groups)
        real_validation_ranking[name] = ranking(y_policy, probabilities)

    synthetic_columns = list(feature_frame(synth_train).columns)
    synthetic_train_features = synthetic_inputs(synth_train, synthetic_columns)
    synthetic_validation_features = synthetic_inputs(synth_val, synthetic_columns)
    synth_models = {name: fit_risk(x, synth_train["label_failed"], synthetic_validation_features[name],
                                  synth_val["label_failed"]) for name, x in synthetic_train_features.items()}
    plan = {
        "real_archive_sha256": manifest["archive_sha256"],
        "real_split_sha256": {name: item["sha256"] for name, item in manifest["splits"].items()},
        "synthetic_test_lock": synth_lock,
        "real_training_end": real_train["order_day"].max().date().isoformat(),
        "real_calibration_end": calibration["order_day"].max().date().isoformat(),
        "real_policy_validation_rows": len(policy_val),
        "real_policy_validation_failed": int(y_policy.sum()),
        "real_feature_sets": features,
        "tested_ship_thresholds": SHIP_THRESHOLDS.tolist(),
        "minimum_release_clusters": MIN_RELEASE_CLUSTERS,
        "cost_pkr": {"false_ship": FALSE_SHIP_PKR, "false_hold": FALSE_HOLD_PKR, "verify": VERIFY_PKR},
        "verification_resolution_grid": RESOLUTION_SCENARIOS,
        "real_release_selection": selection, "real_validation_ranking": real_validation_ranking,
        "synthetic_policy": "Same-capacity re-ranking of reachable orders, preserving all incumbent holds",
        "primary_comparison": "Real purchase-history replay and independently fitted synthetic outcome-history replay",
        "portable_check": "Real order-slip model and cutoff transferred to synthetic without refitting",
    }
    write_json(output / "plan.json", plan)

    synthetic_bundle, _ = fit_and_evaluate(synthetic)
    real = real_results(real_test, real_models, features, selection)
    synth = synthetic_results(synth_test, synthetic_columns, synth_models, synthetic_bundle,
                              real_models["order_slip"], selection["order_slip"]["threshold"])
    primary_real = real["purchase_history"]["policy"]
    primary_synth = synth["synthetic_with_customer_outcomes"]["policy"]
    jointly_positive = all(result["delta_paired_95_interval"][1] < 0 for result in (primary_real, primary_synth))
    portable_pass = all(result["delta_paired_95_interval"][1] < 0 for result in (
        real["order_slip"]["policy"], synth["portable_real_order_slip"]["policy"],
    ))
    return {"[PK-REAL]": real, "[PK-SYNTH]": synth,
            "both_primary_replays_show_lower_modeled_cost": jointly_positive,
            "portable_policy_passed_both_holdouts": portable_pass}


def real_results(test, models, features, selection):
    labels = test["label_failed"].to_numpy()
    groups = test["customer_id"].to_numpy()
    base, _ = incumbent_actions(test[["order_id", *pk_real.FEATURES]])
    eligible = np.ones(len(test), dtype=bool)
    results = {"incumbent": policy_metrics(labels, base, base, groups)}
    seen = test["prior_orders"].gt(0).to_numpy()
    for name, model in models.items():
        probabilities = model.predict(test[list(features[name])])
        actions = release_actions(base, probabilities, eligible, selection[name]["threshold"])
        results[name] = {"ranking": ranking(labels, probabilities),
                         "first_observed_cod": ranking(labels[~seen], probabilities[~seen]),
                         "repeat_cod": ranking(labels[seen], probabilities[seen]),
                         "policy": policy_metrics(labels, base, actions, groups, probabilities)}
    return results


def synthetic_results(test, columns, models, bundle, portable, cutoff):
    labels = test["label_failed"].to_numpy()
    groups = test["order_id"].to_numpy()
    base, base_scores = incumbent_actions(test, bundle)
    reachable = test["phone_valid"].eq(1).to_numpy()
    results = {
        "incumbent": policy_metrics(labels, base, base, groups, base_scores),
        "verify_all": policy_metrics(labels, base, np.full(len(base), VERIFY), groups),
    }
    probabilities = portable.predict(test[list(pk_real.FEATURES)])
    actions = release_actions(base, probabilities, reachable, cutoff)
    results["portable_real_order_slip"] = {"ranking": ranking(labels, probabilities),
                                          "policy": policy_metrics(labels, base, actions, groups, probabilities)}
    for name, features in synthetic_inputs(test, columns).items():
        probabilities = models[name].predict(features)
        actions = reallocate_verification(base, probabilities, reachable)
        results[name] = {"ranking": ranking(labels, probabilities),
                         "policy": policy_metrics(labels, base, actions, groups, probabilities)}
    return results


def write_json(path, contents):
    with path.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(contents, file, indent=2, allow_nan=False)
        file.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with threadpool_limits(limits=1):
        results = run(args.archive, args.output_dir)
    write_json(args.output_dir / "results.json", results)
    print(args.output_dir / "results.json")


if __name__ == "__main__":
    main()
