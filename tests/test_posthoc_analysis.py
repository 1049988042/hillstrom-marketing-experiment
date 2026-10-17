import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
import posthoc_analysis as posthoc


class PosthocAnalysisTest(unittest.TestCase):
    def test_consumption_identity_and_counts(self):
        rows = []
        for arm in posthoc.GROUPS:
            rows += [(arm,0,0,0.0),(arm,1,0,0.0),(arm,1,1,12.0),(arm,1,1,4.0)]
        frame = pd.DataFrame(rows,columns=["segment","visit","conversion","spend"])
        result = posthoc.decomposition(frame)
        for arm in result["arms"].values():
            self.assertEqual(arm["n"],4)
            self.assertEqual(arm["visits_n"],3)
            self.assertEqual(arm["conversions_n"],2)
            self.assertEqual(arm["mean_spend"],4.0)
            self.assertAlmostEqual(arm["factor_product"],4.0)
        frame.loc[2,"visit"] = 0
        with self.assertRaisesRegex(ValueError,"identity assumptions violated"):
            posthoc.decomposition(frame)

    def test_shapley_efficiency_symmetry_and_null_factor(self):
        result = posthoc.shapley_product([1,2,3],[2,4,6])
        np.testing.assert_allclose(list(result["contributions_usd"].values()),[14,14,14])
        self.assertAlmostEqual(sum(result["contributions_usd"].values()),42)
        null = posthoc.shapley_product([1,2,3],[1,4,6])
        self.assertEqual(null["contributions_usd"]["visit_rate"],0)

    def test_fixed_grouping_boundaries_and_partition_counts(self):
        frame = pd.DataFrame({"history_segment":[f"{i}) band" for i in range(1,8)],"recency":[1,3,4,6,7,9,12]})
        grouped = posthoc.add_strata(frame)
        self.assertEqual(grouped.history_group.tolist(),["low:1-2"]*2+["middle:3-4"]*2+["high:5-7"]*3)
        self.assertEqual(grouped.recency_group.tolist(),["1-3","1-3","4-6","4-6","7-9","7-9","10-12"])
        discovery = posthoc.add_strata(posthoc.load_exploration())
        self.assertEqual(len(discovery),44800)
        for feature in ["history_band","history_group","recency_group"]:
            self.assertEqual(int(discovery.groupby(feature).size().sum()),44800)
            for arm,expected in [("Mens E-Mail",14915),("Womens E-Mail",14971),("No E-Mail",14914)]:
                self.assertEqual(int(discovery[discovery.segment.eq(arm)].groupby(feature).size().sum()),expected)

    def test_hc3_wald_matches_independent_cell_mean_contrasts(self):
        # In a saturated model, independent cell means give a separate analytic
        # reference. HC3 variance of a cell mean equals s^2/(n-1).
        levels = ["low","mid","high"]
        rows, means, variances = [], [], []
        cells = [(arm,level) for arm in posthoc.GROUPS for level in levels]
        for i,(arm,level) in enumerate(cells):
            values = np.array([1.,2.,3.,5.,7.]) + (i%3)*(1 if arm==posthoc.CONTROL else 2)
            rows.extend((arm,level,v) for v in values)
            means.append(values.mean())
            variances.append(values.var(ddof=1)/(len(values)-1))
        matrix = []
        for level in levels[1:]:
            for arm in posthoc.GROUPS[:2]:
                row = np.zeros(len(cells))
                for key,sign in [((arm,level),1),((posthoc.CONTROL,level),-1),((arm,levels[0]),-1),((posthoc.CONTROL,levels[0]),1)]:
                    row[cells.index(key)] = sign
                matrix.append(row)
        contrasts = np.asarray(matrix)
        b = contrasts @ np.asarray(means)
        cov = contrasts @ np.diag(variances) @ contrasts.T
        expected = float(b @ np.linalg.solve(cov,b))
        frame = pd.DataFrame(rows,columns=["segment","stratum","spend"])
        result = posthoc.interaction_test(frame,"stratum",levels)
        self.assertEqual(result["status"],"ok")
        self.assertEqual(result["df"],4)
        self.assertAlmostEqual(result["statistic_chi2"],expected,places=9)
        self.assertAlmostEqual(result["p_raw"],stats.chi2.sf(expected,4),places=10)

    def test_subgroup_loader_skips_every_validation_outcome(self):
        with np.load(ROOT/"data/split_indices.npz") as indices:
            discovery,validation = indices["discovery"],indices["validation"]
        original = pd.read_csv
        def guarded_reader(path,**kwargs):
            skip = kwargs["skiprows"]
            self.assertFalse(skip(0))
            self.assertTrue(all(skip(int(i)+1) for i in validation))
            self.assertTrue(all(not skip(int(i)+1) for i in discovery))
            self.assertEqual(set(kwargs["usecols"]),{"segment","history","history_segment","recency","spend"})
            return original(path,**kwargs)
        with patch.object(posthoc.pd,"read_csv",side_effect=guarded_reader):
            selected = posthoc.load_exploration()
        self.assertEqual(len(selected),44800)

    def test_full_sample_loader_excludes_stratification_features(self):
        original = pd.read_csv
        def guarded_reader(path,**kwargs):
            self.assertEqual(set(kwargs["usecols"]),{"segment","visit","conversion","spend"})
            return original(path,**kwargs)
        with patch.object(posthoc.pd,"read_csv",side_effect=guarded_reader):
            data = posthoc.load_full_decomposition()
        self.assertEqual(len(data),64000)

    def test_source_hash_and_mismatched_source_rejection(self):
        checked = posthoc.checked_paths()
        self.assertEqual(checked["raw_sha256"],posthoc.SHA256)
        self.assertEqual(checked["index_sha256"],posthoc.INDEX_SHA256)
        with tempfile.TemporaryDirectory() as directory:
            wrong = Path(directory)/"changed.csv"
            wrong.write_bytes(b"not the source")
            with patch.object(posthoc,"RAW",wrong):
                with self.assertRaisesRegex(ValueError,"Raw CSV SHA256 mismatch"):
                    posthoc.checked_paths()

    def test_sparse_interaction_reports_unestimable(self):
        frame = pd.DataFrame({"segment":[posthoc.CONTROL]*5,"stratum":["low"]*5,"spend":[0.,1.,0.,2.,0.]})
        result = posthoc.interaction_test(frame,"stratum",["low","mid","high"])
        self.assertEqual(result["status"],"unestimable")
        self.assertIn("rank deficient",result["reason"])


if __name__ == "__main__":
    unittest.main()
