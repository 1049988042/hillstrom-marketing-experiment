"""Stage-3 discovery-only heterogeneity analysis; never loads holdout outcomes."""
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from audit import RAW
from create_split import GROUPS, ROOT, SHA256
from effect_analysis import holm, spend_compare

FEATURES = ["mens", "womens", "newbie", "channel"]
TREATMENTS = GROUPS[:2]
CONTROL = GROUPS[2]
LABELS = {"Mens E-Mail": "男装邮件", "Womens E-Mail": "女装邮件", "No E-Mail": "无邮件"}
LEVELS = {"mens": [0, 1], "womens": [0, 1], "newbie": [0, 1],
          "channel": ["Phone", "Multichannel", "Web"]}


def discovery_frame():
    if hashlib.sha256(RAW.read_bytes()).hexdigest() != SHA256:
        raise ValueError("Raw file SHA256 mismatch")
    manifest = json.loads((ROOT/"data/split_manifest.json").read_text(encoding="utf-8"))
    index_path = ROOT/"data/split_indices.npz"
    if hashlib.sha256(index_path.read_bytes()).hexdigest() != manifest["index_file_sha256"]:
        raise ValueError("Split index SHA256 mismatch")
    with np.load(index_path) as indices:
        discovery = indices["discovery"]
        validation = indices["validation"]
    if len(discovery) != 44800 or len(validation) != 19200 or len(np.union1d(discovery, validation)) != 64000:
        raise ValueError("Split partition invalid")
    if np.intersect1d(discovery, validation).size:
        raise ValueError("Overlapping split indices")
    allowed = set(discovery.tolist())
    # skiprows prevents pandas from parsing validation rows, including outcomes.
    df = pd.read_csv(RAW, skiprows=lambda csv_line: csv_line > 0 and csv_line-1 not in allowed)
    if len(df) != 44800 or df.segment.value_counts().to_dict() != {g: manifest["group_counts"][g]["discovery"] for g in GROUPS}:
        raise ValueError("Discovery group counts mismatch")
    return df


def design_matrix(df):
    """One joint model: all four baseline features and all arm interactions."""
    columns = {"intercept": np.ones(len(df))}
    for arm in TREATMENTS:
        columns[f"arm:{arm}"] = df.segment.eq(arm).to_numpy(dtype=float)
    blocks = {}
    for feature in FEATURES:
        blocks[feature] = []
        nonreference = LEVELS[feature][1:]
        for level in nonreference:
            flag = df[feature].eq(level).to_numpy(dtype=float)
            columns[f"base:{feature}={level}"] = flag
            for arm in TREATMENTS:
                name = f"interaction:{arm}*{feature}={level}"
                columns[name] = columns[f"arm:{arm}"] * flag
                blocks[feature].append(name)
    frame = pd.DataFrame(columns)
    return frame, blocks


def hc3_ols(y, x):
    """OLS with HC3 sandwich covariance and conservative rank checks."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    n, p = x.shape
    if n <= p or np.linalg.matrix_rank(x) != p:
        raise ValueError("Model is sparse or rank deficient")
    xtx_inv = np.linalg.inv(x.T @ x)
    beta = xtx_inv @ x.T @ y
    residual = y - x @ beta
    leverage = np.einsum("ij,jk,ik->i", x, xtx_inv, x)
    if not np.isfinite(leverage).all() or np.any(leverage >= 1-1e-10):
        raise ValueError("HC3 leverage invalid")
    weighted = x * (residual/(1-leverage))[:, None]
    covariance = xtx_inv @ (weighted.T @ weighted) @ xtx_inv
    if not np.isfinite(covariance).all():
        raise ValueError("HC3 covariance invalid")
    return beta, covariance


def joint_wald(beta, covariance, positions):
    """Asymptotic robust chi-square Wald test for a coefficient block."""
    b = np.asarray(beta)[positions]
    v = np.asarray(covariance)[np.ix_(positions, positions)]
    if np.linalg.matrix_rank(v) != len(positions):
        raise ValueError("Interaction covariance singular")
    stat = float(b @ np.linalg.solve(v, b))
    return {"statistic_chi2": stat, "df": len(positions), "p_raw": float(stats.chi2.sf(stat, len(positions)))}


def model_results(df, outcome="spend"):
    x, blocks = design_matrix(df)
    beta, covariance = hc3_ols(df[outcome], x)
    tests = {}
    for feature, names in blocks.items():
        indices = [x.columns.get_loc(name) for name in names]
        try:
            test = joint_wald(beta, covariance, indices)
            test["status"] = "ok"
            test["coefficients"] = {name: {"estimate_usd": float(beta[i]),
                                             "ci95_usd": [float(beta[i]-1.959963984540054*np.sqrt(covariance[i,i])),
                                                         float(beta[i]+1.959963984540054*np.sqrt(covariance[i,i]))]}
                                    for name,i in zip(names,indices)}
        except ValueError as error:
            test = {"status": "unestimable", "reason": str(error)}
        tests[feature] = test
    valid = [name for name in FEATURES if tests[name]["status"] == "ok"]
    for name, adjusted in zip(valid, holm([tests[name]["p_raw"] for name in valid])):
        tests[name]["p_holm"] = adjusted
    return {"n": len(df), "columns": list(x.columns), "features": tests,
            "method": "one joint OLS model, HC3 covariance, asymptotic Wald chi-square, Holm across four feature blocks"}


def subgroup_results(df):
    result = []
    for feature in FEATURES:
        for level in LEVELS[feature]:
            subset = df[df[feature].eq(level)]
            arms = {g: subset[subset.segment.eq(g)] for g in GROUPS}
            row = {"feature": feature, "level": str(level),
                   "arms": {g: {"n": len(a), "nonzero_spend_n": int(a.spend.gt(0).sum()),
                                "mean_spend_usd": float(a.spend.mean())} for g,a in arms.items()},
                   "effects_vs_control": {}}
            for treatment in TREATMENTS:
                if len(arms[treatment]) < 2 or len(arms[CONTROL]) < 2:
                    row["effects_vs_control"][treatment] = {"status": "insufficient sample"}
                else:
                    estimate = spend_compare(arms[treatment].spend, arms[CONTROL].spend)
                    row["effects_vs_control"][treatment] = {"difference_usd": estimate["difference_usd"],
                        "ci95_usd": estimate["ci95_usd"], "status": "descriptive, unadjusted"}
            result.append(row)
    return result


def run():
    df = discovery_frame()
    model = model_results(df)
    subgroups = subgroup_results(df)
    cap = float(df.spend.quantile(0.995))
    top = float(df.spend.max())
    winsor = df.copy()
    winsor["spend"] = winsor.spend.clip(upper=cap)
    sensitivity_model = model_results(winsor)
    return {"scope": "discovery only; validation rows skipped at CSV read; no holdout outcomes calculated",
            "discovery_n": len(df), "discovery_group_counts": df.segment.value_counts().to_dict(),
            "full_row_duplicates_retained_in_discovery": int(df.duplicated().sum()),
            "subgroups": subgroups, "interaction_model": model,
            "tail_sensitivity": {"method": "exploratory 99.5th percentile winsorization on discovery spend; not a replacement ATE",
                                 "p995_usd": cap, "maximum_usd": top,
                                 "capped_observations": int(df.spend.gt(cap).sum()),
                                 "winsorized_interaction_model": sensitivity_model}}


def chart(result):
    rows = result["subgroups"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 6.4), sharey=True)
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    names = {"mens": "历史男装", "womens": "历史女装", "newbie": "新客户", "channel": "渠道"}
    labels = [f"{names[r['feature']]}={r['level']}" for r in rows]
    for ax, arm, title in zip(axes, TREATMENTS, ["男装邮件－无邮件", "女装邮件－无邮件"]):
        for i,r in enumerate(rows):
            value = r["effects_vs_control"][arm]
            if value["status"] != "descriptive, unadjusted": continue
            center = value["difference_usd"]
            low, high = value["ci95_usd"]
            ax.errorbar(center, i, xerr=[[center-low],[high-center]], fmt="o", capsize=3, color="#3979a8" if arm==TREATMENTS[0] else "#c35e7d")
        ax.axvline(0, color="#777", lw=1)
        ax.set_yticks(range(len(rows)), labels)
        ax.invert_yaxis()
        ax.set_title(title)
        ax.set_xlabel("探索集人均增量消费（美元/客户），95% CI")
    fig.tight_layout()
    output = ROOT/"figures/heterogeneity_discovery.png"
    fig.savefig(output, dpi=180)
    plt.close(fig)
    return output


def main():
    result = run()
    output = ROOT/"data/heterogeneity_results.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    figure = chart(result)
    print(f"Wrote {output} and {figure}; discovery n={result['discovery_n']}")


if __name__ == "__main__":
    main()
