"""Fetch public Whisper weights once; subsequent voice inference is offline."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parents[1] / "data/whisper/hf_home"))
from verification import prepare_voice_model


if __name__ == "__main__":
    try:
        prepare_voice_model(offline=False)
    except Exception as exc:
        print(f"Voice setup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print("Whisper model cached successfully; Urdu transcription is ready for offline use.")
