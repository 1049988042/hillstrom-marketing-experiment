import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from policy_evaluation import (break_even_cost, contribution, pairwise_spend,
                               policy_summary, scenarios, validate_inputs, verify_plan_hash, PLAN_SHA256)


class PolicyEvaluationTest(unittest.TestCase):
    def test_group_means_include_zero_spend_and_fixed_arms(self):
        frame = pd.DataFrame({"segment": ["No E-Mail"]*2+["Mens E-Mail"]*2+["Womens E-Mail"]*2,
                              "spend": [0,2,0,4,0,6]})
        summary = policy_summary(frame)
        self.assertEqual([summary[p]["mean_spend_usd"] for p in ["P0","P1","P2"]], [1,2,3])
        self.assertEqual(summary["P1"]["nonzero_spend_n"], 1)
        self.assertEqual(summary["P1"]["n"], 2)
        comparisons = pairwise_spend(frame)
        self.assertEqual(comparisons["P1 vs P0"]["difference_usd"], 1)
        self.assertEqual(comparisons["P2 vs P0"]["difference_usd"], 2)
        self.assertEqual(comparisons["P1 vs P2"]["difference_usd"], -1)
        self.assertLess(comparisons["P1 vs P0"]["ci95_usd"][0], 1)
        self.assertGreater(comparisons["P1 vs P0"]["ci95_usd"][1], 1)
        self.assertEqual(len(comparisons), 3)

    def test_contribution_threshold_and_scenarios(self):
        self.assertAlmostEqual(contribution(0.4, 0.8, 0.1), 0.22)
        self.assertAlmostEqual(break_even_cost(0.4, 0.8), 0.32)
        self.assertAlmostEqual(contribution(0.4, 0.8, break_even_cost(0.4, 0.8)), 0)
        with self.assertRaises(ValueError):
            contribution(1.2, 0.8, 0.1)
        comparison = {
            "P1 vs P0": {"difference_usd": 0.8, "ci95_usd": [0.4,1.2]},
            "P2 vs P0": {"difference_usd": 0.2, "ci95_usd": [-0.1,0.5]},
            "P1 vs P2": {"difference_usd": 0.6, "ci95_usd": [0.1,1.1]},
        }
        rows = scenarios(comparison)["scenario_rows"]
        self.assertEqual(len(rows), 9)
        self.assertEqual(next(r for r in rows if r["assumed_margin"]==0.4 and r["assumed_cost_usd"]==0.25)["point_estimate_choice"], "P1")
        self.assertEqual(next(r for r in rows if r["assumed_margin"]==0.2 and r["assumed_cost_usd"]==0.5)["point_estimate_choice"], "P0")

    def test_source_index_and_frozen_rule_constraints(self):
        hashes = validate_inputs()
        manifest = json.loads((ROOT/"data/split_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(hashes["raw_sha256"], manifest["source_sha256"])
        self.assertEqual(hashes["index_sha256"], manifest["index_file_sha256"])
        frozen = json.loads((ROOT/"docs/candidate_rule.json").read_text(encoding="utf-8"))
        self.assertIsNone(frozen["candidate_rule"])
        self.assertEqual(hashes["plan_sha256"], PLAN_SHA256)

    def test_changed_frozen_plan_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            modified = Path(temporary) / "policy_evaluation_plan.md"
            modified.write_bytes((ROOT/"docs/policy_evaluation_plan.md").read_bytes() + b"\nchanged")
            with self.assertRaisesRegex(ValueError, "Frozen policy plan SHA256 mismatch"):
                verify_plan_hash(modified)


if __name__ == "__main__":
    unittest.main()
