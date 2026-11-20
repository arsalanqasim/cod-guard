"""Run a trusted local reply model on retained replies without changing decisions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from round7_models import LABELS, fasttext_predictor, minilm_predictor, zero_shot_predictor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
from reply_corrections import run_shadow, shadow_agreement


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--kind", choices=("fasttext", "minilm", "zero-shot"), required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--state", type=Path,
                        default=Path(os.environ.get("COD_GUARD_DATA_DIR", ROOT / "data")) / "state.json")
    args = parser.parse_args()
    if not args.state.with_suffix(".sqlite3").is_file():
        parser.error("The order database does not exist")
    if args.kind == "fasttext":
        files = [args.artifact]
        predictor = fasttext_predictor(args.artifact)
    elif args.kind == "minilm":
        files = [args.artifact / name for name in ("decision.int8.onnx", "tokenizer.json")]
        predictor = minilm_predictor(args.artifact)
    else:
        files = [args.artifact / name for name in ("onnx/model_int8.onnx", "tokenizer.json", "config.json")]
        predictor = zero_shot_predictor(args.artifact)
    digest = hashlib.sha256()
    for path in files:
        with path.open("rb") as data:
            digest.update(hashlib.file_digest(data, "sha256").digest())
    model = f"{args.kind}:{digest.hexdigest()}"

    def predict(text):
        probabilities = predictor(text)
        index = int(probabilities.argmax())
        return LABELS[index], float(probabilities[index])

    saved = run_shadow(args.state, args.tenant, model, predict)
    print(json.dumps({"saved": saved, "models": shadow_agreement(args.state, args.tenant)}, indent=2))


if __name__ == "__main__":
    main()
