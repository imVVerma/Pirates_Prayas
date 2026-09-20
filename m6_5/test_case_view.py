import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tb_m0"))
sys.path.insert(0, str(ROOT / "tb_m1"))
sys.path.insert(0, str(ROOT / "tb_m4a"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from case_view import build_case_view
from contract import validate_or_raise

FIXTURE = Path(__file__).resolve().parent / "canonical-demo-case.json"

class CaseViewTests(unittest.TestCase):
    def setUp(self):
        self.case = json.loads(FIXTURE.read_text())
        validate_or_raise(self.case)

    def test_projection_is_stable_and_non_mutating(self):
        before = deepcopy(self.case)
        view = build_case_view(self.case)
        self.assertEqual(self.case, before)
        self.assertEqual(view["case_id"], self.case["case_id"])
        self.assertEqual(view["current_stage"], "treatment_follow_up")

    def test_screening_is_displayed_not_reinterpreted(self):
        view = build_case_view(self.case)
        self.assertEqual(view["screening"]["xray"]["flag"], "abnormal")
        self.assertAlmostEqual(view["screening"]["xray"]["confidence"], 0.9847)
        self.assertIsNotNone(view["diagnosis"])
        self.assertEqual(view["diagnosis"]["classification"], "bacteriologically_confirmed")

    def test_missed_pickup_becomes_alert_and_next_action(self):
        view = build_case_view(self.case)
        self.assertTrue(any(a["type"] == "missed_pickup" for a in view["alerts"]))
        self.assertEqual(view["asha"]["next_action"]["type"], "medicine_pickup")
        self.assertEqual(view["asha"]["next_action"]["due"], "2026-09-24")

    def test_revision_and_history_are_exposed(self):
        view = build_case_view(self.case)
        self.assertEqual(view["revision"], 14)
        self.assertEqual(view["history_count"], 10)

if __name__ == "__main__":
    unittest.main()

