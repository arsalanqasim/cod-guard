import base64
import hmac
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
import main
import service
import woocommerce as woo
from connector_orders import connection_state


ORDER = {"id": 42, "status": "processing", "currency": "PKR", "payment_method": "cod", "total": "2500.50",
         "billing": {"first_name": "Demo", "phone": "03001234567"}, "shipping": {"city": "Lahore"},
         "line_items": [{"name": "Shirt", "quantity": 2}]}
STORE = {"tenant_id": "alpha", "url": "https://store.example", "key": "test-key", "secret": "test-secret",
         "webhook_secret": "synthetic-unique-webhook-secret"}
PREFIX = "/integrations/woocommerce"


class WooCommerceTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(folder) / "state.json"
        self.enterContext(patch.object(service, "STATE_PATH", self.path))
        operators = {name: {"tenant_id": name, "key": f"sample-operator-key-for-{name}"}
                     for name in ("alpha", "beta")}
        self.enterContext(patch.dict(os.environ, COD_GUARD_OPERATORS=json.dumps(operators),
                                     COD_GUARD_WOOCOMMERCE=json.dumps({"shop": STORE})))
        self.client = self.enterContext(TestClient(main.app))
        self.alpha = {"Authorization": f"Bearer {operators['alpha']['key']}"}
        self.beta = {"Authorization": f"Bearer {operators['beta']['key']}"}

    def webhook(self, data=ORDER, *, valid=True):
        body = json.dumps(data).encode()
        signature = base64.b64encode(hmac.digest(STORE["webhook_secret"].encode(), body, "sha256")).decode()
        return self.client.post(f"{PREFIX}/shop/webhook", content=body, headers={
            "X-WC-Webhook-Topic": "order.created", "X-WC-Webhook-Signature": signature if valid else "wrong",
        })

    def test_signed_intake_and_tenant_isolation(self):
        ping = self.client.post(f"{PREFIX}/shop/webhook", content=b"webhook_id=4")
        self.assertEqual(ping.status_code, 200)
        self.assertEqual(self.webhook(valid=False).status_code, 401)
        for skipped in ({**ORDER, "currency": "USD"}, {**ORDER, "payment_method": "card"},
                        {**ORDER, "status": "cancelled"}):
            self.assertEqual(self.webhook(skipped).json()["imported"], 0)
        self.assertEqual(self.webhook().json()["imported"], 1)
        self.assertEqual(self.webhook().json()["imported"], 0)
        order, = self.client.get("/orders", headers=self.alpha).json()
        self.assertEqual((order["data_source"], order["amount_pkr"]), ("WOOCOMMERCE", 2500.50))
        self.assertEqual(self.client.get("/orders", headers=self.beta).json(), [])
        self.assertEqual(self.client.get(f"{PREFIX}/connections", headers=self.beta).json(), [])
        health, = self.client.get(f"{PREFIX}/connections", headers=self.alpha).json()
        self.assertTrue(health["last_webhook"])
        self.assertNotIn("key", health)
        self.assertEqual(self.client.post(f"{PREFIX}/shop/poll", headers=self.beta).status_code, 404)

    @patch("woocommerce.WooCommerceClient.request")
    def test_poll_dedup_and_cursor_does_not_advance_on_failure(self, request):
        self.webhook()
        request.side_effect = [([ORDER], 2), woo.WooCommerceError("Simulated downstream error")]
        failed = self.client.post(f"{PREFIX}/shop/poll", headers=self.alpha)
        self.assertEqual(failed.status_code, 502)
        identity = ("alpha", "WOOCOMMERCE", "shop")
        self.assertIsNone(connection_state(self.path, identity)["cursor"])
        request.side_effect = [([ORDER], 2), ([{**ORDER, "id": 43}], 2)]
        repaired = self.client.post(f"{PREFIX}/shop/poll", headers=self.alpha)
        self.assertEqual(repaired.json()["imported"], 1)
        self.assertTrue(repaired.json()["cursor"])
        self.assertIsNone(connection_state(self.path, identity)["last_error"])

    @patch("woocommerce.WooCommerceClient.request")
    def test_outcome_write_requires_scope_and_does_not_repeat_private_note(self, request):
        self.webhook()
        order, = self.client.get("/orders", headers=self.alpha).json()
        order_id = order["order_id"]
        target = f"{PREFIX}/shop/orders/{order_id}/write-outcome"
        self.assertEqual(self.client.post(target, headers=self.beta).status_code, 404)
        self.assertEqual(self.client.post(target, headers=self.alpha).status_code, 409)
        response = self.client.post(f"/orders/{order_id}/outcome", headers=self.alpha, json={"outcome": "delivered"})
        self.assertEqual(response.status_code, 200)
        note = f"COD-Guard outcome: delivered (revision {response.json()['event']['revision']})."
        request.side_effect = [([], None), ({"id": 1}, None), ([{"note": note}], None)]
        for _ in range(2):
            self.assertEqual(self.client.post(target, headers=self.alpha).json()["mode"], "private_note")
        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args_list[1].kwargs["payload"], {"note": note, "customer_note": False})

    @patch("woocommerce.build_opener")
    def test_auth_modes_and_tls_requirement(self, build_opener):
        opener = build_opener.return_value
        for mode in ("basic", "query"):
            store, = woo._stores(json.dumps({"shop": {**STORE, "auth_mode": mode}})).values()
            response = io.BytesIO(b"[]")
            response.headers = {"X-WP-TotalPages": "0"}
            opener.open.return_value = response
            self.assertEqual(woo.WooCommerceClient(store).request("orders"), ([], 0))
            outgoing = opener.open.call_args.args[0]
            url = urlsplit(outgoing.full_url)
            self.assertEqual((url.scheme, url.path), ("https", "/wp-json/wc/v3/orders"))
            if mode == "basic":
                self.assertEqual(outgoing.get_header("Authorization"), "Basic dGVzdC1rZXk6dGVzdC1zZWNyZXQ=")
                self.assertFalse(url.query)
            else:
                self.assertIsNone(outgoing.get_header("Authorization"))
                self.assertEqual(parse_qs(url.query), {"consumer_key": ["test-key"], "consumer_secret": ["test-secret"]})
        with self.assertRaises(ValueError):
            woo._stores(json.dumps({"shop": {**STORE, "url": "http://store.example"}}))
