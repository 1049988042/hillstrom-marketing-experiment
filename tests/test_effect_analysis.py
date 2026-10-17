import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from effect_analysis import RAW, group_summary, holm, proportion_compare, spend_compare, validate


class EffectCalculationsTest(unittest.TestCase):
    def test_group_metrics_include_zero_spend(self):
        frame = pd.DataFrame({"visit": [1, 0], "conversion": [1, 0], "spend": [10.0, 0.0]})
        result = group_summary(frame)
        self.assertEqual(result["n"], 2)
        self.assertEqual(result["mean_spend_usd"], 5.0)
        self.assertEqual(result["nonzero_spend_n"], 1)
        self.assertEqual(result["visit_rate"], 0.5)

    def test_spend_difference_and_interval(self):
        result = spend_compare([1, 2, 3, 4], [0, 1, 2, 3])
        self.assertAlmostEqual(result["difference_usd"], 1)
        self.assertLess(result["ci95_usd"][0], 1)
        self.assertGreater(result["ci95_usd"][1], 1)

    def test_proportion_difference_and_interval(self):
        result = proportion_compare([1]*60+[0]*40, [1]*40+[0]*60)
        self.assertAlmostEqual(result["difference_pp"], 20)
        self.assertLess(result["ci95_pp"][0], 20)
        self.assertGreater(result["ci95_pp"][1], 20)

    def test_holm_adjustment_original_order(self):
        self.assertTrue(np.allclose(holm([0.03, 0.001, 0.02]), [0.04, 0.003, 0.04]))

    def test_raw_constraints(self):
        df = pd.read_csv(RAW)
        validate(df)
        self.assertEqual(len(df), sum(df.segment.value_counts()))
        changed = df.copy()
        changed.loc[0, "visit"] = 2
        with self.assertRaises(ValueError):
            validate(changed)


if __name__ == "__main__":
    unittest.main()
