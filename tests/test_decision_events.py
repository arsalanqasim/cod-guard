import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
import service
from storage import read_state, transaction


class DecisionEventsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.enterContext(patch.object(service, "STATE_PATH", Path(directory.name) / "state.json"))
        self.order = service.load_orders().iloc[0].to_dict()
        self.order_id = self.order["order_id"]

    def test_outcome_freezes_denial_committed_before_outcome_transaction(self):
        service.verify_reply(self.order, "Yes confirm")
        reaching_lock = Event()
        denial_committed = Event()

        @contextmanager
        def interleave(path, *args):
            # The old outcome path read SHIP before reaching this point.
            if not reaching_lock.is_set():
                reaching_lock.set()
                if not denial_committed.wait(10):
                    raise RuntimeError("Denial did not commit before outcome acquired its lock")
            with transaction(path, *args) as state:
                yield state

        with patch.object(service, "transaction", interleave), ThreadPoolExecutor() as executor:
            mark = executor.submit(service.mark_outcome, self.order_id, "refused")
            try:
                self.assertTrue(reaching_lock.wait(10))
                service.verify_reply(self.order, "No, cancel")
            finally:
                denial_committed.set()
            mark.result(timeout=10)
        self.assertEqual(service.live_metrics()["tp"], 1)
        self.assertEqual(service.live_metrics()["fn"], 0)

    def test_correction_appends_with_actor_and_original_decision_revision(self):
        service.verify_reply(self.order, "Yes", actor="operator-a")
        initial = service.mark_outcome(self.order_id, "delivered", actor="operator-b")
        service.verify_reply(self.order, "No, cancel", actor="operator-a")
        edited = service.mark_outcome(self.order_id, "refused", actor="operator-c")
        events = read_state(service.STATE_PATH)["events"][self.order_id]
        self.assertEqual([event["revision"] for event in events], [1, 2, 3, 4])
        self.assertEqual([event["actor"] for event in events],
                         ["operator-a", "operator-b", "operator-a", "operator-c"])
        self.assertTrue(all(event["at"] for event in events))
        self.assertEqual(events[1], initial)
        self.assertEqual(events[3], edited)
        self.assertEqual((initial["outcome"], edited["outcome"]), ("delivered", "refused"))
        self.assertEqual((initial["decision_revision"], edited["decision_revision"]), (1, 1))
        self.assertFalse(initial["correction"])
        self.assertTrue(edited["correction"])
        self.assertEqual(service.live_metrics()["fn"], 1)

    def test_legacy_outcome_without_snapshot_stays_unscored(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(service, "STATE_PATH", Path(directory) / "state.json"):
            service.STATE_PATH.write_text(json.dumps({"outcomes": {self.order_id: "delivered"}}), encoding="utf-8")
            service.verify_reply(self.order, "Yes")
            service.mark_outcome(self.order_id, "refused")
            metrics = service.live_metrics()
        self.assertEqual((metrics["marked"], metrics["unscored"]), (0, 1))

