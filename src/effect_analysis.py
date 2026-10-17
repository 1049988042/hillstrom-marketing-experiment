"""Prespecified, intention-to-treat analysis of the public Hillstrom file."""
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from audit import RAW, EXPECTED

ROOT = Path(__file__).resolve().parents[1]
SHA256 = "0e5893329d8b93cefecc571777672028290ab69865718020c78c7284f291aece"
GROUPS = ["Mens E-Mail", "Womens E-Mail", "No E-Mail"]
PAIRS = [(GROUPS[0], GROUPS[2]), (GROUPS[1], GROUPS[2]), (GROUPS[0], GROUPS[1])]
PRE_NUMERIC = ["recency", "history", "mens", "womens", "newbie"]
PRE_CATEGORICAL = ["channel", "zip_code"]
LABELS = {GROUPS[0]: "男装邮件", GROUPS[1]: "女装邮件", GROUPS[2]: "无邮件"}


def holm(pvalues):
    """Holm adjusted p values in original order."""
    p = np.asarray(pvalues, dtype=float)
    order = np.argsort(p)
    adjusted = np.empty(len(p))
    previous = 0.0
    for rank, index in enumerate(order):
        previous = max(previous, min(1.0, (len(p) - rank) * p[index]))
        adjusted[index] = previous
    return adjusted.tolist()


def validate(df, path=RAW):
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if digest != SHA256:
        raise ValueError(f"Raw SHA256 mismatch: {digest}")
    if df.shape != (64000, 12) or list(df.columns) != EXPECTED:
        raise ValueError("Unexpected raw shape or schema")
    counts = df.segment.value_counts().to_dict()
    if counts != {"Womens E-Mail": 21387, "Mens E-Mail": 21307, "No E-Mail": 21306}:
        raise ValueError(f"Unexpected assignment counts: {counts}")
    if df.isna().any().any() or not df.segment.isin(GROUPS).all():
        raise ValueError("Missing or unknown assignments/values")
    if not df[["mens", "womens", "newbie", "visit", "conversion"]].isin([0, 1]).all().all():
        raise ValueError("Nonbinary indicator")
    if (df.spend < 0).any() or (df.history < 0).any():
        raise ValueError("Negative monetary amount")


def smd(x, y):
    pooled = np.sqrt((np.var(x, ddof=1) + np.var(y, ddof=1)) / 2)
    difference = float(np.mean(x) - np.mean(y))
    return difference / pooled if pooled else (0.0 if difference == 0 else float("inf"))


def spend_compare(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    nx, ny = len(x), len(y)
    diff = float(x.mean() - y.mean())
    vx, vy = x.var(ddof=1), y.var(ddof=1)
    se = np.sqrt(vx/nx + vy/ny)
    df = (vx/nx + vy/ny)**2 / ((vx/nx)**2/(nx-1) + (vy/ny)**2/(ny-1))
    t = diff/se
    critical = stats.t.ppf(0.975, df)
    return {"difference_usd": diff, "relative_lift_percent": float(100*diff/y.mean()) if y.mean() else None,
            "ci95_usd": [float(diff-critical*se), float(diff+critical*se)],
            "statistic": float(t), "degrees_of_freedom": float(df),
            "p_raw": float(2*stats.t.sf(abs(t), df))}


def proportion_compare(x, y):
    """Pooled two-sided z test; unpooled Wald 95% CI for absolute difference."""
    x, y = np.asarray(x), np.asarray(y)
    p1, p0 = x.mean(), y.mean()
    diff = float(p1-p0)
    pooled = (x.sum()+y.sum())/(len(x)+len(y))
    se_test = np.sqrt(pooled*(1-pooled)*(1/len(x)+1/len(y)))
    se_ci = np.sqrt(p1*(1-p1)/len(x)+p0*(1-p0)/len(y))
    z = diff/se_test
    return {"difference_pp": 100*diff, "relative_lift_percent": float(100*diff/p0) if p0 else None,
            "ci95_pp": [float(100*(diff-1.959963984540054*se_ci)), float(100*(diff+1.959963984540054*se_ci))],
            "statistic": float(z), "p_raw": float(2*stats.norm.sf(abs(z)))}


def bootstrap_mean_differences(arrays, repetitions=2000, seed=20261017):
    """Independent within-arm resampling; shared arm draws preserve pair covariance."""
    rng = np.random.default_rng(seed)
    means = {}
    for group in GROUPS:
        values = np.asarray(arrays[group], dtype=float)
        out = np.empty(repetitions)
        for start in range(0, repetitions, 50):
            stop = min(start+50, repetitions)
            index = rng.integers(0, len(values), size=(stop-start, len(values)))
            out[start:stop] = values[index].mean(axis=1)
        means[group] = out
    return {f"{a} vs {b}": [float(v) for v in np.quantile(means[a]-means[b], [0.025, 0.975])]
            for a, b in PAIRS}


def group_summary(a):
    return {"n": len(a), "visit_rate": float(a.visit.mean()), "conversion_rate": float(a.conversion.mean()),
            "mean_spend_usd": float(a.spend.mean()), "spend_sd_usd": float(a.spend.std(ddof=1)),
            "nonzero_spend_n": int(a.spend.gt(0).sum())}


def run(df):
    validate(df)
    arrays = {g: df[df.segment.eq(g)] for g in GROUPS}
    counts = np.array([len(arrays[g]) for g in GROUPS])
    srm_stat, srm_p = stats.chisquare(counts, f_exp=np.full(3, len(df)/3))
    summary = {g: group_summary(a) for g, a in arrays.items()}
    balance = []
    for feature in PRE_NUMERIC:
        values = {g: float(arrays[g][feature].mean()) for g in GROUPS}
        values["max_abs_pairwise_smd"] = max(abs(smd(arrays[a][feature], arrays[b][feature])) for a,b in PAIRS)
        values["pairwise_smd"] = {f"{a} vs {b}": float(smd(arrays[a][feature], arrays[b][feature])) for a,b in PAIRS}
        balance.append({"feature": feature, "type": "numeric_or_binary", **values})
    for feature in PRE_CATEGORICAL:
        for level in sorted(df[feature].unique()):
            values = {g: float(arrays[g][feature].eq(level).mean()) for g in GROUPS}
            proportions = {g: arrays[g][feature].eq(level).astype(int) for g in GROUPS}
            values["max_abs_pairwise_smd"] = max(abs(smd(proportions[a], proportions[b])) for a,b in PAIRS)
            values["max_abs_pairwise_difference_pp"] = max(abs(100*(values[a]-values[b])) for a,b in PAIRS)
            balance.append({"feature": feature, "level": str(level), "type": "category_level", **values})
    spending = {f"{a} vs {b}": spend_compare(arrays[a].spend, arrays[b].spend) for a,b in PAIRS}
    for item, padj in zip(spending.values(), holm([v["p_raw"] for v in spending.values()])):
        item["p_holm"] = padj
    boot = bootstrap_mean_differences({g: arrays[g].spend.to_numpy() for g in GROUPS})
    for key, interval in boot.items():
        spending[key]["bootstrap_ci95_usd"] = interval
    secondary = {metric: {f"{a} vs {b}": proportion_compare(arrays[a][metric], arrays[b][metric]) for a,b in PAIRS}
                 for metric in ["visit", "conversion"]}
    items = [secondary[metric][f"{a} vs {b}"] for metric in ["visit", "conversion"] for a,b in PAIRS]
    for item, padj in zip(items, holm([v["p_raw"] for v in items])):
        item["p_holm"] = padj
    return {"analysis_plan": {"alpha": 0.05, "spend_test": "two-sided Welch", "spend_ci": "Welch t 95%",
              "bootstrap": "2000 independent within-arm resamples, seed 20261017, percentile 95% CI",
              "binary_test": "pooled two-sided z", "binary_ci": "unpooled Wald 95%",
              "multiplicity": "Holm separately for 3 spend and 6 secondary comparisons"},
            "srm": {"expected_ratio": "1:1:1", "counts": counts.tolist(), "chi2": float(srm_stat), "degrees_of_freedom": 2, "p": float(srm_p)},
            "summary": summary, "balance": balance, "spend_comparisons": spending, "secondary_comparisons": secondary,
            "raw_sha256": SHA256, "full_row_duplicates_retained": int(df.duplicated().sum())}


def charts(result, output):
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    groups = GROUPS
    x = np.arange(3)
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8))
    for ax, metric, title, multiplier in zip(axes, ["visit_rate", "conversion_rate", "mean_spend_usd"],
                                             ["网站访问率", "购买转化率", "两周人均消费"], [100,100,1]):
        values = [result["summary"][g][metric]*multiplier for g in groups]
        ax.bar(x, values, color=["#3979a8", "#c35e7d", "#858585"])
        ax.set_xticks(x, [LABELS[g] for g in groups], rotation=12)
        ax.set_title(title)
        ax.set_ylabel("%" if multiplier == 100 else "美元/客户")
        ax.set_ylim(0, max(values)*1.2)
        for i,v in enumerate(values): ax.text(i,v,f"{v:.2f}",ha="center",va="bottom",fontsize=9)
    fig.tight_layout()
    fig.savefig(output/"group_metrics.png", dpi=180)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    labels = ["男装-无邮件", "女装-无邮件", "男装-女装"]
    for i, (key, value) in enumerate(result["spend_comparisons"].items()):
        lo, hi = value["ci95_usd"]
        effect = value["difference_usd"]
        ax.errorbar(effect, i, xerr=[[effect-lo],[hi-effect]], fmt="o", color="#3979a8", capsize=4)
    ax.axvline(0, color="#666", lw=1)
    ax.set_yticks(range(3), labels)
    ax.invert_yaxis()
    ax.set_xlabel("人均消费差（美元/客户），Welch 95% CI")
    ax.set_title("预先指定的三项消费比较")
    fig.tight_layout()
    fig.savefig(output/"spend_effects.png", dpi=180)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7.5, 4))
    rows = result["balance"]
    ax.barh(np.arange(len(rows)), [r["max_abs_pairwise_smd"] for r in rows], color="#6b90a8")
    ax.set_yticks(np.arange(len(rows)), [r["feature"] + (": "+r["level"] if "level" in r else "") for r in rows], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("三组两两比较的最大 |SMD|")
    ax.set_title("实验前特征平衡（描述性）")
    fig.tight_layout()
    fig.savefig(output/"baseline_balance.png", dpi=180)
    plt.close(fig)


def main():
    df = pd.read_csv(RAW)
    result = run(df)
    destination = ROOT/"data/effect_results.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    charts(result, ROOT/"figures")
    print(f"Wrote {destination} and 3 charts")


if __name__ == "__main__":
    main()
