import json
import os
from pathlib import Path
import pickle
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend/app"), str(ROOT)]
import main
import operators
import service
from records import insert_order, write
from risk_candidate import Bands, FEATURES, decide, fit_model
from scripts.pk_real import split_customers_and_time


class Round9RiskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(9)
        frame = pd.DataFrame({"amount_pkr": rng.integers(100, 5000, 300),
                              "items_count": rng.integers(1, 5, 300),
                              "is_repeat_customer": rng.integers(0, 2, 300)})
        frame["label_failed"] = frame["amount_pkr"].add(frame["items_count"] * 100).gt(2700).astype(int)
        cls.estimator, _ = fit_model(frame.iloc[:150], frame.iloc[150:225], frame.iloc[225:])

    def test_policy_only_hard_overrides_adjust_its_calibrated_band(self):
        bands = Bands(.3, .7)
        self.assertEqual(decide(.4, bands)["proposed_decision"], "VERIFY_FIRST")
        self.assertEqual(decide(.1, bands)["proposed_decision"], "SHIP")
        self.assertEqual(decide(.8, bands)["proposed_decision"], "HOLD")
        self.assertEqual(decide(.2, bands, intent="DENY", phone_valid=0)["proposed_decision"], "HOLD_CANCEL")
        self.assertEqual(decide(.5, bands, intent="CONFIRM")["proposed_decision"], "SHIP")
        self.assertEqual(decide(.8, bands, phone_valid=0)["proposed_decision"], "VERIFY_FIRST")
        self.assertEqual(decide(.1, bands, queue_status="closed")["proposed_decision"], "HOLD")
        with self.assertRaises(ValueError):
            Bands(.7, .3)

    def test_tree_path_contributions_sum_to_raw_margin_change(self):
        row = [3500, 2, 1]
        model = self.estimator.model
        raw = float(model.decision_function(pd.DataFrame([row], columns=FEATURES))[0])
        p0, p1 = model.init_.class_prior_
        root = np.log(p1 / p0) + model.learning_rate * sum(tree.tree_.value[0, 0, 0]
                                                           for tree in model.estimators_[:, 0])
        self.assertAlmostEqual(sum(item["log_odds_delta"] for item in self.estimator.explain(row)),
                               raw - root, places=5)

    def test_customer_partitions_are_chronological_and_disjoint(self):
        frame = pd.DataFrame([{"order_id": f"{customer}-{day}", "customer_id": str(customer),
                               "order_day": pd.Timestamp("2020-01-01") + pd.Timedelta(day, "days"),
                               "label_failed": (day + customer) % 2}
                              for day in range(12) for customer in range(100)])
        train, validation, test = split_customers_and_time(frame)
        self.assertLess(train["order_day"].max(), validation["order_day"].min())
        self.assertLess(validation["order_day"].max(), test["order_day"].min())
        self.assertEqual(sum(part["customer_id"].nunique() for part in (train, validation, test)), 100)
        self.assertTrue(set(train["customer_id"]).isdisjoint(set(test["customer_id"])))

    def test_shadow_revisions_cannot_change_dispatch_or_cross_tenant_boundary(self):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        state, artifact = folder / "state.json", folder / "risk.pkl"
        model = {"version": 1, "source": "[SELLER]", "tenant": "alpha",
                 "model_id": "seller-r9-0000000000000001", "estimator": self.estimator,
                 "bands": {"verify_at": .20, "hold_at": .80}}
        artifact.write_bytes(pickle.dumps(model))
        operators_config = {name: {"tenant_id": name, "key": f"round9-operator-fixture-{name}"}
                            for name in ("alpha", "beta")}
        config = {"alpha": {"artifact": str(artifact), "bands": {"verify_at": 0.0, "hold_at": .95}},
                  "beta": {"artifact": str(artifact)}}
        self.enterContext(patch.object(service, "STATE_PATH", state))
        self.enterContext(patch.object(operators, "_write_windows", {}))
        self.enterContext(patch.dict(os.environ, COD_GUARD_OPERATORS=json.dumps(operators_config),
                                     COD_GUARD_RISK_SHADOW=json.dumps(config), COD_GUARD_EXHIBITION="0"))
        client = self.enterContext(TestClient(main.app))
        headers = {name: {"Authorization": f"Bearer {data['key']}"} for name, data in operators_config.items()}
        order = {"order_id": "alpha-order", "city": "Lahore", "customer_name": "Example",
                 "product": "Bag", "phone": "03001234567", "data_source": "SHADOW",
                 "amount_pkr": 3200, "items_count": 2, "is_repeat_customer": 0, "phone_valid": 1}
        with write(state) as db:
            insert_order(db, "alpha", order)
            insert_order(db, "beta", {**order, "order_id": "beta-order"})
        path = "/orders/alpha-order"
        preview = client.get(path + "/risk-shadow", headers=headers["alpha"]).json()
        self.assertIsNotNone(preview["current"]["calibrated_score"])
        self.assertTrue(preview["current"]["contributors"])
        self.assertEqual(preview["current"]["thresholds"], {"verify_at": 0.0, "hold_at": .95})
        self.assertEqual(preview["revisions"], [])
        self.assertEqual(client.get(path + "/risk-shadow", headers=headers["beta"]).status_code, 404)
        self.assertIsNone(client.get("/orders/beta-order/risk-shadow", headers=headers["beta"]).json()["current"])
        committed = client.post(path + "/verify", headers=headers["alpha"], json={"text": "No, cancel"})
        self.assertEqual(committed.json()["decision"], "HOLD_CANCEL")
        client.post(path + "/verify", headers=headers["alpha"], json={"text": "Phone 0300-1234567"})
        detail = client.get(path, headers=headers["alpha"]).json()
        self.assertEqual(detail["decision"], "HOLD_CANCEL")
        self.assertEqual(detail["messages"][-1]["text"], "Phone ••••67")
        revisions = client.get(path + "/risk-shadow", headers=headers["alpha"]).json()["revisions"]
        self.assertEqual(len(revisions), 2)
        self.assertEqual({row["recorded_decision"] for row in revisions}, {"HOLD_CANCEL"})
        self.assertIn("Buyer denial always holds the order", revisions[-1]["policy_rules"])
        self.assertEqual(client.get(path + "/risk-shadow?after=1", headers=headers["alpha"]).json()["revisions"],
                         revisions[1:])
        with patch.dict(os.environ, COD_GUARD_EXHIBITION="1"):
            self.assertEqual(client.get(path + "/risk-shadow", headers=headers["alpha"]).json(),
                             {"current": None, "revisions": []})
        research = folder / "research.pkl"
        research.write_bytes(pickle.dumps({**model, "source": "[PK-REAL]"}))
        with patch.dict(os.environ, COD_GUARD_RISK_SHADOW=json.dumps({"alpha": {"artifact": str(research)}})):
            self.assertIsNone(client.get(path + "/risk-shadow", headers=headers["alpha"]).json()["current"])


if __name__ == "__main__":
    unittest.main()
