import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from create_split import stratified_positions
from heterogeneity import design_matrix, hc3_ols, joint_wald, subgroup_results


class HeterogeneityTest(unittest.TestCase):
    def test_split_is_disjoint_stratified_and_reproducible(self):
        arms = ["Mens E-Mail"]*10 + ["Womens E-Mail"]*10 + ["No E-Mail"]*10
        a, b, counts = stratified_positions(arms)
        a2, b2, _ = stratified_positions(arms)
        np.testing.assert_array_equal(a, a2)
        np.testing.assert_array_equal(b, b2)
        self.assertEqual(len(a), 21)
        self.assertEqual(len(b), 9)
        self.assertEqual(len(np.intersect1d(a, b)), 0)
        self.assertTrue(all(v["validation"] == 3 for v in counts.values()))

    def test_joint_model_and_wald(self):
        rows = []
        for arm in ["Mens E-Mail", "Womens E-Mail", "No E-Mail"]:
            for mens in [0,1]:
                for womens in [0,1]:
                    for newbie in [0,1]:
                        for channel in ["Phone", "Multichannel", "Web"]:
                            for repeat in range(2):
                                rows.append((arm,mens,womens,newbie,channel,repeat))
        frame = pd.DataFrame(rows, columns=["segment","mens","womens","newbie","channel","repeat"])
        matrix, blocks = design_matrix(frame)
        self.assertEqual(len(blocks["channel"]), 4)
        y = 3 + 2*matrix["arm:Mens E-Mail"].to_numpy() + 0.5*frame.repeat.to_numpy()
        beta, covariance = hc3_ols(y, matrix)
        self.assertAlmostEqual(beta[matrix.columns.get_loc("arm:Mens E-Mail")], 2)
        positions = [matrix.columns.get_loc(c) for c in blocks["channel"]]
        self.assertGreaterEqual(joint_wald(beta, covariance, positions)["p_raw"], 0)

    def test_rank_failure_is_reported(self):
        with self.assertRaises(ValueError):
            hc3_ols([1,2,3], [[1,1],[1,1],[1,1]])

    def test_subgroup_summary_retains_zero_spend(self):
        rows = []
        for arm in ["Mens E-Mail", "Womens E-Mail", "No E-Mail"]:
            for mens in [0,1]:
                for value in [0.0, 10.0]:
                    rows.append((arm,mens,0,0,"Phone",value))
        frame = pd.DataFrame(rows, columns=["segment","mens","womens","newbie","channel","spend"])
        results = subgroup_results(frame)
        first = next(r for r in results if r["feature"] == "mens" and r["level"] == "0")
        self.assertEqual(first["arms"]["Mens E-Mail"]["n"], 2)
        self.assertEqual(first["arms"]["Mens E-Mail"]["nonzero_spend_n"], 1)
        self.assertEqual(first["arms"]["Mens E-Mail"]["mean_spend_usd"], 5.0)


if __name__ == "__main__":
    unittest.main()
