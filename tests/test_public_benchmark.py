import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
import service
from courier_outcomes import store
from public_benchmark import benchmark_markdown
from records import insert_order, write
from savings_report import seller_report


class PublicBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.evaluation = json.loads((ROOT / "data/evaluation.json").read_text(encoding="utf-8"))

    def test_public_report_matches_locked_version(self):
        markdown = benchmark_markdown(self.evaluation)
        self.assertEqual(markdown, (ROOT / "docs/BENCHMARK.md").read_text(encoding="utf-8"))
        self.assertIn("Urdu voice | Not evaluated |", markdown)
        self.assertIn("WooCommerce | Not evaluated |", markdown)
        self.evaluation["split"]["test_labels_sha256"] = "bad digest"
        with self.assertRaisesRegex(ValueError, "holdout lock"):
            benchmark_markdown(self.evaluation)

    def test_charges_are_scoped_observations_not_savings(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "state.json"
        self.enterContext(patch.object(service, "STATE_PATH", path))
        with write(path) as db:
            insert_order(db, "first", {"order_id": "fixture", "customer_name": "Fixture", "product": "Parcel",
                                       "city": "Lahore", "phone": "", "data_source": "SHADOW"})
        store("first", "operator", [("fixture", "postex", "FIXTURE", "returned", 20000)], "operator-csv")
        measured = seller_report("first", self.evaluation)["measured"]
        self.assertEqual(measured["failed_shipment_billed_fee_paisa"], 20000)
        self.assertIsNone(measured["seller_savings_pkr"])
        self.assertIsNone(seller_report("other", self.evaluation)["measured"]["billed_fee_total_paisa"])
        self.assertIsNotNone(seller_report("demo", self.evaluation)["estimated"]["benchmark_cost_difference_pkr"])
        service.mark_outcome("fixture", "delivered", tenant_id="first")
        self.assertIsNone(seller_report("first", self.evaluation)["measured"]["billed_fee_total_paisa"])
