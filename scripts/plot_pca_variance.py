#!/usr/bin/env python3
"""
Plot variance explained by each PC for RNA embeddings (scree plot).
Uses the same CSV as visualize_rna_embeddings.py. Run with fewer components to avoid slow SVD.
"""
import csv
import sys
from pathlib import Path

import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    csv_path = Path("data/luad/bulk_matrix_matrix_bulkformer_embeddings_with_tcga.csv")
    out_path = Path("data/luad/rna_pca_variance.png")
    if len(sys.argv) >= 2:
        csv_path = Path(sys.argv[1])
    if len(sys.argv) >= 3:
        out_path = Path(sys.argv[2])

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = [h for h in (reader.fieldnames or []) if h != "tcga_id" and (h or "").strip()]
        rows = [row for row in reader if (row.get("tcga_id") or "").strip()]

    X = np.array([[float(row.get(k, 0)) for k in header] for row in rows], dtype=np.float32)
    X = StandardScaler().fit_transform(X)

    n_components = min(30, X.shape[0] - 1, X.shape[1])
    n_components = max(2, n_components)
    pca = PCA(n_components=n_components, random_state=42, svd_solver="full")
    pca.fit(X)

    fig, ax1 = plt.subplots(figsize=(10, 5))
    n_pc = len(pca.explained_variance_ratio_)
    x = range(1, n_pc + 1)
    ax1.bar(x, pca.explained_variance_ratio_ * 100, color="steelblue", alpha=0.8, label="Variance per PC")
    ax1.set_xlabel("Principal component")
    ax1.set_ylabel("Variance explained (%)")
    ax1.set_ylim(0, None)
    ax2 = ax1.twinx()
    cumvar = np.cumsum(pca.explained_variance_ratio_) * 100
    ax2.plot(x, cumvar, color="coral", linewidth=2, marker="o", markersize=4, label="Cumulative")
    ax2.set_ylabel("Cumulative variance explained (%)")
    ax2.set_ylim(0, 105)
    ax2.axhline(90, color="gray", linestyle="--", alpha=0.6)
    ax1.legend(loc="upper right")
    ax2.legend(loc="center right")
    ax1.set_title("PCA: variance explained by each principal component (RNA embeddings)")
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
