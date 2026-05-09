#!/usr/bin/env python3
"""Train survival (and optional binary outcome) models from LUAD embeddings + outcome labels.

Loads:
- Outcome labels CSV (from build_outcome_labels_table.py): case_id, survival_time_days, event, ...
- Slide embeddings: either (1) directory of .npy per slide (tile-level; mean-pooled to slide-level)
  or (2) a precomputed slide-level matrix CSV/NumPy with case_id/slide_id key.
Optionally concatenates RNA feature vector (TIDE, GEP, CYT, etc.) from a CSV keyed by case_id.

Trains:
- Cox proportional hazards (if sksurv available), or
- XGBoost survival (if xgboost available), or
- Logistic regression or MLP for binary 1/2/5-yr survival (sklearn).

Saves model artifact and optional metrics JSON.

Usage:
  # 1) Build labels (run first)
  python scripts/build_outcome_labels_table.py --cohort-csv ... --clinical-xml-dir ... --out data/labels/survival_labels.csv

  # 2) Train from tile embeddings (mean-pool per slide)
  python scripts/train_survival_from_embeddings.py \\
    --labels-csv data/labels/survival_labels.csv \\
    --embeddings-dir data/luad/embeddings/level0 \\
    --out-dir models/survival

  # 3) With precomputed slide-level vectors and optional RNA features
  python scripts/train_survival_from_embeddings.py \\
    --labels-csv data/labels/survival_labels.csv \\
    --slide-vectors-csv data/luad/slide_vectors.csv \\
    --rna-features-csv data/luad/transcriptomics_features.csv \\
    --out-dir models/survival
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]


def _path_from_env(*names: str) -> Path | None:
    for n in names:
        v = os.getenv(n, "").strip()
        if v:
            return Path(v).expanduser()
    return None


def _case_to_slide_id(case_id: str) -> str:
    """Default: TCGA-xx-xxxx -> TCGA-xx-xxxx-DX1."""
    c = (case_id or "").strip()
    if not c:
        return ""
    if "-DX" in c.upper():
        return c
    return f"{c}-DX1"


def _find_embedding_path_for_slide(embeddings_dir: Path, slide_id: str) -> Path | None:
    """Find a .npy file (not *_coords.npy) that matches slide_id (by stem/name)."""
    if not embeddings_dir.is_dir() or not slide_id:
        return None
    slide_lower = slide_id.lower()
    candidates: list[Path] = []
    for p in embeddings_dir.rglob("*.npy"):
        if p.name.endswith("_coords.npy"):
            continue
        stem = p.stem.lower()
        name = p.name.lower()
        if slide_lower in stem or slide_lower in name:
            candidates.append(p)
    if not candidates:
        return None
    for p in sorted(candidates, key=lambda x: (x.stem.lower() != slide_lower, len(x.parts))):
        return p
    return candidates[0]


def load_slide_vector_from_npy(path: Path) -> np.ndarray | None:
    """Load .npy (shape [n_tiles, dim]) and return mean-pooled vector (dim,)."""
    if np is None:
        return None
    try:
        arr = np.load(path, allow_pickle=False)
        if arr.size == 0:
            return None
        if arr.ndim == 1:
            return arr.astype(np.float32)
        return np.asarray(arr.mean(axis=0), dtype=np.float32)
    except (OSError, ValueError):
        return None


def load_labels_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_slide_vectors_from_dir(
    embeddings_dir: Path,
    case_ids: list[str],
) -> dict[str, np.ndarray]:
    """For each case_id, resolve slide_id, find .npy, mean-pool -> vector."""
    out: dict[str, np.ndarray] = {}
    for case_id in case_ids:
        slide_id = _case_to_slide_id(case_id)
        if not slide_id:
            continue
        ep = _find_embedding_path_for_slide(embeddings_dir, slide_id)
        if ep is None:
            continue
        vec = load_slide_vector_from_npy(ep)
        if vec is not None:
            out[case_id] = vec
    return out


def load_slide_vectors_csv(path: Path, case_col: str = "case_id") -> dict[str, np.ndarray]:
    """Load CSV with case_id and numeric columns (embedding dims)."""
    if np is None:
        return {}
    rows = load_labels_csv(path)
    if not rows:
        return {}
    fieldnames = [k for k in rows[0].keys() if k != case_col]
    out: dict[str, np.ndarray] = {}
    for row in rows:
        cid = row.get(case_col, "").strip()
        if not cid:
            continue
        try:
            vec = np.array([float(row.get(f, 0)) for f in fieldnames], dtype=np.float32)
        except (ValueError, TypeError):
            continue
        out[cid] = vec
    return out


def build_matrix_and_labels(
    labels_rows: list[dict[str, Any]],
    slide_vectors: dict[str, np.ndarray],
    rna_features: dict[str, np.ndarray] | None = None,
    target_event: str = "event",
    target_time: str = "survival_time_days",
    min_time_days: float = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Build X, y_time, y_event for cases with both label and embedding."""
    if np is None:
        raise RuntimeError("numpy is required for training")

    case_ids: list[str] = []
    X_list: list[np.ndarray] = []
    y_time_list: list[float] = []
    y_event_list: list[int] = []

    for row in labels_rows:
        case_id = (row.get("case_id") or "").strip()
        if not case_id or case_id not in slide_vectors:
            continue
        try:
            t = float(row.get(target_time) or 0)
            e = int(row.get(target_event) or 0)
        except (ValueError, TypeError):
            continue
        if t < min_time_days:
            continue

        vec = slide_vectors[case_id].copy()
        if rna_features and case_id in rna_features:
            vec = np.concatenate([vec, rna_features[case_id]])
        X_list.append(vec)
        y_time_list.append(t)
        y_event_list.append(e)
        case_ids.append(case_id)

    if not X_list:
        return np.zeros((0, 0)), np.zeros(0), np.zeros(0), []

    X = np.stack(X_list).astype(np.float32)
    y_time = np.array(y_time_list, dtype=np.float64)
    y_event = np.array(y_event_list, dtype=np.int32)
    return X, y_time, y_event, case_ids


def train_cox(X: np.ndarray, y_time: np.ndarray, y_event: np.ndarray) -> Any:
    try:
        from sksurv.linear_model import CoxPHSurvivalAnalysis
        from sksurv.util import Surv
    except ImportError:
        return None
    y = Surv.from_arrays(event=y_event.astype(bool), time=y_time)
    model = CoxPHSurvivalAnalysis(alpha=0.5)
    model.fit(X, y)
    return model


def train_xgb_survival(X: np.ndarray, y_time: np.ndarray, y_event: np.ndarray) -> Any:
    try:
        import xgboost as xgb
    except ImportError:
        return None
    dtrain = xgb.DMatrix(X, label=y_time)
    dtrain.set_float_info("label_lower_bound", y_time)
    dtrain.set_float_info("label_upper_bound", np.where(y_event, y_time, np.inf))
    params = {"objective": "survival:aft", "eval_metric": "aft-nloglik", "tree_method": "hist"}
    model = xgb.train(params, dtrain, num_boost_round=50)
    return model


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train survival (and optional binary) models from embeddings + outcome labels.",
    )
    parser.add_argument("--labels-csv", type=Path, required=True, help="Outcome labels CSV (from build_outcome_labels_table.py).")
    parser.add_argument(
        "--embeddings-dir",
        type=Path,
        default=None,
        help="Directory of tile-level .npy embeddings (mean-pooled per slide). Overridden by --slide-vectors-csv if set.",
    )
    parser.add_argument(
        "--slide-vectors-csv",
        type=Path,
        default=None,
        help="Precomputed slide-level vectors CSV (case_id + numeric columns).",
    )
    parser.add_argument(
        "--rna-features-csv",
        type=Path,
        default=None,
        help="Optional RNA features CSV (case_id, tide, gep, cyt, ...) to concatenate.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "models/survival",
        help="Output directory for model and metrics.",
    )
    parser.add_argument(
        "--model-type",
        choices=["cox", "xgb", "binary_1yr", "binary_2yr", "binary_5yr", "mlp_1yr", "mlp_2yr", "mlp_5yr"],
        default="cox",
        help="Model to train.",
    )
    parser.add_argument(
        "--min-survival-days",
        type=float,
        default=0,
        help="Minimum survival_time_days to include (exclude 0 or missing).",
    )
    args = parser.parse_args()

    if np is None:
        print("numpy is required. pip install numpy", file=sys.stderr)
        return 1

    if not args.labels_csv.is_file():
        print(f"Labels CSV not found: {args.labels_csv}", file=sys.stderr)
        return 1

    labels_rows = load_labels_csv(args.labels_csv)
    if not labels_rows:
        print("No rows in labels CSV.", file=sys.stderr)
        return 1

    case_ids_from_labels = list({(r.get("case_id") or "").strip() for r in labels_rows if (r.get("case_id") or "").strip()})

    if args.slide_vectors_csv and args.slide_vectors_csv.is_file():
        slide_vectors = load_slide_vectors_csv(args.slide_vectors_csv)
    else:
        emb_dir = args.embeddings_dir or _path_from_env("ENSO_EMBEDDINGS_DIR", "LUAD_AUDIT_EMBEDDINGS_DIR") or (REPO_ROOT / "data/luad/embeddings/level0")
        if not emb_dir.is_dir():
            print(f"Embeddings dir not found: {emb_dir}. Use --embeddings-dir or --slide-vectors-csv.", file=sys.stderr)
            return 1
        slide_vectors = load_slide_vectors_from_dir(emb_dir, case_ids_from_labels)

    if not slide_vectors:
        print("No slide vectors found; check embeddings-dir or slide-vectors-csv.", file=sys.stderr)
        return 1

    rna_features: dict[str, np.ndarray] | None = None
    if args.rna_features_csv and args.rna_features_csv.is_file():
        rna_features = load_slide_vectors_csv(args.rna_features_csv, case_col="case_id")

    X, y_time, y_event, case_ids = build_matrix_and_labels(
        labels_rows,
        slide_vectors,
        rna_features=rna_features,
        min_time_days=args.min_survival_days,
    )

    if len(case_ids) < 10:
        print(f"Only {len(case_ids)} samples with both labels and embeddings; recommend at least 10.", file=sys.stderr)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    metrics: dict[str, Any] = {"n_samples": len(case_ids), "n_features": X.shape[1] if X.size else 0}

    if args.model_type == "cox":
        model = train_cox(X, y_time, y_event)
        if model is None:
            print("Cox model requires sksurv. pip install scikit-survival", file=sys.stderr)
            return 1
        import pickle
        with (args.out_dir / "cox_model.pkl").open("wb") as f:
            pickle.dump(model, f)
        metrics["model_path"] = "cox_model.pkl"

    elif args.model_type == "xgb":
        model = train_xgb_survival(X, y_time, y_event)
        if model is None:
            print("XGBoost survival requires xgboost. pip install xgboost", file=sys.stderr)
            return 1
        model.save_model(str(args.out_dir / "xgb_survival.json"))
        metrics["model_path"] = "xgb_survival.json"

    elif args.model_type.startswith("binary_") or args.model_type.startswith("mlp_"):
        horizon_map = {
            "binary_1yr": 365, "binary_2yr": 730, "binary_5yr": 1825,
            "mlp_1yr": 365, "mlp_2yr": 730, "mlp_5yr": 1825,
        }
        horizon = horizon_map[args.model_type]
        col = f"survived_{horizon // 365}yr"
        y_bin: list[int] = []
        valid_case_ids: list[str] = []
        for i, cid in enumerate(case_ids):
            row = next((r for r in labels_rows if (r.get("case_id") or "").strip() == cid), {})
            v = (row.get(col) or "").strip()
            if v == "1":
                y_bin.append(1)
                valid_case_ids.append(cid)
            elif v == "0":
                y_bin.append(0)
                valid_case_ids.append(cid)
        if len(y_bin) < 5:
            print(f"Binary label {col} has too few valid 0/1; skipping.", file=sys.stderr)
            return 1
        idx = [case_ids.index(c) for c in valid_case_ids]
        X_bin = X[idx]
        y_bin_arr = np.array(y_bin, dtype=np.int32)
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.neural_network import MLPClassifier
        except ImportError:
            print("Binary/MLP models require sklearn. pip install scikit-learn", file=sys.stderr)
            return 1
        if args.model_type.startswith("mlp_"):
            model = MLPClassifier(
                hidden_layer_sizes=(64, 32),
                activation="relu",
                max_iter=500,
                random_state=42,
            )
            model.fit(X_bin, y_bin_arr)
            import pickle
            with (args.out_dir / f"mlp_{col}.pkl").open("wb") as f:
                pickle.dump(model, f)
            metrics["model_path"] = f"mlp_{col}.pkl"
        else:
            model = LogisticRegression(max_iter=500, random_state=42)
            model.fit(X_bin, y_bin_arr)
            import pickle
            with (args.out_dir / f"logistic_{col}.pkl").open("wb") as f:
                pickle.dump(model, f)
            metrics["model_path"] = f"logistic_{col}.pkl"
        metrics["target"] = col
        metrics["n_samples"] = len(y_bin)
    else:
        print("Unsupported model type.", file=sys.stderr)
        return 1

    with (args.out_dir / "metrics.json").open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print(f"Trained {args.model_type}; n_samples={metrics['n_samples']}, n_features={metrics['n_features']}")
    print(f"Model and metrics written to {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
