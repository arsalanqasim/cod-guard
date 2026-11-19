import json
import os
import shutil
import sys
import tempfile
import unittest
from threading import Event
from time import monotonic, sleep
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
import service
import artifacts
import train_model
from records import connect


class LearningTests(unittest.TestCase):
    def test_mark_retrain_and_restart_consumes_the_observed_label(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            model_path = directory / "model.pkl"
            baseline_path = ROOT / "backend/app/model.pkl"
            baseline_version = artifacts.active_version(baseline_path)
            shutil.copyfile(baseline_version / "model.pkl" if baseline_version else baseline_path, model_path)
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
                with connect(service.STATE_PATH) as db:
                    self.assertEqual(db.execute("SELECT model_id FROM model_versions").fetchone()[0], current["model_id"])
                self.assertEqual(result["training_rows"], 3553)
                self.assertEqual(service.learning_status()["pending"], 0)
                baseline = json.loads((ROOT / "data/evaluation.json").read_text(encoding="utf-8"))
                after = service.latest_evaluation()
                self.assertEqual(after["split"]["test_ids_sha256"], baseline["split"]["test_ids_sha256"])
                service._cached_bundle.cache_clear()  # simulate a new process
                self.assertEqual(service.learning_status()["trained_outcomes"], 1)
                with self.assertRaisesRegex(ValueError, "No new"):
                    service.retrain_model()

    def test_every_publish_write_failure_keeps_old_pair_active_and_feedback_pending(self):
        current = service._bundle()
        candidate = {**current, "model_id": "candidate", "feedback": {}}
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "model.pkl"
            artifacts.publish(current, service.latest_evaluation(), "baseline", model, expected=None)
            initial = artifacts.active_version(model)
            with patch.object(service, "MODEL_PATH", model), \
                 patch.object(service, "STATE_PATH", Path(directory) / "state.json"):
                order = service.load_orders().iloc[0].to_dict()
                service.mark_outcome(order["order_id"], "refused")
                candidate["feedback"] = {order["order_id"]: "refused"}
                for step in ("model.pkl", "evaluation.json", "report.md", "model.active"):
                    with self.subTest(step=step):
                        write = artifacts.atomic_write

                        def fail(path, content):
                            if path.name == step:
                                raise OSError("simulated disk failure")
                            write(path, content)

                        with patch.object(artifacts, "atomic_write", side_effect=fail):
                            with self.assertRaises(OSError):
                                artifacts.publish(candidate, {"model_id": "candidate"}, "next", model, expected=initial)
                        self.assertEqual(artifacts.active_version(model), initial)
                        self.assertEqual(service.model_status()["model_id"], current["model_id"])
                        self.assertEqual(service.latest_evaluation()["model_id"], current["model_id"])
                        self.assertEqual(service.learning_status()["pending"], 1)
                        self.assertEqual(list(initial.parent.iterdir()), [initial])

    def test_background_training_leaves_order_writes_available(self):
        from fastapi.testclient import TestClient
        import main
        import operators

        fitting, resume = Event(), Event()

        def fail_after_pause(*args, **kwargs):
            fitting.set()
            if not resume.wait(10):
                raise RuntimeError("Timed out waiting for the concurrent write")
            raise ValueError("simulated training failure")

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(service, "STATE_PATH", Path(directory) / "state.json"), \
             patch.object(train_model, "fit_and_evaluate", side_effect=fail_after_pause):
            order = service.load_orders().iloc[0].to_dict()
            service.mark_outcome(order["order_id"], "refused")
            key = "synthetic-training-operator-key"
            config = {"trainer": {"tenant_id": "demo", "key": key},
                      "other": {"tenant_id": "demo", "key": "synthetic-other-operator-key"}}
            with patch.dict(os.environ, COD_GUARD_OPERATORS=json.dumps(config)), \
                 patch.object(operators, "_write_windows", {}), \
                 TestClient(main.app, headers={"Authorization": f"Bearer {key}"}) as client:
                submitted = client.post("/model/retrain")
                self.assertEqual(submitted.status_code, 202)
                job_url = f"/model/retrain/{submitted.json()['job_id']}"
                try:
                    self.assertTrue(fitting.wait(5))
                    self.assertEqual(client.get(job_url).json()["status"], "running")
                    self.assertEqual(client.get(job_url, headers={
                        "Authorization": "Bearer synthetic-other-operator-key"}).status_code, 404)
                    self.assertEqual(client.post("/model/retrain").status_code, 429)
                    service.verify_reply(order, "Yes")
                finally:
                    resume.set()
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    status = client.get(job_url).json()
                    if status["status"] == "failed":
                        break
                    sleep(0.02)
                self.assertEqual(status["error"], "simulated training failure")
                self.assertEqual(service.learning_status()["pending"], 1)
                with connect(service.STATE_PATH) as db:
                    actor = db.execute("SELECT actor FROM audit_events WHERE action='retrain'").fetchone()[0]
                self.assertEqual(actor, "trainer")


if __name__ == "__main__":
    unittest.main()
