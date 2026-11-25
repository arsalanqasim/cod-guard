"""Tune Round 8 reply policies on validation, then score the frozen holdout once."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np

from evaluate_reply_models import (COMMIT, LABELS, ROOT, TRAPS, calibration_error, load_corpus,
                                   observe, temperature_scale, parse_reply)
from round7_finetune import train_minilm
from round7_models import fasttext_predictor, minilm_predictor, train_fasttext
from scipy.special import softmax

LANGUAGES = ("en", "roman_ur", "ur")
LOCK = ROOT / "data/reply_evaluation.v1.lock.json"


def file_hash(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def corpus_hash():
    return hashlib.sha256(LOCK.read_text(encoding="utf-8").encode()).hexdigest()


def policy_label(rule, label, confidence, thresholds):
    agreement, expansion = thresholds
    if label not in COMMIT:
        return "UNCLEAR"
    if (rule == label and confidence >= agreement) or (rule == "UNCLEAR" and confidence >= expansion):
        return label
    return "UNCLEAR"


def candidates(scores, rows):
    return [(row, parse_reply(row["text"]), LABELS[int(score.argmax())], float(score.max()))
            for row, score in zip(rows, scores)]


def select_thresholds(samples):
    result = {}
    for language in LANGUAGES:
        group = [sample for sample in samples if sample[0]["language"] == language]
        best = (-1, 0, 0)
        for agree, expand in itertools.product((0.50, 0.60, 0.70, 0.80, 0.90),
                                               (0.80, 0.85, 0.90, 0.95, 0.99, 1.01)):
            if expand <= agree:
                continue
            accepted = [row["label"] == label for row, rule, label, confidence in group
                        if policy_label(rule, label, confidence, (agree, expand)) in COMMIT]
            if all(accepted):
                best = max(best, (len(accepted), expand, agree))
        result[language] = [best[2], best[1]]
    return result


def summarize(samples, thresholds=None):
    values = []
    for row, rule, label, confidence in samples:
        decision = rule if thresholds is None else policy_label(
            rule, label, confidence, thresholds.get(row["language"], (1.01, 1.01)))
        values.append((row, rule, decision))
    accepted = [(row, rule, decision) for row, rule, decision in values if decision in COMMIT]
    errors = [row["id"] for row, _, decision in accepted if decision != row["label"]]
    traps = {trap: {"cases": sum(row.get("trap") == trap for row, _, _ in values),
                    "committed": sum(row.get("trap") == trap for row, _, _ in accepted),
                    "errors": sum(row.get("trap") == trap and decision != row["label"]
                                  for row, _, decision in accepted)} for trap in TRAPS}
    return {"cases": len(values), "committed": len(accepted), "wrong": len(errors),
            "error_rate": len(errors) / len(accepted) if accepted else None,
            "expanded": sum(rule == "UNCLEAR" for _, rule, _ in accepted),
            "review_only_commits": sum(row["label"] not in COMMIT for row, _, _ in accepted),
            "wrong_ids": errors, "traps": traps}


def tune_one(predict, val, truth):
    scores, _ = observe(predict, val)
    scaled, temperature = temperature_scale(scores, truth, np.ones(len(val), dtype=bool))
    samples = candidates(scaled, val)
    thresholds = select_thresholds(samples)
    report = summarize(samples, thresholds)
    return {"temperature": temperature, "thresholds": thresholds,
            "validation": report, "validation_accuracy": float((scaled.argmax(axis=1) == truth).mean())}


def tune(corpus, work, checkpoint):
    train = [row for row in corpus if row["split"] == "train"]
    val = [row for row in corpus if row["split"] == "val"]
    truth = np.array([LABELS.index(row["label"]) for row in val])
    finalists, sweep = {}, []
    for index, ((word, minn, maxn), rate, epochs) in enumerate(itertools.product(
            ((1, 0, 0), (2, 2, 4), (3, 3, 5)), (0.15, 0.35), (30, 80)), start=1):
        model = work / f"fasttext-{index}.bin"
        options = {"word_ngrams": word, "minn": minn, "maxn": maxn, "lr": rate, "epoch": epochs}
        try:
            train_fasttext(train, model, **options)
        except RuntimeError as exc:
            if "Encountered NaN" not in str(exc):
                raise
            sweep.append({"settings": options, "error": "Training produced NaN"})
            continue
        score = tune_one(fasttext_predictor(model), val, truth)
        sweep.append({"settings": options, "artifact": model.name, **score})
    best = max((row for row in sweep if "validation" in row),
               key=lambda row: (row["validation"]["committed"], row["validation_accuracy"]))
    finalists["fastText"] = {**best, "files": {best["artifact"]: file_hash(work / best["artifact"])}}
    folder = work / "minilm"
    train_minilm(train, checkpoint, folder, epochs=14)
    finalists["MiniLM"] = {**tune_one(minilm_predictor(folder), val, truth), "settings": {"epochs": 14},
                           "files": {name: file_hash(work / name) for name in
                                     ("minilm/decision.int8.onnx", "minilm/tokenizer.json")}}
    return {"corpus_lock_sha256": corpus_hash(), "fasttext_sweep": sweep, "finalists": finalists}


def test(corpus, work, plan):
    if plan["corpus_lock_sha256"] != corpus_hash():
        raise ValueError("Frozen corpus changed after validation")
    rows = [row for row in corpus if row["split"] in {"test", "regression"}]
    test_rows = [row for row in rows if row["split"] == "test"]
    baseline = candidates(np.zeros((len(rows), len(LABELS))), rows)
    report = {"rules": {"all": summarize(baseline), "novel": summarize(
        [sample for sample in baseline if sample[0]["split"] == "test"])}, "models": {}}
    for name, finalist in plan["finalists"].items():
        if any(file_hash(work / path) != digest for path, digest in finalist["files"].items()):
            raise ValueError(f"Artifact changed after validation for {name}")
        predict = fasttext_predictor(work / finalist["artifact"]) if name == "fastText" else minilm_predictor(work / "minilm")
        scores, latency = observe(predict, rows)
        scaled = softmax(np.log(np.clip(scores, 1e-10, 1)) / finalist["temperature"], axis=1)
        samples = candidates(scaled, rows)
        novel = [sample for sample in samples if sample[0]["split"] == "test"]
        thresholds = finalist["thresholds"]
        all_metrics, novel_metrics = summarize(samples, thresholds), summarize(novel, thresholds)
        prediction = np.array(LABELS)[scaled.argmax(axis=1)]
        raw_ece = calibration_error(scaled.max(axis=1), prediction == [row["label"] for row in rows])
        size = sum((work / path).stat().st_size for path in finalist["files"])
        p95 = float(np.percentile(latency, 95))
        passed = (all_metrics["error_rate"] is not None
                  and all_metrics["error_rate"] <= report["rules"]["all"]["error_rate"]
                  and all(item["errors"] == 0 for item in all_metrics["traps"].values())
                  and all(item["committed"] > 0 for item in novel_metrics["traps"].values())
                  and raw_ece <= 0.10 and size < 250_000_000 and p95 < 100)
        report["models"][name] = {"all": all_metrics, "novel": novel_metrics, "raw_ece": raw_ece,
                                  "bytes": size, "p95_ms": p95, "gate_passed": passed,
                                  "by_language": {language: summarize(
                                      [s for s in novel if s[0]["language"] == language], thresholds)
                                      for language in LANGUAGES}}
    assert report["rules"]["novel"]["cases"] == len(test_rows)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("tune", "test"))
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    args = parser.parse_args()
    work = args.work_dir
    work.mkdir(parents=True, exist_ok=True)
    plan_path, result_path = work / "plan.json", work / "test-results.json"
    output = plan_path if args.stage == "tune" else result_path
    if output.exists():
        parser.error(f"{output} already exists")
    if args.stage == "tune" and not args.checkpoint:
        parser.error("--checkpoint is required to tune")
    corpus, _ = load_corpus()
    report = (tune(corpus, work, args.checkpoint) if args.stage == "tune"
              else test(corpus, work, json.loads(plan_path.read_text(encoding="utf-8"))))
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    main()
