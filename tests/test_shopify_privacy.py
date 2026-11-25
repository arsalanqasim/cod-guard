"""Compliance payload contract checks that run without a provider or database."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
import merchant_shopify_privacy as privacy


class ShopifyPrivacyInputTests(unittest.TestCase):
    def test_signed_body_shapes_are_distinct_between_customer_and_shop_redaction(self):
        shop = {"shop_id": 10, "shop_domain": "fixture.myshopify.com"}
        customer = {**shop, "customer": {"id": 11}, "orders_to_redact": [1002, 1001, 1002]}
        self.assertEqual(privacy._requested_orders(privacy.SHOP_REDACT, shop), [])
        self.assertEqual(privacy._requested_orders(privacy.CUSTOMER_REDACT, customer), ["1001", "1002"])
        with self.assertRaises(ValueError):
            privacy._requested_orders(privacy.SHOP_REDACT, customer)
        with self.assertRaises(ValueError):
            privacy._requested_orders(privacy.CUSTOMER_REDACT, {**customer, "orders_to_redact": [True]})
        with self.assertRaises(ValueError):
            privacy._requested_orders(privacy.DATA_REQUEST, {**shop, "customer": {}, "orders_requested": [1001]})

    def test_shop_redaction_preserves_an_active_reinstallation(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = {"id": "fixture.myshopify.com"}
        with patch.object(privacy, "_order_links") as linked:
            self.assertFalse(privacy._erase_shop(db, "fixture", "fixture.myshopify.com"))
        linked.assert_not_called()
        self.assertEqual(db.execute.call_count, 1)
