#!/usr/bin/env python3
"""Build pathology artifact JSON bundles from SegLungTCGA segmented PNG mosaics.

Outputs follow the backend contract used by apps/api/services/pathology.py:
- tissue_composition
- heatmap
- evidence

Optional: copy SegLung PNG mosaics into a heatmap assets directory using
`<slide_id>_attention.png` naming so `/v1/pathology/slides/{slide_id}/heatmap/image`
can resolve real files immediately.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class MappingRow:
    seglung_file_id: str
    tcga_file_id: str
    patient_id: str


# Approximate class colors observed in SegLungTCGA mosaics.
PALETTE = [
    ("Background", np.array([0, 0, 0], dtype=np.int32)),
    ("Tumor", np.array([232, 72, 32], dtype=np.int32)),
    ("Stroma", np.array([72, 168, 40], dtype=np.int32)),
    ("Mixed", np.array([240, 184, 40], dtype=np.int32)),
    ("Vessel", np.array([184, 48, 152], dtype=np.int32)),
    ("Necrosis", np.array([136, 136, 136], dtype=np.int32)),
    ("Lung", np.array([0, 0, 128], dtype=np.int32)),
    ("Lymphocyte-rich", np.array([40, 144, 184], dtype=np.int32)),
    ("Bronchi", np.array([248, 216, 200], dtype=np.int32)),
]

LABEL_TO_INDEX = {label: i for i, (label, _) in enumerate(PALETTE)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seglung-dir",
        type=Path,
        required=True,
        help="Directory containing SegLungTCGA PNG files (uuid.png)",
    )
    parser.add_argument(
        "--mapping-csv",
        type=Path,
        required=True,
        help="SegLung mapping CSV (seglung_file_id, tcga_file_id, patient_id)",
    )
    parser.add_argument(
        "--out-artifacts-dir",
        type=Path,
        required=True,
        help="Output directory for pathology artifact JSON bundles",
    )
    parser.add_argument(
        "--out-heatmap-dir",
        type=Path,
        default=None,
        help="Optional output dir for copied heatmap PNG assets (<slide_id>_attention.png)",
    )
    parser.add_argument(
        "--tile-px",
        type=int,
        default=160,
        help="Coarse tile size for evidence hotspot extraction (default: 160)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of rows to process (0=all)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    return parser.parse_args()


def load_mapping_rows(path: Path) -> list[MappingRow]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        expected = {"seglung_file_id", "tcga_file_id", "patient_id"}
        missing = expected - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"Mapping CSV missing required columns: {sorted(missing)}")

        rows: list[MappingRow] = []
        for raw in reader:
            seglung_file_id = (raw.get("seglung_file_id") or "").strip()
            tcga_file_id = (raw.get("tcga_file_id") or "").strip()
            patient_id = (raw.get("patient_id") or "").strip().upper()
            if not seglung_file_id or not patient_id:
                continue
            rows.append(
                MappingRow(
                    seglung_file_id=seglung_file_id,
                    tcga_file_id=tcga_file_id,
                    patient_id=patient_id,
                )
            )
    return rows


def classify_pixels(rgb: np.ndarray) -> np.ndarray:
    """Map each pixel to nearest palette color index."""
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise RuntimeError(f"Expected RGB image, got shape {rgb.shape}")

    rgb_i32 = rgb.astype(np.int32)
    height, width, _ = rgb_i32.shape
    best_index = np.zeros((height, width), dtype=np.uint8)
    best_distance = np.full((height, width), np.iinfo(np.int64).max, dtype=np.int64)

    for idx, (_, color) in enumerate(PALETTE):
        diff = rgb_i32 - color
        dist = (diff[:, :, 0].astype(np.int64) ** 2) + (diff[:, :, 1].astype(np.int64) ** 2) + (
            diff[:, :, 2].astype(np.int64) ** 2
        )
        mask = dist < best_distance
        best_distance[mask] = dist[mask]
        best_index[mask] = idx

    return best_index


def compute_tissue_fractions(labels: np.ndarray) -> tuple[list[dict[str, float]], float]:
    counts = np.bincount(labels.reshape(-1), minlength=len(PALETTE)).astype(np.int64)

    background = counts[LABEL_TO_INDEX["Background"]]
    total_pixels = int(counts.sum())
    non_background = max(0, total_pixels - int(background))
    coverage = 0.0 if total_pixels <= 0 else float(non_background / total_pixels)

    tumor = int(counts[LABEL_TO_INDEX["Tumor"]])
    necrosis = int(counts[LABEL_TO_INDEX["Necrosis"]])
    lymph = int(counts[LABEL_TO_INDEX["Lymphocyte-rich"]])
    stroma = int(
        counts[LABEL_TO_INDEX["Stroma"]]
        + counts[LABEL_TO_INDEX["Mixed"]]
        + counts[LABEL_TO_INDEX["Vessel"]]
        + counts[LABEL_TO_INDEX["Lung"]]
        + counts[LABEL_TO_INDEX["Bronchi"]]
    )

    denominator = max(1, tumor + stroma + necrosis + lymph)
    fractions = [
        {"tissue": "Tumor", "fraction": round(tumor / denominator, 6)},
        {"tissue": "Stroma", "fraction": round(stroma / denominator, 6)},
        {"tissue": "Necrosis", "fraction": round(necrosis / denominator, 6)},
        {"tissue": "Lymphocyte-rich", "fraction": round(lymph / denominator, 6)},
    ]
    return fractions, round(coverage, 6)


def compute_viewport_hint(labels: np.ndarray) -> dict[str, float]:
    height, width = labels.shape
    if height <= 0 or width <= 0:
        return {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}

    non_bg_mask = labels != LABEL_TO_INDEX["Background"]
    ys, xs = np.where(non_bg_mask)
    if ys.size == 0 or xs.size == 0:
        return {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}

    x0 = int(xs.min())
    x1 = int(xs.max())
    y0 = int(ys.min())
    y1 = int(ys.max())

    return {
        "x": round(x0 / width, 6),
        "y": round(y0 / height, 6),
        "width": round(max(1, (x1 - x0 + 1)) / width, 6),
        "height": round(max(1, (y1 - y0 + 1)) / height, 6),
    }


def _tile_rationale(dominant_label: str) -> str:
    if dominant_label == "Tumor":
        return "Tumor-dominant hotspot from SegLungTCGA segmentation"
    if dominant_label == "Lymphocyte-rich":
        return "Immune-rich hotspot from SegLungTCGA segmentation"
    if dominant_label == "Necrosis":
        return "Necrotic hotspot from SegLungTCGA segmentation"
    return "Tissue hotspot from SegLungTCGA segmentation"


def compute_evidence_tiles(labels: np.ndarray, tile_px: int) -> list[dict[str, object]]:
    height, width = labels.shape
    tile_px = max(32, int(tile_px))
    rows = math.ceil(height / tile_px)
    cols = math.ceil(width / tile_px)

    candidates: list[dict[str, object]] = []
    for row in range(rows):
        y0 = row * tile_px
        y1 = min(height, y0 + tile_px)
        for col in range(cols):
            x0 = col * tile_px
            x1 = min(width, x0 + tile_px)
            cell = labels[y0:y1, x0:x1]
            if cell.size == 0:
                continue

            counts = np.bincount(cell.reshape(-1), minlength=len(PALETTE)).astype(np.float64)
            total = counts.sum()
            if total <= 0:
                continue

            tumor_f = counts[LABEL_TO_INDEX["Tumor"]] / total
            lymph_f = counts[LABEL_TO_INDEX["Lymphocyte-rich"]] / total
            nec_f = counts[LABEL_TO_INDEX["Necrosis"]] / total

            score = float((0.65 * tumor_f) + (0.25 * lymph_f) - (0.15 * nec_f))
            if score <= 0.02:
                continue

            dominant_idx = int(np.argmax(counts))
            dominant_label = PALETTE[dominant_idx][0]

            bbox = {
                "x": round(x0 / width, 6),
                "y": round(y0 / height, 6),
                "width": round((x1 - x0) / width, 6),
                "height": round((y1 - y0) / height, 6),
            }

            candidates.append(
                {
                    "tile_id": f"r{row + 1:02d}_c{col + 1:02d}",
                    "score": round(max(0.0, min(1.0, score)), 6),
                    "rationale": _tile_rationale(dominant_label),
                    "bbox": bbox,
                    "tile_coordinates": {
                        "row": row + 1,
                        "col": col + 1,
                        "one_based_index": True,
                    },
                }
            )

    if not candidates:
        return []

    candidates.sort(key=lambda item: (-float(item["score"]), str(item["tile_id"])))
    return candidates[:8]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()

    seglung_dir = args.seglung_dir.expanduser().resolve()
    mapping_csv = args.mapping_csv.expanduser().resolve()
    out_artifacts_dir = args.out_artifacts_dir.expanduser().resolve()
    out_heatmap_dir = args.out_heatmap_dir.expanduser().resolve() if args.out_heatmap_dir else None

    if not seglung_dir.is_dir():
        raise RuntimeError(f"SegLung dir not found: {seglung_dir}")
    if not mapping_csv.is_file():
        raise RuntimeError(f"Mapping CSV not found: {mapping_csv}")

    rows = load_mapping_rows(mapping_csv)
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    out_artifacts_dir.mkdir(parents=True, exist_ok=True)
    if out_heatmap_dir:
        out_heatmap_dir.mkdir(parents=True, exist_ok=True)

    # ensure deterministic slide ids when patients have multiple SegLung files
    patient_counts: dict[str, int] = defaultdict(int)

    processed = 0
    skipped_missing_png = 0
    for row in rows:
        png_path = seglung_dir / f"{row.seglung_file_id}.png"
        if not png_path.is_file():
            skipped_missing_png += 1
            continue

        patient_counts[row.patient_id] += 1
        dx_index = patient_counts[row.patient_id]
        slide_id = f"{row.patient_id}-DX{dx_index}"

        artifact_path = out_artifacts_dir / f"{slide_id}.json"
        if artifact_path.exists() and not args.overwrite:
            continue

        rgb = np.array(Image.open(png_path).convert("RGB"))
        labels = classify_pixels(rgb)

        fractions, coverage = compute_tissue_fractions(labels)
        viewport_hint = compute_viewport_hint(labels)
        top_tiles = compute_evidence_tiles(labels, tile_px=args.tile_px)

        provenance = {
            "data_source": "seglung",
            "model_id": "seglung-tcga-v2021",
            "tile_encoder_model_id": "google/path-foundation",
            "run_id": f"seglung:{row.seglung_file_id}",
            "embedding_source_id": row.seglung_file_id,
            "source_dataset": "SegLungTCGA",
            "source_tcga_file_id": row.tcga_file_id,
            "source_png_sha256": file_sha256(png_path),
            "source_png_path": str(png_path),
        }

        payload = {
            "case_id": row.patient_id,
            "slide_id": slide_id,
            "provenance": provenance,
            "tissue_composition": {
                "fractions": fractions,
                "qc": {
                    "coverage": coverage,
                    "artifact_warning": "Derived from SegLungTCGA pre-segmented mosaic",
                },
                "provenance": provenance,
            },
            "heatmap": {
                "viewport_hint": viewport_hint,
                "provenance": provenance,
            },
            "evidence": {
                "top_tiles": top_tiles,
                "provenance": provenance,
            },
        }

        artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        if out_heatmap_dir is not None:
            destination = out_heatmap_dir / f"{slide_id}_attention.png"
            if args.overwrite or not destination.exists():
                shutil.copy2(png_path, destination)

        processed += 1

    summary = {
        "rows_considered": len(rows),
        "artifacts_written": processed,
        "missing_png_rows": skipped_missing_png,
        "output_artifacts_dir": str(out_artifacts_dir),
        "output_heatmap_dir": str(out_heatmap_dir) if out_heatmap_dir else None,
        "unique_patients_processed": len(patient_counts),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
