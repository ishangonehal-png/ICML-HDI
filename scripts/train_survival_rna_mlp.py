#!/usr/bin/env python3
"""
Train an MLP for survival (binary outcome) from pathology + RNA embeddings + patient metadata. All three inputs are required.

Concatenates (all required):
  - Pathology: per-slide .npy in --pathology-embeddings-dir, mean-pooled to slide-level; OR --pathology-embeddings-csv (tcga_id first column, same layout as RNA)
  - RNA embeddings (e.g. BulkFormer CSV)
  - Patient metadata from cohort CSV, one-hot encoded

Uses survival labels from build_outcome_labels_table.py (survived_1yr, 2yr, 5yr).
Saves sklearn MLPClassifier and metrics.

Usage:
  # 1) Build outcome labels (if you don't have them)
  python scripts/build_outcome_labels_table.py \\
    --cohort-csv data/luad/tcga_matched_cohort.csv \\
    --clinical-xml-dir /path/to/clinical/xml \\
    --out data/luad/survival_labels.csv

  # Or with pathology from directory (mean-pool at load time):
  python scripts/train_survival_rna_mlp.py \\
    --pathology-embeddings-dir yc-overlap-embeddings-129-2026-03-08/embeddings_level0 \\
    --rna-embeddings-csv data/luad/bulkformer_sample_embeddings.csv \\
    --cohort-csv data/luad/tcga_matched_cohort.csv \\
    --labels-csv data/luad/survival_labels.csv \\
  --out-dir models/survival_rna_mlp \\
  [--horizon 2]

Model artifacts are written to --out-dir (default: models/survival_rna_mlp):
  - mlp_survival.pkl   (sklearn MLPClassifier)
  - scaler.pkl         (StandardScaler)
  - encoder_state.json (one-hot categories for metadata)
  - feature_names.json
  - metrics.json

To use this model in the API, set:
  SURVIVAL_MLP_MODEL_DIR=models/survival_rna_mlp
  SURVIVAL_MLP_PATHOLOGY_EMBEDDINGS_DIR=yc-overlap-embeddings-129-2026-03-08/embeddings_level0   (required)
  SURVIVAL_MLP_EMBEDDINGS_CSV=data/luad/bulkformer_sample_embeddings.csv
  SURVIVAL_MLP_COHORT_CSV=data/luad/tcga_matched_cohort.csv
Then GET /v1/clinical/{case_id}/survival-mlp returns the prediction and it is
included in the agent context.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]

# Normalize TCGA-XX-XXXX-01 -> TCGA-XX-XXXX for matching
def _normalize_case_id(s: str) -> str:
    s = (s or "").strip().upper()
    if not s or not s.startswith("TCGA-"):
        return s
    parts = s.split("-")
    if len(parts) >= 3:
        return "-".join(parts[:3])
    return s


def _case_to_slide_id(case_id: str) -> str:
    c = (case_id or "").strip()
    if not c:
        return ""
    if "-DX" in c.upper() or "-01Z-" in c.upper():
        return c
    return f"{c}-01Z-00-DX1"


def _find_pathology_embedding_path(embeddings_dir: Path, slide_id: str):
    if not embeddings_dir.is_dir() or not slide_id:
        return None
    slide_lower = slide_id.lower()
    candidates = [p for p in embeddings_dir.rglob("*.npy")
                  if not p.name.startswith(".") and not p.name.endswith("_coords.npy")
                  and (slide_lower in p.stem.lower() or slide_lower in p.name.lower())]
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: (x.stem.lower() != slide_lower, len(x.parts)))[0]


def load_pathology_embeddings(embeddings_dir: Path, case_ids: list[str]) -> dict[str, np.ndarray]:
    out = {}
    for cid in case_ids:
        slide_id = _case_to_slide_id(cid)
        path = _find_pathology_embedding_path(embeddings_dir, slide_id)
        if path is None:
            continue
        try:
            arr = np.load(path, allow_pickle=False)
            if arr.size == 0:
                continue
            vec = np.asarray(arr.mean(axis=0), dtype=np.float32) if arr.ndim > 1 else arr.astype(np.float32)
            out[cid] = vec
        except (OSError, ValueError):
            continue
    return out


def load_pathology_embeddings_csv(path: Path, id_col: str = "tcga_id") -> dict[str, np.ndarray]:
    """Load pathology embeddings from a precomputed CSV (tcga_id first column, rest = dims). Same layout as RNA CSV."""
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    if not rows:
        return {}
    keys = [k for k in fieldnames if k != id_col and (k or "").strip()]
    if not keys:
        keys = [k for k in (rows[0].keys() or []) if k != id_col]
    out: dict[str, np.ndarray] = {}
    for row in rows:
        cid = (row.get(id_col) or (row.get(fieldnames[0]) if fieldnames else "") or "").strip()
        if not cid:
            continue
        cid = _normalize_case_id(cid)
        try:
            vec = np.array([float(row.get(k, 0)) for k in keys], dtype=np.float32)
        except (ValueError, TypeError):
            continue
        out[cid] = vec
    return out


def load_rna_embeddings_csv(path: Path, id_col: str = "case_id") -> dict[str, np.ndarray]:
    """Load CSV: one row per sample, first column (or id_col) = id, rest = embedding dims."""
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    if not rows:
        return {}
    keys = [k for k in fieldnames if k != id_col and (k or "").strip()]
    if not keys:
        keys = list(rows[0].keys())[1:]
    out: dict[str, np.ndarray] = {}
    for row in rows:
        sid = (row.get(id_col) or (row.get(fieldnames[0]) if fieldnames else "") or "").strip()
        if not sid:
            continue
        try:
            vec = np.array([float(row.get(k, 0)) for k in keys], dtype=np.float32)
        except (ValueError, TypeError):
            continue
        out[sid] = vec
    return out


def load_cohort_metadata(path: Path) -> dict[str, dict[str, Any]]:
    """Load cohort CSV; return dict by normalized patient_id with metadata fields."""
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        pid = _normalize_case_id(row.get("patient_id") or row.get("case_id") or "")
        if not pid:
            continue
        out[pid] = {
            "gender": (row.get("gender") or "").strip().lower(),
            "race": (row.get("race") or "").strip().lower(),
            "ethnicity": (row.get("ethnicity") or "").strip().lower(),
            "tumor_stage": (row.get("tumor_stage") or "").strip().lower(),
            "smoking_status": (row.get("smoking_status") or "").strip().lower(),
            "age_at_diagnosis_years": row.get("age_at_diagnosis_years", "").strip(),
        }
    return out


def load_labels_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def one_hot_encode_metadata(
    cohort_meta: dict[str, dict[str, Any]],
    case_ids: list[str],
) -> tuple[np.ndarray, list[str], dict[str, list[str]]]:
    """
    Build numeric matrix from metadata: one-hot for categoricals, float for age.
    Returns (X_meta, feature_names, encoder_state for inference).
    """
    # Collect all unique values per field (for consistent one-hot)
    categoricals = ["gender", "race", "ethnicity", "tumor_stage", "smoking_status"]
    categories: dict[str, list[str]] = {}
    ages: list[float] = []
    for cid in case_ids:
        m = cohort_meta.get(cid, {})
        for k in categoricals:
            v = (m.get(k) or "").strip() or "unknown"
            categories.setdefault(k, set()).add(v)
        a = m.get("age_at_diagnosis_years") or ""
        try:
            ages.append(float(a))
        except (ValueError, TypeError):
            ages.append(np.nan)

    # Ordered categories (unknown last)
    encoder_state: dict[str, list[str]] = {}
    feature_names: list[str] = ["age_at_diagnosis_years"]
    for k in categoricals:
        vals = sorted(categories.get(k, {"unknown"}))
        if "unknown" in vals:
            vals.remove("unknown")
            vals.append("unknown")
        encoder_state[k] = vals
        for v in vals:
            feature_names.append(f"{k}_{v}")

    # Build matrix
    age_median = float(np.nanmedian(ages)) if ages else 0.0
    X_list: list[np.ndarray] = []
    for cid in case_ids:
        m = cohort_meta.get(cid, {})
        row: list[float] = []
        # age
        a = m.get("age_at_diagnosis_years") or ""
        try:
            row.append(float(a))
        except (ValueError, TypeError):
            row.append(age_median)
        # one-hots
        for k in categoricals:
            v = (m.get(k) or "").strip() or "unknown"
            for opt in encoder_state[k]:
                row.append(1.0 if opt == v else 0.0)
        X_list.append(np.array(row, dtype=np.float32))
    X_meta = np.stack(X_list)
    return X_meta, feature_names, encoder_state


def build_rna_key_to_case_id(cohort_csv: Path) -> dict[str, str]:
    """Map sample_id (file_name stem) -> normalized case_id from cohort."""
    if not cohort_csv.is_file():
        return {}
    with cohort_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    m: dict[str, str] = {}
    for row in rows:
        pid = _normalize_case_id(row.get("patient_id") or "")
        if not pid:
            continue
        fname = (row.get("selected_rna_file_name") or "").strip().rstrip(".tsv")
        if fname:
            m[fname] = pid
        fid = (row.get("selected_rna_file_id") or "").strip()
        if fid:
            m[f"{fid}.rna_seq.augmented_star_gene_counts"] = pid
    return m


def load_fused_csv_and_labels(
    fused_csv: Path,
    labels_csv: Path,
    horizon: int,
    id_col: str = "tcga_id",
) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    """
    Load a single fused CSV (tcga_id + feature columns) and labels CSV.
    Match on patient_id (labels) = tcga_id (fused). Return X, y, case_ids, feature_names.
    """
    col = f"survived_{horizon}yr"
    # Labels: patient_id -> 0 or 1
    label_by_patient: dict[str, int] = {}
    for row in load_labels_csv(labels_csv):
        pid = _normalize_case_id(row.get("patient_id") or row.get("case_id") or "")
        if not pid:
            continue
        v = (row.get(col) or "").strip()
        if v == "1":
            label_by_patient[pid] = 1
        elif v == "0":
            label_by_patient[pid] = 0

    with fused_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        rows = list(reader)

    feature_cols = [h for h in header if h != id_col and (h or "").strip()]
    case_ids: list[str] = []
    X_list: list[list[float]] = []
    y_list: list[int] = []

    for row in rows:
        cid = _normalize_case_id((row.get(id_col) or "").strip())
        if not cid or cid not in label_by_patient:
            continue
        try:
            vec = [float(row.get(k, 0)) for k in feature_cols]
        except (ValueError, TypeError):
            continue
        case_ids.append(cid)
        X_list.append(vec)
        y_list.append(label_by_patient[cid])

    if not X_list:
        return np.array([]), np.array([]), [], feature_cols
    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.int32)
    return X, y, case_ids, feature_cols


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train MLP for survival from pathology + RNA embeddings + one-hot patient metadata, or from a single fused CSV.",
    )
    parser.add_argument(
        "--fused-csv",
        type=Path,
        default=None,
        help="Single CSV with tcga_id + all features (pathology_*, rna_*, metadata). If set, only --labels-csv is required; other embedding/cohort args are ignored.",
    )
    parser.add_argument(
        "--rna-embeddings-csv",
        type=Path,
        default=None,
        help="CSV: first column = case_id or sample_id, rest = embedding dimensions. Required when not using --fused-csv.",
    )
    parser.add_argument(
        "--pathology-embeddings-dir",
        type=Path,
        default=None,
        help="Directory of per-slide .npy tile embeddings. Required if --pathology-embeddings-csv is not set. Mean-pooled per slide.",
    )
    parser.add_argument(
        "--pathology-embeddings-csv",
        type=Path,
        default=None,
        help="Precomputed pathology embeddings CSV (tcga_id first column, rest = dims). Same layout as RNA CSV. If set, overrides --pathology-embeddings-dir for training.",
    )
    parser.add_argument(
        "--cohort-csv",
        type=Path,
        default=REPO_ROOT / "data/luad/tcga_matched_cohort.csv",
        help="Cohort CSV for metadata and optional sample_id -> case_id mapping.",
    )
    parser.add_argument(
        "--labels-csv",
        type=Path,
        required=True,
        help="Outcome labels CSV (survival_time_days, event, survived_1yr/2yr/5yr) from build_outcome_labels_table.py.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "models/survival_rna_mlp",
        help="Output directory for model and metrics.",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        choices=[1, 2, 5],
        default=2,
        help="Survival horizon for binary target: survived_{horizon}yr (1, 2, or 5).",
    )
    parser.add_argument(
        "--id-column",
        type=str,
        default="case_id",
        help="Column name for sample/case id in RNA embeddings CSV (or first column if missing).",
    )
    parser.add_argument(
        "--hidden",
        type=str,
        default="128,64",
        help="Comma-separated hidden layer sizes (e.g. 128,64).",
    )
    parser.add_argument(
        "--max-iter",
        type=int,
        default=500,
        help="MLP max iterations.",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.01,
        help="L2 regularization (default 0.01; increase if p >> n).",
    )
    parser.add_argument(
        "--pca-components",
        type=int,
        default=None,
        help="If set, reduce features with PCA to this many components before training (useful when n_features >> n_samples).",
    )
    args = parser.parse_args()

    if args.fused_csv is not None and args.fused_csv.is_file():
        # --- Fused CSV path: single file + labels only ---
        if not args.labels_csv.is_file():
            print(f"Labels CSV not found: {args.labels_csv}", file=sys.stderr)
            return 1
        X, y, case_ids, feature_names = load_fused_csv_and_labels(
            args.fused_csv, args.labels_csv, args.horizon, id_col="tcga_id"
        )
        if X.size == 0 or len(case_ids) < 5:
            print(f"Only {len(case_ids)} samples with fused features + valid label survived_{args.horizon}yr; need at least 5.", file=sys.stderr)
            return 1
        encoder_state = {}
        n_pathology_dims = sum(1 for n in feature_names if n.startswith("pathology_"))
        n_rna_dims = sum(1 for n in feature_names if n.startswith("rna_"))
        n_meta_dims = len(feature_names) - n_pathology_dims - n_rna_dims
        col = f"survived_{args.horizon}yr"
    else:
        # --- Original path: pathology + RNA + cohort ---
        if not args.rna_embeddings_csv or not args.rna_embeddings_csv.is_file():
            print("Provide --fused-csv or valid --rna-embeddings-csv.", file=sys.stderr)
            return 1
        if not args.labels_csv.is_file():
            print(f"Labels CSV not found: {args.labels_csv}", file=sys.stderr)
            return 1
        if not args.cohort_csv.is_file():
            print(f"Cohort CSV not found: {args.cohort_csv}", file=sys.stderr)
            return 1
        if not args.pathology_embeddings_csv and not args.pathology_embeddings_dir:
            print("Provide either --pathology-embeddings-csv or --pathology-embeddings-dir.", file=sys.stderr)
            return 1
        if args.pathology_embeddings_csv and not args.pathology_embeddings_csv.is_file():
            print(f"Pathology embeddings CSV not found: {args.pathology_embeddings_csv}", file=sys.stderr)
            return 1
        if args.pathology_embeddings_dir and not args.pathology_embeddings_dir.is_dir():
            print(f"Pathology embeddings dir not found: {args.pathology_embeddings_dir}", file=sys.stderr)
            return 1

        rna_emb = load_rna_embeddings_csv(args.rna_embeddings_csv, id_col=args.id_column)
        if not rna_emb:
            print("No rows loaded from RNA embeddings CSV.", file=sys.stderr)
            return 1

        rna_key_to_case = build_rna_key_to_case_id(args.cohort_csv)
        case_to_rna: dict[str, np.ndarray] = {}
        for k, v in rna_emb.items():
            case_id = rna_key_to_case.get(k) or _normalize_case_id(k)
            if not case_id:
                continue
            case_to_rna[case_id] = v

        cohort_meta = load_cohort_metadata(args.cohort_csv)
        labels_rows = load_labels_csv(args.labels_csv)
        col = f"survived_{args.horizon}yr"
        # Valid (case_id, y) for binary
        valid: list[tuple[str, int]] = []
        for row in labels_rows:
            cid = _normalize_case_id(row.get("case_id") or row.get("patient_id") or "")
            if not cid or cid not in case_to_rna:
                continue
            v = (row.get(col) or "").strip()
            if v == "1":
                valid.append((cid, 1))
            elif v == "0":
                valid.append((cid, 0))
        case_ids_with_rna_and_label = [c for c, _ in valid]
        if args.pathology_embeddings_csv and args.pathology_embeddings_csv.is_file():
            case_to_pathology = load_pathology_embeddings_csv(args.pathology_embeddings_csv, id_col="tcga_id")
        else:
            case_to_pathology = load_pathology_embeddings(args.pathology_embeddings_dir, case_ids_with_rna_and_label)
        valid = [(c, lbl) for c, lbl in valid if c in case_to_pathology]
        if len(valid) < 10:
            print(f"Only {len(valid)} samples with pathology + RNA + valid binary label {col}; need at least 10.", file=sys.stderr)
            return 1

        case_ids = [c for c, _ in valid]
        y = np.array([lbl for _, lbl in valid], dtype=np.int32)
        X_path = np.stack([case_to_pathology[c] for c in case_ids])
        X_rna = np.stack([case_to_rna[c] for c in case_ids])
        X_meta, meta_feature_names, encoder_state = one_hot_encode_metadata(cohort_meta, case_ids)
        X = np.concatenate([X_path, X_rna, X_meta], axis=1).astype(np.float32)
        feature_names = [f"pathology_{i}" for i in range(X_path.shape[1])] + [f"rna_{i}" for i in range(X_rna.shape[1])] + meta_feature_names
        n_pathology_dims = X_path.shape[1]
        n_rna_dims = X_rna.shape[1]
        n_meta_dims = X_meta.shape[1]

    try:
        from sklearn.neural_network import MLPClassifier
        from sklearn.model_selection import cross_val_score
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        print("sklearn is required. pip install scikit-learn", file=sys.stderr)
        return 1

    pca = None
    if args.pca_components is not None and X.shape[1] > args.pca_components and X.shape[0] > args.pca_components:
        from sklearn.decomposition import PCA
        n_comp = min(args.pca_components, X.shape[0] - 2, X.shape[1])
        n_comp = max(2, n_comp)
        pca = PCA(n_components=n_comp, random_state=42)
        X = pca.fit_transform(X)
        feature_names = [f"pca_{i}" for i in range(n_comp)]
        print(f"Reduced to {n_comp} PCA components.", file=sys.stderr)
    elif X.shape[1] > X.shape[0]:
        from sklearn.decomposition import PCA
        n_comp = min(20, X.shape[0] - 2, X.shape[1])
        n_comp = max(2, n_comp)
        pca = PCA(n_components=n_comp, random_state=42)
        X = pca.fit_transform(X)
        feature_names = [f"pca_{i}" for i in range(n_comp)]
        print(f"Auto-reduced to {n_comp} PCA components (n_features > n_samples).", file=sys.stderr)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    hidden = [int(x) for x in args.hidden.split(",") if x.strip()]
    if not hidden:
        hidden = [128, 64]
    model = MLPClassifier(
        hidden_layer_sizes=tuple(hidden),
        activation="relu",
        max_iter=args.max_iter,
        random_state=42,
        alpha=args.alpha,
    )
    model.fit(X_scaled, y)

    # Cross-validation (use fewer folds when n is small to avoid degenerate splits)
    cv = min(5, max(2, len(y) // 4))
    scores = cross_val_score(
        MLPClassifier(hidden_layer_sizes=tuple(hidden), activation="relu", max_iter=args.max_iter, random_state=42, alpha=args.alpha),
        X_scaled, y, cv=cv, scoring="accuracy"
    )
    cv_acc = float(scores.mean())
    cv_std = float(scores.std())

    args.out_dir.mkdir(parents=True, exist_ok=True)
    import pickle
    with (args.out_dir / "mlp_survival.pkl").open("wb") as f:
        pickle.dump(model, f)
    with (args.out_dir / "scaler.pkl").open("wb") as f:
        pickle.dump(scaler, f)
    with (args.out_dir / "encoder_state.json").open("w", encoding="utf-8") as f:
        json.dump(encoder_state, f, indent=2)
    with (args.out_dir / "feature_names.json").open("w", encoding="utf-8") as f:
        json.dump(feature_names, f)
    if pca is not None:
        with (args.out_dir / "pca.pkl").open("wb") as f:
            pickle.dump(pca, f)

    metrics = {
        "n_samples": int(y.shape[0]),
        "n_pathology_dims": int(n_pathology_dims),
        "n_rna_dims": int(n_rna_dims),
        "n_meta_dims": int(n_meta_dims),
        "n_features": int(X.shape[1]),
        "target": col,
        "horizon_years": args.horizon,
        "cv_accuracy_mean": round(cv_acc, 4),
        "cv_accuracy_std": round(cv_std, 4),
        "train_accuracy": round(float((model.predict(X_scaled) == y).mean()), 4),
    }
    if pca is not None:
        metrics["pca_components"] = pca.n_components_
    with (args.out_dir / "metrics.json").open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print(f"Trained MLP for {col}: n_samples={metrics['n_samples']}, n_features={metrics['n_features']}")
    print(f"  CV accuracy (5-fold): {cv_acc:.4f} (+/- {cv_std:.4f})")
    print(f"  Model, scaler, encoder_state, metrics written to {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
