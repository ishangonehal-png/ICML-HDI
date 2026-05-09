#!/usr/bin/env python3
"""Deterministic pathology-data coverage audit for TCGA-LUAD full475.

This script audits manifest↔embedding↔artifact alignment and emits deterministic
CSV/JSON reports suitable for release gating.

Per manifest slide, outputs include:
- embedding presence and embedding file count
- patch count aggregates (total/max across embedding arrays)
- coordinate sidecar presence
- artifact presence and artifact section completeness
- tissue fractions (Tumor/Stroma/Necrosis/Lymphocyte-rich)

Summary output includes:
- missing embedding slide ids
- missing artifact slide ids
- orphan embedding ids (embedding ids not in manifest)
- patch-count read errors
- deterministic rows digest
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

TCGA_FULL475_ROOT_ENV = "TCGA_FULL475_ROOT"
DEFAULT_MANIFEST_ENV = "LUAD_AUDIT_MANIFEST"
DEFAULT_EMBEDDINGS_DIR_ENV = "LUAD_AUDIT_EMBEDDINGS_DIR"
DEFAULT_ARTIFACTS_DIR_ENV = "LUAD_AUDIT_ARTIFACTS_DIR"

# Backward-compatible aliases used in API runtime config.
EMBEDDINGS_DIR_ENV_ALIASES = ("ENSO_EMBEDDINGS_DIR",)
ARTIFACTS_DIR_ENV_ALIASES = ("PATHOLOGY_ARTIFACT_DIR",)

DEFAULT_MANIFEST_RELATIVE = Path(
    "hansons-context/tcga_downloads/tcga_luad_exact_matched_manifest_slides.tsv"
)
DEFAULT_EMBEDDINGS_DIR_RELATIVE = Path("data/luad/embeddings/level0")
DEFAULT_ARTIFACTS_DIR_RELATIVE = Path("data/pathology_artifacts/full475")

DEFAULT_OUT_CSV_NAME = "luad_embedding_coverage_audit.csv"
DEFAULT_OUT_JSON_NAME = "luad_embedding_coverage_summary.json"

TARGET_TISSUE_ORDER = (
    "Tumor",
    "Stroma",
    "Necrosis",
    "Lymphocyte-rich",
)

SLIDE_LIKE_SUFFIXES = {
    ".svs",
    ".tif",
    ".tiff",
    ".ndpi",
    ".mrxs",
    ".scn",
    ".vms",
    ".vmu",
    ".bif",
    ".qptiff",
    ".isyntax",
}

KNOWN_SUFFIXES = {
    # arrays
    ".npy",
    ".npz",
    # image/slide suffixes
    *SLIDE_LIKE_SUFFIXES,
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    # metadata/text formats
    ".json",
    ".csv",
    ".tsv",
    ".txt",
    ".parquet",
    ".pkl",
    ".pickle",
    # compression wrappers
    ".gz",
    ".bz2",
    ".xz",
    ".zip",
}

CASE_ID_PATTERN = re.compile(r"(TCGA-[A-Za-z0-9]+-[A-Za-z0-9]+)", re.IGNORECASE)
DX_TOKEN_PATTERN = re.compile(r"(DX[0-9A-Za-z]+)", re.IGNORECASE)
NON_ALNUM_DASH_PATTERN = re.compile(r"[^A-Za-z0-9-]+")
MULTI_DASH_PATTERN = re.compile(r"-+")


def _path_from_env(*env_names: str) -> Path | None:
    for env_name in env_names:
        raw_value = os.getenv(env_name, "").strip()
        if raw_value:
            return Path(raw_value).expanduser()
    return None


def _tcga_full475_root() -> Path | None:
    return _path_from_env(TCGA_FULL475_ROOT_ENV)


def default_manifest_path() -> Path:
    explicit = _path_from_env(DEFAULT_MANIFEST_ENV)
    if explicit is not None:
        return explicit

    tcga_root = _tcga_full475_root()
    if tcga_root is not None:
        return tcga_root / "tcga_luad_exact_matched_manifest_slides.tsv"

    return REPO_ROOT / DEFAULT_MANIFEST_RELATIVE


def default_embeddings_dir() -> Path:
    explicit = _path_from_env(DEFAULT_EMBEDDINGS_DIR_ENV, *EMBEDDINGS_DIR_ENV_ALIASES)
    if explicit is not None:
        return explicit

    tcga_root = _tcga_full475_root()
    if tcga_root is not None:
        return tcga_root / "embeddings" / "level0"

    return REPO_ROOT / DEFAULT_EMBEDDINGS_DIR_RELATIVE


def default_artifacts_dir() -> Path:
    explicit = _path_from_env(DEFAULT_ARTIFACTS_DIR_ENV, *ARTIFACTS_DIR_ENV_ALIASES)
    if explicit is not None:
        return explicit

    tcga_root = _tcga_full475_root()
    if tcga_root is not None:
        return tcga_root / "pathology_artifacts" / "full475"

    return REPO_ROOT / DEFAULT_ARTIFACTS_DIR_RELATIVE


# Backward-compatible module-level defaults used by sibling scripts.
DEFAULT_MANIFEST = default_manifest_path()
DEFAULT_EMBEDDINGS_DIR = default_embeddings_dir()
DEFAULT_ARTIFACTS_DIR = default_artifacts_dir()


@dataclass(frozen=True)
class ManifestSlide:
    row_index: int
    source_column: str
    source_value: str
    slide_id: str
    case_id: str


@dataclass(frozen=True)
class EmbeddingFileStat:
    path: Path
    slide_id: str
    patch_count: int | None
    patch_count_error: str | None


@dataclass(frozen=True)
class ArtifactRecord:
    path: Path
    slide_id: str
    case_id: str
    tissue_fractions: dict[str, float]
    has_tissue_composition: bool
    has_heatmap: bool
    has_evidence: bool
    is_symlink: bool


def normalize_identifier(value: str) -> str:
    token = value.strip().upper()
    if not token:
        return ""
    token = NON_ALNUM_DASH_PATTERN.sub("-", token)
    token = MULTI_DASH_PATTERN.sub("-", token)
    return token.strip("-")


def strip_known_suffixes(value: str) -> str:
    """Remove known multi-extension wrappers (e.g. .svs.npy → stem)."""
    stem = Path(value).name
    while True:
        suffix = Path(stem).suffix.lower()
        if not suffix or suffix not in KNOWN_SUFFIXES:
            break
        stem = Path(stem).stem
    return stem


def extract_case_id(value: str) -> str:
    token = strip_known_suffixes(value)
    match = CASE_ID_PATTERN.search(token)
    if match is None:
        return ""
    return normalize_identifier(match.group(1))


def extract_dx_token(value: str) -> str:
    token = strip_known_suffixes(value)
    match = DX_TOKEN_PATTERN.search(token)
    if match is None:
        return ""
    return normalize_identifier(match.group(1))


def canonical_slide_id(value: str) -> str:
    token = strip_known_suffixes(value)
    case_id = extract_case_id(token)
    dx_token = extract_dx_token(token)

    if case_id and dx_token:
        return f"{case_id}-{dx_token}"

    normalized = normalize_identifier(token)
    if case_id:
        # Keep token-level specificity when available, otherwise fall back to case id.
        return normalized or case_id
    return normalized


def best_slide_id_from_path(path: Path) -> str:
    candidates = [path.name, path.stem, path.parent.name]
    resolved = [canonical_slide_id(candidate) for candidate in candidates if candidate]

    # Prefer case+DX ids when available.
    for candidate in resolved:
        if "TCGA-" in candidate and "-DX" in candidate:
            return candidate

    for candidate in resolved:
        if candidate.startswith("TCGA-"):
            return candidate

    for candidate in resolved:
        if candidate:
            return candidate

    return ""


def choose_manifest_slide_source(row: dict[str, str]) -> tuple[str, str]:
    preferred_columns = (
        "slide_id",
        "selected_slide_file_name",
        "selected_slide_filename",
        "filename",
        "file_name",
        "path",
        "source_path",
        "id",
    )

    def _is_slide_like(text: str) -> bool:
        upper = text.upper()
        suffix = Path(text).suffix.lower()
        return "TCGA" in upper or "DX" in upper or suffix in SLIDE_LIKE_SUFFIXES

    for column in preferred_columns:
        value = (row.get(column) or "").strip()
        if value and _is_slide_like(value):
            return column, value

    for column in preferred_columns:
        value = (row.get(column) or "").strip()
        if value:
            return column, value

    for column, value in row.items():
        candidate = (value or "").strip()
        if candidate and _is_slide_like(candidate):
            return column, candidate

    for column, value in row.items():
        candidate = (value or "").strip()
        if candidate:
            return column, candidate

    return "", ""


def detect_delimiter(path: Path) -> str:
    if path.suffix.lower() == ".tsv":
        return "\t"

    with path.open("r", encoding="utf-8", newline="") as handle:
        sample = handle.read(4096)

    try:
        return csv.Sniffer().sniff(sample, delimiters="\t,").delimiter
    except csv.Error:
        return "\t" if "\t" in sample else ","


def load_manifest_slides(manifest_path: Path) -> list[ManifestSlide]:
    if not manifest_path.is_file():
        raise RuntimeError(f"Manifest file not found: {manifest_path}")

    delimiter = detect_delimiter(manifest_path)
    slides: list[ManifestSlide] = []

    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if reader.fieldnames is None:
            raise RuntimeError(f"Manifest has no header row: {manifest_path}")

        for row_index, row in enumerate(reader, start=1):
            source_column, source_value = choose_manifest_slide_source(row)
            if not source_value:
                raise RuntimeError(
                    f"Could not resolve slide identifier for manifest row {row_index}."
                )

            slide_id = canonical_slide_id(source_value)
            case_id = extract_case_id(source_value) or extract_case_id(slide_id)

            slides.append(
                ManifestSlide(
                    row_index=row_index,
                    source_column=source_column,
                    source_value=source_value,
                    slide_id=slide_id,
                    case_id=case_id,
                )
            )

    return slides


def is_coords_filename(path: Path) -> bool:
    return "coord" in path.name.lower()


def read_patch_count_from_npy(path: Path) -> tuple[int | None, str | None]:
    """Best-effort patch count loading.

    NumPy import is lazy so the script can still run in lightweight environments
    that only need presence/orphan auditing.
    """
    try:
        import numpy as np  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - environment dependent
        return None, f"numpy unavailable ({type(exc).__name__})"

    try:
        array = np.load(path, mmap_mode="r", allow_pickle=False)
    except Exception as exc:  # noqa: BLE001 - robust audit flow on edge files
        return None, str(exc)

    shape = getattr(array, "shape", None)
    if shape is None:
        return None, "array shape unavailable"

    if len(shape) == 0:
        return 1, None

    return int(shape[0]), None


def collect_embedding_files(
    embeddings_dir: Path,
) -> tuple[
    dict[str, list[EmbeddingFileStat]],
    dict[str, int],
    list[str],
    int,
]:
    embedding_files_by_slide: dict[str, list[EmbeddingFileStat]] = defaultdict(list)
    coords_files_count_by_slide: dict[str, int] = defaultdict(int)
    patch_count_errors: list[str] = []
    embedding_files_total = 0

    if not embeddings_dir.is_dir():
        print(
            f"WARN: Embeddings directory not found (treating as empty): {embeddings_dir}",
            file=sys.stderr,
        )
        return embedding_files_by_slide, coords_files_count_by_slide, patch_count_errors, 0

    for npy_path in sorted(embeddings_dir.rglob("*.npy")):
        slide_id = best_slide_id_from_path(npy_path)
        if not slide_id:
            continue

        if is_coords_filename(npy_path):
            coords_files_count_by_slide[slide_id] += 1
            continue

        patch_count, patch_count_error = read_patch_count_from_npy(npy_path)
        embedding_files_total += 1

        if patch_count_error:
            patch_count_errors.append(f"{npy_path}: {patch_count_error}")

        embedding_files_by_slide[slide_id].append(
            EmbeddingFileStat(
                path=npy_path,
                slide_id=slide_id,
                patch_count=patch_count,
                patch_count_error=patch_count_error,
            )
        )

    return (
        embedding_files_by_slide,
        coords_files_count_by_slide,
        sorted(patch_count_errors),
        embedding_files_total,
    )


def has_neighbor_coords_file(embedding_path: Path) -> bool:
    parent = embedding_path.parent
    stem = embedding_path.stem

    candidate_stems = {
        f"{stem}_coords",
        f"{stem}.coords",
        f"{stem}_coordinates",
        f"{stem}_xy",
    }

    substitution_pairs = (
        ("embeddings", "coords"),
        ("embedding", "coords"),
        ("features", "coords"),
        ("feature", "coords"),
        ("emb", "coords"),
    )

    lower_stem = stem.lower()
    for source, target in substitution_pairs:
        if source in lower_stem:
            candidate_stems.add(re.sub(source, target, stem, flags=re.IGNORECASE))

    candidate_suffixes = (".npy", ".npz", ".csv", ".json", ".txt", ".parquet")

    for candidate_stem in candidate_stems:
        for suffix in candidate_suffixes:
            candidate_path = parent / f"{candidate_stem}{suffix}"
            if candidate_path.is_file():
                return True

    return False


def load_json_if_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    return payload


def normalize_tissue_key(value: str) -> str:
    token = value.strip().lower().replace("_", " ").replace("-", " ")
    token = " ".join(token.split())

    if token == "tumor":
        return "Tumor"
    if token == "stroma":
        return "Stroma"
    if token == "necrosis":
        return "Necrosis"
    if token in {"lymphocyte rich", "lymphocyte rich area", "lymphocyte"}:
        return "Lymphocyte-rich"

    return ""


def extract_tissue_fractions(payload: dict[str, Any]) -> dict[str, float]:
    section = payload.get("tissue_composition")
    if not isinstance(section, dict):
        return {}

    fractions = section.get("fractions")
    if not isinstance(fractions, list):
        return {}

    resolved: dict[str, float] = {}
    for item in fractions:
        if not isinstance(item, dict):
            continue

        tissue_name = normalize_tissue_key(str(item.get("tissue", "")))
        if not tissue_name:
            continue

        raw_fraction = item.get("fraction")
        try:
            fraction = float(raw_fraction)
        except (TypeError, ValueError):
            continue

        resolved[tissue_name] = fraction

    return resolved


def _artifact_section_presence(payload: dict[str, Any]) -> tuple[bool, bool, bool]:
    return (
        isinstance(payload.get("tissue_composition"), dict),
        isinstance(payload.get("heatmap"), dict),
        isinstance(payload.get("evidence"), dict),
    )


def collect_artifacts(
    artifacts_dir: Path,
    *,
    excluded_json_filenames: set[str],
) -> tuple[dict[str, list[ArtifactRecord]], dict[str, list[ArtifactRecord]], list[ArtifactRecord]]:
    artifacts_by_slide: dict[str, list[ArtifactRecord]] = defaultdict(list)
    artifacts_by_case: dict[str, list[ArtifactRecord]] = defaultdict(list)
    all_artifacts: list[ArtifactRecord] = []

    if not artifacts_dir.exists():
        return artifacts_by_slide, artifacts_by_case, all_artifacts

    for json_path in sorted(artifacts_dir.rglob("*.json")):
        if json_path.name in excluded_json_filenames:
            continue

        payload = load_json_if_object(json_path)
        if payload is None:
            continue

        payload_slide = payload.get("slide_id")
        payload_case = payload.get("case_id")

        filename_slide_id = best_slide_id_from_path(json_path)
        slide_id = filename_slide_id
        if isinstance(payload_slide, str) and payload_slide.strip():
            payload_slide_id = canonical_slide_id(payload_slide)
            if payload_slide_id:
                slide_id = payload_slide_id

        case_id = extract_case_id(slide_id) or extract_case_id(json_path.name)
        if isinstance(payload_case, str) and payload_case.strip():
            payload_case_id = extract_case_id(payload_case)
            if payload_case_id:
                case_id = payload_case_id

        has_tissue_composition, has_heatmap, has_evidence = _artifact_section_presence(payload)

        artifact_record = ArtifactRecord(
            path=json_path,
            slide_id=slide_id,
            case_id=case_id,
            tissue_fractions=extract_tissue_fractions(payload),
            has_tissue_composition=has_tissue_composition,
            has_heatmap=has_heatmap,
            has_evidence=has_evidence,
            is_symlink=json_path.is_symlink(),
        )

        all_artifacts.append(artifact_record)

        if slide_id:
            artifacts_by_slide[slide_id].append(artifact_record)
        if case_id:
            artifacts_by_case[case_id].append(artifact_record)

    return artifacts_by_slide, artifacts_by_case, all_artifacts


def _path_depth(path: Path) -> int:
    return len(path.parts)


def resolve_artifact_for_slide(
    *,
    slide_id: str,
    case_id: str,
    artifacts_by_slide: dict[str, list[ArtifactRecord]],
    artifacts_by_case: dict[str, list[ArtifactRecord]],
) -> ArtifactRecord | None:
    candidates: list[ArtifactRecord] = []
    seen_paths: set[Path] = set()

    for record in artifacts_by_slide.get(slide_id, []):
        if record.path in seen_paths:
            continue
        seen_paths.add(record.path)
        candidates.append(record)

    for record in artifacts_by_case.get(case_id, []):
        if record.path in seen_paths:
            continue
        seen_paths.add(record.path)
        candidates.append(record)

    if not candidates:
        return None

    def score(record: ArtifactRecord) -> tuple[int, int, int, int, int, str]:
        exact_slide_match_rank = 0 if record.slide_id == slide_id else 1
        has_complete_sections_rank = 0 if (
            record.has_tissue_composition and record.has_heatmap and record.has_evidence
        ) else 1
        has_tissue_rank = 0 if record.tissue_fractions else 1
        symlink_rank = 1 if record.is_symlink else 0
        depth_rank = _path_depth(record.path)
        return (
            exact_slide_match_rank,
            has_complete_sections_rank,
            has_tissue_rank,
            symlink_rank,
            depth_rank,
            record.path.as_posix().lower(),
        )

    return sorted(candidates, key=score)[0]


def build_audit_rows(
    *,
    manifest_slides: list[ManifestSlide],
    embedding_files_by_slide: dict[str, list[EmbeddingFileStat]],
    coords_files_count_by_slide: dict[str, int],
    artifacts_by_slide: dict[str, list[ArtifactRecord]],
    artifacts_by_case: dict[str, list[ArtifactRecord]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for slide in manifest_slides:
        embedding_files = embedding_files_by_slide.get(slide.slide_id, [])
        embedding_files_count = len(embedding_files)

        patch_counts = [
            file_stat.patch_count
            for file_stat in embedding_files
            if file_stat.patch_count is not None
        ]
        patch_count_total = int(sum(patch_counts)) if patch_counts else 0
        patch_count_max = int(max(patch_counts)) if patch_counts else 0

        coords_files_count = coords_files_count_by_slide.get(slide.slide_id, 0)
        coords_file_present = coords_files_count > 0
        if not coords_file_present and embedding_files:
            coords_file_present = any(has_neighbor_coords_file(file_stat.path) for file_stat in embedding_files)

        has_embedding = embedding_files_count > 0

        artifact = resolve_artifact_for_slide(
            slide_id=slide.slide_id,
            case_id=slide.case_id,
            artifacts_by_slide=artifacts_by_slide,
            artifacts_by_case=artifacts_by_case,
        )
        has_artifact = artifact is not None

        tissue_fractions = {tissue_name: None for tissue_name in TARGET_TISSUE_ORDER}
        if artifact is not None:
            for tissue_name, fraction in artifact.tissue_fractions.items():
                tissue_fractions[tissue_name] = fraction

        has_complete_artifact = bool(
            artifact
            and artifact.has_tissue_composition
            and artifact.has_heatmap
            and artifact.has_evidence
        )

        rows.append(
            {
                "manifest_row_index": slide.row_index,
                "manifest_source_column": slide.source_column,
                "manifest_source_value": slide.source_value,
                "slide_id": slide.slide_id,
                "case_id": slide.case_id,
                "embedding_files_count": embedding_files_count,
                "patch_count_total": patch_count_total,
                "patch_count_max": patch_count_max,
                "coords_files_count": coords_files_count,
                "coords_file_present": coords_file_present,
                "has_embedding": has_embedding,
                "has_artifact": has_artifact,
                "has_complete_artifact": has_complete_artifact,
                "artifact_path": str(artifact.path) if artifact is not None else "",
                "artifact_is_symlink": bool(artifact.is_symlink) if artifact is not None else False,
                "artifact_has_tissue_composition": bool(artifact.has_tissue_composition) if artifact else False,
                "artifact_has_heatmap": bool(artifact.has_heatmap) if artifact else False,
                "artifact_has_evidence": bool(artifact.has_evidence) if artifact else False,
                "tissue_fraction_tumor": tissue_fractions["Tumor"],
                "tissue_fraction_stroma": tissue_fractions["Stroma"],
                "tissue_fraction_necrosis": tissue_fractions["Necrosis"],
                "tissue_fraction_lymphocyte_rich": tissue_fractions["Lymphocyte-rich"],
            }
        )

    return rows


def write_audit_csv(rows: list[dict[str, Any]], out_csv_path: Path) -> None:
    out_csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "manifest_row_index",
        "manifest_source_column",
        "manifest_source_value",
        "slide_id",
        "case_id",
        "embedding_files_count",
        "patch_count_total",
        "patch_count_max",
        "coords_files_count",
        "coords_file_present",
        "has_embedding",
        "has_artifact",
        "has_complete_artifact",
        "artifact_path",
        "artifact_is_symlink",
        "artifact_has_tissue_composition",
        "artifact_has_heatmap",
        "artifact_has_evidence",
        "tissue_fraction_tumor",
        "tissue_fraction_stroma",
        "tissue_fraction_necrosis",
        "tissue_fraction_lymphocyte_rich",
    ]

    with out_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary_json(summary_payload: dict[str, Any], out_json_path: Path) -> None:
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(
        json.dumps(summary_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def rows_digest_sha256(rows: list[dict[str, Any]]) -> str:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        normalized_rows.append(
            {
                "manifest_row_index": row["manifest_row_index"],
                "slide_id": row["slide_id"],
                "case_id": row["case_id"],
                "embedding_files_count": row["embedding_files_count"],
                "patch_count_total": row["patch_count_total"],
                "patch_count_max": row["patch_count_max"],
                "coords_file_present": bool(row["coords_file_present"]),
                "has_embedding": bool(row["has_embedding"]),
                "has_artifact": bool(row["has_artifact"]),
                "has_complete_artifact": bool(row["has_complete_artifact"]),
                "artifact_path": row["artifact_path"],
            }
        )

    payload = json.dumps(normalized_rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return path.absolute()


def _validate_output_path(path: Path) -> None:
    if path.exists() and not path.is_file():
        raise RuntimeError(f"Output path exists but is not a file: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit LUAD manifest slides against embedding/artifact coverage.",
    )

    resolved_default_manifest = default_manifest_path()
    resolved_default_embeddings_dir = default_embeddings_dir()
    resolved_default_artifacts_dir = default_artifacts_dir()

    parser.add_argument(
        "--manifest",
        type=Path,
        default=resolved_default_manifest,
        help=(
            "Manifest slides TSV path "
            f"(default: {resolved_default_manifest}; env: {DEFAULT_MANIFEST_ENV} or {TCGA_FULL475_ROOT_ENV})"
        ),
    )
    parser.add_argument(
        "--embeddings-dir",
        type=Path,
        default=resolved_default_embeddings_dir,
        help=(
            "Embeddings directory containing .npy files "
            f"(default: {resolved_default_embeddings_dir}; env: {DEFAULT_EMBEDDINGS_DIR_ENV}, "
            f"{', '.join(EMBEDDINGS_DIR_ENV_ALIASES)} or {TCGA_FULL475_ROOT_ENV})"
        ),
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=resolved_default_artifacts_dir,
        help=(
            "Artifact directory containing pathology JSON files and where outputs will be written "
            f"(default: {resolved_default_artifacts_dir}; env: {DEFAULT_ARTIFACTS_DIR_ENV}, "
            f"{', '.join(ARTIFACTS_DIR_ENV_ALIASES)} or {TCGA_FULL475_ROOT_ENV})"
        ),
    )
    parser.add_argument(
        "--out-csv",
        type=Path,
        default=None,
        help=(
            "Optional explicit CSV output path. "
            "Defaults to <artifacts-dir>/luad_embedding_coverage_audit.csv"
        ),
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help=(
            "Optional explicit JSON output path. "
            "Defaults to <artifacts-dir>/luad_embedding_coverage_summary.json"
        ),
    )
    parser.add_argument(
        "--print-orphans",
        action="store_true",
        help="Print orphan embedding slide ids to stdout.",
    )
    parser.add_argument(
        "--expected-slide-count",
        type=int,
        default=None,
        help="Optional expected manifest slide count (for full475 use 475).",
    )
    parser.add_argument(
        "--fail-on-missing-embeddings",
        action="store_true",
        help="Exit non-zero when any manifest slide is missing embeddings.",
    )
    parser.add_argument(
        "--fail-on-missing-artifacts",
        action="store_true",
        help="Exit non-zero when any manifest slide is missing artifact JSON.",
    )
    parser.add_argument(
        "--fail-on-incomplete-artifacts",
        action="store_true",
        help="Exit non-zero when any artifact-backed slide is missing required sections.",
    )
    parser.add_argument(
        "--fail-on-orphan-embeddings",
        action="store_true",
        help="Exit non-zero when orphan embeddings are detected.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Enable all fail gates (missing embeddings/artifacts/incomplete artifacts/"
            "orphan embeddings) and treat expected slide mismatch as fatal when provided."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print report summary without writing CSV/JSON files.",
    )
    return parser.parse_args()


def _failure_reasons(
    *,
    summary: dict[str, Any],
    args: argparse.Namespace,
) -> list[str]:
    reasons: list[str] = []

    strict = bool(args.strict)
    fail_on_missing_embeddings = strict or bool(args.fail_on_missing_embeddings)
    fail_on_missing_artifacts = strict or bool(args.fail_on_missing_artifacts)
    fail_on_incomplete_artifacts = strict or bool(args.fail_on_incomplete_artifacts)
    fail_on_orphan_embeddings = strict or bool(args.fail_on_orphan_embeddings)

    if args.expected_slide_count is not None:
        if int(summary["slides_total"]) != int(args.expected_slide_count):
            reasons.append(
                f"slides_total={summary['slides_total']} does not match "
                f"expected_slide_count={args.expected_slide_count}"
            )

    if fail_on_missing_embeddings and int(summary["slides_missing_embeddings"]) > 0:
        reasons.append(
            f"slides_missing_embeddings={summary['slides_missing_embeddings']}"
        )

    if fail_on_missing_artifacts and int(summary["slides_missing_artifacts"]) > 0:
        reasons.append(
            f"slides_missing_artifacts={summary['slides_missing_artifacts']}"
        )

    if fail_on_incomplete_artifacts and int(summary["slides_missing_complete_artifacts"]) > 0:
        reasons.append(
            "slides_missing_complete_artifacts="
            f"{summary['slides_missing_complete_artifacts']}"
        )

    if fail_on_orphan_embeddings and int(summary["orphan_embedding_count"]) > 0:
        reasons.append(
            f"orphan_embedding_count={summary['orphan_embedding_count']}"
        )

    return reasons


def main() -> int:
    args = parse_args()

    manifest_path = args.manifest.expanduser().resolve()
    embeddings_dir = args.embeddings_dir.expanduser().resolve()
    artifacts_dir = args.artifacts_dir.expanduser().resolve()

    out_csv_path = (
        args.out_csv.expanduser().resolve()
        if args.out_csv is not None
        else artifacts_dir / DEFAULT_OUT_CSV_NAME
    )
    out_json_path = (
        args.out_json.expanduser().resolve()
        if args.out_json is not None
        else artifacts_dir / DEFAULT_OUT_JSON_NAME
    )

    _validate_output_path(out_csv_path)
    _validate_output_path(out_json_path)

    manifest_slides = load_manifest_slides(manifest_path)
    (
        embedding_files_by_slide,
        coords_files_count_by_slide,
        patch_count_errors,
        embedding_files_total,
    ) = collect_embedding_files(embeddings_dir)

    artifacts_by_slide, artifacts_by_case, all_artifacts = collect_artifacts(
        artifacts_dir,
        excluded_json_filenames={out_json_path.name},
    )

    audit_rows = build_audit_rows(
        manifest_slides=manifest_slides,
        embedding_files_by_slide=embedding_files_by_slide,
        coords_files_count_by_slide=coords_files_count_by_slide,
        artifacts_by_slide=artifacts_by_slide,
        artifacts_by_case=artifacts_by_case,
    )

    manifest_slide_ids = {slide.slide_id for slide in manifest_slides}
    manifest_slide_counts: dict[str, int] = defaultdict(int)
    for slide in manifest_slides:
        manifest_slide_counts[slide.slide_id] += 1
    manifest_duplicate_slide_ids = sorted(
        slide_id for slide_id, count in manifest_slide_counts.items() if count > 1
    )
    embedding_slide_ids = set(embedding_files_by_slide.keys())

    orphan_embedding_ids = sorted(embedding_slide_ids - manifest_slide_ids)
    orphan_embedding_files_total = int(
        sum(len(embedding_files_by_slide[slide_id]) for slide_id in orphan_embedding_ids)
    )

    slides_total = len(audit_rows)
    slides_with_embeddings = sum(1 for row in audit_rows if row["has_embedding"])
    slides_missing_embeddings = slides_total - slides_with_embeddings
    slides_missing_embedding_ids = sorted(
        row["slide_id"] for row in audit_rows if not row["has_embedding"]
    )

    slides_with_artifacts = sum(1 for row in audit_rows if row["has_artifact"])
    slides_missing_artifacts = slides_total - slides_with_artifacts
    slides_missing_artifact_ids = sorted(
        row["slide_id"] for row in audit_rows if not row["has_artifact"]
    )

    slides_with_complete_artifacts = sum(1 for row in audit_rows if row["has_complete_artifact"])
    slides_missing_complete_artifacts = slides_total - slides_with_complete_artifacts

    artifact_unique_files = {
        str(_safe_resolve(record.path))
        for record in all_artifacts
    }

    summary = {
        "slides_total": slides_total,
        "slides_with_embeddings": slides_with_embeddings,
        "slides_missing_embeddings": slides_missing_embeddings,
        "slides_missing_embedding_ids": slides_missing_embedding_ids,
        "slides_with_artifacts": slides_with_artifacts,
        "slides_missing_artifacts": slides_missing_artifacts,
        "slides_missing_artifact_ids": slides_missing_artifact_ids,
        "slides_with_complete_artifacts": slides_with_complete_artifacts,
        "slides_missing_complete_artifacts": slides_missing_complete_artifacts,
        "embedding_files_total": embedding_files_total,
        "orphan_embedding_count": len(orphan_embedding_ids),
        "orphan_embedding_ids": orphan_embedding_ids,
        "orphan_embedding_files_total": orphan_embedding_files_total,
        "embedding_patch_count_error_count": len(patch_count_errors),
        "embedding_patch_count_errors": patch_count_errors,
        "manifest_unique_slide_count": len(manifest_slide_ids),
        "manifest_duplicate_slide_count": len(manifest_duplicate_slide_ids),
        "manifest_duplicate_slide_ids": manifest_duplicate_slide_ids,
        "artifact_files_total": len(all_artifacts),
        "artifact_unique_file_count": len(artifact_unique_files),
        "artifact_unique_slide_count": len(artifacts_by_slide),
        "artifact_unique_case_count": len(artifacts_by_case),
        "artifact_section_coverage": {
            "tissue_composition": sum(1 for row in audit_rows if row["artifact_has_tissue_composition"]),
            "heatmap": sum(1 for row in audit_rows if row["artifact_has_heatmap"]),
            "evidence": sum(1 for row in audit_rows if row["artifact_has_evidence"]),
        },
        "rows_digest_sha256": rows_digest_sha256(audit_rows),
    }

    if args.expected_slide_count is not None:
        summary["expected_slide_count"] = int(args.expected_slide_count)
        summary["expected_slide_count_match"] = bool(slides_total == int(args.expected_slide_count))

    report_payload = {
        "manifest_path": str(manifest_path),
        "embeddings_dir": str(embeddings_dir),
        "artifacts_dir": str(artifacts_dir),
        "output_csv": str(out_csv_path),
        "output_json": str(out_json_path),
        "summary": summary,
    }

    if not args.dry_run:
        write_audit_csv(audit_rows, out_csv_path)
        write_summary_json(report_payload, out_json_path)

    print("LUAD embedding coverage audit complete")
    print(f"slides_total={slides_total}")
    print(f"slides_with_embeddings={slides_with_embeddings}")
    print(f"slides_missing_embeddings={slides_missing_embeddings}")
    print(f"slides_with_artifacts={slides_with_artifacts}")
    print(f"slides_missing_artifacts={slides_missing_artifacts}")
    print(f"slides_with_complete_artifacts={slides_with_complete_artifacts}")
    print(f"slides_missing_complete_artifacts={slides_missing_complete_artifacts}")
    print(f"embedding_files_total={embedding_files_total}")
    print(f"orphan_embedding_count={len(orphan_embedding_ids)}")
    print(f"orphan_embedding_files_total={orphan_embedding_files_total}")
    print(f"rows_digest_sha256={summary['rows_digest_sha256']}")

    if args.expected_slide_count is not None:
        expected_ok = summary.get("expected_slide_count_match", False)
        print(f"expected_slide_count={args.expected_slide_count}")
        print(f"expected_slide_count_match={expected_ok}")

    if args.print_orphans:
        for orphan_id in orphan_embedding_ids:
            print(f"orphan_embedding_id={orphan_id}")

    if args.dry_run:
        print("dry_run=true")
    else:
        print(f"audit_csv={out_csv_path}")
        print(f"audit_json={out_json_path}")

    reasons = _failure_reasons(summary=summary, args=args)
    if reasons:
        print("FAIL: pathology coverage gate(s) failed", file=sys.stderr)
        for reason in reasons:
            print(f"- {reason}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
