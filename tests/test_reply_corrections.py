import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend/app"), str(ROOT)]
import main
import operators
import service
from scripts.purge_replies import purge
from records import connect, insert_order, write
from reply_corrections import run_shadow


class ReplyCorrectionTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(temp) / "state.json"
        self.enterContext(patch.object(service, "STATE_PATH", self.path))
        self.enterContext(patch.object(operators, "_write_windows", {}))
        config = {tenant: {"tenant_id": tenant, "key": f"fixture-reply-operator-key-{tenant}"}
                  for tenant in ("alpha", "beta")}
        self.enterContext(patch.dict(os.environ, COD_GUARD_OPERATORS=json.dumps(config)))
        self.alpha = self.enterContext(TestClient(main.app, headers={
            "Authorization": f"Bearer {config['alpha']['key']}"}))
        self.beta = self.enterContext(TestClient(main.app, headers={
            "Authorization": f"Bearer {config['beta']['key']}"}))
        self.order = service.load_orders().to_dict("records")[0]
        self.order_id = self.order["order_id"]
        self.url = f"/orders/{self.order_id}"
        with write(self.path) as db:
            insert_order(db, "alpha", self.order)

    def reply(self, text):
        response = self.alpha.post(self.url + "/verify", json={"text": text})
        self.assertEqual(response.status_code, 200)
        return self.alpha.get(self.url).json()["decision_revision"]

    def correct(self, source, expected, label, client=None):
        return (client or self.alpha).post(f"{self.url}/replies/{source}/correction",
                                          json={"label": label, "expected_revision": expected})

    def export(self, client=None, **params):
        response = (client or self.alpha).get("/reply-corrections/export", params=params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return [json.loads(line) for line in response.text.splitlines()]

    def test_unclear_resolution_and_override_keep_the_original_reply_and_export_versions(self):
        source = self.reply("Jee poora order radd kar dein")
        self.assertEqual(self.correct(source, source, "DENY", self.beta).status_code, 404)
        first = self.correct(source, source, "DENY")
        self.assertEqual(first.status_code, 201, first.text)
        result = first.json()
        self.assertEqual(result["decision"], "HOLD_CANCEL")
        self.assertEqual(self.correct(source, source, "DENY").status_code, 409)
        second = self.correct(source, result["decision_revision"], "MODIFICATION")
        self.assertEqual(second.status_code, 201, second.text)
        self.assertTrue(second.json()["needs_review"])
        self.assertIn(second.json()["decision"], {"HOLD", "VERIFY_FIRST"})
        detail = self.alpha.get(self.url).json()
        self.assertEqual([message["intent"] for message in detail["messages"]], ["UNCLEAR"])
        self.assertFalse(detail["verified"])
        rows = self.export()
        self.assertEqual([row["label"] for row in rows], ["DENY", "MODIFICATION"])
        self.assertEqual({(row["schema_version"], row["language"], row["text"]) for row in rows},
                         {(1, "roman_ur", "Jee poora order radd kar dein")})
        self.assertEqual(self.export(limit=1), rows[:1])
        self.assertEqual(self.export(after=rows[0]["id"]), rows[1:])
        self.assertEqual(self.export(self.beta), [])

    def test_stale_or_signed_reply_cannot_be_used_for_a_correction(self):
        first = self.reply("جی نہیں")
        latest = self.reply("Yes")
        self.assertEqual(self.correct(first, latest, "DENY").status_code, 409)
        with write(self.path) as db, service.update_state(db, "alpha", (self.order_id,)) as state:
            service.apply_verification(state, self.order, "Confirm", "CONFIRM", "whatsapp_button", "webhook")
        revision = self.alpha.get(self.url).json()["decision_revision"]
        self.assertEqual(self.correct(revision, revision, "DENY").status_code, 409)
        self.assertEqual(self.export(), [])

    def test_shadow_is_idempotent_advisory_and_pairs_with_operator_labels(self):
        source = self.reply("ہاں، نیلی قمیض کے بغیر بھیج دیں")
        before = service.assess_order(self.order, tenant_id="alpha")
        predict = unittest.mock.Mock(return_value=("MODIFICATION", 0.95))
        self.assertEqual(run_shadow(self.path, "alpha", "fixture-v1", predict), 1)
        self.assertEqual(run_shadow(self.path, "alpha", "fixture-v1", predict), 0)
        predict.assert_called_once_with("ہاں، نیلی قمیض کے بغیر بھیج دیں")
        self.assertEqual(service.assess_order(self.order, tenant_id="alpha"), before)
        self.assertEqual(self.alpha.get("/reply-corrections/shadow").json()[0]["labeled"], 0)
        self.assertEqual(self.correct(source, source, "MODIFICATION").status_code, 201)
        self.assertEqual(self.alpha.get("/reply-corrections/shadow").json(), [
            {"model": "fixture-v1", "predicted": 1, "labeled": 1, "agreement": 1, "agreement_rate": 1.0}
        ])
        self.assertEqual(self.beta.get("/reply-corrections/shadow").json(), [])
        self.assertEqual(self.export()[0]["language"], "ur")

    def test_purge_removes_the_exported_text_without_copying_it_into_the_log(self):
        revision = self.reply("I am afraid the order won't work for me")
        corrected = self.correct(revision, revision, "DENY")
        self.assertEqual(corrected.status_code, 201)
        self.assertEqual(purge(self.path, 30, today=datetime.now(timezone.utc) + timedelta(days=31)), 1)
        self.assertEqual(self.export(), [])
        with connect(self.path) as db:
            self.assertEqual(db.execute("SELECT label FROM reply_corrections").fetchone()["label"], "DENY")


if __name__ == "__main__":
    unittest.main()
