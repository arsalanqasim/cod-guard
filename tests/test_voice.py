import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
import verification


class VoiceTests(unittest.TestCase):
    def test_installed_audio_decoder_accepts_a_real_wav(self):
        from faster_whisper.audio import decode_audio
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decoder.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b"\x00\x00" * 16000)
            self.assertEqual(len(decode_audio(str(path), sampling_rate=16000)), 16000)

    def test_missing_and_oversized_audio_are_explicit_errors(self):
        self.assertEqual(verification.transcribe_voice_note("not-a-file.ogg")["error"], "invalid_audio")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.ogg"
            with path.open("wb") as handle:
                handle.truncate(verification.VOICE_LIMIT_BYTES + 1)
            self.assertEqual(verification.transcribe_voice_note(path)["error"], "invalid_audio")

    def test_transcript_is_unchanged_and_model_failure_does_not_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b"\x00\x00" * 16000)
            model = SimpleNamespace(transcribe=lambda *a, **k: (
                iter([SimpleNamespace(text=" جی نہیں", avg_logprob=-0.2)]), SimpleNamespace()))
            with patch.object(verification, "prepare_voice_model", return_value=model):
                result = verification.transcribe_voice_note(path)
                self.assertTrue(result["ok"])
                self.assertEqual(result["text"], "جی نہیں")
                self.assertEqual(verification.parse_reply(result["text"]), "DENY")
            with patch.object(verification, "prepare_voice_model", side_effect=RuntimeError("offline weights missing")):
                result = verification.transcribe_voice_note(path)
                self.assertEqual(result["error"], "model_unavailable")
                self.assertIn("offline weights missing", result["reason"])


if __name__ == "__main__":
    unittest.main()
