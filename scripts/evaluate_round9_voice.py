"""Reproduce the offline stock-versus-fine-tune Urdu comparison."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tarfile
from time import perf_counter

from evaluate_urdu_voice import (MANIFEST, ROOT, audio_members, edits, parse_reply, read_clip,
                                 transcribe_voice_note, words)

SHORT_PROMPTS = ROOT / "data/urdu_short_replies.v1.json"


def build_short(checkpoint, prompts, output):
    import numpy as np
    import torch
    from scipy.io.wavfile import write
    from transformers import AutoTokenizer, VitsModel

    torch.set_num_threads(1)
    tokenizer = AutoTokenizer.from_pretrained(checkpoint, local_files_only=True)
    model = VitsModel.from_pretrained(checkpoint, local_files_only=True).eval()
    sample_rate = model.config.sampling_rate
    output.mkdir(parents=True)
    compiled = []
    for index, row in enumerate(prompts["rows"]):
        if parse_reply(row["reference"]) != row["intent"]:
            raise ValueError(f"Reference label changed for {row['id']}")
        torch.manual_seed(900 + index)
        with torch.inference_mode():
            samples = model(**tokenizer(row["reference"], return_tensors="pt")).waveform[0].numpy()
        audio = np.pad(np.clip(samples, -1, 1), int(sample_rate * 0.15))
        path = output / (row["id"] + ".wav")
        write(path, sample_rate, (audio * 32767).astype(np.int16))
        compiled.append({**row, "sha256": digest(path.read_bytes())})
    (output / "manifest.json").write_text(json.dumps(compiled, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")


def digest(audio):
    return hashlib.sha256(audio).hexdigest()


def compare_group(rows, read):
    measurements = []
    for row in rows:
        audio = read(row)
        if digest(audio) != row["sha256"]:
            raise ValueError(f"Audio hash mismatch for {row['id']}")
        start = perf_counter()
        result = transcribe_voice_note(audio, suffix=".wav")
        transcript = result.get("text", "")
        intent = parse_reply(transcript) if result["ok"] and not result.get("warning") else "UNCLEAR"
        reference = words(row["reference"])
        measurement = {"id": row["id"], "reference_words": len(reference),
                       "word_edits": edits(reference, words(transcript)), "transcript": transcript,
                       "expected_intent": row["intent"], "intent": intent, "ok": result["ok"],
                       "warning": result.get("warning") or result.get("reason"),
                       "seconds": round(perf_counter() - start, 3)}
        measurements.append(measurement)
        print(f"{row['id']}: {measurements[-1]['word_edits']} edits; intent {intent}", flush=True)
    total_words = sum(row["reference_words"] for row in measurements)
    word_edits = sum(row["word_edits"] for row in measurements)
    accurate = sum(row["ok"] and row["intent"] == row["expected_intent"] for row in measurements)
    return {"clips": len(rows), "reference_words": total_words, "word_edits": word_edits,
            "wer": word_edits / total_words, "correct_intents": accurate, "rows": measurements}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tts-checkpoint", type=Path, help="Generate a fresh short set with this local checkpoint")
    parser.add_argument("--short", type=Path, required=True, help="Short WAV set directory")
    parser.add_argument("--fleurs", type=Path, help="Also replay the official FLEURS test archive")
    parser.add_argument("--skip-short", action="store_true")
    parser.add_argument("--checkpoint", type=Path, help="Local CTranslate2 directory (defaults to stock small)")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    os.environ["COD_GUARD_OFFLINE"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    prompts = json.loads(SHORT_PROMPTS.read_text(encoding="utf-8"))
    if args.tts_checkpoint:
        build_short(args.tts_checkpoint, prompts, args.short)
        return
    if args.output is None or (args.skip_short and args.fleurs is None):
        parser.error("Supply --output and at least one evaluation set")
    if args.checkpoint and not (args.checkpoint / "model.bin").is_file():
        parser.error("Expected a local CTranslate2 checkpoint containing model.bin")
    os.environ["COD_GUARD_WHISPER_MODEL"] = str(args.checkpoint.resolve()) if args.checkpoint else "small"
    outcome = {"checkpoint": args.checkpoint.name if args.checkpoint else "Whisper small (stock)", "sets": {}}
    if not args.skip_short:
        rows = json.loads((args.short / "manifest.json").read_text(encoding="utf-8"))
        if [{key: row[key] for key in ("id", "reference", "intent")} for row in rows] != prompts["rows"]:
            raise ValueError("Short reply manifest differs from the versioned prompts")
        outcome["sets"]["[PK-SYNTH] short Urdu"] = compare_group(
            rows, lambda row: (args.short / (row["id"] + ".wav")).read_bytes())
    if args.fleurs:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        with tarfile.open(args.fleurs, "r:gz") as archive:
            members = audio_members(archive)
            outcome["sets"]["[PK-REAL] FLEURS read speech"] = compare_group(
                manifest["rows"], lambda row: read_clip(archive, members, row["file"]))
    args.output.write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
