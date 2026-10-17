"""Post-reference descriptive decomposition and discovery-only exploration.

The original four stages, holdout, and frozen policies are never rewritten.
"""
import hashlib
import itertools
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from audit import RAW
from create_split import GROUPS, ROOT, SHA256
from effect_analysis import holm, spend_compare
from heterogeneity import hc3_ols, joint_wald

INDEX_SHA256 = "eb9dfa4fc8a51fecc801bbfb764c192af95531086431d5349fa80a15c7dc089e"
HISTORY_LEVELS = ["low:1-2", "middle:3-4", "high:5-7"]
RECENCY_LEVELS = ["1-3", "4-6", "7-9", "10-12"]
FACTORS = ["visit_rate", "conversion_given_visit", "mean_spend_given_conversion"]
CONTROL = "No E-Mail"
ARM_LABELS = {"Mens E-Mail": "男装邮件", "Womens E-Mail": "女装邮件", CONTROL: "无邮件"}
REFERENCE = "https://www.stochasticsolutions.com/pdf/HillstromChallenge.pdf"


def checked_paths():
    raw_hash = hashlib.sha256(RAW.read_bytes()).hexdigest()
    index_path = ROOT / "data/split_indices.npz"
    index_hash = hashlib.sha256(index_path.read_bytes()).hexdigest()
    if raw_hash != SHA256:
        raise ValueError(f"Raw CSV SHA256 mismatch: {raw_hash}")
    if index_hash != INDEX_SHA256:
        raise ValueError(f"Split index SHA256 mismatch: {index_hash}")
    manifest = json.loads((ROOT / "data/split_manifest.json").read_text(encoding="utf-8"))
    if manifest["source_sha256"] != raw_hash or manifest["index_file_sha256"] != index_hash:
        raise ValueError("Frozen split manifest mismatch")
    return {"raw_sha256": raw_hash, "index_sha256": index_hash,
            "posthoc_plan_sha256": hashlib.sha256((ROOT/"docs/posthoc_analysis_plan.md").read_bytes()).hexdigest()}


def load_full_decomposition():
    """Full sample has no baseline features, so it cannot feed subgroup search."""
    data = pd.read_csv(RAW, usecols=["segment", "visit", "conversion", "spend"])
    if len(data) != 64000 or data.segment.value_counts().to_dict() != {
        "Mens E-Mail": 21307, "Womens E-Mail": 21387, "No E-Mail": 21306
    }:
        raise ValueError("Full sample counts changed")
    return data


def load_exploration():
    """Only discovery indices may be selected; validation outcomes are skipped."""
    with np.load(ROOT / "data/split_indices.npz") as indices:
        selected = indices["discovery"]
        other = indices["validation"]
    if (len(selected) != 44800 or len(other) != 19200
            or np.intersect1d(selected, other).size
            or not np.array_equal(np.union1d(selected, other), np.arange(64000))):
        raise ValueError("Frozen discovery partition invalid")
    allowed = set(selected.tolist())
    data = pd.read_csv(RAW, usecols=["segment", "history", "history_segment", "recency", "spend"],
                       skiprows=lambda line: line > 0 and line-1 not in allowed)
    if len(data) != 44800 or data.segment.value_counts().to_dict() != {
        "Mens E-Mail": 14915, "Womens E-Mail": 14971, "No E-Mail": 14914
    }:
        raise ValueError("Discovery sample counts changed")
    return data


def decomposition(data):
    if data[["segment", "visit", "conversion", "spend"]].isna().any().any():
        raise ValueError("Missing decomposition values")
    if not data[["visit", "conversion"]].isin([0, 1]).all().all() or not data.segment.isin(GROUPS).all():
        raise ValueError("Invalid binary outcome or assignment")
    checks = {
        "conversion_without_visit": int((data.conversion.eq(1) & data.visit.eq(0)).sum()),
        "positive_spend_without_conversion": int((data.spend.gt(0) & data.conversion.eq(0)).sum()),
        "conversion_without_positive_spend": int((data.conversion.eq(1) & data.spend.le(0)).sum()),
        "negative_or_nonfinite_spend": int((data.spend.lt(0) | ~np.isfinite(data.spend)).sum()),
    }
    if any(checks.values()):
        raise ValueError(f"Consumption identity assumptions violated: {checks}")
    rows = {}
    for group in GROUPS:
        arm = data[data.segment.eq(group)]
        visits, conversions = int(arm.visit.sum()), int(arm.conversion.sum())
        if len(arm) == 0 or visits == 0 or conversions == 0:
            raise ValueError(f"Conditional metric undefined for {group}")
        visit_rate = visits / len(arm)
        conditional_conversion = conversions / visits
        conditional_spend = float(arm.loc[arm.conversion.eq(1), "spend"].mean())
        mean = float(arm.spend.mean())
        product = visit_rate * conditional_conversion * conditional_spend
        if not np.isclose(product, mean, rtol=1e-12, atol=1e-12):
            raise ValueError(f"Identity does not hold for {group}")
        rows[group] = {"n": len(arm), "visits_n": visits, "conversions_n": conversions,
                       "visit_rate": visit_rate, "conversion_given_visit": conditional_conversion,
                       "mean_spend_given_conversion": conditional_spend,
                       "conversion_rate": conversions / len(arm), "mean_spend": mean,
                       "factor_product": product, "identity_residual": mean-product}
    return {"logic_checks": checks, "arms": rows}


def shapley_product(base, treated):
    """Symmetric accounting attribution over every factor replacement order."""
    base, treated = np.asarray(base, dtype=float), np.asarray(treated, dtype=float)
    if base.shape != (3,) or treated.shape != (3,) or not np.isfinite([base, treated]).all():
        raise ValueError("Expected three finite factors")
    contributions = np.zeros(3)
    for ordering in itertools.permutations(range(3)):
        current = base.copy()
        for index in ordering:
            before = float(np.prod(current))
            current[index] = treated[index]
            contributions[index] += (float(np.prod(current))-before)/6
    total = float(np.prod(treated)-np.prod(base))
    if not np.isclose(contributions.sum(), total, atol=1e-12, rtol=1e-12):
        raise ValueError("Shapley contributions do not sum to total")
    return {"contributions_usd": dict(zip(FACTORS, contributions.tolist())),
            "total_difference_usd": total, "sum_residual": float(total-contributions.sum())}


def add_strata(data):
    result = data.copy()
    bands = result.history_segment.str.extract(r"^([1-7])\)", expand=False)
    if bands.isna().any() or not result.recency.between(1, 12).all():
        raise ValueError("Unknown history band or recency")
    band = bands.astype(int)
    result["history_band"] = band
    result["history_group"] = band.map({1:HISTORY_LEVELS[0], 2:HISTORY_LEVELS[0],
                                        3:HISTORY_LEVELS[1], 4:HISTORY_LEVELS[1],
                                        5:HISTORY_LEVELS[2], 6:HISTORY_LEVELS[2], 7:HISTORY_LEVELS[2]})
    result["recency_group"] = pd.cut(result.recency, bins=[0,3,6,9,12], labels=RECENCY_LEVELS).astype(str)
    return result


def stratified_summary(data, feature, levels):
    rows = []
    for level in levels:
        subset = data.loc[data[feature].eq(level)]
        arms = {g: subset.loc[subset.segment.eq(g), "spend"] for g in GROUPS}
        summaries = {g: {"n": len(v), "nonzero_spend_n": int(v.gt(0).sum()),
                         "mean_spend_usd": float(v.mean()) if len(v) else None} for g,v in arms.items()}
        effects = {}
        for arm in GROUPS[:2]:
            if min(len(arms[arm]), len(arms[CONTROL])) < 2 or min(arms[arm].var(), arms[CONTROL].var()) <= 0:
                effects[arm] = {"status": "insufficient sample or zero variance"}
                continue
            value = spend_compare(arms[arm], arms[CONTROL])
            effects[arm] = {"difference_usd": value["difference_usd"], "ci95_usd": value["ci95_usd"],
                            "status": "post-hoc descriptive; ordinary unadjusted CI"}
        rows.append({"level": str(level), "arms": summaries, "effects_vs_control": effects})
    return rows


def interaction_test(data, feature, levels):
    """Separate saturated treatment x stratum model; no additional covariates."""
    if not data[feature].isin(levels).all() or not data.segment.isin(GROUPS).all():
        raise ValueError("Unknown model level")
    columns = {"intercept": np.ones(len(data))}
    for arm in GROUPS[:2]:
        columns[f"arm:{arm}"] = data.segment.eq(arm).to_numpy(dtype=float)
    interactions = []
    for level in levels[1:]:
        indicator = data[feature].eq(level).to_numpy(dtype=float)
        columns[f"stratum:{level}"] = indicator
        for arm in GROUPS[:2]:
            name = f"interaction:{arm}*{level}"
            columns[name] = columns[f"arm:{arm}"] * indicator
            interactions.append(name)
    matrix = pd.DataFrame(columns)
    try:
        beta, cov = hc3_ols(data.spend, matrix)
        positions = [matrix.columns.get_loc(c) for c in interactions]
        test = joint_wald(beta, cov, positions)
        test.update({"status": "ok", "n": len(data), "reference_level": str(levels[0]),
                     "coefficients": {c: float(beta[i]) for c,i in zip(interactions, positions)},
                     "model_columns": list(matrix.columns)})
        return test
    except ValueError as error:
        return {"status": "unestimable", "reason": str(error), "n": len(data)}


def exploratory_analysis(data):
    """This API receives only the discovery frame from load_exploration()."""
    data = add_strata(data)
    if data.spend.isna().any() or not np.isfinite(data.spend).all() or data.spend.lt(0).any():
        raise ValueError("Invalid discovery spend")
    tests = {"history_group": interaction_test(data, "history_group", HISTORY_LEVELS),
             "recency_group": interaction_test(data, "recency_group", RECENCY_LEVELS)}
    # Keep both planned tests in the multiplicity family if one is unestimable.
    adjusted = holm([v["p_raw"] if v["status"] == "ok" else 1.0 for v in tests.values()])
    for test, p in zip(tests.values(), adjusted):
        test["p_holm"] = p if test["status"] == "ok" else None
    return {"scope": "post-reference post-hoc; discovery only; not independently validated",
            "n": len(data), "group_counts": data.segment.value_counts().to_dict(),
            "history_seven_bands": stratified_summary(data, "history_band", list(range(1,8))),
            "history_three_groups": stratified_summary(data, "history_group", HISTORY_LEVELS),
            "recency_four_groups": stratified_summary(data, "recency_group", RECENCY_LEVELS),
            "interaction_tests": tests,
            "method": "two separate treatment x categorical-stratum OLS models, HC3, joint chi-square Wald, Holm family of 2"}


def run():
    checked = checked_paths()
    full = decomposition(load_full_decomposition())
    base = [full["arms"][CONTROL][f] for f in FACTORS]
    attribution = {arm: shapley_product(base, [full["arms"][arm][f] for f in FACTORS]) for arm in GROUPS[:2]}
    # Explicitly pass only this separate loader's discovery data to new features.
    exploration = exploratory_analysis(load_exploration())
    return {"reference_url": REFERENCE, "classification": "supplement after reading historical winning paper",
            "checks": checked, "full_sample_decomposition": full, "shapley_decomposition": attribution,
            "exploration": exploration,
            "scope_note": "Full sample only for aggregate accounting decomposition; new subgroup analysis uses discovery rows only; no policy search or new validation evaluation"}


def charts(result):
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    labels = ["访问率", "访问后购买率", "购买者平均消费"]
    colors = ["#3979a8", "#e4a23a", "#65a084"]
    fig, ax = plt.subplots(figsize=(8.5,4.5))
    for i,arm in enumerate(GROUPS[:2]):
        positive, negative = 0.0, 0.0
        value = result["shapley_decomposition"][arm]
        for k,(factor,label,color) in enumerate(zip(FACTORS,labels,colors)):
            amount = value["contributions_usd"][factor]
            left = positive if amount >= 0 else negative
            ax.barh(i,amount,left=left,color=color,label=label if i==0 else None)
            if amount >= 0: positive += amount
            else: negative += amount
        ax.text(positive+0.015,i,f"总差 +${value['total_difference_usd']:.4f}",va="center",fontsize=10)
    ax.set_yticks([0,1],["男装－无邮件","女装－无邮件"])
    ax.invert_yaxis()
    ax.axvline(0,color="#777",lw=1)
    ax.set_xlim(-0.04,1.02)
    ax.set_xlabel("人均消费差的 Shapley 会计贡献（美元/客户）")
    ax.set_title("全样本消费增长结构：描述性分解，不是因果中介效应")
    ax.legend(loc="lower right",fontsize=9)
    fig.tight_layout()
    fig.savefig(ROOT/"figures/spend_decomposition.png",dpi=180)
    plt.close(fig)

    for key,output,title in [("history_seven_bands","history_effects.png","历史消费原始七档（仅探索集）"),
                              ("recency_four_groups","recency_effects.png","距上次购买月数（仅探索集）")]:
        rows = result["exploration"][key]
        fig,ax = plt.subplots(figsize=(9,5))
        for arm,offset,color in [(GROUPS[0],-0.10,"#3979a8"),(GROUPS[1],0.10,"#c35e7d")]:
            for i,row in enumerate(rows):
                effect = row["effects_vs_control"][arm]
                if "difference_usd" not in effect: continue
                center = effect["difference_usd"]
                low,high = effect["ci95_usd"]
                ax.errorbar(center,i+offset,xerr=[[center-low],[high-center]],fmt="o",capsize=3,color=color,
                            label=ARM_LABELS[arm] if i==0 else None)
        tick_labels = ["$0–100", "$100–200", "$200–350", "$350–500", "$500–750", "$750–1,000", "$1,000+"] if key=="history_seven_bands" else [f"{r['level']} 月" for r in rows]
        ax.set_yticks(range(len(rows)),tick_labels)
        ax.invert_yaxis()
        ax.axvline(0,color="#777",lw=1)
        ax.set_title(f"事后探索：{title}")
        ax.set_xlabel("相对无邮件的人均消费差（美元/客户），普通 Welch 95% CI")
        ax.legend()
        fig.tight_layout()
        fig.savefig(ROOT/"figures"/output,dpi=180)
        plt.close(fig)


def main():
    result = run()
    output = ROOT/"data/posthoc_results.json"
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    charts(result)
    print(f"Wrote {output}; decomposition n=64000, exploratory strata n=44800; no rule search")


if __name__ == "__main__":
    main()
