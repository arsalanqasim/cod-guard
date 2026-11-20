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
import operators
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
        self.enterContext(patch.object(operators, "_write_windows", {}))
        settings = {name: {"tenant_id": name, "key": f"sample-operator-key-for-{name}"}
                    for name in ("alpha", "beta")}
        self.enterContext(patch.dict(os.environ, COD_GUARD_OPERATORS=json.dumps(settings),
                                     COD_GUARD_WOOCOMMERCE=json.dumps({"shop": STORE})))
        self.client = self.enterContext(TestClient(main.app))
        self.alpha = {"Authorization": f"Bearer {settings['alpha']['key']}"}
        self.beta = {"Authorization": f"Bearer {settings['beta']['key']}"}

    def webhook(self, data=ORDER, *, valid=True, topic="order.created"):
        body = json.dumps(data).encode()
        signature = base64.b64encode(hmac.digest(STORE["webhook_secret"].encode(), body, "sha256")).decode()
        return self.client.post(f"{PREFIX}/shop/webhook", content=body, headers={
            "X-WC-Webhook-Topic": topic, "X-WC-Webhook-Signature": signature if valid else "wrong",
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
    def test_webhook_refreshes_open_order_and_closes_it_on_source_cancellation(self, request):
        created = ORDER | {"date_modified_gmt": "2026-11-20T09:00:00"}
        self.assertEqual(self.webhook(created).json()["imported"], 1)
        amended = created | {"total": "2600.50", "date_modified_gmt": "2026-11-20T09:01:00"}
        self.assertEqual(self.webhook(amended, topic="order.updated").status_code, 200)
        order, = self.client.get("/orders", headers=self.alpha).json()
        self.assertEqual((order["queue_status"], order["amount_pkr"]), ("open", 2600.50))
        cancelled = amended | {"status": "cancelled", "date_modified_gmt": "2026-11-20T09:02:00"}
        for event in (cancelled, cancelled, created):
            self.assertEqual(self.webhook(event, topic="order.updated").status_code, 200)
        order, = self.client.get("/orders", headers=self.alpha).json()
        self.assertEqual((order["queue_status"], order["storefront_conflict"]), ("closed_cancelled", False))
        with service.connect(self.path) as db:
            events = db.execute("SELECT reference FROM audit_events WHERE action='storefront_order_reconciled'")
            self.assertEqual([row["reference"] for row in events], ["WOOCOMMERCE:open", "WOOCOMMERCE:closed_cancelled"])
        request.assert_not_called()

    @patch("woocommerce.WooCommerceClient.request")
    def test_poll_marks_paid_order_out_of_scope_and_preserves_decision_and_outcome(self, request):
        self.webhook()
        order, = self.client.get("/orders", headers=self.alpha).json()
        path = f"/orders/{order['order_id']}"
        self.assertEqual(self.client.post(f"{path}/verify", headers=self.alpha,
                                          json={"text": "Yes"}).json()["decision"], "SHIP")
        self.assertEqual(self.client.post(f"{path}/outcome", headers=self.alpha,
                                          json={"outcome": "delivered"}).status_code, 200)
        paid = ORDER | {"date_paid_gmt": "2026-11-20T09:02:00", "date_modified_gmt": "2026-11-20T09:02:00"}
        request.return_value = ([paid], 1)
        self.assertEqual(self.client.post(f"{PREFIX}/shop/poll", headers=self.alpha).status_code, 200)
        order = self.client.get(path, headers=self.alpha).json()
        self.assertEqual((order["queue_status"], order["decision"], order["outcome"],
                          order["storefront_conflict"], order["needs_review"], order["verified"]),
                         ("out_of_cod_scope", "SHIP", "delivered", True, True, False))
        self.assertIn("date_paid_gmt", request.call_args.kwargs["params"]["_fields"])

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
