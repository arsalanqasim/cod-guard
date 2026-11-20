import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
from train_model import split_benchmark, feature_frame, fit_and_evaluate
import service
import train_model


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
        assessment = service.assess_order(order, state={"decisions": {}, "outcomes": {}})
        self.assertEqual(assessment["ml_probability"], round(probability, 3))

    def test_test_split_id_or_label_changes_abort_before_fitting(self):
        train, validation, test, demo = split_benchmark(self.benchmark)
        for field, value in (("order_id", "replacement-id"), ("label_failed", 1 - test.iloc[0]["label_failed"])):
            with self.subTest(field=field):
                changed = test.copy()
                changed.loc[test.index[0], field] = value
                with patch.object(train_model, "split_benchmark", return_value=(train, validation, changed, demo)), \
                     patch.object(train_model.HistGradientBoostingClassifier, "fit", side_effect=AssertionError("fit was called")):
                    with self.assertRaisesRegex(ValueError, "Test split lock mismatch"):
                        fit_and_evaluate(self.benchmark)

    def test_committed_evaluation_records_the_id_and_label_digests(self):
        report = json.loads((ROOT / "data/evaluation.json").read_text(encoding="utf-8"))
        committed = json.loads(train_model.TEST_LOCK_PATH.read_text(encoding="utf-8"))
        self.assertEqual({key: report["split"][key] for key in committed}, committed)

    def test_outcome_fed_report_has_its_own_version_section(self):
        baseline = json.loads((ROOT / "data/evaluation.json").read_text(encoding="utf-8"))
        followup = {**baseline, "version": 2, "split": {**baseline["split"], "feedback": 1}}
        self.assertIn("## Outcome-fed version 2", train_model.render_report(followup))
        self.assertNotIn("Outcome-fed version", train_model.render_report(baseline))


if __name__ == "__main__":
    unittest.main()
