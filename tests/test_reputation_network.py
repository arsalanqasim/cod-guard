import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
import main
import reputation_network as network
import service
from courier_outcomes import store
from records import connect, insert_order, write


SELLERS = ("alpha", "beta", "gamma", "delta", "epsilon")
PHONE = "03000000000"


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "state.json"
        self.enterContext(patch.object(service, "STATE_PATH", self.path))
        operators = {name: {"tenant_id": name, "key": f"test-network-operator-key-{name}"} for name in (*SELLERS, "outsider")}
        self.enterContext(patch.dict(os.environ, COD_GUARD_NETWORK_KEY="x" * 43, COD_GUARD_NETWORK_TENANTS=",".join(SELLERS),
                                     COD_GUARD_OPERATORS=json.dumps(operators)))
        self.client = self.enterContext(TestClient(main.app))
        with write(self.path) as db:
            for seller in SELLERS:
                insert_order(db, seller, {"order_id": f"order-{seller}", "customer_name": "Fixture", "product": "Parcel",
                                          "city": "Lahore", "phone": PHONE if seller == "alpha" else "+92 300 0000000",
                                          "data_source": "SHADOW"})
            insert_order(db, "alpha", {"order_id": "daraz-order", "customer_name": "Fixture", "product": "Parcel",
                                       "city": "Lahore", "phone": PHONE, "data_source": "DARAZ"})

    def auth(self, seller):
        return {"Authorization": f"Bearer test-network-operator-key-{seller}"}

    def enroll(self, seller, enabled=True):
        return self.client.put("/network/enrollment", headers=self.auth(seller), json={"enabled": enabled})

    def consent(self, seller, enabled=True, order_id=None):
        return self.client.put(f"/network/orders/{order_id or f'order-{seller}'}/consent", headers=self.auth(seller),
                               json={"enabled": enabled, "evidence_reference": "fixture-consent"})

    def report(self, seller):
        return self.client.get(f"/network/orders/order-{seller}/counts", headers=self.auth(seller)).json()

    def label(self, seller, outcome="delivered"):
        return store(seller, "fixture", [(f"order-{seller}", "tcs", "CN-FIXTURE", outcome, None)], "operator-csv")

    def test_only_consent_and_threshold_unlock_advisory_counts(self):
        self.assertEqual(self.enroll("outsider").status_code, 409)
        self.assertEqual(self.consent("alpha").status_code, 409)
        for seller in SELLERS:
            self.assertEqual(self.enroll(seller).status_code, 200)
        self.assertEqual(self.consent("alpha", order_id="daraz-order").status_code, 409)
        self.label("epsilon", "refused")
        self.consent("epsilon")
        self.label("epsilon", "refused")
        self.assertEqual(self.client.get("/network/size").json()["contributing_sellers"], 0)
        order = service.get_order("order-alpha", "alpha")
        before = service.assess_order(order, tenant_id="alpha")
        self.consent("alpha")
        for seller in ("beta", "gamma"):
            self.consent(seller)
            self.label(seller)
        self.assertIsNone(self.report("alpha")["counts"])
        self.consent("delta")
        self.label("delta", "returned")
        self.assertEqual(self.report("alpha"), {"advisory_only": True, "counts": {"delivered": 2, "returned": 1, "refused": 0}})
        self.assertEqual(service.assess_order(order, tenant_id="alpha"), before)
        self.assertEqual(self.client.get("/network/orders/order-beta/counts", headers=self.auth("alpha")).status_code, 404)
        service.mark_outcome("order-beta", "returned", tenant_id="beta")
        self.assertIsNone(self.report("alpha")["counts"])

    def test_withdrawal_appeal_and_pseudonymous_storage(self):
        for seller in SELLERS[:4]:
            self.enroll(seller)
            self.consent(seller)
            self.label(seller)
        with connect(self.path) as db:
            keys = [row[0] for row in db.execute("SELECT DISTINCT phone_key FROM network_contributions")]
            self.assertEqual(len(keys), 1)
            self.assertRegex(keys[0], r"^[0-9a-f]{64}$")
        self.consent("beta", False)
        self.assertEqual(self.client.get("/network/size").json()["contributing_sellers"], 3)
        self.assertIsNone(self.report("alpha")["counts"])
        self.assertEqual(network.suppress_subject(self.path, PHONE, "appeal-fixture"), 3)
        self.assertEqual(self.client.get("/network/size").json()["contributing_sellers"], 0)
        self.assertEqual(self.consent("beta").status_code, 409)
        with patch.dict(os.environ, COD_GUARD_NETWORK_KEY="y" * 43):
            self.assertFalse(self.client.get("/network/size").json()["enabled"])
            self.assertEqual(self.enroll("beta").status_code, 409)

    def test_records_expire_and_seller_withdrawal_cascades(self):
        with patch.object(network, "time", return_value=1000):
            for seller in ("alpha", "beta"):
                self.enroll(seller)
                self.consent(seller)
                self.label(seller)
            self.enroll("beta", False)
            self.assertEqual(network.size(self.path)["contributing_sellers"], 1)
        with patch.object(network, "time", return_value=1000 + network.TTL):
            self.assertEqual(network.size(self.path)["contributing_sellers"], 0)
            self.assertEqual(network.purge_expired(self.path), 1)
        with connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM network_contributions").fetchone()[0], 0)
