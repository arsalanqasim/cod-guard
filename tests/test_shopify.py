import base64
import hmac
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
import service


STORE = "fixture-one.myshopify.com"
SECRET = "example-shopify-test-secret-only"
ORDER = {"id": 11, "payment_gateway_names": ["Cash on Delivery (COD)"], "currency": "PKR",
         "total_price": "1200.25", "financial_status": "pending", "cancelled_at": None, "test": False,
         "customer": {"email": "not-persisted@example.invalid"},
         "shipping_address": {"name": "Fixture", "city": "Lahore", "phone": "+920000000000",
                              "address1": "Unstored fixture address"}, "line_items": [{"title": "Pen", "quantity": 2}]}


class ShopifyTests(unittest.TestCase):
    def setUp(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "state.json"
        self.enterContext(patch.object(service, "STATE_PATH", path))
        self.config = {STORE: {"tenant_id": "alpha", "secret": SECRET, "cod_gateway": "Cash on Delivery (COD)"}}
        operators = {name: {"tenant_id": name, "key": f"shopify-fixture-operator-key-{name}"}
                     for name in ("alpha", "beta")}
        self.enterContext(patch.dict(os.environ, COD_GUARD_SHOPIFY=json.dumps(self.config),
                                     COD_GUARD_OPERATORS=json.dumps(operators)))
        self.client = self.enterContext(TestClient(main.app))

    def submit(self, payload, *, domain=STORE, secret=SECRET):
        body = json.dumps(payload).encode()
        signature = base64.b64encode(hmac.digest(secret.encode(), body, "sha256")).decode()
        return self.client.post(f"/integrations/shopify/webhooks/{STORE}", content=body, headers={
            "X-Shopify-Hmac-Sha256": signature, "X-Shopify-Shop-Domain": domain, "X-Shopify-Topic": "orders/create"})

    def test_signature_idempotence_and_protected_fields_default_off(self):
        self.assertEqual(self.submit(ORDER, secret="wrong").status_code, 401)
        self.assertEqual(self.submit(ORDER, domain="other.myshopify.com").status_code, 401)
        self.assertEqual(self.submit(ORDER).json()["queued"], 1)
        self.assertEqual(self.submit(ORDER).json()["queued"], 0)
        row = service.load_orders("alpha").iloc[0].to_dict()
        self.assertEqual((row["phone"], row["customer_name"], row["city"]), ("", "Name unavailable", ""))
        self.assertTrue(service.load_orders("beta").empty)
        for name in ("alpha", "beta"):
            result = self.client.get("/integrations/shopify/status", headers={
                "Authorization": f"Bearer shopify-fixture-operator-key-{name}"}).json()
            self.assertEqual(STORE in result, name == "alpha")

    def test_cod_filter_and_enabled_minimal_fields(self):
        self.config[STORE]["allow_protected_fields"] = True
        os.environ["COD_GUARD_SHOPIFY"] = json.dumps(self.config)
        for other in ({"test": True}, {"currency": "USD"}, {"financial_status": "paid"},
                      {"payment_gateway_names": ["Cash on Delivery (COD)", "card"]}):
            self.assertEqual(self.submit({**ORDER, **other}).json()["queued"], 0)
        self.assertEqual(self.submit(ORDER).json()["queued"], 1)
        self.assertEqual(self.submit({**ORDER, "id": 12, "shipping_address": None}).json()["queued"], 1)
        rows = service.load_orders("alpha").to_dict("records")
        row = next(item for item in rows if item["phone"])
        self.assertEqual((row["address_words"], row["customer_name"], row["amount_pkr"]), (3, "Fixture", 1200.25))
        self.assertNotIn("Unstored fixture address", str(rows))
