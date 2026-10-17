"""Read the untouched Hillstrom CSV and write a descriptive audit JSON."""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/Kevin_Hillstrom_MineThatData_E-MailAnalytics_DataMiningChallenge_2008.03.20.csv"
EXPECTED = ["recency", "history_segment", "history", "mens", "womens", "zip_code", "newbie", "channel", "segment", "visit", "conversion", "spend"]
GROUPS = {"Mens E-Mail", "Womens E-Mail", "No E-Mail"}


def audit(path: Path) -> dict:
    raw = path.read_bytes()
    df = pd.read_csv(path)
    if list(df.columns) != EXPECTED:
        raise ValueError(f"Unexpected columns: {list(df.columns)}")
    result = {
        "source_file": path.name,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "rows": len(df), "columns": len(df.columns),
        "dtypes": {c: str(df[c].dtype) for c in df},
        "missing": {c: int(df[c].isna().sum()) for c in df},
        "full_row_duplicates": int(df.duplicated().sum()),
        "groups": {str(k): {"count": int(v), "percent": round(100*v/len(df), 4)} for k, v in df.segment.value_counts().items()},
        "values": {c: {str(k): int(v) for k, v in df[c].value_counts(dropna=False).items()} for c in ["history_segment", "zip_code", "channel", "segment"]},
        "numeric_ranges": {c: {"min": float(df[c].min()), "max": float(df[c].max()), "unique": int(df[c].nunique())} for c in df.select_dtypes(include="number")},
    }
    expected_segments = [
        ("1) $0 - $100", lambda s: s < 100),
        ("2) $100 - $200", lambda s: (s >= 100) & (s < 200)),
        ("3) $200 - $350", lambda s: (s >= 200) & (s < 350)),
        ("4) $350 - $500", lambda s: (s >= 350) & (s < 500)),
        ("5) $500 - $750", lambda s: (s >= 500) & (s < 750)),
        ("6) $750 - $1,000", lambda s: (s >= 750) & (s < 1000)),
        ("7) $1,000 +", lambda s: s >= 1000),
    ]
    valid_band = pd.Series(False, index=df.index)
    for label, rule in expected_segments:
        valid_band |= df.history_segment.eq(label) & rule(df.history)
    checks = {
        "invalid_group": ~df.segment.isin(GROUPS),
        "invalid_recency": ~df.recency.between(1, 12),
        "negative_history": df.history.lt(0),
        "invalid_binary": ~df[["mens", "womens", "newbie", "visit", "conversion"]].isin([0, 1]).all(axis=1),
        "history_segment_mismatch": ~valid_band,
        "negative_spend": df.spend.lt(0),
        "conversion_without_visit": df.conversion.eq(1) & df.visit.eq(0),
        "positive_spend_without_conversion": df.spend.gt(0) & df.conversion.eq(0),
        "conversion_without_positive_spend": df.conversion.eq(1) & df.spend.le(0),
        "positive_spend_without_visit": df.spend.gt(0) & df.visit.eq(0),
    }
    result["checks"] = {k: int(v.sum()) for k, v in checks.items()}
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=RAW)
    parser.add_argument("--output", type=Path, default=ROOT / "data/audit_summary.json")
    args = parser.parse_args()
    result = audit(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Audited {result['rows']} rows, {result['columns']} columns; wrote {args.output}")


if __name__ == "__main__":
    main()
