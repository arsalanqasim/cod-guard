import sys
import json
import os
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
        with patch.object(main, "transcribe_voice_note", return_value=result):
            preview = self.client.post(f"/orders/{self.order_id}/voice", files={"file": ("note.ogg", b"audio", "audio/ogg")})
            self.assertEqual(preview.status_code, 200)
            self.assertFalse(preview.json()["applied"])
            self.assertEqual(service.conversation(self.order_id), [])
            applied = self.client.post(f"/orders/{self.order_id}/voice?commit_decision=true",
                                       files={"file": ("note.ogg", b"audio", "audio/ogg")})
            self.assertEqual(applied.json()["decision"], "HOLD_CANCEL")
        result["warning"] = "Low transcription confidence"
        with patch.object(main, "transcribe_voice_note", return_value=result):
            response = self.client.post(f"/orders/{self.order_id}/voice?commit_decision=true",
                                        files={"file": ("note.ogg", b"audio", "audio/ogg")})
            self.assertFalse(response.json()["applied"])
            self.assertEqual(response.json()["intent"], "UNCLEAR")


if __name__ == "__main__":
    unittest.main()
