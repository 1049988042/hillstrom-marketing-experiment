"""Deterministic stratified row-position split without reading outcomes."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from audit import RAW

ROOT = Path(__file__).resolve().parents[1]
SHA256 = "0e5893329d8b93cefecc571777672028290ab69865718020c78c7284f291aece"
GROUPS = ["Mens E-Mail", "Womens E-Mail", "No E-Mail"]
SEED = 20261017


def stratified_positions(segment, seed=SEED):
    """Only input is original row-order assignment, never an outcome."""
    segment = np.asarray(segment)
    rng = np.random.default_rng(seed)
    discovery, validation, counts = [], [], {}
    for group in GROUPS:
        positions = np.flatnonzero(segment == group)
        shuffled = rng.permutation(positions)
        n_validation = round(0.30 * len(positions))
        validation.extend(shuffled[:n_validation])
        discovery.extend(shuffled[n_validation:])
        counts[group] = {"discovery": len(positions)-n_validation, "validation": n_validation}
    if len(discovery)+len(validation) != len(segment):
        raise ValueError("Unknown assignment in split input")
    return np.sort(np.asarray(discovery, dtype=np.int32)), np.sort(np.asarray(validation, dtype=np.int32)), counts


def main():
    digest = hashlib.sha256(RAW.read_bytes()).hexdigest()
    if digest != SHA256:
        raise ValueError(f"Raw SHA256 mismatch: {digest}")
    segment = pd.read_csv(RAW, usecols=["segment"])["segment"]
    if len(segment) != 64000 or segment.value_counts().to_dict() != {"Womens E-Mail": 21387, "Mens E-Mail": 21307, "No E-Mail": 21306}:
        raise ValueError("Unexpected rows or group counts")
    discovery, validation, counts = stratified_positions(segment)
    output = ROOT/"data/split_indices.npz"
    np.savez_compressed(output, discovery=discovery, validation=validation)
    manifest = {"source_sha256": digest, "seed": SEED, "stratification": "segment",
                "unit": "zero-based original CSV row position, excluding header", "rule": "round(0.30 * each arm size) validation; remaining discovery",
                "discovery_n": len(discovery), "validation_n": len(validation), "group_counts": counts,
                "index_file_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "validation_outcomes_accessed": False,
                "qualification": "internal holdout after full-sample stage-2 summaries; not external or wholly unseen evidence"}
    (ROOT/"data/split_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"discovery_n": len(discovery), "validation_n": len(validation), "group_counts": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
