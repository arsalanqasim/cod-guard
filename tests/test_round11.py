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
import operators
import service
import woocommerce
from order_intake import import_orders
from records import connect, write
from risk_engine import assess


STORE = "r11-store.myshopify.com"
SECRET = "round11-shopify-test-secret-key"


class Round11Tests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "state.json"
        self.enterContext(patch.object(service, "STATE_PATH", self.path))
        self.enterContext(patch.object(operators, "_write_windows", {}))
        self.shop_config = {
            STORE: {
                "tenant_id": "alpha",
                "secret": SECRET,
                "cod_gateway": "Cash on Delivery (COD)",
                "allow_protected_fields": True,
            }
        }
        self.op_config = {
            "ops1": {"tenant_id": "alpha", "key": "round11-initial-operator-key-0001"}
        }
        self.enterContext(patch.dict(
            os.environ,
            COD_GUARD_SHOPIFY=json.dumps(self.shop_config),
            COD_GUARD_OPERATORS=json.dumps(self.op_config),
        ))
        self.client = self.enterContext(TestClient(main.app))

    def test_ws2_wal_mode_and_concurrent_read(self):
        with connect(self.path) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            self.assertGreaterEqual(db.execute("PRAGMA busy_timeout").fetchone()[0], 15000)
        with write(self.path) as writer:
            writer.execute(
                "INSERT INTO settings (key) VALUES (?)",
                ("wal-concurrency-check",),
            )
            with connect(self.path) as reader:
                # Reader must not block or raise database is locked while writer holds write lock.
                self.assertIsNotNone(reader.execute("SELECT COUNT(*) FROM settings").fetchone())
        with connect(self.path) as reader:
            row = reader.execute(
                "SELECT 1 FROM settings WHERE key=?",
                ("wal-concurrency-check",),
            ).fetchone()
            self.assertIsNotNone(row)

    def test_ws3_operator_key_rotation_without_recreating_app(self):
        old_key = "round11-initial-operator-key-0001"
        new_key = "round11-rotated-operator-key-0002"
        self.assertEqual(
            self.client.get("/orders", headers={"Authorization": f"Bearer {old_key}"}).status_code,
            200,
        )
        self.assertEqual(
            self.client.get("/orders", headers={"Authorization": f"Bearer {new_key}"}).status_code,
            401,
        )
        # Rotate key in environment without recreating main.app or TestClient.
        os.environ["COD_GUARD_OPERATORS"] = json.dumps(
            {"ops1": {"tenant_id": "alpha", "key": new_key}}
        )
        self.assertEqual(
            self.client.get("/orders", headers={"Authorization": f"Bearer {old_key}"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.get("/orders", headers={"Authorization": f"Bearer {new_key}"}).status_code,
            200,
        )

    def test_ws5_csv_intake_captures_traffic_source_without_changing_scoring(self):
        csv_body = (
            "order_id,customer_name,product,phone,city,amount_pkr,utm_source,utm_medium,utm_campaign,referring_site\n"
            "ORD-CSV-1,Ayesha,Kurta,+923001234567,Lahore,3500,instagram,paid_social,eid26,https://l.instagram.com/\n"
            "ORD-CSV-2,Bilal,Shoes,+923001234568,Lahore,3500,,,,\n"
        ).encode("utf-8")
        receipt = import_orders(self.path, "alpha", "ops1", "r11-csv-1", csv_body)
        self.assertEqual(receipt["imported"], 2)
        self.assertEqual(receipt["errors"], [])

        order_with = service.get_order("ORD-CSV-1", tenant_id="alpha")
        order_without = service.get_order("ORD-CSV-2", tenant_id="alpha")
        self.assertEqual(order_with["utm_source"], "instagram")
        self.assertEqual(order_with["utm_medium"], "paid_social")
        self.assertEqual(order_with["utm_campaign"], "eid26")
        self.assertEqual(order_with["referring_site"], "https://l.instagram.com/")
        self.assertIsNone(order_without["utm_source"])
        self.assertIsNone(order_without["referring_site"])

        # Scoring must be unaffected by traffic-source fields in Round 11.
        self.assertEqual(assess({k: v for k, v in order_with.items() if v is not None}), assess({k: v for k, v in order_without.items() if v is not None}))

    def test_ws5_shopify_webhook_captures_landing_and_referrer(self):
        payload = {
            "id": 9011,
            "payment_gateway_names": ["Cash on Delivery (COD)"],
            "currency": "PKR",
            "total_price": "4200.00",
            "financial_status": "pending",
            "cancelled_at": None,
            "test": False,
            "landing_site": "/products/shawl?utm_source=tiktok&utm_medium=cpc&utm_campaign=winter26",
            "referring_site": "https://www.tiktok.com/",
            "shipping_address": {
                "name": "Hina",
                "city": "Karachi",
                "phone": "+923009876543",
                "address1": "House 12 Block 4 Clifton",
            },
            "line_items": [{"title": "Shawl", "quantity": 1}],
        }
        body = json.dumps(payload).encode()
        signature = base64.b64encode(hmac.digest(SECRET.encode(), body, "sha256")).decode()
        resp = self.client.post(
            f"/integrations/shopify/webhooks/{STORE}",
            content=body,
            headers={
                "X-Shopify-Hmac-Sha256": signature,
                "X-Shopify-Shop-Domain": STORE,
                "X-Shopify-Topic": "orders/create",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["queued"], 1)

        headers = {"Authorization": "Bearer round11-initial-operator-key-0001"}
        order_id = self.client.get("/orders", headers=headers).json()[0]["order_id"]
        detail = self.client.get(f"/orders/{order_id}", headers=headers).json()
        self.assertEqual(detail["utm_source"], "tiktok")
        self.assertEqual(detail["utm_medium"], "cpc")
        self.assertEqual(detail["utm_campaign"], "winter26")
        self.assertEqual(detail["referring_site"], "https://www.tiktok.com/")

    def test_ws5_woocommerce_meta_attribution_parsed(self):
        payload = {
            "id": 4401,
            "status": "processing",
            "payment_method": "cod",
            "currency": "PKR",
            "total": "2500",
            "billing": {"first_name": "Omar", "last_name": "Khan", "phone": "+923001112233", "city": "Islamabad"},
            "shipping": {"address_1": "Street 5 Sector F-7", "city": "Islamabad"},
            "line_items": [{"name": "Watch", "quantity": 1}],
            "meta_data": [
                {"key": "_wc_order_attribution_utm_source", "value": "google"},
                {"key": "_wc_order_attribution_utm_medium", "value": "organic"},
                {"key": "_wc_order_attribution_utm_campaign", "value": "brand"},
                {"key": "_wc_order_attribution_session_entry", "value": "https://shop.example.pk/?utm_source=google"},
            ],
        }
        snap = woocommerce.parse_order(payload)
        self.assertEqual(snap.details["utm_source"], "google")
        self.assertEqual(snap.details["utm_medium"], "organic")
        self.assertEqual(snap.details["utm_campaign"], "brand")
        self.assertEqual(snap.details["referring_site"], "https://shop.example.pk/?utm_source=google")

    def test_ws5_social_dm_confirm_captures_traffic_source(self):
        headers = {"Authorization": "Bearer round11-initial-operator-key-0001"}
        resp = self.client.post(
            "/integrations/social/dm/confirm",
            headers=headers,
            json={
                "channel": "instagram",
                "confirmation_id": "a" * 32,
                "confirmed": True,
                "name": "Zara",
                "phone": "03001234567",
                "address": "House 8 Street 3 Gulberg Lahore",
                "city": "Lahore",
                "items": "Bag",
                "amount_pkr": "3200",
                "utm_source": "instagram",
                "utm_medium": "dm_story",
                "utm_campaign": "flash_sale",
                "referring_site": "https://instagram.com/stories/example",
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["queued"], 1)
        order_id = self.client.get("/orders", headers=headers).json()[0]["order_id"]
        detail = self.client.get(f"/orders/{order_id}", headers=headers).json()
        self.assertEqual(detail["utm_source"], "instagram")
        self.assertEqual(detail["utm_medium"], "dm_story")
        self.assertEqual(detail["utm_campaign"], "flash_sale")
        self.assertEqual(detail["referring_site"], "https://instagram.com/stories/example")


if __name__ == "__main__":
    unittest.main()
