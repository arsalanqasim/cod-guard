"""Regression tests for failures found during the exhibition-readiness audit."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
from verification import parse_reply


class ReplyRegressionTests(unittest.TestCase):
    def test_negated_dispatch_and_polite_denials(self):
        for reply in ["Ji nahi", "جی نہیں", "No, don't send it",
                      "Please do not confirm", "I did not place this order",
                      "مت بھیجیں", "یہ آرڈر میرا نہیں ہے"]:
            with self.subTest(reply=reply):
                self.assertEqual(parse_reply(reply), "DENY")

    def test_negated_cancellation_is_not_a_denial(self):
        self.assertEqual(parse_reply("Don't cancel, please send my order"), "CONFIRM")
        self.assertEqual(parse_reply("No problem, yes confirm"), "CONFIRM")

    def test_politeness_substrings_and_future_promises_are_not_consent(self):
        for reply in ["مجید صاحب سے بات کریں", "ٹھیکیدار سے بات کریں",
                      "deliverance", "جی، کل بتاؤں گا", "I will confirm tomorrow",
                      "Can you confirm the price?", "", None]:
            with self.subTest(reply=reply):
                self.assertEqual(parse_reply(reply), "UNCLEAR")


if __name__ == "__main__":
    unittest.main()
