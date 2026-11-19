import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
import courier_evaluation
import main
import service
from records import connect, insert_order, write
from train_model import FEATURES


PREFIX = "/integrations/couriers"
HEADER = "order_id,courier,tracking_number,outcome,billed_fee_pkr\n"


class CourierTests(unittest.TestCase):
    def setUp(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "state.json"
        self.enterContext(patch.object(service, "STATE_PATH", path))
        accounts = {name: {"tenant_id": name, "key": f"test-courier-operator-key-{name}"}
                    for name in ("alpha", "beta", "demo")}
        self.enterContext(patch.dict(os.environ, COD_GUARD_OPERATORS=json.dumps(accounts),
                                     COD_GUARD_TCS=json.dumps({"alpha": "mock-token-not-secret"})))
        self.client = self.enterContext(TestClient(main.app))
        with write(path) as db:
            for order_id in ("one", "two", "three"):
                insert_order(db, "alpha", {**dict.fromkeys(FEATURES, 0), "amount_pkr": 1000,
                                           "order_id": order_id, "customer_name": "Fixture", "product": "Parcel",
                                           "city": "Lahore", "phone": "", "data_source": "SHADOW"})

    def auth(self, name="alpha"):
        return {"Authorization": f"Bearer test-courier-operator-key-{name}"}

    def upload(self, text, name="alpha"):
        return self.client.post(f"{PREFIX}/outcomes/import", headers=self.auth(name),
                                files={"file": ("invoice.csv", (HEADER + text).encode(), "text/csv")})

    def test_atomic_csv_scope_idempotence_and_correction(self):
        row = "one,postex,ABC123,refused,175.50\n"
        self.assertEqual(self.upload(row + "unknown,trax,DEF123,returned,100\n").status_code, 404)
        self.assertEqual(service._load_state("alpha")["outcomes"], {})
        self.assertEqual(self.upload(row, "beta").status_code, 404)
        self.assertEqual(self.upload(row, "demo").status_code, 403)
        self.assertEqual(self.upload(row).json()["labels_added"], 1)
        self.assertEqual(self.upload(row).json()["evidence_updated"], 0)
        self.assertEqual(self.upload("two,postex,abc123,delivered,0\n").status_code, 409)
        self.assertEqual(self.upload(row.replace("refused", "returned")).status_code, 409)
        self.assertEqual(self.upload("two,trax,DEF123,returned,100\n").status_code, 200)
        with connect(service.STATE_PATH) as db:
            self.assertEqual(db.execute("SELECT billed_fee_paisa FROM courier_outcome_evidence WHERE order_id='one'").fetchone()[0], 17550)

    @patch("courier_outcomes.httpx.request")
    def test_tcs_uses_only_latest_matching_status(self, request):
        def lookup():
            return self.client.post(f"{PREFIX}/tcs/orders/three/refresh", headers=self.auth(),
                                    json={"tracking_number": "12345"})
        events = [{"consignmentno": "99999", "status": "Delivered", "datetime": "Saturday Oct 19, 2024 00:00"},
                  {"consignmentno": "12345", "status": "Delivered", "datetime": "Thursday Oct 17, 2024 12:58"},
                  {"consignmentno": "12345", "status": "Awaiting Receiver Collection", "datetime": "Friday Oct 18, 2024 12:58"}]
        request.return_value = httpx.Response(200, request=httpx.Request("GET", "https://example.invalid"),
                                               json={"deliveryinfo": events})
        self.assertEqual(lookup().json()["terminal"], False)
        request.return_value = httpx.Response(200, request=httpx.Request("GET", "https://example.invalid"),
                                               json={"deliveryinfo": events[:2]})
        self.assertEqual(lookup().json()["labels_added"], 1)
        self.assertEqual(request.call_args.kwargs["json"], {"consignee": ["12345"]})
        self.assertFalse(request.call_args.kwargs["follow_redirects"])

    def test_shadow_candidate_cannot_publish(self):
        self.assertEqual(self.upload("one,tcs,12345,delivered,100\n").status_code, 200)
        result = courier_evaluation.run("alpha")
        self.assertEqual(result["eligible_training_rows"], 1)
        self.assertFalse(result["published"])
        self.assertEqual(result["test_source"], "SYNTHETIC")
