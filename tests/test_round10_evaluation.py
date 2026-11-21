from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))
from evaluate_round10 import (
    lagged_outcome_features, order_cost, purchase_features, reallocate_verification, release_actions, select_release,
)
from evaluate_round9 import HOLD, SHIP, VERIFY


class Round10EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.orders = pd.DataFrame({
            "customer_id": ["a", "a", "a", "a", "a", "b"],
            "order_day": pd.to_datetime(["2020-01-01", "2020-02-01", "2020-02-29", "2020-03-01",
                                         "2020-03-02", "2020-02-29"]),
            "amount_pkr": [50, 100, 200, 300, 400, 1000],
            "label_failed": [1, 0, 1, 0, 1, 1],
        })
        self.targets = self.orders.loc[[3, 0, 5]].copy()

    def test_purchase_history_keeps_target_order_and_excludes_same_day_and_other_buyers(self):
        history = purchase_features(self.targets, self.orders.drop(columns="label_failed"))
        self.assertEqual(history.index.tolist(), [3, 0, 5])
        self.assertEqual(history["prior_orders"].tolist(), [3, 0, 0])
        self.assertEqual(history["prior_orders_30d"].tolist(), [2, 0, 0])
        self.assertEqual(history["prior_orders_90d"].tolist(), [3, 0, 0])
        self.assertEqual(history.loc[3, "days_since_purchase"], 1)
        self.assertTrue(np.isnan(history.loc[0, "days_since_purchase"]))
        same_day = self.orders.iloc[[3]].assign(amount_pkr=20_000)
        pd.testing.assert_frame_equal(history, purchase_features(self.targets, pd.concat([self.orders, same_day])))

    def test_proxy_history_respects_lag_and_cutoff(self):
        lagged = lagged_outcome_features(self.targets, self.orders, 29)
        self.assertEqual(lagged["prior_label_count"].tolist(), [2, 0, 0])
        self.assertEqual(lagged.loc[3, "last_proxy_failed"], 0)
        capped = lagged_outcome_features(self.targets, self.orders, 29, observed_through=pd.Timestamp("2020-01-31"))
        self.assertEqual(capped["prior_label_count"].tolist(), [1, 0, 0])
        self.assertAlmostEqual(capped.loc[3, "smoothed_failure_rate"], 2 / 3)

    def test_release_and_budget_preserve_holds_and_protected_orders(self):
        base = np.array([VERIFY, SHIP, VERIFY, HOLD, SHIP])
        probabilities = np.array([.10, .80, .11, .01, .20])
        eligible = np.array([True, True, False, True, True])
        np.testing.assert_array_equal(release_actions(base, probabilities, eligible, .15),
                                      [SHIP, SHIP, VERIFY, HOLD, SHIP])
        np.testing.assert_array_equal(reallocate_verification(base, probabilities, eligible),
                                      [SHIP, VERIFY, VERIFY, HOLD, SHIP])
        np.testing.assert_array_equal(reallocate_verification(base, np.full(len(base), .5), eligible), base)
        np.testing.assert_array_equal(base, [VERIFY, SHIP, VERIFY, HOLD, SHIP])

    def test_release_uses_economic_effect_and_independent_clusters(self):
        labels = np.array([0] * 90 + [1] * 10 + [0] * 10 + [1] * 90)
        scores = np.array([.15] * 100 + [.25] * 100)
        base = np.full(len(labels), VERIFY)
        eligible = np.ones(len(labels), dtype=bool)
        chosen = select_release(base, scores, eligible, labels, np.arange(len(labels)))
        self.assertEqual(chosen["threshold"], .15)
        self.assertEqual(chosen["released"], 100)
        self.assertIsNone(select_release(base, scores, eligible, labels, np.zeros(len(labels)))["threshold"])
        np.testing.assert_allclose(order_cost(np.array([0, 1, 0, 1, 0, 1]),
                                             np.array([SHIP, SHIP, VERIFY, VERIFY, HOLD, HOLD])),
                                   [0, 650, 230, 50, 450, 0])
