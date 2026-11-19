import sys
import unittest
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/app")]
from data.generate_benchmark import generate_benchmark
from round2_evaluation import (capacity_comparison, contact_plan, evaluation_batch,
                               expected_metrics, final_hold_probabilities,
                               predictability_ceiling, priority_order)
from train_model import feature_frame, split_benchmark


class Round2EvaluationTests(unittest.TestCase):
    def test_published_zero_outreach_reproduces_served_metrics(self):
        report = json.loads((ROOT / "data/evaluation.json").read_text(encoding="utf-8"))
        result = report["round2"]["verification_sensitivity"]["no_outreach"]
        self.assertEqual(result["contact_attempts"], 0)
        for key in ("fp", "fn", "tp", "tn", "fp_rate", "fn_rate", "total_cost"):
            self.assertEqual(result[key], report["chosen"][key])

    def test_recognized_replies_override_only_when_contact_is_possible(self):
        zones = np.array(["RED", "AMBER", "GREEN", "GREEN", "RED", "GREEN"])
        labels = np.array([False, False, True, True, True, True])
        valid = np.array([True, False, True, False, True, True])
        attempts = contact_plan(zones, .2)
        holds = final_hold_probabilities(zones, labels, valid, attempts, (.6, .02, .1, .25))
        np.testing.assert_allclose(holds, [.4, 1, .05, 0, .9, .05])
        metrics = expected_metrics(labels, holds, attempts, 650, 450, 50)
        self.assertAlmostEqual(metrics["fp"], 1.4)
        self.assertAlmostEqual(metrics["fn"], 3)
        self.assertAlmostEqual(metrics["contact_attempts"], 3.6)
        self.assertAlmostEqual(metrics["total_cost"], 2760)

    def test_capacity_is_hard_and_test_labels_cannot_select_utilization(self):
        n = 11
        ranking = list(range(n))
        labels = np.array([True] * 6 + [False] * 5)
        validation = {"rankings": {"ranked": ranking, "ship_everything": []},
                      "labels": labels, "valid_phone": np.ones(n, dtype=bool)}
        original = capacity_comparison(validation, validation, 650, 450)
        flipped = capacity_comparison(validation, {**validation, "labels": ~labels}, 650, 450)
        for left, right in zip(original, flipped, strict=True):
            policy = left["policies"]["ranked"]
            changed = right["policies"]["ranked"]
            self.assertLessEqual(policy["flagged"], n * left["budget_pct"] // 100)
            self.assertEqual(policy["flagged"], changed["flagged"])
            self.assertEqual(policy["validation_utilization_pct"], changed["validation_utilization_pct"])
            self.assertEqual(left["validation_winners"], right["validation_winners"])
        self.assertNotEqual(original[0]["observed_test_winners"], flipped[0]["observed_test_winners"])

    def test_tied_priority_is_invariant_to_input_order(self):
        ids = np.array(["CG-2", "CG-1", "CG-3"])
        scores = np.array([20, 20, 20])
        eligible = np.array([True, True, False])
        forward = ids[priority_order(scores, eligible, ids)].tolist()
        backward = ids[::-1][priority_order(scores[::-1], eligible[::-1], ids[::-1])].tolist()
        self.assertEqual(forward, backward)
        self.assertNotIn("CG-3", forward)

    def test_oracle_is_separate_and_bounds_same_capacity_capture(self):
        benchmark, oracle = generate_benchmark()
        pd.testing.assert_frame_equal(benchmark, pd.read_csv(ROOT / "data/benchmark_orders.csv"))
        self.assertTrue(oracle["oracle_probability"].between(0, 1, inclusive="neither").all())
        _, validation, _, _ = split_benchmark(benchmark)
        indexed = oracle.set_index("order_id")
        joined = validation.join(indexed, on="order_id")
        pd.testing.assert_frame_equal(feature_frame(validation), feature_frame(joined))
        probs = np.linspace(.30, .80, len(validation))
        batch = evaluation_batch(validation, probs, .50)
        for policy in ("served_capped", "cod_guard_ml_ranked", "two_signal_rules_ranked"):
            self.assertTrue(all(batch["signal_counts"][i] >= 2 for i in batch["rankings"][policy]))
        aligned = indexed.loc[validation["order_id"]]
        ceiling = predictability_ceiling(batch, aligned)
        self.assertLessEqual(ceiling["served_expected_recall"], ceiling["oracle_two_signal_expected_recall"])
        self.assertLessEqual(ceiling["oracle_two_signal_expected_recall"], ceiling["oracle_unrestricted_expected_recall"])
        flipped = predictability_ceiling({**batch, "labels": ~batch["labels"]}, aligned)
        self.assertEqual(ceiling["ordinary_signal_variance_share"], flipped["ordinary_signal_variance_share"])
        self.assertEqual(ceiling["oracle_two_signal_expected_recall"], flipped["oracle_two_signal_expected_recall"])
        self.assertAlmostEqual(ceiling["ordinary_signal_variance_share"] + ceiling["ordinary_noise_variance_share"], 1)


if __name__ == "__main__":
    unittest.main()
