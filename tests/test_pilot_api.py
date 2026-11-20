import json
import os
import pickle
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend/app"), str(ROOT)]
import main
import operators
import service
import artifacts
from train_model import render_report
from records import connect
from scripts.purge_replies import purge


class PilotApiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "state.json"
        self.enterContext(patch.object(service, "STATE_PATH", self.path))
        self.enterContext(patch.object(operators, "_write_windows", {}))
        self.config = {tenant: {"tenant_id": tenant, "key": f"synthetic-operator-key-{tenant}"}
                       for tenant in ("demo", "alpha", "beta")}
        self.enterContext(patch.dict(os.environ, COD_GUARD_OPERATORS=json.dumps(self.config)))

    def client(self, tenant=None):
        headers = {"Authorization": f"Bearer {self.config[tenant]['key']}"} if tenant else {}
        return self.enterContext(TestClient(main.app, headers=headers))

    def import_csv(self, client, data, key="request-1"):
        return client.post("/orders/import", files={"file": ("orders.csv", data, "text/csv")},
                           headers={"Idempotency-Key": key})

    def test_invalid_model_is_unavailable_and_order_scoring_falls_back(self):
        original = service._bundle()
        client = self.client("demo")
        model_path = self.path.with_suffix(".pkl")
        with patch.object(service, "MODEL_PATH", model_path):
            for candidate in ({k: v for k, v in original.items() if k != "threshold"},
                              {**original, "threshold": None},
                              {**original, "columns": original["columns"][1:]}):
                with self.subTest(candidate=list(candidate)):
                    model_path.write_bytes(pickle.dumps(candidate))
                    self.assertEqual(client.get("/health").json(), {"status": "ok"})
                    self.assertEqual(client.get("/ready").status_code, 503)
                    self.assertFalse(client.get("/model").json()["available"])
                    orders = client.get("/orders")
                    self.assertEqual(orders.status_code, 200)
                    self.assertIsNone(orders.json()[0]["ml_probability"])

    def test_unreadable_db_and_malformed_legacy_file_map_to_the_same_503(self):
        client = self.client("demo")
        self.path.write_text("{not json", encoding="utf-8")
        for endpoint in ("/orders", "/metrics", "/model", "/ready"):
            response = client.get(endpoint)
            self.assertEqual((response.status_code, response.json()["error"]), (503, "state_unavailable"))
        self.path.with_suffix(".sqlite3").write_bytes(b"not a database")
        self.assertEqual(client.get("/orders/CG-00203").json()["error"], "state_unavailable")
        self.assertEqual(client.get("/health").status_code, 200)

    def test_ready_requires_a_coherent_versioned_evaluation_set(self):
        client = self.client("demo")
        model_path = self.path.with_suffix(".pkl")
        evaluation = json.loads((ROOT / "data/evaluation.json").read_text(encoding="utf-8"))
        bundle = service._bundle() | {key: evaluation[key] for key in ("model_id", "version", "trained_at")}
        markdown = render_report(evaluation)
        artifacts.publish(bundle, evaluation, markdown, model_path, expected=None)
        version = artifacts.active_version(model_path)
        evaluation_path = version / "evaluation.json"
        report_path = version / "report.md"
        with patch.object(service, "MODEL_PATH", model_path):
            self.assertEqual(client.get("/ready").status_code, 200)
            for path, content in (
                (evaluation_path, None), (evaluation_path, "{bad JSON"),
                (evaluation_path, json.dumps(evaluation | {"model_id": "different"})),
                (evaluation_path, json.dumps(evaluation | {"version": evaluation["version"] + 1})),
                (evaluation_path, json.dumps(evaluation | {"trained_at": "different"})),
                (evaluation_path, json.dumps(evaluation | {"chosen": {"threshold": .99}})),
                (report_path, None), (report_path, markdown.replace(evaluation["model_id"], "different")),
            ):
                with self.subTest(path=path.name, content=content is not None):
                    original = path.read_bytes()
                    try:
                        if content is None:
                            path.unlink()
                        else:
                            path.write_text(content, encoding="utf-8")
                        response = client.get("/ready")
                        self.assertEqual(response.status_code, 503)
                        self.assertEqual(response.json()["error"], "evaluation_unavailable")
                        self.assertEqual(client.get("/health").status_code, 200)
                        if path == evaluation_path:
                            self.assertEqual(client.get("/evaluation").status_code, 404)
                    finally:
                        path.write_bytes(original)
            self.assertEqual(client.get("/ready").status_code, 200)

    def test_intake_replays_receipt_reports_bad_rows_and_flags_missing_features(self):
        client = self.client("alpha")
        csv = ("order_id,customer_name,product,phone,phone_valid,order_hour\n"
               "one,Customer,Shirt,03001234567,,\n"
               "two,Customer,Shirt,03001234567,2,12\n"
               "three,Customer,Shirt,03001234567,0,24\n")
        first = self.import_csv(client, csv)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["imported"], 1)
        self.assertEqual([error["row"] for error in first.json()["errors"]], [3, 4])
        self.assertEqual(self.import_csv(client, csv).json(), first.json())
        self.assertEqual(self.import_csv(client, csv + "\n").status_code, 409)
        listed = client.get("/orders").json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["decision"], "VERIFY_FIRST")
        self.assertNotIn("03001234567", listed[0]["phone"])

    def test_keys_isolate_orders_and_record_actors_on_detail_and_writes(self):
        alpha, beta, anonymous = self.client("alpha"), self.client("beta"), self.client()
        csv = "order_id,customer_name,product,phone\none,Customer,Shirt,03001234567\n"
        self.assertEqual(self.import_csv(anonymous, csv).status_code, 401)
        self.assertEqual(self.import_csv(alpha, csv).status_code, 201)
        path = "/orders/one"
        self.assertEqual(anonymous.get(path).status_code, 401)
        self.assertEqual(beta.get(path).status_code, 404)
        self.assertEqual(beta.post(path + "/verify", json={"text": "Yes"}).status_code, 404)
        self.assertEqual(beta.post(path + "/outcome", json={"outcome": "refused"}).status_code, 404)
        self.assertEqual(beta.get("/orders").json(), [])
        self.assertEqual(alpha.get(path).json()["phone"], "03001234567")
        self.assertEqual(alpha.post(path + "/verify", json={"text": "Yes"}).status_code, 200)
        self.assertEqual(alpha.post(path + "/outcome", json={"outcome": "delivered"}).status_code, 200)
        self.assertEqual(anonymous.post("/model/retrain").status_code, 401)
        self.assertEqual(alpha.post("/model/retrain").status_code, 403)
        with connect(self.path) as db:
            events = [tuple(row) for row in db.execute("SELECT tenant_id, actor, action FROM audit_events ORDER BY id")]
        self.assertEqual(events, [("alpha", "alpha", action) for action in ("import", "phone_read", "decision", "outcome")])

    def test_body_cap_applies_to_streamed_requests_and_writes_are_rate_limited(self):
        client = self.client("demo")
        block = b"x" * 1024 * 1024
        huge = client.post("/model/retrain", content=(block for _ in range(14)))
        self.assertEqual(huge.status_code, 413)
        for _ in range(60):
            self.assertEqual(client.post("/orders/missing/verify", json={"text": "Yes"}).status_code, 404)
        self.assertEqual(client.post("/orders/missing/verify", json={"text": "Yes"}).status_code, 429)
        self.assertEqual(client.get("/health").status_code, 200)

    def test_retention_removes_raw_text_but_preserves_decision(self):
        client = self.client("demo")
        order = service.load_orders().iloc[0].to_dict()
        service.verify_reply(order, "Yes")
        with connect(self.path) as db, db:
            db.execute("UPDATE messages SET at='2000-01-01T00:00:00+00:00'")
        service.verify_reply(order, "No")
        self.assertEqual(purge(self.path, 30), 1)
        detail = client.get(f"/orders/{order['order_id']}").json()
        self.assertEqual([message["text"] for message in detail["messages"]], [None, "No"])
        self.assertEqual(detail["decision"], "HOLD_CANCEL")
