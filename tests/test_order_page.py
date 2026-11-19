import json
import os
import statistics
import sys
import tempfile
import unittest
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
import main
import service
from records import insert_order, write


class OrderPageTests(unittest.TestCase):
    def test_page_of_50_at_10000_orders_scores_one_batch_in_under_a_second(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(service, "STATE_PATH", Path(folder) / "state.json"))
        key = "synthetic-page-operator-key"
        operator = {"load": {"tenant_id": "load", "key": key}}
        self.enterContext(patch.dict(os.environ, COD_GUARD_OPERATORS=json.dumps(operator)))
        fixture = service.get_order("CG-00203")
        with write(service.STATE_PATH) as db:
            for index in range(10_000):
                insert_order(db, "load", {**fixture, "order_id": f"LOAD-{index:05d}"})
        client = self.enterContext(TestClient(main.app, headers={"Authorization": f"Bearer {key}"}))
        estimator = service._bundle()["model"]
        with patch.object(estimator, "predict_proba", wraps=estimator.predict_proba) as predict:
            times = []
            for _ in range(5):
                start = perf_counter()
                result = client.get("/orders?limit=50&offset=75")
                times.append(perf_counter() - start)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(len(result.json()), 50)
                self.assertEqual(result.json()[0]["order_id"], "LOAD-00075")
                self.assertEqual(result.headers["X-Total-Count"], "10000")
            self.assertEqual([len(call.args[0]) for call in predict.call_args_list], [50] * 5)
        median = statistics.median(times)
        print(f"50 of 10,000 orders, TestClient median of five: {median:.3f}s")
        self.assertLess(median, 1.0)
        self.assertEqual(client.get("/orders?limit=101").status_code, 422)
