"""Transcribe a real audio file and print the unedited transcript and intent.

Usage: python scripts/test_voice.py path/to/urdu-note.ogg
Run scripts/prepare_voice.py once while online before using the offline demo.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
from verification import transcribe_voice_note, parse_reply


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path, nargs="?",
                        default=Path(__file__).resolve().parents[1] / "data/voice_samples/fleurs_ur_pk_test_0.ogg")
    args = parser.parse_args()
    result = transcribe_voice_note(str(args.audio))
    if not result["ok"]:
        print(result["reason"], file=sys.stderr)
        return 1
    print("Transcript (verbatim):")
    print(result["text"])
    print("Intent:", parse_reply(result["text"]))
    if result.get("warning"):
        print("Warning:", result["warning"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
