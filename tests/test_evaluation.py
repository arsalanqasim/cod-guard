import json
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
from train_model import split_benchmark, feature_frame, fit_and_evaluate
import service


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.benchmark = pd.read_csv(ROOT / "data/benchmark_orders.csv")

    def test_splits_and_reserved_demo_are_disjoint(self):
        partitions = split_benchmark(self.benchmark)
        ids = [set(frame["order_id"]) for frame in partitions]
        self.assertEqual(sum(map(len, ids)), len(self.benchmark))
        for i, left in enumerate(ids):
            for right in ids[i + 1:]:
                self.assertFalse(left & right)
        demo = pd.read_csv(ROOT / "data/demo_orders.csv")
        self.assertEqual(set(demo["order_id"]), ids[3])

    def test_feedback_cannot_consume_a_held_out_order(self):
        test = split_benchmark(self.benchmark)[2]
        with self.assertRaisesRegex(ValueError, "cannot overlap"):
            fit_and_evaluate(self.benchmark, feedback_rows=test.head(1))

    def test_labels_and_outcomes_never_become_features(self):
        frame = self.benchmark.head(4).copy()
        expected = feature_frame(frame)
        frame["label_failed"] = 1 - frame["label_failed"]
        frame["outcome"] = "refused"
        pd.testing.assert_frame_equal(expected, feature_frame(frame))

    def test_service_uses_the_published_operating_threshold(self):
        report = json.loads((ROOT / "data/evaluation.json").read_text(encoding="utf-8"))
        status = service.model_status()
        self.assertEqual(status["model_id"], report["model_id"])
        self.assertEqual(status["threshold"], report["chosen"]["threshold"])
        order = self.benchmark.iloc[0].to_dict()
        bundle = service._bundle()
        probability = bundle["model"].predict_proba(feature_frame(pd.DataFrame([order]), bundle["columns"]))[0][1]
        self.assertAlmostEqual(service._ml_probability(order), probability)


if __name__ == "__main__":
    unittest.main()
