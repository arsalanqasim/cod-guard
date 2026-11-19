"""Render the versioned public report from an evaluation with a verified lock."""

import argparse
import json
from pathlib import Path

from artifacts import atomic_write


ROOT = Path(__file__).resolve().parents[2]


def cohorts(report):
    chosen = report["chosen"]
    return [{"Cohort": "All held-out synthetic orders (pre-reply)", "Orders": str(report["split"]["test"]),
             "Precision": f"{chosen['precision']:.2%}", "Recall": f"{chosen['recall']:.2%}",
             "FPR": f"{chosen['fp_rate']:.2%}"}] + [
        {"Cohort": label, "Orders": "Not evaluated", "Precision": "—", "Recall": "—", "FPR": "—"}
        for label in ("Channel · WooCommerce", "Channel · Shopify", "Channel · Daraz",
                      "Channel · Social DM / Sheets", "Channel · WhatsApp verification",
                      "Language · English text", "Language · Roman Urdu text",
                      "Language · Urdu script text", "Language · Urdu voice")]


def render(report, lock):
    split = report["split"]
    if report["data_source"] != "SYNTHETIC" or set(lock) != {"test_ids_sha256", "test_labels_sha256"} or any(
            split.get(name) != digest for name, digest in lock.items()):
        raise ValueError("Benchmark report does not match the committed synthetic holdout lock")
    chosen = report["chosen"]
    lines = ["# Public benchmark", "",
             f"Model `{report['model_id']}` · Version {report['version']} · Report format 1 · **SYNTHETIC**", "",
             "## Results", "", "| Cohort | Orders | Precision | Recall | FPR |", "| --- | ---: | ---: | ---: | ---: |"]
    lines.extend("| " + " | ".join(row.values()) + " |" for row in cohorts(report))
    lines += ["", f"Confusion matrix: TP {chosen['tp']}, FP {chosen['fp']}, FN {chosen['fn']}, TN {chosen['tn']}.",
              "Precision = TP / (TP + FP), recall = TP / (TP + FN), FPR = FP / (FP + TN).", "",
              "## Method and dataset", "",
              f"Deterministically generated dataset: {report['benchmark_rows']:,} synthetic COD orders. The split has",
              f"{split['training']:,} training rows (including {split['feedback']} marked demo outcomes),",
              f"{split['validation']:,} validation orders and {split['test']:,} locked test orders. The {split['reserved_demo']}",
              "demo orders are separately reserved. AMBER or RED counts as a positive before any reply.",
              f"The model and {chosen['threshold']:.2f} threshold are selected on validation cost, not test labels.",
              "The positive label is COD failure, not proof of fraud. The checkout and human reply cohorts are not sampled.",
              "The [full evaluation](EVAL_REPORT.md) contains city slices and offline outreach sensitivity scenarios,",
              "not live reply measurements. [Metric protocol](METRIC_PROTOCOL.md).", "",
              f"- Benchmark SHA-256: `{report['benchmark_sha256']}`",
              f"- Holdout IDs SHA-256: `{lock['test_ids_sha256']}`",
              f"- Holdout ID/label SHA-256: `{lock['test_labels_sha256']}`", "",
              "## Reproduce", "", "Install `requirements.txt` and run `python scripts/build_demo.py` to regenerate",
              "the synthetic baseline, including this Markdown. To render the committed evaluation without fitting,",
              "run `python backend/app/public_benchmark.py`. After demo retraining, the dashboard can download the",
              "report rendered from the active model’s matching evaluation. Real courier pilot candidates are not published.",
              "", "## Limits", "", "No subgroup accuracy, merchant pilot, measured savings, or production lift is established.",
              "Urdu voice is a functional demonstration; transcription or intent accuracy was not evaluated on this holdout.",
              "Channel and language rows are not zeroes: the dataset has neither cohort labels nor recorded conversations.", ""]
    return "\n".join(lines)


def benchmark_markdown(report):
    lock = json.loads((ROOT / "data/test_split.lock.json").read_text(encoding="utf-8"))
    return render(report, lock)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, default=ROOT / "data/evaluation.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/BENCHMARK.md")
    args = parser.parse_args()
    atomic_write(args.output, benchmark_markdown(json.loads(args.evaluation.read_text(encoding="utf-8"))).encode("utf-8"))
