import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
from train_model import render_report


class ClaimTests(unittest.TestCase):
    def test_demo_claims_label_baseline_funnel_and_budget(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8").casefold()
        demo = (ROOT / "docs/DEMO_SCRIPT.md").read_text(encoding="utf-8").casefold()
        for name, copy in (("readme", readme), ("demo", demo)):
            with self.subTest(name=name):
                self.assertIn("baseline v1", copy)
                self.assertIn("amber or red", copy)
                self.assertIn("49–57", copy)
                self.assertIn("measurement windows", copy)
                self.assertIn("one retailer", copy)
        self.assertIn("offline budget", demo)
        self.assertIn("341 flags", demo)
        self.assertIn("355", demo)
        self.assertIn("decision revision", readme)

    def test_obsolete_claims_do_not_reappear_in_active_copy(self):
        forbidden = ("independent" + " adverse signal", "two-independent" + "-signal",
                     "another independent" + " signal", "equal flag" + " cap",
                     "how fake COD orders" + " actually behave", "both current" + " rates")
        sources = ("README.md", "docs/DEMO_SCRIPT.md", "docs/EVAL_REPORT.md", "frontend/dashboard.py",
                   "backend/app/train_model.py", "backend/app/risk_engine.py", "data/generate_benchmark.py")
        for source in sources:
            copy = (ROOT / source).read_text(encoding="utf-8").casefold()
            for phrase in forbidden:
                with self.subTest(source=source, phrase=phrase):
                    self.assertNotIn(phrase.casefold(), copy)

    def test_generated_report_uses_current_claims(self):
        payload = json.loads((ROOT / "data/evaluation.json").read_text(encoding="utf-8"))
        rendered = render_report(payload)
        self.assertIn("two distinct adverse signal groups", rendered)
        self.assertIn("49–57 cash collections", rendered)
        self.assertEqual((ROOT / "docs/EVAL_REPORT.md").read_text(encoding="utf-8"), rendered)
