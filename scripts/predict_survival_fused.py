#!/usr/bin/env python3
"""
Predict 2-year survival (fused model) for a case: load model + PCA + scaler and fused
embeddings CSV, look up case by tcga_id, run PCA -> scale -> MLP, print probability and class.

Use this with the model trained on fused_pathology_rna_embeddings_with_metadata_matched_survival.csv
and the full fused CSV (e.g. fused_pathology_rna_embeddings_with_metadata.csv) for lookup.

Usage:
  python scripts/predict_survival_fused.py \\
    --model-dir models/survival_fused_matched \\
    --fused-csv data/luad/fused_pathology_rna_embeddings_with_metadata.csv \\
    --case-id TCGA-05-4395

  # List cases in fused CSV
  python scripts/predict_survival_fused.py --fused-csv data/luad/fused_pathology_rna_embeddings_with_metadata.csv --list-cases
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np


def _normalize_case_id(s: str) -> str:
    s = (s or "").strip().upper()
    if not s or not s.startswith("TCGA-"):
        return s
    parts = s.split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else s


def load_fused_csv(path: Path, id_col: str = "tcga_id") -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if not rows:
        return {}
    feature_cols = [k for k in fieldnames if (k or "").strip() and k != id_col]
    for row in rows:
        cid = (row.get(id_col) or "").strip()
        if not cid:
            continue
        try:
            vec = [float(row.get(k, 0)) for k in feature_cols]
        except (ValueError, TypeError):
            continue
        out[_normalize_case_id(cid)] = vec
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Predict survival (fused model) for a case.")
    ap.add_argument("--model-dir", type=Path, default=Path("models/survival_fused_matched"))
    ap.add_argument("--fused-csv", type=Path, default=Path("data/luad/fused_pathology_rna_embeddings_with_metadata.csv"))
    ap.add_argument("--case-id", type=str, help="TCGA case id (e.g. TCGA-05-4395).")
    ap.add_argument("--list-cases", action="store_true", help="Print case IDs in fused CSV and exit.")
    args = ap.parse_args()

    if args.list_cases:
        if not args.fused_csv.is_file():
            print(f"Fused CSV not found: {args.fused_csv}", file=sys.stderr)
            return 1
        fused = load_fused_csv(args.fused_csv)
        for cid in sorted(fused.keys()):
            print(cid)
        print(f"Total: {len(fused)} cases", file=sys.stderr)
        return 0

    if not args.case_id:
        print("Provide --case-id or --list-cases.", file=sys.stderr)
        return 1
    if not args.model_dir.is_dir():
        print(f"Model dir not found: {args.model_dir}", file=sys.stderr)
        return 1
    if not args.fused_csv.is_file():
        print(f"Fused CSV not found: {args.fused_csv}", file=sys.stderr)
        return 1

    import pickle
    mlp_path = args.model_dir / "mlp_survival.pkl"
    scaler_path = args.model_dir / "scaler.pkl"
    pca_path = args.model_dir / "pca.pkl"
    if not mlp_path.is_file() or not scaler_path.is_file() or not pca_path.is_file():
        print("Model dir must contain mlp_survival.pkl, scaler.pkl, and pca.pkl.", file=sys.stderr)
        return 1

    with mlp_path.open("rb") as f:
        mlp = pickle.load(f)
    with scaler_path.open("rb") as f:
        scaler = pickle.load(f)
    with pca_path.open("rb") as f:
        pca = pickle.load(f)

    fused = load_fused_csv(args.fused_csv)
    normalized = _normalize_case_id(args.case_id)
    vec = fused.get(normalized)
    if vec is None:
        print(f"Case not found in fused CSV: {args.case_id}", file=sys.stderr)
        return 1

    X = np.array(vec, dtype=np.float32).reshape(1, -1)
    X_pca = pca.transform(X)
    X_scaled = scaler.transform(X_pca)
    proba = mlp.predict_proba(X_scaled)[0]
    prob_survived = float(proba[1]) if len(proba) == 2 else float(proba[0])
    pred_class = int(mlp.predict(X_scaled)[0])
    horizon = 2
    if (args.model_dir / "metrics.json").is_file():
        metrics = json.loads((args.model_dir / "metrics.json").read_text())
        horizon = int(metrics.get("horizon_years", 2))

    print(f"case_id: {args.case_id}")
    print(f"horizon: {horizon}yr")
    print(f"P(survived): {prob_survived:.4f}")
    print(f"predicted_class: {pred_class}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
