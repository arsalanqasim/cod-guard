"""Leakage-controlled synthetic evaluation and outcome-fed model training.

The operating policy is risk_engine.assess(), also used by the service.
Candidates and thresholds are chosen ONLY on validation data. All 80 demo
orders are reserved outside training/validation/test so marking a demo
outcome can feed training without contaminating the evaluation holdout.
"""
import hashlib
import json
import os
import pickle
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, precision_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from risk_engine import assess
from round2_evaluation import analyze_round2, render_round2

ROOT = Path(__file__).resolve().parents[2]
COST_FN, COST_FP = 650, 450
FEATURES = ["phone_valid", "phone_fraud_history", "phone_velocity_24h",
            "address_words", "address_has_landmark", "amount_pkr", "items_count",
            "order_hour", "is_repeat_customer", "customer_past_delivered",
            "customer_past_refusals"]
THRESHOLDS = [round(float(t), 2) for t in np.arange(0.25, 0.86, 0.05)]
TEST_LOCK_PATH = ROOT / "data/test_split.lock.json"


def evaluate(y_true, y_flag):
    tn, fp, fn, tp = confusion_matrix(y_true, y_flag, labels=[0, 1]).ravel()
    return {"tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
            "fp_rate": float(fp / (fp + tn)) if fp + tn else None,
            "fn_rate": float(fn / (fn + tp)) if fn + tp else None,
            "precision": float(precision_score(y_true, y_flag, zero_division=0)),
            "recall": float(recall_score(y_true, y_flag, zero_division=0)),
            "total_cost": int(fp * COST_FP + fn * COST_FN)}


def split_benchmark(df):
    if not df["order_id"].is_unique:
        raise ValueError("Benchmark order IDs must be unique")
    demo = df.sample(min(80, len(df)), random_state=3)
    pool = df.drop(demo.index)
    train, holdout = train_test_split(pool, test_size=0.40, random_state=7,
                                     stratify=pool["label_failed"])
    validation, test = train_test_split(holdout, test_size=0.50, random_state=8,
                                       stratify=holdout["label_failed"])
    return train, validation, test, demo


def feature_frame(df, columns=None):
    frame = pd.get_dummies(df[FEATURES + ["city"]], columns=["city"], dtype=float)
    if columns is not None:
        frame = frame.reindex(columns=columns, fill_value=0)
    if not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise ValueError("Model features must be finite numeric values")
    return frame


def policy_flags(rows, probabilities, threshold):
    return np.array([assess(order, float(p), threshold)["zone"] != "GREEN"
                     for order, p in zip(rows, probabilities)], dtype=int)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def verify_test_lock(test):
    try:
        expected = json.loads(TEST_LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Committed test split lock is unavailable") from exc
    if not test["label_failed"].isin((0, 1)).all():
        raise ValueError("Test split lock requires binary labels")
    ids = sorted(test["order_id"])
    labels = sorted((order_id, int(label)) for order_id, label in zip(test["order_id"], test["label_failed"]))
    actual = {"test_ids_sha256": _digest(ids), "test_labels_sha256": _digest(labels)}
    if actual != expected:
        raise ValueError("Test split lock mismatch. Review benchmark IDs and labels before training.")
    return actual


def fit_and_evaluate(df, feedback_rows=None, feedback=None, previous_version=0, *, oracle=None):
    train, validation, test, demo = split_benchmark(df)
    test_lock = verify_test_lock(test)
    train = train.copy()
    feedback = feedback or {}
    if set(df.get("data_source", [])) != {"SYNTHETIC"}:
        raise ValueError("The benchmark must explicitly label every row SYNTHETIC")
    if feedback_rows is not None and len(feedback_rows):
        if not feedback_rows["order_id"].is_unique:
            raise ValueError("Each order can contribute only one current outcome")
        protected = set(pd.concat([train, validation, test])["order_id"])
        if protected.intersection(feedback_rows["order_id"]):
            raise ValueError("Feedback cannot overlap benchmark training/validation/test IDs; use reserved demo orders")
        if not set(feedback_rows["label_failed"]).issubset({0, 1}):
            raise ValueError("Feedback labels must be binary observed outcomes")
        if set(feedback_rows["order_id"]) != set(feedback):
            raise ValueError("Feedback rows and recorded outcome IDs must match")
        for _, row in feedback_rows.iterrows():
            outcome = feedback[row["order_id"]]
            if outcome not in ("delivered", "returned", "refused") or int(row["label_failed"]) != int(outcome != "delivered"):
                raise ValueError("Feedback labels must match the recorded outcomes")
        train = pd.concat([train, feedback_rows], ignore_index=True)
    X_train = feature_frame(train)
    columns = list(X_train.columns)
    X_validation = feature_frame(validation, columns)
    X_test = feature_frame(test, columns)
    validation_rows = validation.to_dict("records")
    test_rows = test.to_dict("records")
    candidates = {
        "regularized_gradient_boosting": HistGradientBoostingClassifier(
            max_leaf_nodes=7, max_iter=120, learning_rate=0.05,
            min_samples_leaf=40, l2_regularization=15, random_state=7),
        "gradient_boosting": HistGradientBoostingClassifier(
            max_leaf_nodes=15, max_iter=100, l2_regularization=8, random_state=7),
        "logistic_regression": make_pipeline(StandardScaler(),
            LogisticRegression(C=1.0, max_iter=1000, random_state=7)),
    }
    selections = []
    fitted = {}
    with threadpool_limits(limits=1):
        for name, model in candidates.items():
            model.fit(X_train, train["label_failed"])
            fitted[name] = model
            probabilities = model.predict_proba(X_validation)[:, 1]
            sweep = [{"threshold": threshold,
                      **evaluate(validation["label_failed"], policy_flags(validation_rows, probabilities, threshold))}
                     for threshold in THRESHOLDS]
            choice = min(sweep, key=lambda entry: (entry["total_cost"], entry["fp_rate"] + entry["fn_rate"]))
            selections.append({"model_name": name, **choice})
        selected = min(selections, key=lambda entry: (entry["total_cost"], entry["fp_rate"] + entry["fn_rate"]))
        model = fitted[selected["model_name"]]
        if oracle is not None:
            val_probs = model.predict_proba(X_validation)[:, 1]
        probabilities = model.predict_proba(X_test)[:, 1]
    test_sweep = [{"threshold": threshold,
                   **evaluate(test["label_failed"], policy_flags(test_rows, probabilities, threshold))}
                  for threshold in THRESHOLDS]
    chosen = next(entry for entry in test_sweep if entry["threshold"] == selected["threshold"])
    flags = policy_flags(test_rows, probabilities, selected["threshold"])
    rules = [assess(row) for row in test_rows]
    any_signal = np.array([entry["signal_count"] > 0 for entry in rules], dtype=int)
    baselines = {
        "ship_everything": evaluate(test["label_failed"], np.zeros(len(test), dtype=int)),
        "block_any_adverse_signal": evaluate(test["label_failed"], any_signal),
        "rules_only_two_signal_policy": evaluate(test["label_failed"],
            np.array([entry["zone"] != "GREEN" for entry in rules], dtype=int)),
    }
    pattern = ((test["phone_fraud_history"] >= 1) | (test["phone_velocity_24h"] >= 3)).to_numpy()
    pattern_metrics = evaluate(test["label_failed"].to_numpy()[pattern], flags[pattern]) if pattern.any() else None
    segments = []
    for city in sorted(test["city"].unique()):
        mask = (test["city"] == city).to_numpy()
        segments.append({"city": city, "rows": int(mask.sum()),
                         **evaluate(test["label_failed"].to_numpy()[mask], flags[mask])})
    benchmark_hash = hashlib.sha256(df.to_csv(index=False).encode("utf-8")).hexdigest()
    model_id = "cg-" + _digest({"benchmark": benchmark_hash, "feedback": feedback,
                              "model": selected["model_name"], "threshold": selected["threshold"],
                              "version": previous_version + 1})[:12]
    trained_at = datetime.now(timezone.utc).isoformat()
    bundle = {"model": model, "columns": columns, "threshold": selected["threshold"],
              "format_version": 2, "version": previous_version + 1,
              "model_id": model_id, "model_name": selected["model_name"],
              "trained_at": trained_at, "feedback": feedback,
              "data_source": "SYNTHETIC benchmark + marked demo outcomes"}
    report = {"data_source": "SYNTHETIC", "benchmark_rows": len(df),
              "benchmark_sha256": benchmark_hash, "failure_rate": float(df["label_failed"].mean()),
              "target_failure_rate": 0.51, "model_id": model_id, "trained_at": trained_at,
              "model_name": selected["model_name"], "version": bundle["version"],
              "split": {"training": len(train), "validation": len(validation), "test": len(test),
                        "reserved_demo": len(demo), "feedback": len(feedback),
                        "validation_ids_sha256": _digest(sorted(validation["order_id"])),
                        **test_lock},
              "cost_assumptions_pkr": {"false_negative": COST_FN, "false_positive": COST_FP},
              "selection": "model and threshold chosen on validation cost only; test labels are not used for selection",
              "validation_candidates": selections, "chosen": chosen, "test_threshold_sweep": test_sweep,
              "baselines": baselines, "pattern_segment": {"rows": int(pattern.sum()), "metrics": pattern_metrics},
              "city_segments": segments,
              "limitations": ["All examples are synthetic; there are no merchant pilots or production accuracy claims.",
                              "Failed labels combine non-collection/refusal/cancellation; they do not establish deliberate fraud.",
                              "Benchmark generator and cost assumptions do not reproduce any merchant population.",
                              "Verification overrides are demonstrated by functional tests, not simulated as perfect human responses.",
                              "Marked demo outcomes are demonstrations, not prospectively collected field evidence."]}
    if oracle is not None:
        report["round2"] = analyze_round2(validation, test, val_probs, probabilities,
                                          selected["threshold"], oracle, COST_FN, COST_FP)
    return bundle, report


def render_report(report):
    chosen = report["chosen"]
    split = report["split"]
    lines = ["# COD-Guard — FP/FN evaluation", "",
             "**SYNTHETIC BENCHMARK — no real merchant records or pilots.**", "",
             "Reference figures supplied in the mission brief: OrderNation (~170k orders), "
             "37.3% COD cancelled and ~49/100 cash collected. These are different measures. "
             "We target 51% expected non-collection, not 37.3% cancellation. "
             "Individual feature relationships remain synthetic assumptions.", "",
             f"Generated rows: {report['benchmark_rows']}; empirical failure rate: {report['failure_rate']:.4%}. "
             f"Benchmark SHA-256: `{report['benchmark_sha256']}`.", "",
             f"Model `{report['model_id']}`: {report['model_name']}, version {report['version']}. "
             f"Training {split['training']} / validation {split['validation']} / test {split['test']}. "
             f"{split['reserved_demo']} demo orders reserved outside all three splits; "
             f"{split['feedback']} marked demo outcomes added to training.", "",
             "## Method", "",
             "Models and operating thresholds are selected on **validation only**. "
             "The test split is untouched during selection. The reported flag is the actual serving policy: "
             "rules + the saved ML threshold + the two-independent-signal guard. "
             "Both address checks count as one signal. A lone signal cannot hold or require verification; "
             "ML alone is not another independent signal. Confirmation overrides a flag; denial overrides a pass.", "",
             f"Cost assumptions: false negative PKR {COST_FN}; false positive PKR {COST_FP}. "
             "These are illustrative costs, not measured merchant losses. Any non-GREEN recommendation is "
             "counted as flagged, even though verification can later recover a genuine order.", "",
             "## Frozen operating point on the test split", "",
             f"Validation-selected threshold **{chosen['threshold']:.2f}**. "
             f"TP={chosen['tp']}, FP={chosen['fp']}, FN={chosen['fn']}, TN={chosen['tn']}. "
             f"FPR **{chosen['fp_rate']:.2%}**; FNR **{chosen['fn_rate']:.2%}**; "
             f"precision {chosen['precision']:.2%}; recall {chosen['recall']:.2%}. "
             f"Illustrative cost PKR {chosen['total_cost']:,}.", "",
             "## Baselines on the same test orders", "",
             "| Policy | TP | FP | FN | TN | FPR | FNR | Illustrative cost PKR |",
             "|---|---:|---:|---:|---:|---:|---:|---:|",]
    for name, entry in {**report["baselines"], "serving_policy": chosen}.items():
        lines.append(f"| {name} | {entry['tp']} | {entry['fp']} | {entry['fn']} | {entry['tn']} | "
                     f"{entry['fp_rate']:.3f} | {entry['fn_rate']:.3f} | {entry['total_cost']:,} |")
    lines += ["", "## Test threshold trade-off (diagnostic, not used to select the threshold)", "",
              "| Threshold | TP | FP | FN | TN | FPR | FNR | Illustrative cost PKR |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for entry in report["test_threshold_sweep"]:
        lines.append(f"| {entry['threshold']:.2f} | {entry['tp']} | {entry['fp']} | {entry['fn']} | {entry['tn']} | "
                     f"{entry['fp_rate']:.3f} | {entry['fn_rate']:.3f} | {entry['total_cost']:,} |")
    lines += ["", "## Validation candidate comparison", "",
              "| Model | Selected threshold | Validation FPR | Validation FNR | Validation cost PKR |",
              "|---|---:|---:|---:|---:|"]
    for entry in report["validation_candidates"]:
        lines.append(f"| {entry['model_name']} | {entry['threshold']:.2f} | {entry['fp_rate']:.3f} | "
                     f"{entry['fn_rate']:.3f} | {entry['total_cost']:,} |")
    lines += ["", "## Pattern and city checks", "",
              "The fraud-linked-phone / 3+ orders-per-day segment is an observable pattern, "
              "not ground truth that an order is deliberately fraudulent."]
    pattern = report["pattern_segment"]
    if pattern["metrics"]:
        lines.append(f"Pattern n={pattern['rows']}, recall={pattern['metrics']['recall']:.3f}, "
                     f"FNR={pattern['metrics']['fn_rate']:.3f}.")
    lines += ["", "| City | Rows | FPR | FNR |", "|---|---:|---:|---:|"]
    for entry in report["city_segments"]:
        lines.append(f"| {entry['city']} | {entry['rows']} | {entry['fp_rate']:.3f} | {entry['fn_rate']:.3f} |")
    if split["feedback"]:
        lines += ["", f"## Outcome-fed version {report['version']}", "",
                  f"This version added {split['feedback']} marked demo outcomes to training. "
                  "Compare with the separately retained baseline v1 on the same locked test split."]
    if "round2" in report:
        lines += render_round2(report["round2"])
    lines += ["", "## Limits and brief conflicts", ""]
    lines += ["- " + limitation for limitation in report["limitations"]]
    lines += ["- The original generator produced 27.5% failure despite its calibration claim; "
              "its 4.88% FPR / 62.23% FNR report selected a threshold on test data and did not evaluate the served policy. "
              "The new calibration and split differ, so old and new percentages are not a like-for-like improvement claim.",
              "- No low-FP-and-low-FN production claim is supported. Unpredictable refusals remain a material false-negative risk.",
              "- Competitors: Tasdeek, Botaura, OrderWitness, DukaanFlow. No claim of being first or of competitor capabilities."]
    return "\n".join(lines) + "\n"


def _atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def publish(bundle, report, model_path, evaluation_path, report_path=None):
    _atomic_write(model_path, pickle.dumps(bundle))
    _atomic_write(evaluation_path, json.dumps(report, indent=2).encode("utf-8"))
    if report_path is not None:
        _atomic_write(report_path, render_report(report).encode("utf-8"))


def main():
    sys.path.insert(0, str(ROOT))
    from data.generate_benchmark import generate_benchmark

    benchmark = pd.read_csv(ROOT / "data/benchmark_orders.csv")
    generated, oracle = generate_benchmark()
    if not benchmark.equals(generated):
        raise ValueError("Benchmark differs from the generator. Run data/generate_benchmark.py before training.")
    bundle, report = fit_and_evaluate(benchmark, oracle=oracle.set_index("order_id"))
    publish(bundle, report, ROOT / "backend/app/model.pkl", ROOT / "data/evaluation.json", ROOT / "docs/EVAL_REPORT.md")
    print(json.dumps({"model_id": bundle["model_id"], "model": bundle["model_name"],
                      "chosen": report["chosen"], "split": report["split"],
                      "baselines": report["baselines"]}, indent=2))
    print("Wrote docs/EVAL_REPORT.md, data/evaluation.json and backend/app/model.pkl (SYNTHETIC)")


if __name__ == "__main__":
    main()
