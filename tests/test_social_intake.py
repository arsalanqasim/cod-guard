import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
import main
import service


PREFIX = "/integrations/social"
TRANSCRIPT = "Name: Fixture\nPhone: 03000000000\nAddress: House 1 Road 2\nCity: Lahore\nItems: Pen x 2\nTotal: PKR 1,200.50"


class SocialTests(unittest.TestCase):
    def setUp(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "state.json"
        self.enterContext(patch.object(service, "STATE_PATH", path))
        accounts = {name: {"tenant_id": name, "key": f"example-social-operator-key-{name}"}
                    for name in ("alpha", "beta", "demo")}
        self.enterContext(patch.dict(os.environ, COD_GUARD_OPERATORS=json.dumps(accounts)))
        self.client = self.enterContext(TestClient(main.app))
        self.headers = {"Authorization": "Bearer example-social-operator-key-alpha"}

    def test_preview_conflict_and_explicit_confirm(self):
        request = {"channel": "instagram", "transcript": TRANSCRIPT + "\nTotal: PKR 900"}
        result = self.client.post(f"{PREFIX}/dm/preview", json=request, headers=self.headers).json()
        self.assertEqual((result["saved"], result["draft"]["amount_pkr"]), (False, ""))
        self.assertTrue(service.load_orders("alpha").empty)
        body = {**result["draft"], "confirmation_id": "c" * 32,
                "channel": "instagram", "amount_pkr": "1200.50", "confirmed": False}
        self.assertEqual(self.client.post(f"{PREFIX}/dm/confirm", json=body, headers=self.headers).status_code, 422)
        body["confirmed"] = True
        for expected in (1, 0):
            self.assertEqual(self.client.post(f"{PREFIX}/dm/confirm", json=body, headers=self.headers).json()["queued"], expected)
        order = service.load_orders("alpha").iloc[0].to_dict()
        self.assertEqual((order["data_source"], order["address_words"], order["amount_pkr"]), ("DM_INSTAGRAM", 4, 1200.5))
        self.assertNotIn("House 1 Road 2", str(order))
        self.assertTrue(service.load_orders("beta").empty)

    def test_sheets_receipt_and_demo_rejection(self):
        fixture = b"order_id,customer_name,product,phone\nsh1,Fixture,Pen,03000000000\nsh2,Fixture,Pen,broken\n"
        url = f"{PREFIX}/sheets/import"
        files = {"file": ("export.csv", fixture)}
        headers = {**self.headers, "Idempotency-Key": "sheets-fixture"}
        self.assertEqual(self.client.post(url, files=files, headers={**headers, "Authorization":
                         "Bearer example-social-operator-key-demo"}).status_code, 403)
        response = self.client.post(url, files=files, headers=headers).json()
        self.assertEqual(response["imported"], 1)
        self.assertEqual(response["errors"][0]["row"], 3)
        self.assertEqual(self.client.post(url, files=files, headers=headers).json(), response)
        self.assertEqual(service.get_order("sh1", "alpha")["data_source"], "GOOGLE_SHEETS")

    def test_seller_screen_keeps_draft_unsaved_until_review(self):
        def route(url, **kwargs):
            return self.client.post(url.split(":8000", 1)[1], headers=kwargs["headers"], json=kwargs["json"])

        def press(app, label):
            return next(button for button in app.button if button.label == label).click().run()

        with patch.dict(os.environ, COD_GUARD_INTAKE_API="http://127.0.0.1:8000"), patch("httpx.post", side_effect=route):
            app = AppTest.from_file(str(ROOT / "frontend/social_intake.py")).run()
            app.text_input(key="operator_key").set_value("example-social-operator-key-alpha").run()
            app.text_area(key="dm_transcript").set_value(TRANSCRIPT)
            press(app, "Extract draft")
            self.assertFalse(app.exception, str(app.exception))
            press(app, "Confirm and save")
            self.assertTrue(service.load_orders("alpha").empty)
            app.text_input(key="draft_items").set_value("Corrected fixture")
            app.checkbox(key="dm_reviewed").set_value(True)
            press(app, "Confirm and save")
            self.assertFalse(app.exception, str(app.exception))
            self.assertEqual(service.load_orders("alpha").iloc[0]["product"], "Corrected fixture")
            self.assertEqual(app.text_area(key="dm_transcript").value, "")
