"""Replay the frozen Round 7 reply and social-intake benchmarks."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter_ns

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import softmax

from round7_models import (LABELS, dm_predictor, fasttext_predictor, minilm_predictor,
                           train_fasttext, zero_shot_predictor)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
from pakistan_phone import normalize_phone
from social_routes import extract
from verification import parse_reply

LANGUAGES = ("en", "roman_ur", "ur", "other")
DM_FIELDS = ("name", "phone", "address", "items")
COMMIT = {"CONFIRM", "DENY"}
TRAPS = ("DENY→SHIP", "CONFIRM→HOLD")


def load_corpus():
    data = ROOT / "data"
    lock = json.loads((data / "reply_evaluation.v1.lock.json").read_text(encoding="utf-8"))
    corpora = {}
    for filename, digest in lock["sha256"].items():
        body = (data / filename).read_text(encoding="utf-8")
        if hashlib.sha256(body.encode("utf-8")).hexdigest() != digest:
            raise ValueError(f"Frozen corpus hash mismatch: {filename}")
        corpora[filename] = [json.loads(line) for line in body.splitlines()]
    replies = corpora["reply_intents.v1.jsonl"]
    if Counter(row["split"] for row in replies) != lock["reply_counts"]:
        raise ValueError("Unexpected split sizes")
    families, messages = {}, {}
    for row in replies:
        split = row["split"]
        text = (row["text"] or "").strip().casefold().rstrip(".!")
        if families.setdefault(row["family"], split) != split or messages.setdefault(text, split) != split:
            raise ValueError(f"Split overlap at {row['id']}")
    if len({row["id"] for row in replies}) != len(replies):
        raise ValueError("Duplicate reply IDs")
    return replies, corpora["dm_extraction.v1.jsonl"]


def _training_rows(corpus, corrections):
    training = [row for row in corpus if row["split"] == "train"]
    if not corrections:
        return training
    reserved = {" ".join((row["text"] or "").casefold().split())
                for row in corpus if row["split"] != "train"}
    latest = {}
    for line in corrections.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        text = row.get("text")
        if (row.get("schema_version") != 1 or row.get("label") not in LABELS
                or not isinstance(text, str) or not text.strip()
                or type(row.get("message_id")) is not int or type(row.get("id")) is not int):
            raise ValueError("Expected version 1 correction rows with retained text and valid labels")
        previous = latest.get(row["message_id"])
        if previous is None or row["id"] > previous["id"]:
            latest[row["message_id"]] = row
    for row in latest.values():
        text = row["text"]
        if " ".join(text.casefold().split()) not in reserved:
            training.append({"text": text, "label": row["label"]})
    return training


def observe(predict, rows):
    for row in rows[:10]:
        predict(row["text"])
    predictions, duration_ms = [], []
    for row in rows:
        before = perf_counter_ns()
        predictions.append(predict(row["text"]))
        duration_ms.append((perf_counter_ns() - before) / 1e6)
    scores = np.asarray(predictions)
    if (scores.shape != (len(rows), len(LABELS)) or not np.isfinite(scores).all()
            or (scores < 0).any() or not np.allclose(scores.sum(axis=1), 1)):
        raise ValueError("Expected four finite probabilities summing to one per reply")
    return scores, np.array(duration_ms)


def temperature_scale(scores, truth, validation):
    log_prob = np.log(np.clip(scores, 1e-10, 1))
    targets = truth[validation]
    result = minimize_scalar(
        lambda temp: -np.log(softmax(log_prob[validation] / temp, axis=1)
                             [np.arange(len(targets)), targets]).mean(),
        method="bounded", bounds=(0.25, 8.0))
    return softmax(log_prob / result.x, axis=1), float(result.x)


def operating_threshold(scores, labels, truth, validation):
    # Use the lowest threshold with nonempty, error-free validation commits.
    eligible = validation & np.isin(labels, tuple(COMMIT))
    for cutoff in (0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.99):
        accepted = eligible & (scores >= cutoff)
        if accepted.any() and (labels[accepted] == truth[accepted]).all():
            return cutoff, True
    return 0.99, False


def calibration_error(confidence, correct):
    # Equal-width bins over top-label confidence. Empty bins carry zero weight.
    bins = np.minimum((confidence * 10).astype(int), 9)
    return sum(float(mask.mean()) * abs(float(correct[mask].mean()) - float(confidence[mask].mean()))
               for index in range(10) if (mask := bins == index).any())


def metrics(rows, scores, predicted, threshold, durations):
    n = len(rows)
    truth = np.array([row["label"] for row in rows])
    confidence = scores.max(axis=1)
    committed = np.isin(predicted, tuple(COMMIT)) & (confidence >= threshold)
    correct = predicted == truth
    traps = {}
    for trap, opposite in zip(TRAPS, ("CONFIRM", "DENY")):
        family = np.array([row.get("trap") == trap for row in rows])
        traps[trap] = {"cases": int(family.sum()), "committed": int((family & committed).sum()),
                       "errors": int((family & committed & ~correct).sum()),
                       "top1_opposite": int((family & (predicted == opposite)).sum())}
    error_count = int((committed & ~correct).sum())
    return {"n": n, "accuracy": float(correct.mean()),
            "brier": float(np.square(scores - np.eye(len(LABELS))[[LABELS.index(label) for label in truth]])
                           .sum(axis=1).mean()),
            "ece": calibration_error(confidence, correct),
            "commits": int(committed.sum()), "errors": error_count,
            "commit_error": error_count / int(committed.sum()) if committed.any() else None,
            "coverage": float(committed.mean()), "traps": traps,
            "review_commits": int((committed & ~np.isin(truth, tuple(COMMIT))).sum()),
            "p95_ms": float(np.percentile(durations, 95)),
            "wrong_commits": [row["id"] for row, wrong in zip(rows, committed & ~correct) if wrong]}


def measure(name, predictor, size, rows, *, calibrate=False):
    scores, durations = observe(predictor, rows)
    truth = np.array([row["label"] for row in rows])
    splits = np.array([row["split"] for row in rows])
    validation = splits == "val"
    temperature = None
    if calibrate:
        scores, temperature = temperature_scale(scores, np.array([LABELS.index(label) for label in truth]),
                                               validation)
    predicted = np.array(LABELS)[scores.argmax(axis=1)]
    threshold, selected = (1.0, True) if name == "Rules" else operating_threshold(
        scores.max(axis=1), predicted, truth, validation)
    metrics_by_group = {}
    for group, include in (("all", splits != "val"), ("test", splits == "test"),
                           ("regression", splits == "regression"), ("validation", validation)):
        languages = np.array([row["language"] for row in rows])
        for language in ("", *LANGUAGES):
            mask = include & (languages == language) if language else include
            if mask.any():
                metrics_by_group[group + (f"/{language}" if language else "")] = metrics(
                    [row for row, keep in zip(rows, mask) if keep], scores[mask], predicted[mask],
                    threshold, durations[mask])
    return {"threshold": threshold, "threshold_validated": selected, "bytes": size,
            "temperature": temperature, "groups": metrics_by_group}


def gate(candidate, rules):
    all_rows = candidate["groups"]["all"]
    test = candidate["groups"]["test"]
    return {
        "cpu_p95": all_rows["p95_ms"] < 100,
        "artifact_size": candidate["bytes"] < 250_000_000,
        "validated_threshold": candidate["threshold_validated"],
        "both_trap_families_covered_on_novel_rows": all(item["committed"] for item in test["traps"].values()),
        "zero_trap_errors": all(not item["errors"] for item in all_rows["traps"].values()),
        "committed_error_no_worse_than_rules": (all_rows["commit_error"] is not None
                                                and all_rows["commit_error"] <= rules["groups"]["all"]["commit_error"]),
        "novel_accuracy_above_rules": test["accuracy"] > rules["groups"]["test"]["accuracy"],
        "calibration": all_rows["ece"] <= 0.10,
    }


def _normalized(text):
    return " ".join(text.casefold().split()).rstrip(" .،۔")


def measure_dm(predict, rows):
    fields = {field: Counter() for field in DM_FIELDS}
    examples = []
    exact = 0
    for row in rows:
        draft = predict(row["text"])
        matches = []
        for field, expected in row["expected"].items():
            raw = draft[field]
            guess = "" if _normalized(raw) in {"", "unknown"} else raw
            if field == "phone" and guess:
                guess = normalize_phone(guess) or guess
            match = _normalized(guess) == _normalized(expected)
            matches.append(match)
            counts = fields[field]
            counts["total"] += 1
            counts["present"] += bool(expected)
            counts["correct_present"] += bool(expected) and match
            if match:
                counts["correct"] += 1
                continue
            error = "spurious" if not expected else "wrong" if guess else "missing"
            counts[error] += 1
            examples.append({"id": row["id"], "field": field, "error": error, "guess": guess})
        exact += all(matches)
    return {"n": len(rows), "exact": exact, "fields": fields, "errors": examples}


def file_size(directory, *names):
    return sum((directory / name).stat().st_size for name in names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    minilm = parser.add_mutually_exclusive_group()
    minilm.add_argument("--minilm-checkpoint", type=Path, help="Local original MiniLM checkpoint to fine-tune")
    minilm.add_argument("--minilm-model", type=Path, help="Directory containing a previously fine-tuned INT8 model")
    parser.add_argument("--zero-shot", type=Path, help="Local quantized multilingual MiniLMv2 NLI checkpoint")
    parser.add_argument("--dm-model", type=Path, help="Local LaMini-Flan-T5 ONNX checkpoint")
    parser.add_argument("--corrections", type=Path, help="Reviewed local version 1 correction export")
    parser.add_argument("--train-only", action="store_true")
    args = parser.parse_args()
    corpus, dm = load_corpus()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    training = _training_rows(corpus, args.corrections)
    fasttext_path = args.work_dir / "reply.fasttext.bin"
    train_fasttext(training, fasttext_path)
    minilm_path = args.minilm_model
    if args.minilm_checkpoint:
        from round7_finetune import train_minilm
        minilm_path = args.work_dir / "minilm-trained"
        train_minilm(training, args.minilm_checkpoint, minilm_path)
    if args.train_only:
        return
    held_out = [row for row in corpus if row["split"] != "train"]
    rules = measure("Rules", lambda text: np.eye(len(LABELS))[LABELS.index(parse_reply(text))], 0, held_out)
    contenders = {"fastText": measure("fastText", fasttext_predictor(fasttext_path),
                                     fasttext_path.stat().st_size, held_out, calibrate=True)}
    if minilm_path:
        contenders["Fine-tuned MiniLM INT8"] = measure(
            "Fine-tuned MiniLM INT8", minilm_predictor(minilm_path),
            file_size(minilm_path, "decision.int8.onnx", "tokenizer.json"), held_out, calibrate=True)
    if args.zero_shot:
        contenders["Zero-shot MiniLMv2 NLI INT8"] = measure(
            "Zero-shot MiniLMv2 NLI INT8", zero_shot_predictor(args.zero_shot),
            file_size(args.zero_shot, "onnx/model_int8.onnx", "tokenizer.json", "config.json"), held_out)
    for contender in contenders.values():
        contender["gate"] = gate(contender, rules)
    report = {"replies": {"Rules": rules, **contenders}, "dm": {"Rules": measure_dm(extract, dm)}}
    if args.dm_model:
        predict_dm = dm_predictor(args.dm_model)
        report["dm"]["LaMini-Flan-T5"] = measure_dm(
            lambda transcript: {field: predict_dm(transcript, field) for field in DM_FIELDS}, dm)
    output = args.work_dir / "metrics.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
