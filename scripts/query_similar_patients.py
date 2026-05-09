#!/usr/bin/env python3
"""Query similar patients by case_id from an index built by build_similar_patient_index.py.

Loads index and case_id mapping from --index-dir, finds the row for --case-id,
returns top-k nearest neighbors (excluding self) as JSON to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query similar patients by embedding distance.",
    )
    parser.add_argument(
        "--index-dir",
        type=Path,
        required=True,
        help="Directory containing faiss.index (or vectors.npy), case_ids.json, and config.json.",
    )
    parser.add_argument(
        "--case-id",
        type=str,
        required=True,
        help="Case ID to find similar patients for.",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=5,
        help="Number of similar patients to return (default 5).",
    )
    args = parser.parse_args()

    index_dir = args.index_dir.resolve()
    if not index_dir.is_dir():
        print(f"Index dir not found: {index_dir}", file=sys.stderr)
        return 1

    case_ids_path = index_dir / "case_ids.json"
    config_path = index_dir / "config.json"
    vectors_path = index_dir / "vectors.npy"
    if not case_ids_path.is_file():
        print(f"case_ids.json not found in {index_dir}", file=sys.stderr)
        return 1
    if not config_path.is_file():
        print(f"config.json not found in {index_dir}", file=sys.stderr)
        return 1
    if not vectors_path.is_file():
        print(f"vectors.npy not found in {index_dir}", file=sys.stderr)
        return 1

    try:
        import numpy as np
    except ImportError:
        print("numpy is required. pip install numpy", file=sys.stderr)
        return 1

    with case_ids_path.open("r", encoding="utf-8") as f:
        case_ids = json.load(f)
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    case_id_to_idx = {c: i for i, c in enumerate(case_ids)}
    if args.case_id not in case_id_to_idx:
        print(f"case_id not in index: {args.case_id}", file=sys.stderr)
        return 1

    idx = case_id_to_idx[args.case_id]
    vectors = np.load(vectors_path, allow_pickle=False).astype(np.float32)
    query = vectors[idx : idx + 1]
    n, dim = vectors.shape

    k_actual = min(args.k + 1, n)  # +1 to include self, then drop self

    index_path = config.get("index_path", "faiss.index")
    metric = config.get("metric", "l2")
    use_faiss = (index_path == "faiss.index") and (index_dir / index_path).is_file()

    if use_faiss:
        try:
            import faiss
            index = faiss.read_index(str(index_dir / index_path))
            if metric == "cosine":
                D, I = index.search(query, k_actual)
                distances = (1.0 - D[0]).tolist()
            else:
                D, I = index.search(query, k_actual)
                distances = D[0].tolist()
            indices = I[0].tolist()
        except Exception:
            use_faiss = False

    if not use_faiss:
        # Fallback: sklearn pairwise distances
        from sklearn.metrics.pairwise import pairwise_distances
        if metric == "cosine":
            dist = pairwise_distances(query, vectors, metric="cosine")[0]
        else:
            dist = pairwise_distances(query, vectors, metric="euclidean")[0]
        indices = np.argsort(dist)[:k_actual].tolist()
        distances = [float(dist[i]) for i in indices]

    # Exclude self and take top k
    similar_list = []
    for i, (pos, d) in enumerate(zip(indices, distances)):
        if pos == idx:
            continue
        if len(similar_list) >= args.k:
            break
        similar_list.append({"case_id": case_ids[pos], "distance": round(d, 6)})

    out = {"case_id": args.case_id, "similar": similar_list}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
