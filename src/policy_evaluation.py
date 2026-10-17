"""Stage-4 fixed-policy evaluation on the internal validation partition."""
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
from effect_analysis import bootstrap_mean_differences, holm, spend_compare

INDEX_SHA256 = "eb9dfa4fc8a51fecc801bbfb764c192af95531086431d5349fa80a15c7dc089e"
PLAN_SHA256 = "2b52aee5cc79b4011a1f26b2cfc3ab6997821e3d1e3fa32aedee3983d625284b"
POLICIES = {"P0": "No E-Mail", "P1": "Mens E-Mail", "P2": "Womens E-Mail"}
PAIRS = [("P1", "P0"), ("P2", "P0"), ("P1", "P2")]
MARGINS = [0.20, 0.40, 0.60]
COSTS = [0.05, 0.25, 0.50]
SCALE_CUSTOMERS = 100000


def verify_plan_hash(path):
    """Reject any change to the plan committed before validation evaluation."""
    plan = Path(path)
    if not plan.is_file():
        raise ValueError(f"Frozen policy plan missing: {plan}")
    actual = hashlib.sha256(plan.read_bytes()).hexdigest()
    if actual != PLAN_SHA256:
        raise ValueError(f"Frozen policy plan SHA256 mismatch: expected {PLAN_SHA256}, got {actual}")
    return actual


def validate_inputs():
    source_hash = hashlib.sha256(RAW.read_bytes()).hexdigest()
    if source_hash != SHA256:
        raise ValueError(f"Raw CSV SHA256 mismatch: {source_hash}")
    index_path = ROOT / "data/split_indices.npz"
    index_hash = hashlib.sha256(index_path.read_bytes()).hexdigest()
    if index_hash != INDEX_SHA256:
        raise ValueError(f"Split index SHA256 mismatch: {index_hash}")
    manifest = json.loads((ROOT / "data/split_manifest.json").read_text(encoding="utf-8"))
    if manifest["source_sha256"] != source_hash or manifest["index_file_sha256"] != index_hash:
        raise ValueError("Split manifest hash mismatch")
    frozen = json.loads((ROOT / "docs/candidate_rule.json").read_text(encoding="utf-8"))
    if frozen.get("candidate_rule", "missing") is not None or frozen.get("status") != "no_targeted_candidate":
        raise ValueError("Targeted rule is not frozen null")
    expected = {"all_mens": "Mens E-Mail", "all_womens": "Womens E-Mail", "send_none": "No E-Mail"}
    if {key: frozen["baseline_policies"][key]["action"] for key in expected} != expected:
        raise ValueError("Frozen baselines changed")
    plan = ROOT / "docs/policy_evaluation_plan.md"
    plan_hash = verify_plan_hash(plan)
    return {"raw_sha256": source_hash, "index_sha256": index_hash,
            "plan_sha256": plan_hash, "manifest": manifest}


def load_partition(name, manifest):
    if name not in {"discovery", "validation"}:
        raise ValueError("Unknown partition")
    with np.load(ROOT / "data/split_indices.npz") as index_file:
        indices = index_file[name]
        other = index_file["validation" if name == "discovery" else "discovery"]
    if len(indices) != manifest[f"{name}_n"] or len(np.union1d(indices, other)) != 64000 or np.intersect1d(indices, other).size:
        raise ValueError("Invalid split partition")
    allowed = set(indices.tolist())
    # Only selected rows are parsed; no rule is trained on validation data.
    data = pd.read_csv(RAW, skiprows=lambda csv_line: csv_line > 0 and csv_line-1 not in allowed)
    expected = {group: manifest["group_counts"][group][name] for group in GROUPS}
    if len(data) != len(indices) or data.segment.value_counts().to_dict() != expected:
        raise ValueError("Partition group counts mismatch")
    if data.spend.isna().any() or data.spend.lt(0).any():
        raise ValueError("Invalid spend")
    return data


def policy_summary(data):
    result = {}
    for policy, group in POLICIES.items():
        spend = data.loc[data.segment.eq(group), "spend"].to_numpy(dtype=float)
        n = len(spend)
        mean = float(spend.mean())
        se = float(spend.std(ddof=1) / np.sqrt(n))
        critical = stats.t.ppf(0.975, n-1)
        result[policy] = {"arm": group, "n": n, "mean_spend_usd": mean,
                          "sd_spend_usd": float(spend.std(ddof=1)),
                          "nonzero_spend_n": int(np.count_nonzero(spend)),
                          "mean_ci95_usd": [mean-critical*se, mean+critical*se]}
    return result


def pairwise_spend(data):
    samples = {policy: data.loc[data.segment.eq(group), "spend"].to_numpy(dtype=float)
               for policy, group in POLICIES.items()}
    results = {f"{a} vs {b}": spend_compare(samples[a], samples[b]) for a,b in PAIRS}
    for item, adjusted in zip(results.values(), holm([v["p_raw"] for v in results.values()])):
        item["p_holm"] = adjusted
    return results


def contribution(margin, delta_revenue, cost):
    """Hypothetical per-customer incremental contribution, not actual profit."""
    if not 0 <= margin <= 1 or cost < 0:
        raise ValueError("Invalid hypothetical margin or cost")
    return margin*delta_revenue - cost


def break_even_cost(margin, delta_revenue):
    if not 0 <= margin <= 1:
        raise ValueError("Invalid margin")
    return margin*delta_revenue


def scenarios(comparisons):
    mens = comparisons["P1 vs P0"]
    womens = comparisons["P2 vs P0"]
    between = comparisons["P1 vs P2"]
    thresholds = {}
    equal_cost_difference = {}
    for margin in MARGINS:
        key = f"{margin:.2f}"
        thresholds[key] = {
            policy: {"estimate_usd": break_even_cost(margin, item["difference_usd"]),
                     "ci95_usd": [break_even_cost(margin, endpoint) for endpoint in item["ci95_usd"]]}
            for policy,item in [("P1",mens),("P2",womens)]}
        equal_cost_difference[key] = {"P1_minus_P2_usd": margin*between["difference_usd"],
                                      "ci95_usd": [margin*endpoint for endpoint in between["ci95_usd"]]}
    rows = []
    for margin in MARGINS:
        for cost in COSTS:
            values = {"P0": 0.0,
                      "P1": contribution(margin, mens["difference_usd"], cost),
                      "P2": contribution(margin, womens["difference_usd"], cost)}
            chosen = max(POLICIES, key=lambda policy: values[policy])
            rows.append({"assumed_margin": margin, "assumed_cost_usd": cost,
                         "incremental_contribution_usd_per_customer": values,
                         "point_estimate_choice": chosen,
                         "illustrative_100000_customer_contribution_usd": {p: v*SCALE_CUSTOMERS for p,v in values.items()}})
    return {"parameters_are_hypothetical": True, "margins": MARGINS, "costs_usd": COSTS,
            "break_even_cost_thresholds": thresholds,
            "same_cost_P1_minus_P2_contribution": equal_cost_difference,
            "scenario_rows": rows, "illustrative_customer_count": SCALE_CUSTOMERS}


def evaluate():
    checked = validate_inputs()
    manifest = checked.pop("manifest")
    # Load only after the plan has been frozen and committed.
    validation = load_partition("validation", manifest)
    discovery = load_partition("discovery", manifest)
    summary = {"validation": policy_summary(validation), "discovery": policy_summary(discovery)}
    comparisons = {"validation": pairwise_spend(validation), "discovery": pairwise_spend(discovery)}
    groups = {group: validation.loc[validation.segment.eq(group), "spend"].to_numpy(dtype=float) for group in GROUPS}
    bootstrap = bootstrap_mean_differences(groups, repetitions=2000, seed=20261017)
    for a,b in PAIRS:
        source_key = f"{POLICIES[a]} vs {POLICIES[b]}"
        comparisons["validation"][f"{a} vs {b}"]["bootstrap_ci95_usd"] = bootstrap[source_key]
    return {"checks": checked, "partition_note": "Internal holdout; stage-2 full sample included these rows; no new external experiment",
            "policy_definitions": POLICIES, "summary": summary, "comparisons": comparisons,
            "economic_scenarios": scenarios(comparisons["validation"]),
            "full_row_duplicates_retained": {"validation": int(validation.duplicated().sum()),
                                             "discovery": int(discovery.duplicated().sum())}}


def charts(result):
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    figure_dir = ROOT / "figures"
    fig, ax = plt.subplots(figsize=(8,4))
    for i,key in enumerate(["P1 vs P0", "P2 vs P0", "P1 vs P2"]):
        for label,offset,color in [("discovery",-0.12,"#7f9eae"),("validation",0.12,"#c35e7d")]:
            value = result["comparisons"][label][key]
            center = value["difference_usd"]
            low,high = value["ci95_usd"]
            ax.errorbar(center,i+offset,xerr=[[center-low],[high-center]],fmt="o",capsize=3,color=color,
                        label="探索集" if i==0 and label=="discovery" else ("验证集" if i==0 else None))
    ax.axvline(0,color="#777",lw=1)
    ax.set_yticks(range(3),["男装－不发送","女装－不发送","男装－女装"])
    ax.invert_yaxis()
    ax.set_xlabel("两周人均消费差（美元/客户），Welch 95% CI")
    ax.set_title("固定策略效果：内部子样本稳定性对照")
    ax.legend()
    fig.tight_layout()
    fig.savefig(figure_dir/"policy_stability.png",dpi=180)
    plt.close(fig)
    fig,axes=plt.subplots(1,3,figsize=(11,3.8),sharey=True)
    choice_colors={"P0":"#888888","P1":"#3979a8","P2":"#c35e7d"}
    for ax,margin in zip(axes,MARGINS):
        data=[r for r in result["economic_scenarios"]["scenario_rows"] if r["assumed_margin"]==margin]
        ax.plot(COSTS,[r["incremental_contribution_usd_per_customer"]["P1"] for r in data],"o-",color=choice_colors["P1"],label="全部男装")
        ax.plot(COSTS,[r["incremental_contribution_usd_per_customer"]["P2"] for r in data],"o-",color=choice_colors["P2"],label="全部女装")
        ax.axhline(0,color=choice_colors["P0"],ls="--",label="不发送")
        ax.set_title(f"假设毛利率 {margin:.0%}")
        ax.set_xlabel("假设成本（美元/客户）")
        ax.set_xticks(COSTS)
    axes[0].set_ylabel("假设增量贡献（美元/客户）")
    axes[2].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(figure_dir/"policy_scenarios.png",dpi=180)
    plt.close(fig)


def main():
    result = evaluate()
    output = ROOT / "data/policy_evaluation_results.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n",encoding="utf-8")
    charts(result)
    print(f"Wrote {output}; validation n={sum(x['n'] for x in result['summary']['validation'].values())}")


if __name__ == "__main__":
    main()
