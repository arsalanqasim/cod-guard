import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
import service


class LearningTests(unittest.TestCase):
    def test_mark_retrain_and_restart_consumes_the_observed_label(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            model_path = directory / "model.pkl"
            shutil.copyfile(ROOT / "backend/app/model.pkl", model_path)
            with patch.object(service, "STATE_PATH", directory / "state.json"), \
                 patch.object(service, "MODEL_PATH", model_path):
                order = service.load_orders().iloc[0].to_dict()
                previous = service.model_status()
                outcome = "delivered" if int(order["label_failed"]) else "refused"
                service.mark_outcome(order["order_id"], outcome)
                self.assertEqual(service.learning_status()["pending"], 1)
                result = service.retrain_model()
                current = service.model_status()
                self.assertNotEqual(previous["model_id"], current["model_id"])
                self.assertEqual(current["version"], previous["version"] + 1)
                self.assertEqual(current["feedback"][order["order_id"]], outcome)
                self.assertEqual(result["training_rows"], 3553)
                self.assertEqual(service.learning_status()["pending"], 0)
                baseline = json.loads((ROOT / "data/evaluation.json").read_text(encoding="utf-8"))
                after = service.latest_evaluation()
                self.assertEqual(after["split"]["test_ids_sha256"], baseline["split"]["test_ids_sha256"])
                service._cached_bundle.cache_clear()  # simulate a new process
                self.assertEqual(service.learning_status()["trained_outcomes"], 1)
                with self.assertRaisesRegex(ValueError, "No new"):
                    service.retrain_model()


if __name__ == "__main__":
    unittest.main()
