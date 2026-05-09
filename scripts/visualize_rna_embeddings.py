#!/usr/bin/env python3
"""
Visualize RNA embeddings in 2D using PCA or UMAP.

Loads an RNA embeddings CSV (tcga_id first column, rest = dimensions), reduces to 2D,
and writes a scatter plot. Optionally colors points by vital_status from the cohort CSV.

Usage:
  # PCA only (sklearn + matplotlib)
  python scripts/visualize_rna_embeddings.py \\
    --embeddings-csv data/luad/bulk_matrix_matrix_bulkformer_embeddings_with_tcga.csv \\
    --output data/luad/rna_embeddings_2d.png

  # With cohort for coloring by vital status
  python scripts/visualize_rna_embeddings.py \\
    --embeddings-csv data/luad/bulk_matrix_matrix_bulkformer_embeddings_with_tcga.csv \\
    --cohort-csv data/luad/tcga_matched_cohort.csv \\
    --output data/luad/rna_embeddings_2d.png

  # UMAP (if umap-learn installed) + interactive HTML (if plotly installed)
  pip install umap-learn plotly
  python scripts/visualize_rna_embeddings.py \\
    --embeddings-csv data/luad/bulk_matrix_matrix_bulkformer_embeddings_with_tcga.csv \\
    --cohort-csv data/luad/tcga_matched_cohort.csv \\
    --method umap --output data/luad/rna_embeddings_2d.png \\
    --output-html data/luad/rna_embeddings_2d.html
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np


def _normalize_case_id(s: str) -> str:
    s = (s or "").strip().upper()
    if not s or not s.startswith("TCGA-"):
        return s
    parts = s.split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else s


def load_embeddings(csv_path: Path, id_col: str = "tcga_id") -> tuple[list[str], np.ndarray]:
    """Return (ids, matrix) with shape (n_samples, n_dims)."""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        rows = list(reader)
    feature_cols = [h for h in header if h != id_col and (h or "").strip()]
    ids = []
    X_list = []
    for row in rows:
        cid = (row.get(id_col) or "").strip()
        if not cid:
            continue
        try:
            vec = [float(row.get(k, 0)) for k in feature_cols]
        except (ValueError, TypeError):
            continue
        ids.append(cid)
        X_list.append(vec)
    X = np.array(X_list, dtype=np.float32)
    return ids, X


def load_vital_by_patient(cohort_csv: Path) -> dict[str, str]:
    """patient_id (TCGA-XX-XXXX) -> vital_status."""
    out = {}
    with cohort_csv.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            pid = _normalize_case_id(row.get("patient_id") or "")
            if pid:
                out[pid] = (row.get("vital_status") or "").strip() or "Unknown"
    return out


def reduce_2d(X: np.ndarray, method: str = "pca", random_state: int = 42) -> np.ndarray:
    """Reduce to 2D. method in ('pca', 'umap')."""
    if method == "pca":
        from sklearn.decomposition import PCA
        pca = PCA(n_components=2, random_state=random_state)
        return pca.fit_transform(X)
    if method == "umap":
        try:
            import umap
        except ImportError:
            raise SystemExit("UMAP not installed. pip install umap-learn")
        reducer = umap.UMAP(n_components=2, random_state=random_state, n_neighbors=min(15, X.shape[0] - 1))
        return reducer.fit_transform(X)
    raise ValueError(f"Unknown method: {method}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Visualize RNA embeddings in 2D (PCA or UMAP).")
    ap.add_argument("--embeddings-csv", type=Path, required=True, help="RNA embeddings CSV (tcga_id first column).")
    ap.add_argument("--cohort-csv", type=Path, default=None, help="Optional: cohort CSV for vital_status coloring.")
    ap.add_argument("--output", "-o", type=Path, required=True, help="Output PNG path.")
    ap.add_argument("--output-variance", type=Path, default=None, help="Optional: PNG path for PCA variance (scree) plot. Only when --method pca.")
    ap.add_argument("--output-html", type=Path, default=None, help="Optional: output interactive HTML (requires plotly).")
    ap.add_argument("--method", choices=["pca", "umap"], default="pca", help="Dimensionality reduction method.")
    ap.add_argument("--id-column", default="tcga_id")
    args = ap.parse_args()

    if not args.embeddings_csv.is_file():
        print(f"Embeddings CSV not found: {args.embeddings_csv}", file=sys.stderr)
        return 1

    ids, X = load_embeddings(args.embeddings_csv, id_col=args.id_column)
    if len(ids) < 2:
        print("Need at least 2 samples.", file=sys.stderr)
        return 1

    # Optional: scale for UMAP (PCA is scale-invariant in relative terms but scaling is still good practice)
    from sklearn.preprocessing import StandardScaler
    X_scaled = StandardScaler().fit_transform(X)

    pca_for_variance = None
    if args.method == "pca":
        from sklearn.decomposition import PCA
        n_components = min(50, X_scaled.shape[0] - 1, X_scaled.shape[1])
        n_components = max(2, n_components)
        pca = PCA(n_components=n_components, random_state=42, svd_solver="full")
        coords = pca.fit_transform(X_scaled)[:, :2]
        if args.output_variance:
            pca_for_variance = pca
    else:
        coords = reduce_2d(X_scaled, method=args.method)

    # Colors: by vital_status if cohort provided
    vital = load_vital_by_patient(args.cohort_csv) if args.cohort_csv and args.cohort_csv.is_file() else {}
    colors = [vital.get(_normalize_case_id(i), "Unknown") for i in ids]

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib required: pip install matplotlib", file=sys.stderr)
        return 1

    fig, ax = plt.subplots(figsize=(8, 6))

    if vital:
        for status in sorted(set(colors)):
            mask = [c == status for c in colors]
            ax.scatter(
                coords[mask, 0], coords[mask, 1],
                label=status, alpha=0.7, s=40
            )
        ax.legend(loc="best", fontsize=9)
    else:
        ax.scatter(coords[:, 0], coords[:, 1], alpha=0.7, s=40, c="steelblue", edgecolors="white", linewidths=0.5)

    ax.set_xlabel(f"{args.method.upper()} 1")
    ax.set_ylabel(f"{args.method.upper()} 2")
    ax.set_title("RNA embeddings (BulkFormer)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {args.output}", file=sys.stderr)

    # Variance explained by each PC (scree plot)
    if args.output_variance and pca_for_variance is not None:
        fig2, ax1 = plt.subplots(figsize=(10, 5))
        n_pc = len(pca_for_variance.explained_variance_ratio_)
        x = range(1, n_pc + 1)
        ax1.bar(x, pca_for_variance.explained_variance_ratio_ * 100, color="steelblue", alpha=0.8, label="Variance per PC")
        ax1.set_xlabel("Principal component")
        ax1.set_ylabel("Variance explained (%)")
        ax1.set_ylim(0, None)
        ax2 = ax1.twinx()
        cumvar = np.cumsum(pca_for_variance.explained_variance_ratio_) * 100
        ax2.plot(x, cumvar, color="coral", linewidth=2, marker="o", markersize=4, label="Cumulative")
        ax2.set_ylabel("Cumulative variance explained (%)")
        ax2.set_ylim(0, 105)
        ax2.axhline(90, color="gray", linestyle="--", alpha=0.6)
        ax1.legend(loc="upper right")
        ax2.legend(loc="center right")
        ax1.set_title("PCA: variance explained by each principal component")
        plt.tight_layout()
        args.output_variance.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(args.output_variance, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Saved {args.output_variance}", file=sys.stderr)

    if args.output_html:
        try:
            import plotly.express as px
            import pandas as pd
        except ImportError:
            print("Skipping HTML (plotly required: pip install plotly pandas).", file=sys.stderr)
        else:
            df = pd.DataFrame({
                "x": coords[:, 0],
                "y": coords[:, 1],
                "tcga_id": ids,
                "vital_status": colors,
            })
            fig = px.scatter(df, x="x", y="y", color="vital_status" if vital else None,
                            hover_data=["tcga_id"], title="RNA embeddings (BulkFormer)")
            fig.update_layout(xaxis_title=f"{args.method.upper()} 1", yaxis_title=f"{args.method.upper()} 2")
            args.output_html.parent.mkdir(parents=True, exist_ok=True)
            fig.write_html(str(args.output_html))
            print(f"Saved {args.output_html}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
