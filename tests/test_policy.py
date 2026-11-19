import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
from risk_engine import DEFAULTS, assess


class PolicyTests(unittest.TestCase):
    def test_every_single_signal_remains_dispatchable_even_with_high_ml(self):
        signals = [{"phone_fraud_history": 1}, {"phone_velocity_24h": 8},
                   {"phone_valid": 0}, {"customer_past_refusals": 10},
                   {"address_words": 2, "address_has_landmark": 0},
                   {"amount_pkr": 60000}, {"order_hour": 1}]
        for signal in signals:
            with self.subTest(signal=signal):
                self.assertEqual(assess({**DEFAULTS, **signal}, 0.99)["zone"], "GREEN")

    def test_two_signals_can_be_held_and_threshold_controls_ml(self):
        order = {**DEFAULTS, "amount_pkr": 21000, "order_hour": 1}
        self.assertEqual(assess(order, 0.65, 0.60)["zone"], "AMBER")
        self.assertEqual(assess(order, 0.65, 0.70)["zone"], "GREEN")

    def test_invalid_numeric_features_are_not_silently_scored(self):
        self.assertEqual(assess({"phone_valid": "0"})["signal_count"], 1)
        for order in [{"address_words": None}, {"amount_pkr": float("nan")},
                      {"order_hour": 24}, {"customer_past_refusals": -1}]:
            with self.subTest(order=order), self.assertRaises(ValueError):
                assess(order)

    def test_empty_order_requires_verification(self):
        result = assess({})
        self.assertEqual(result["zone"], "AMBER")
        self.assertTrue(any("Missing risk features" in reason for reason in result["reasons"]))


if __name__ == "__main__":
    unittest.main()
