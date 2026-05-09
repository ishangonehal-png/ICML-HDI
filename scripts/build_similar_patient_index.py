#!/usr/bin/env python3
"""Build a similar-patient index from slide (and optional RNA) embeddings.

Loads slide vectors from --embeddings-dir (per-slide .npy) or --slide-vectors-csv.
Optionally restricts to case_ids from --labels-csv or --cohort-csv and/or
concatenates --rna-features-csv for fused vectors.
Builds a FAISS index (or sklearn fallback) and saves index + case_id mapping
so query_similar_patients.py can look up by case_id and k.

Reuses helpers from train_survival_from_embeddings for consistent slide resolution.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Import shared helpers (same CLI/env conventions as train_survival_from_embeddings)
try:
    from train_survival_from_embeddings import (
        load_labels_csv,
        load_slide_vectors_csv,
        load_slide_vectors_from_dir,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from train_survival_from_embeddings import (
        load_labels_csv,
        load_slide_vectors_csv,
        load_slide_vectors_from_dir,
    )


def _path_from_env(*names: str) -> Path | None:
    for n in names:
        v = os.getenv(n, "").strip()
        if v:
            return Path(v).expanduser()
    return None


def _case_ids_from_csv(path: Path, case_col: str = "case_id") -> list[str]:
    rows = load_labels_csv(path)
    return list({(r.get(case_col) or "").strip() for r in rows if (r.get(case_col) or "").strip()})


def _case_ids_from_embeddings_dir(embeddings_dir: Path) -> list[str]:
    """Derive case_ids from .npy stems (e.g. TCGA-xx-xxxx-DX1 -> TCGA-xx-xxxx)."""
    case_ids: set[str] = set()
    for p in embeddings_dir.rglob("*.npy"):
        if p.name.endswith("_coords.npy"):
            continue
        stem = p.stem
        if stem.upper().endswith("-DX1"):
            case_ids.add(stem[:-4])
        else:
            case_ids.add(stem)
    return sorted(case_ids)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build similar-patient index from slide/RNA embeddings.",
    )
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
        "--labels-csv",
        type=Path,
        default=None,
        help="Optional outcome labels CSV to restrict case_ids and order.",
    )
    parser.add_argument(
        "--cohort-csv",
        type=Path,
        default=None,
        help="Optional cohort CSV (case_id column) to restrict case_ids.",
    )
    parser.add_argument(
        "--rna-features-csv",
        type=Path,
        default=None,
        help="Optional RNA features CSV to concatenate for fused vectors.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "models/similar_patient_index",
        help="Output directory for index and case_id mapping.",
    )
    parser.add_argument(
        "--metric",
        choices=["l2", "cosine"],
        default="l2",
        help="Distance metric: l2 (L2) or cosine (vectors normalized, IndexFlatIP).",
    )
    args = parser.parse_args()

    try:
        import numpy as np
    except ImportError:
        print("numpy is required. pip install numpy", file=sys.stderr)
        return 1

    # Resolve case_ids and slide vectors
    if args.slide_vectors_csv and args.slide_vectors_csv.is_file():
        slide_vectors = load_slide_vectors_csv(args.slide_vectors_csv)
        case_ids_ordered = list(slide_vectors.keys())
    else:
        emb_dir = args.embeddings_dir or _path_from_env("ENSO_EMBEDDINGS_DIR", "LUAD_AUDIT_EMBEDDINGS_DIR") or (REPO_ROOT / "data/luad/embeddings/level0")
        if not emb_dir.is_dir():
            print(f"Embeddings dir not found: {emb_dir}. Use --embeddings-dir or --slide-vectors-csv.", file=sys.stderr)
            return 1
        if args.labels_csv and args.labels_csv.is_file():
            case_ids_ordered = _case_ids_from_csv(args.labels_csv)
        elif args.cohort_csv and args.cohort_csv.is_file():
            case_ids_ordered = _case_ids_from_csv(args.cohort_csv)
        else:
            case_ids_ordered = _case_ids_from_embeddings_dir(emb_dir)
        slide_vectors = load_slide_vectors_from_dir(emb_dir, case_ids_ordered)
        # Keep order of case_ids that have vectors
        case_ids_ordered = [c for c in case_ids_ordered if c in slide_vectors]

    if not slide_vectors:
        print("No slide vectors found.", file=sys.stderr)
        return 1

    # Optional RNA fusion
    rna_features: dict[str, np.ndarray] | None = None
    if args.rna_features_csv and args.rna_features_csv.is_file():
        rna_features = load_slide_vectors_csv(args.rna_features_csv, case_col="case_id")

    # Build matrix in stable order (case_ids_ordered, then drop missing RNA if fused)
    if rna_features:
        case_ids_ordered = [c for c in case_ids_ordered if c in slide_vectors and c in rna_features]
        if not case_ids_ordered:
            print("No cases with both slide and RNA features.", file=sys.stderr)
            return 1
        vectors = np.stack([
            np.concatenate([slide_vectors[c], rna_features[c]]) for c in case_ids_ordered
        ]).astype(np.float32)
    else:
        case_ids_ordered = [c for c in case_ids_ordered if c in slide_vectors]
        vectors = np.stack([slide_vectors[c] for c in case_ids_ordered]).astype(np.float32)

    n, dim = vectors.shape
    if args.metric == "cosine":
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1
        vectors = vectors / norms

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Save vectors for query-time lookup (query script needs the row vector for the case_id)
    np.save(args.out_dir / "vectors.npy", vectors)

    # Build index: FAISS or fallback
    use_faiss = False
    try:
        import faiss
        use_faiss = True
    except ImportError:
        pass

    if use_faiss:
        if args.metric == "cosine":
            index = faiss.IndexFlatIP(dim)
        else:
            index = faiss.IndexFlatL2(dim)
        index.add(vectors)
        faiss.write_index(index, str(args.out_dir / "faiss.index"))
        index_path = "faiss.index"
    else:
        # Fallback: save vectors and use flat index marker
        np.save(args.out_dir / "vectors.npy", vectors)
        index_path = "vectors.npy"

    # Mapping: index dimension 0 corresponds to case_ids[i]
    with (args.out_dir / "case_ids.json").open("w", encoding="utf-8") as f:
        json.dump(case_ids_ordered, f, indent=0)
    with (args.out_dir / "config.json").open("w", encoding="utf-8") as f:
        json.dump(
            {"metric": args.metric, "index_path": index_path, "dim": dim, "n_cases": n, "vectors_npy": "vectors.npy"},
            f,
            indent=2,
        )

    print(f"Indexed {n} cases, dimension {dim}")
    print(f"Index: {args.out_dir / index_path}")
    print(f"Mapping: {args.out_dir / 'case_ids.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
