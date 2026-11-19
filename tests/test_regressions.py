"""Regression tests for failures found during the exhibition-readiness audit."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
import service
from verification import parse_reply


def clean_order(**overrides):
    return {"order_id": "TEST-1", "customer_name": "Synthetic Customer",
            "product": "Demo item", "phone": "03001234567", "city": "Lahore",
            "phone_valid": 1, "phone_fraud_history": 0, "phone_velocity_24h": 0,
            "address_words": 12, "address_has_landmark": 1, "amount_pkr": 3500,
            "items_count": 1, "order_hour": 14, "is_repeat_customer": 0,
            "customer_past_delivered": 0, "customer_past_refusals": 0,
            "label_failed": 1, **overrides}


class ServiceRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.order = clean_order()
        self.state_patch = patch.object(service, "STATE_PATH", Path(self.temp.name) / "state.json")
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        for target, value in [("load_orders", pd.DataFrame([self.order])), ("_ml_probability", None)]:
            active = patch.object(service, target, return_value=value)
            active.start()
            self.addCleanup(active.stop)

    def test_observed_outcome_replaces_synthetic_label_in_live_metrics(self):
        service.verify_reply(self.order, "Yes confirm")
        service.mark_outcome("TEST-1", "delivered")
        metrics = service.live_metrics()
        self.assertEqual((metrics["tn"], metrics["fn"]), (1, 0))

    def test_marking_an_unverified_order_records_its_dispatch_decision(self):
        service.mark_outcome("TEST-1", "refused")
        metrics = service.live_metrics()
        self.assertEqual((metrics["marked"], metrics["fn"]), (1, 1))

    def test_invalid_outcomes_and_unknown_orders_are_rejected(self):
        with self.assertRaises(ValueError):
            service.mark_outcome("TEST-1", "anything")
        with self.assertRaises(KeyError):
            service.mark_outcome("MISSING", "delivered")

    def test_ml_cannot_hold_an_order_on_one_signal(self):
        with patch.object(service, "_ml_probability", return_value=0.99):
            self.assertEqual(service.assess_order(clean_order(phone_fraud_history=1))["zone"], "GREEN")

    def test_later_denial_cannot_rewrite_a_recorded_dispatch_decision(self):
        service.mark_outcome("TEST-1", "delivered")
        service.verify_reply(self.order, "No, cancel")
        self.assertEqual(service.live_metrics()["tn"], 1)

    def test_unclear_reply_cannot_erase_an_explicit_denial(self):
        service.verify_reply(self.order, "No, cancel")
        self.assertEqual(service.verify_reply(self.order, "Kal bataunga")["decision"], "HOLD_CANCEL")

    def test_ambiguous_scope_routes_to_operator_without_flipping_prior_decision(self):
        service.verify_reply(self.order, "Yes confirm")
        partial = service.verify_reply(self.order, "Please cancel the extra item only")
        self.assertEqual((partial["intent"], partial["decision"], partial["needs_review"]),
                         ("UNCLEAR", "SHIP", True))
        self.assertTrue(service.assess_order(self.order)["needs_review"])
        service.verify_reply(self.order, "No, cancel")
        self.assertFalse(service.assess_order(self.order)["needs_review"])
        negated = service.verify_reply(self.order, "I did not confirm this order")
        self.assertEqual((negated["intent"], negated["decision"], negated["needs_review"]),
                         ("UNCLEAR", "HOLD_CANCEL", True))

    def test_concurrent_state_updates_do_not_lose_messages(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: service.verify_reply(self.order, "Yes"), range(8)))
        self.assertEqual(len(service.conversation("TEST-1")), 8)


if __name__ == "__main__":
    unittest.main()
