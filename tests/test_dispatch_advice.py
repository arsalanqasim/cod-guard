import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
import dispatch_advice
import main
import operators
import service
from address_quality import classify_address
from records import connect, insert_order, now, write


class DispatchAdviceTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(folder) / "state.json"
        self.enterContext(patch.object(service, "STATE_PATH", self.path))
        self.enterContext(patch.object(operators, "_write_windows", {}))
        operators_config = {tenant: {"tenant_id": tenant, "key": f"dispatch-test-operator-{tenant}"}
                            for tenant in ("alpha", "beta")}
        dispatch_config = {"alpha": {"prepaid": {"discount_pct": 7, "payment_method": "Easypaisa"},
                                     "courier_choice": True, "address_quality": True}}
        self.enterContext(patch.dict(os.environ, {"COD_GUARD_OPERATORS": json.dumps(operators_config),
                                                 "COD_GUARD_DISPATCH_EXPERIMENTS": json.dumps(dispatch_config),
                                                 "COD_GUARD_WHATSAPP": "{}", "COD_GUARD_EXHIBITION": "0"}))
        self.clients = {tenant: self.enterContext(TestClient(main.app, headers={
            "Authorization": f"Bearer {operator['key']}"})) for tenant, operator in operators_config.items()}
        self.alpha, self.beta = self.clients["alpha"], self.clients["beta"]
        order_csv = ("order_id,customer_name,product,phone,city,address\n"
                     'ORD-1,Example,Scarf,03000000001,Lahore,"Near Sample Mosque, Lahore"\n')
        for client in self.clients.values():
            response = client.post("/orders/import", headers={"Idempotency-Key": "dispatch-fixture"},
                                   files={"file": ("orders.csv", order_csv, "text/csv")})
            self.assertEqual(response.json()["imported"], 1)

    def test_address_clarification_is_distinct_from_risk_and_drafted_once(self):
        path = "/orders/ORD-1"
        before = self.alpha.get(path).json()
        self.assertEqual(before["address_quality"]["status"], "flagged")
        self.assertEqual(before["decision"], "VERIFY_FIRST")
        first = self.alpha.post(path + "/verification/preview").json()
        second = self.alpha.post("/integrations/whatsapp" + path + "/send").json()
        self.assertFalse(first["sent"])
        self.assertFalse(second["sent"])
        self.assertTrue(first["address_clarification"]["created"])
        self.assertFalse(second["shadow"]["address_clarification"]["created"])
        self.assertEqual(second["preview"].count(first["address_clarification"]["text"]), 1)
        self.assertNotIn("Near Sample Mosque", json.dumps(before))
        after = self.alpha.get(path).json()
        for key in ("decision_revision", "decision", "zone", "rule_score", "needs_review"):
            self.assertEqual(after[key], before[key])
        with connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM address_clarifications").fetchone()[0], 1)

    def test_prepaid_offer_tracks_a_monotone_operator_reported_funnel(self):
        path = "/orders/ORD-1"
        listing = self.alpha.get("/orders").json()[0]
        self.assertIn("Easypaisa for 7% off", listing["prepaid_offer"]["text"])
        self.assertIsNone(listing["prepaid_outcome"])
        endpoint = path + "/prepaid/outcome"
        self.assertEqual(self.alpha.post(endpoint, json={"stage": "paid"}).status_code, 409)
        for stage in ("sent", "accepted", "paid"):
            saved = self.alpha.post(endpoint, json={"stage": stage})
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertIsNotNone(saved.json()[f"{stage}_at"])
            self.assertEqual(self.alpha.post(endpoint, json={"stage": stage}).json(), saved.json())
        self.assertEqual(self.alpha.get(path).json()["decision"], "VERIFY_FIRST")
        self.assertEqual(self.beta.post(endpoint, json={"stage": "sent"}).status_code, 409)
        self.assertNotIn("prepaid_outcome", self.beta.get(path).json())
        with patch.dict(os.environ, COD_GUARD_EXHIBITION="1"):
            self.assertNotIn("prepaid_offer", self.alpha.get("/orders").json()[0])
            self.assertEqual(self.alpha.post(path + "/verification/preview").status_code, 409)

    def test_courier_uses_tenant_city_history_and_excludes_tiny_cohorts(self):
        history = (("leopards", "Lahore", 8, 1), ("tcs", "لاہور", 8, 4), ("postex", "Lahore", 1, 0))
        with write(self.path) as db:
            for courier, city, count, returned in history:
                for i in range(count):
                    order = {"order_id": f"{courier}-{i}", "city": city, "customer_name": "Example",
                             "product": "Scarf", "phone": "", "data_source": "SHADOW"}
                    insert_order(db, "alpha", order)
                    db.execute("INSERT INTO courier_outcome_evidence VALUES (?,?,?,?,?,?,?,?)",
                               ("alpha", order["order_id"], courier, f"TEST-{i}",
                                "returned" if i < returned else "delivered", "fixture", now(), None))
        self.alpha.post("/orders/ORD-1/verify", json={"text": "Yes"})
        detail = self.alpha.get("/orders/ORD-1").json()
        self.assertEqual(detail["decision"], "SHIP")
        recommendation = detail["courier_recommendation"]
        self.assertEqual(recommendation["courier"], "leopards")
        evidence = recommendation["evidence"]
        self.assertEqual([(row["courier"], row["n"], row["returned"]) for row in evidence],
                         [("leopards", 8, 1), ("tcs", 8, 4)])
        self.assertGreater(evidence[0]["return_rate"], evidence[0]["raw_return_rate"])
        self.assertNotIn("courier_recommendation", self.beta.get("/orders/ORD-1").json())
        with connect(self.path) as db:
            self.assertEqual(dispatch_advice.courier_history(db, "beta"), [])

    def test_address_rules_distinguish_missing_data_and_city_details(self):
        self.assertIsNone(classify_address(None, "Multan"))
        self.assertEqual(classify_address("House 30, Lahore Road, Cantt, Multan", "Multan"), [])
        self.assertEqual(classify_address("مکان ۱۲، گلی ۳، گلبرگ، لاہور", "Lahore"), [])
        self.assertEqual(classify_address("Street 22, Model Town, Lahroe", "Lahore"), ["city_misspelling"])
        self.assertEqual(classify_address("House 13, Street 2, Lahore", "Karachi"), ["city_mismatch"])


if __name__ == "__main__":
    unittest.main()
