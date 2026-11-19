import sys
import json
import os
from threading import Event
from time import monotonic, sleep
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
import main
import service
import operators


class ApiTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        active = patch.object(service, "STATE_PATH", Path(temp.name) / "state.json")
        active.start()
        self.addCleanup(active.stop)
        key = "synthetic-test-operator-key"
        config = {"operator-a": {"tenant_id": "demo", "key": key}}
        self.enterContext(patch.dict(os.environ, COD_GUARD_OPERATORS=json.dumps(config)))
        self.enterContext(patch.object(operators, "_write_windows", {}))
        self.client = TestClient(main.app, headers={"Authorization": f"Bearer {key}"})
        self.order_id = service.load_orders().iloc[0]["order_id"]

    def test_unknown_orders_are_404_and_outcomes_are_validated(self):
        self.assertEqual(self.client.post("/orders/MISSING/verify", json={"text": "Yes"}).status_code, 404)
        self.assertEqual(self.client.post("/orders/MISSING/outcome", json={"outcome": "delivered"}).status_code, 404)
        self.assertEqual(self.client.post(f"/orders/{self.order_id}/outcome", json={"outcome": "unknown"}).status_code, 422)
        self.assertEqual(self.client.post(f"/orders/{self.order_id}/verify", json={"text": " "}).status_code, 422)

    def test_confirm_and_deny_override_the_served_order(self):
        response = self.client.post(f"/orders/{self.order_id}/verify", json={"text": "Yes confirm"})
        self.assertEqual(response.json()["decision"], "SHIP")
        response = self.client.post(f"/orders/{self.order_id}/verify", json={"text": "جی نہیں"})
        self.assertEqual(response.json()["decision"], "HOLD_CANCEL")
        self.assertNotIn("label_failed", self.client.get(f"/orders/{self.order_id}").json())

    def test_voice_preview_requires_an_explicit_apply_action(self):
        result = {"ok": True, "text": "جی نہیں", "warning": None}
        path = f"/orders/{self.order_id}/voice"
        audio = {"file": ("note.ogg", b"audio", "audio/ogg")}

        def completed(response):
            self.assertEqual(response.status_code, 202)
            url = f"{path}/{response.json()['job_id']}"
            deadline = monotonic() + 5
            while monotonic() < deadline:
                status = self.client.get(url).json()
                if status["status"] in {"done", "failed"}:
                    self.assertEqual(status["status"], "done", status)
                    return status["result"]
                sleep(0.01)
            self.fail("Voice job did not finish")

        started, resume = Event(), Event()

        def pause(*args, **kwargs):
            started.set()
            if not resume.wait(5):
                raise RuntimeError("Voice job did not return control to the API")
            return result

        with patch.object(main, "transcribe_voice_note", side_effect=pause):
            preview = self.client.post(path, files=audio)
            try:
                self.assertEqual(preview.status_code, 202)
                self.assertTrue(started.wait(5))
                job_id = preview.json()["job_id"]
                self.assertEqual(self.client.get(f"{path}/{job_id}").json()["status"], "running")
                self.assertEqual(self.client.get(f"/orders/other/voice/{job_id}").status_code, 404)
                self.assertEqual(TestClient(main.app).get(f"{path}/{job_id}").status_code, 401)
                self.assertEqual(service.conversation(self.order_id), [])
            finally:
                resume.set()
            self.assertFalse(completed(preview)["applied"])
            self.assertEqual(service.conversation(self.order_id), [])
        with patch.object(main, "transcribe_voice_note", return_value=result):
            applied = completed(self.client.post(path + "?commit_decision=true", files=audio))
            self.assertEqual(applied["decision"], "HOLD_CANCEL")
        result["warning"] = "Low transcription confidence"
        with patch.object(main, "transcribe_voice_note", return_value=result):
            response = completed(self.client.post(path + "?commit_decision=true", files=audio))
            self.assertFalse(response["applied"])
            self.assertEqual(response["intent"], "UNCLEAR")


if __name__ == "__main__":
    unittest.main()
