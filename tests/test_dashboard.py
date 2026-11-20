import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
import service
from reply_corrections import export_page


class DashboardTests(unittest.TestCase):
    def test_operator_can_correct_the_latest_unclear_reply(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(service, "STATE_PATH", Path(directory) / "state.json"):
            app = AppTest.from_file(str(ROOT / "frontend/dashboard.py"), default_timeout=30).run()
            order_id = app.selectbox(key="verify_order").value
            app.chat_input(key=f"reply_{order_id}").set_value("I need to back out of this purchase").run()
            revision = service.verification_revision("demo", order_id)
            app.selectbox(key=f"reply_label_{order_id}_{revision}").set_value("DENY")
            next(button for button in app.button if button.label == "Save correction").click().run()
            self.assertFalse(app.exception, str(app.exception))
            self.assertEqual(service.assess_order(service.get_order(order_id))["decision"], "HOLD_CANCEL")
            self.assertEqual(export_page(service.STATE_PATH, "demo", "test")[0]["label"], "DENY")

    def test_moves_between_pages_without_scoring_the_full_queue(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(service, "STATE_PATH", Path(directory) / "state.json"), \
             patch.object(service, "_batch_probabilities", wraps=service._batch_probabilities) as batch:
            app = AppTest.from_file(str(ROOT / "frontend/dashboard.py"), default_timeout=30).run()
            self.assertFalse(app.exception, str(app.exception))
            first = app.selectbox(key="verify_order").options
            self.assertEqual(len(first), 50)
            app.number_input(key="dispatch_page").set_value(2).run()
            self.assertFalse(app.exception, str(app.exception))
            second = app.selectbox(key="verify_order").options
            self.assertEqual(len(second), 30)
            self.assertFalse(set(first) & set(second))
            self.assertEqual([len(call.args[1]) for call in batch.call_args_list], [50, 30])

    def test_three_tabs_overrides_and_visible_pending_outcome(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(service, "STATE_PATH", Path(directory) / "state.json"):
            app = AppTest.from_file(str(ROOT / "frontend/dashboard.py"), default_timeout=30).run()
            self.assertFalse(app.exception, str(app.exception))
            self.assertEqual(len(app.tabs), 3)
            orders = service.load_orders().to_dict("records")
            red = next(row for row in orders if service.assess_order(row)["zone"] == "RED")
            green = next(row for row in orders if service.assess_order(row)["zone"] == "GREEN")
            app.selectbox(key="verify_order").set_value(red["order_id"]).run()
            app.chat_input(key=f"reply_{red['order_id']}").set_value("Ji theek hai, bhej dein").run()
            self.assertEqual(service.assess_order(red)["decision"], "SHIP")
            app.chat_input(key=f"reply_{red['order_id']}").set_value("Please cancel the blue shirt").run()
            self.assertEqual(service.assess_order(red)["decision"], "SHIP")
            self.assertTrue(any("Clarify the last reply" in item.value for item in app.warning))
            app.selectbox(key="verify_order").set_value(green["order_id"]).run()
            app.chat_input(key=f"reply_{green['order_id']}").set_value("جی نہیں").run()
            self.assertEqual(service.assess_order(green)["decision"], "HOLD_CANCEL")
            app.selectbox(key="outcome_order").set_value(green["order_id"]).run()
            app.radio(key="outcome_value").set_value("refused").run()
            app.button(key="save_outcome").click().run()
            self.assertFalse(app.exception, str(app.exception))
            self.assertEqual(service.live_metrics()["tp"], 1)
            self.assertEqual(service.learning_status()["pending"], 1)
            self.assertFalse(app.button(key="retrain").disabled)


if __name__ == "__main__":
    unittest.main()
