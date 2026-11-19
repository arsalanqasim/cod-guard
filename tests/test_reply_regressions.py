"""Regression tests for failures found during the exhibition-readiness audit."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
from verification import parse_reply


class ReplyRegressionTests(unittest.TestCase):
    def test_negated_scoped_and_contradictory_replies_abstain(self):
        for reply in ["I did not confirm this order", "Please cancel the extra item only",
                      "I haven't confirmed this order", "I did not cancel my order",
                      "Don't cancel my order", "I did not say yes",
                      "Yes, confirm the blue shirt only", "Please cancel one item",
                      "Confirm the address, please", "Please cancel the extra item",
                      "Order nahi, sirf address confirm karna hai", "صرف ایک آئٹم کینسل کریں",
                      "Yes, confirm the order, but please cancel it", "Please confirm and cancel",
                      "Please do not cancel one item", "Yes, confirm if the size is large",
                      "Did you cancel my order?", "Please cancel the blue shirt",
                      "Yes, cancel my second product", "Confirm payment",
                      "Please stop calling me", "I did not ask you to confirm",
                      "I don't want to confirm", "I cannot confirm this order", "Not yes"]:
            with self.subTest(reply=reply):
                self.assertEqual(parse_reply(reply), "UNCLEAR")

    def test_negated_dispatch_and_polite_denials(self):
        for reply in ["Ji nahi", "جی نہیں", "No, don't send it",
                      "Please do not confirm", "I did not place this order",
                      "مت بھیجیں", "یہ آرڈر میرا نہیں ہے", "confirm nahi karna",
                      "Ji theek nhi hai", "bhejna nahi", "کنفرم نہیں کرنا"]:
            with self.subTest(reply=reply):
                self.assertEqual(parse_reply(reply), "DENY")

    def test_negated_cancellation_is_not_a_denial(self):
        self.assertEqual(parse_reply("Don't cancel, please send my order"), "CONFIRM")
        self.assertEqual(parse_reply("No problem, yes confirm"), "CONFIRM")
        self.assertEqual(parse_reply("Cancel mat karna, bhej dein"), "CONFIRM")
        self.assertEqual(parse_reply("کینسل مت کریں، بھیج دیں"), "CONFIRM")

    def test_politeness_substrings_and_future_promises_are_not_consent(self):
        for reply in ["مجید صاحب سے بات کریں", "ٹھیکیدار سے بات کریں",
                      "deliverance", "جی، کل بتاؤں گا", "I will confirm tomorrow",
                      "Can you confirm the price?", "", None]:
            with self.subTest(reply=reply):
                self.assertEqual(parse_reply(reply), "UNCLEAR")

    def test_general_negative_speech_is_not_order_cancellation(self):
        for reply in ["ان کے دور میں آلودگی مسئلہ نہیں تھی", "There is no weather update",
                      "Is this a fake order?"]:
            with self.subTest(reply=reply):
                self.assertEqual(parse_reply(reply), "UNCLEAR")
        self.assertEqual(parse_reply("کوئی مسئلہ نہیں، بھیج دیں"), "CONFIRM")
        self.assertEqual(parse_reply("No problems, send it"), "CONFIRM")


if __name__ == "__main__":
    unittest.main()
