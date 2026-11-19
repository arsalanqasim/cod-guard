"""Rebuild the synthetic exhibition baseline and run project checks in order.

This replaces generated benchmark/model artifacts. Marked outcomes are retained
and can be learned again. --verify-only checks the current generated artifacts.
--voice adds a real offline transcription using the attributed bundled sample.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--voice", action="store_true")
    args = parser.parse_args()
    steps = [] if args.verify_only else [["data/generate_benchmark.py"],
                                          ["backend/app/train_model.py"], ["scripts/seed_demo.py"]]
    steps += [["tests/test_risk_engine.py"], ["tests/test_verification.py"],
              ["-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
              ["-m", "pip", "check"]]
    if args.voice:
        steps.append(["scripts/test_voice.py"])
    for step in steps:
        print("\n$ python " + " ".join(step), flush=True)
        result = subprocess.run([sys.executable, *step], cwd=ROOT)
        if result.returncode:
            print(f"FAILED: python {' '.join(step)} (exit {result.returncode})", file=sys.stderr)
            return result.returncode
    print("\nAll requested checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
