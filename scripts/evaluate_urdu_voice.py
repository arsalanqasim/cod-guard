"""Measure the deployed offline Whisper → rules pipeline on frozen FLEURS Urdu audio."""
import argparse
import csv
import hashlib
import json
import os
import sys
import tarfile
import unicodedata
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
from verification import parse_reply, transcribe_voice_note

MANIFEST = ROOT / "data/urdu_voice_test.v1.json"
BUNDLED_ID = 1806


def words(text):
    normalized = unicodedata.normalize("NFKC", text).translate(str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی"}))
    return "".join(char if char.isalnum() else "" if unicodedata.combining(char) else " "
                   for char in normalized.casefold()).split()


def edits(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for index, expected in enumerate(reference, start=1):
        current = [index]
        for column, heard in enumerate(hypothesis, start=1):
            current.append(min(current[-1] + 1, previous[column] + 1,
                               previous[column - 1] + (heard != expected)))
        previous = current
    return previous[-1]


def audio_members(archive):
    return {Path(member.name).name: member for member in archive if member.isfile()}


def read_clip(archive, members, filename):
    with archive.extractfile(members[filename]) as stream:
        return stream.read()


def freeze(reference_tsv, archive, members):
    with reference_tsv.open(encoding="utf-8", newline="") as source:
        candidates = sorted(csv.reader(source, delimiter="\t"),
                            key=lambda row: hashlib.sha256(row[1].encode()).digest())
    rows, seen = [], {BUNDLED_ID}
    for row in candidates:
        sentence_id, filename, reference = int(row[0]), row[1], row[2]
        if sentence_id in seen or filename not in members:
            continue
        seen.add(sentence_id)
        audio = read_clip(archive, members, filename)
        rows.append({"id": sentence_id, "file": filename, "reference": reference,
                     "intent": parse_reply(reference), "sha256": hashlib.sha256(audio).hexdigest()})
        if len(rows) == 12:
            return {"version": 1, "dataset": "google/fleurs", "configuration": "ur_pk", "split": "test",
                    "revision": "4683b04", "license": "CC BY 4.0", "rows": rows}
    raise ValueError("Expected 12 unique Urdu test sentences")


def evaluate(manifest, archive, members):
    results = []
    for row in manifest["rows"]:
        audio = read_clip(archive, members, row["file"])
        if hashlib.sha256(audio).hexdigest() != row["sha256"]:
            raise ValueError(f"Audio hash mismatch for {row['file']}")
        start = perf_counter()
        result = transcribe_voice_note(audio, suffix=".wav")
        elapsed = perf_counter() - start
        transcript = result.get("text", "")
        intent = parse_reply(transcript) if result.get("ok") and not result.get("warning") else "UNCLEAR"
        expected = words(row["reference"])
        results.append({**row, "transcript": transcript, "predicted_intent": intent,
                        "reference_words": len(expected), "word_edits": edits(expected, words(transcript)),
                        "seconds": round(elapsed, 3), "ok": result["ok"],
                        "warning": result.get("warning") or result.get("reason")})
        print(f"{row['id']}: {results[-1]['word_edits']}/{len(expected)} edits; {intent}; {elapsed:.2f}s",
              flush=True)
    count = len(results)
    return {"version": 1, "manifest_sha256": hashlib.sha256(
                MANIFEST.read_text(encoding="utf-8").encode()).hexdigest(),
            "model": os.environ.get("COD_GUARD_WHISPER_MODEL", "small"),
            "wer": sum(row["word_edits"] for row in results) / sum(row["reference_words"] for row in results),
            "intent_accuracy": sum(row["ok"] and row["predicted_intent"] == row["intent"]
                                   for row in results) / count,
            "rows": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    stage = parser.add_mutually_exclusive_group(required=True)
    stage.add_argument("--freeze-from", type=Path, help="Official test.tsv, used once before scoring")
    stage.add_argument("--output", type=Path)
    args = parser.parse_args()
    os.environ["COD_GUARD_OFFLINE"] = "1"
    with tarfile.open(args.archive, "r:gz") as archive:
        members = audio_members(archive)
        if args.freeze_from:
            manifest = freeze(args.freeze_from, archive, members)
            with MANIFEST.open("x", encoding="utf-8", newline="\n") as target:
                json.dump(manifest, target, ensure_ascii=False, indent=2)
                target.write("\n")
        else:
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
            report = evaluate(manifest, archive, members)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"WER {report['wer']:.1%}; end-to-end intent {report['intent_accuracy']:.1%}")


if __name__ == "__main__":
    main()
