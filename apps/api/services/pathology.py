from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from schemas.pathology import (
    MethodMetadata,
    EvidenceTile,
    PathologyDataSource,
    PathologyEvidenceResponse,
    PathologyHeatmapResponse,
    PathologyProvenance,
    PathologyQc,
    PathologyTissueCompositionResponse,
    TissueFraction,
    ViewportHint,
)

from .pathology_id_resolution import derive_case_id_from_slide_id, iter_artifact_json_paths
from .pathology_seglung import SegLungResolvedData, resolve_seglung_slide_data

_METHOD_VERSION = "hackathon-p0"
_METHOD_TIMESTAMP = "2026-03-01T00:00:00Z"
_ARTIFACT_DIR_ENV = "PATHOLOGY_ARTIFACT_DIR"
_STRICT_MISSING_ENV = "PATHOLOGY_STRICT_MISSING_DATA"
_ARTIFACT_TISSUE_METHOD = "pathology-tissue-artifact-v1"
_ARTIFACT_HEATMAP_METHOD = "pathology-heatmap-artifact-v1"
_ARTIFACT_EVIDENCE_METHOD = "pathology-evidence-artifact-v1"
_SEGLUNG_TISSUE_METHOD = "pathology-tissue-seglung-v1"
_SEGLUNG_HEATMAP_METHOD = "pathology-heatmap-seglung-v1"
_SEGLUNG_EVIDENCE_METHOD = "pathology-evidence-seglung-v1"
_DETERMINISTIC_MODEL_ID = "pathology-proxy-deterministic-v1"
_PATHOLOGY_TILE_ENCODER_MODEL_ENV = "PATHOLOGY_TILE_ENCODER_MODEL"
_DEFAULT_PATHOLOGY_TILE_ENCODER_MODEL = "google/path-foundation"
_FALLBACK_CHECKPOINT_SENTINEL = "deterministic-no-checkpoint"
_RESOLVER_STRATEGY = "recursive-non-symlink-first-v1"
_TILE_COORDINATE_PATTERN = re.compile(r"(?:^|_)r(?P<row>\d+)_c(?P<col>\d+)(?:$|_)", re.IGNORECASE)


class PathologyDataUnavailableError(RuntimeError):
    def __init__(self, *, section: str, slide_id: str, detail: str) -> None:
        super().__init__(detail)
        self.section = section
        self.slide_id = slide_id
        self.detail = detail


@dataclass(frozen=True)
class _ArtifactPayloadRecord:
    path: Path
    payload: dict[str, Any]


def build_pathology_metadata(method: str) -> MethodMetadata:
    return MethodMetadata(
        method=method,
        version=_METHOD_VERSION,
        timestamp=_METHOD_TIMESTAMP,
        proxy_estimate=True,
    )


def _artifact_directory() -> Path | None:
    artifact_dir = os.getenv(_ARTIFACT_DIR_ENV, "").strip()
    if not artifact_dir:
        return None
    return Path(artifact_dir)


def _strict_missing_default_enabled() -> bool:
    token = os.getenv(_STRICT_MISSING_ENV, "").strip().lower()
    return token in {"1", "true", "yes", "on"}


def _strict_missing_enabled(strict_missing: bool | None) -> bool:
    if strict_missing is None:
        return _strict_missing_default_enabled()
    return strict_missing


def _pathology_tile_encoder_model_id() -> str:
    configured = os.getenv(_PATHOLOGY_TILE_ENCODER_MODEL_ENV, "").strip()
    if configured:
        return configured
    return _DEFAULT_PATHOLOGY_TILE_ENCODER_MODEL


def _read_artifact_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as artifact_file:
            payload = json.load(artifact_file)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _iter_artifact_payload_records(slide_id: str, case_id: str) -> Iterator[_ArtifactPayloadRecord]:
    artifact_dir = _artifact_directory()
    if artifact_dir is None:
        return

    for artifact_path in iter_artifact_json_paths(artifact_dir, (slide_id, case_id)):
        artifact_payload = _read_artifact_json(artifact_path)
        if artifact_payload is None:
            continue
        yield _ArtifactPayloadRecord(path=artifact_path, payload=artifact_payload)


def _first_non_empty_str(candidates: list[Mapping[str, Any]], *keys: str) -> str | None:
    for mapping in candidates:
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _artifact_timestamp_iso(path: Path) -> str | None:
    try:
        mtime_seconds = path.stat().st_mtime
    except OSError:
        return None

    return datetime.fromtimestamp(mtime_seconds, tz=UTC).isoformat().replace("+00:00", "Z")


def _artifact_sha256(path: Path) -> str | None:
    try:
        payload = path.read_bytes()
    except OSError:
        return None

    return hashlib.sha256(payload).hexdigest()


def _build_artifact_provenance(
    *,
    slide_id: str,
    section_payload: dict[str, Any],
    artifact_payload: dict[str, Any],
    artifact_path: Path,
) -> PathologyProvenance:
    provenance_candidates: list[Mapping[str, Any]] = []
    for candidate in (
        section_payload.get("provenance"),
        artifact_payload.get("provenance"),
        section_payload.get("meta"),
        artifact_payload.get("meta"),
    ):
        if isinstance(candidate, Mapping):
            provenance_candidates.append(candidate)

    model_id = _first_non_empty_str(
        provenance_candidates,
        "model_id",
        "model_name",
        "model",
    )
    checkpoint_sha256 = _first_non_empty_str(
        provenance_candidates,
        "checkpoint_sha256",
        "model_checkpoint_sha256",
        "weights_sha256",
    )
    tile_encoder_model_id = _first_non_empty_str(
        provenance_candidates,
        "tile_encoder_model_id",
        "encoder_model_id",
        "tile_model_id",
    )
    run_id = _first_non_empty_str(
        provenance_candidates,
        "run_id",
        "inference_run_id",
        "job_id",
    )
    embedding_source_id = _first_non_empty_str(
        provenance_candidates,
        "embedding_source_id",
        "embedding_id",
        "slide_embedding_id",
    )

    source_path = artifact_path.resolve(strict=False).as_posix()
    return PathologyProvenance(
        data_source="artifact",
        resolver_strategy=_RESOLVER_STRATEGY,
        artifact_path=source_path,
        source_path=source_path,
        artifact_sha256=_artifact_sha256(artifact_path),
        artifact_updated_at=_artifact_timestamp_iso(artifact_path),
        model_id=model_id,
        tile_encoder_model_id=tile_encoder_model_id,
        checkpoint_sha256=checkpoint_sha256,
        run_id=run_id,
        embedding_source_id=embedding_source_id or slide_id,
    )


def _build_deterministic_provenance(
    *,
    slide_id: str,
    case_id: str,
) -> PathologyProvenance:
    return PathologyProvenance(
        data_source="deterministic_fallback",
        resolver_strategy=_RESOLVER_STRATEGY,
        model_id=_DETERMINISTIC_MODEL_ID,
        tile_encoder_model_id=_pathology_tile_encoder_model_id(),
        checkpoint_sha256=_FALLBACK_CHECKPOINT_SENTINEL,
        run_id=f"deterministic:{case_id}:{slide_id}",
        embedding_source_id=slide_id,
    )


def _build_seglung_provenance(
    *,
    slide_id: str,
    case_id: str,
    seglung_data: SegLungResolvedData,
) -> PathologyProvenance:
    source_path = seglung_data.source_path.resolve(strict=False).as_posix()
    return PathologyProvenance(
        data_source="seglung",
        resolver_strategy=_RESOLVER_STRATEGY,
        source_path=source_path,
        artifact_sha256=seglung_data.source_sha256,
        artifact_updated_at=seglung_data.source_updated_at,
        model_id=seglung_data.model_id or _pathology_tile_encoder_model_id(),
        tile_encoder_model_id=_pathology_tile_encoder_model_id(),
        run_id=seglung_data.run_id or f"seglung:{case_id}:{slide_id}",
        embedding_source_id=slide_id,
    )


def _raise_if_strict_missing(
    *,
    strict_missing: bool,
    section_key: str,
    slide_id: str,
    artifact_records_seen: int,
    section_payloads_seen: int,
) -> None:
    if not strict_missing:
        return

    if _artifact_directory() is None:
        detail = (
            f"Strict missing-data mode enabled, but {_ARTIFACT_DIR_ENV} is not configured "
            f"for pathology section '{section_key}' (slide '{slide_id}')."
        )
    elif artifact_records_seen == 0:
        detail = (
            f"Strict missing-data mode enabled and no artifact JSON matched pathology section "
            f"'{section_key}' for slide '{slide_id}'."
        )
    elif section_payloads_seen == 0:
        detail = (
            f"Strict missing-data mode enabled and matched artifacts do not contain a valid "
            f"'{section_key}' section for slide '{slide_id}'."
        )
    else:
        detail = (
            f"Strict missing-data mode enabled and no schema-valid '{section_key}' payload could "
            f"be loaded for slide '{slide_id}'."
        )

    raise PathologyDataUnavailableError(section=section_key, slide_id=slide_id, detail=detail)


def _deterministic_tissue_composition(case_id: str, slide_id: str) -> PathologyTissueCompositionResponse:
    return PathologyTissueCompositionResponse(
        case_id=case_id,
        slide_id=slide_id,
        fractions=[
            TissueFraction(tissue="Tumor", fraction=0.61),
            TissueFraction(tissue="Stroma", fraction=0.24),
            TissueFraction(tissue="Necrosis", fraction=0.08),
            TissueFraction(tissue="Lymphocyte-rich", fraction=0.07),
        ],
        qc=PathologyQc(
            coverage=0.93,
            artifact_warning="Mild pen-mark artifact at peripheral region",
        ),
        meta=build_pathology_metadata("pathology-tissue-v1"),
        provenance=_build_deterministic_provenance(slide_id=slide_id, case_id=case_id),
    )


def _heatmap_image_uri(slide_id: str) -> str:
    return f"/v1/pathology/slides/{slide_id}/heatmap/image"


def _slide_preview_uri(slide_id: str) -> str:
    return f"/v1/pathology/slides/{slide_id}/preview/image"


def _deterministic_heatmap(case_id: str, slide_id: str) -> PathologyHeatmapResponse:
    return PathologyHeatmapResponse(
        case_id=case_id,
        slide_id=slide_id,
        heatmap_uri=_heatmap_image_uri(slide_id),
        slide_preview_uri=_slide_preview_uri(slide_id),
        viewport_hint=ViewportHint(
            x=0.12,
            y=0.19,
            width=0.42,
            height=0.33,
        ),
        meta=build_pathology_metadata("pathology-heatmap-v1"),
        provenance=_build_deterministic_provenance(slide_id=slide_id, case_id=case_id),
    )


def _deterministic_evidence(case_id: str, slide_id: str) -> PathologyEvidenceResponse:
    return PathologyEvidenceResponse(
        case_id=case_id,
        slide_id=slide_id,
        top_tiles=[
            EvidenceTile(
                tile_id="tile_183",
                score=0.87,
                rationale="Dense tumor-infiltrating lymphocyte cluster",
                bbox={"x": 0.18, "y": 0.21, "width": 0.16, "height": 0.18},
                tile_coordinates={"row": 0, "col": 0, "one_based_index": False},
            ),
            EvidenceTile(
                tile_id="tile_204",
                score=0.82,
                rationale="Immune-rich stroma adjacent to tumor",
                bbox={"x": 0.52, "y": 0.24, "width": 0.16, "height": 0.18},
                tile_coordinates={"row": 0, "col": 1, "one_based_index": False},
            ),
            EvidenceTile(
                tile_id="tile_097",
                score=0.74,
                rationale="Necrotic pocket with peri-necrotic inflammation",
                bbox={"x": 0.63, "y": 0.58, "width": 0.16, "height": 0.18},
                tile_coordinates={"row": 1, "col": 0, "one_based_index": False},
            ),
        ],
        meta=build_pathology_metadata("pathology-evidence-v1"),
        provenance=_build_deterministic_provenance(slide_id=slide_id, case_id=case_id),
    )


def _seglung_tissue_composition(case_id: str, slide_id: str) -> PathologyTissueCompositionResponse | None:
    seglung_data = resolve_seglung_slide_data(slide_id, case_id)
    if seglung_data is None or not seglung_data.tissue_fractions:
        return None

    try:
        return PathologyTissueCompositionResponse.model_validate(
            {
                "case_id": case_id,
                "slide_id": slide_id,
                "fractions": seglung_data.tissue_fractions,
                "qc": {
                    "coverage": seglung_data.tissue_coverage,
                    "artifact_warning": seglung_data.artifact_warning,
                },
                "meta": build_pathology_metadata(_SEGLUNG_TISSUE_METHOD).model_dump(),
                "provenance": _build_seglung_provenance(
                    slide_id=slide_id,
                    case_id=case_id,
                    seglung_data=seglung_data,
                ).model_dump(),
            }
        )
    except ValidationError:
        return None


def _seglung_heatmap(case_id: str, slide_id: str) -> PathologyHeatmapResponse | None:
    seglung_data = resolve_seglung_slide_data(slide_id, case_id)
    if seglung_data is None or seglung_data.viewport_hint is None:
        return None

    try:
        return PathologyHeatmapResponse.model_validate(
            {
                "case_id": case_id,
                "slide_id": slide_id,
                "heatmap_uri": _heatmap_image_uri(slide_id),
                "slide_preview_uri": _slide_preview_uri(slide_id),
                "viewport_hint": seglung_data.viewport_hint,
                "meta": build_pathology_metadata(_SEGLUNG_HEATMAP_METHOD).model_dump(),
                "provenance": _build_seglung_provenance(
                    slide_id=slide_id,
                    case_id=case_id,
                    seglung_data=seglung_data,
                ).model_dump(),
            }
        )
    except ValidationError:
        return None


def _seglung_evidence(case_id: str, slide_id: str) -> PathologyEvidenceResponse | None:
    seglung_data = resolve_seglung_slide_data(slide_id, case_id)
    if seglung_data is None or not seglung_data.evidence_tiles:
        return None

    normalized_tiles = _normalize_evidence_tiles(seglung_data.evidence_tiles)

    try:
        return PathologyEvidenceResponse.model_validate(
            {
                "case_id": case_id,
                "slide_id": slide_id,
                "top_tiles": normalized_tiles,
                "meta": build_pathology_metadata(_SEGLUNG_EVIDENCE_METHOD).model_dump(),
                "provenance": _build_seglung_provenance(
                    slide_id=slide_id,
                    case_id=case_id,
                    seglung_data=seglung_data,
                ).model_dump(),
            }
        )
    except ValidationError:
        return None


def _parse_tile_coordinates(tile_id: str) -> tuple[int, int] | None:
    match = _TILE_COORDINATE_PATTERN.search(tile_id)
    if match is None:
        return None
    row = int(match.group("row"))
    col = int(match.group("col"))
    return row, col


def _infer_tile_bbox(
    *,
    row: int,
    col: int,
    one_based_index: bool,
    row_count: int,
    col_count: int,
) -> dict[str, float] | None:
    if row_count <= 0 or col_count <= 0:
        return None

    row_index = row - 1 if one_based_index else row
    col_index = col - 1 if one_based_index else col
    if row_index < 0 or col_index < 0:
        return None

    width = 1.0 / col_count
    height = 1.0 / row_count
    x = min(max(col_index * width, 0.0), 1.0 - width)
    y = min(max(row_index * height, 0.0), 1.0 - height)

    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    }


def _tile_coordinates_payload(*, row: int, col: int, one_based_index: bool) -> dict[str, Any]:
    return {
        "row": row,
        "col": col,
        "one_based_index": one_based_index,
    }


def _normalize_evidence_tiles(top_tiles: Any) -> Any:
    if not isinstance(top_tiles, list):
        return top_tiles

    parsed_coordinates: dict[int, tuple[int, int]] = {}
    for index, tile in enumerate(top_tiles):
        if not isinstance(tile, dict):
            continue
        tile_id = tile.get("tile_id")
        if not isinstance(tile_id, str):
            continue
        coordinates = _parse_tile_coordinates(tile_id)
        if coordinates is None:
            continue
        parsed_coordinates[index] = coordinates

    if not parsed_coordinates:
        tile_count = len(top_tiles)
        if tile_count == 0:
            return top_tiles

        # Fallback: generate a deterministic coarse grid from list order when
        # tile_id does not expose rXX_cYY coordinates.
        grid_cols = max(1, int(tile_count**0.5))
        if grid_cols * grid_cols < tile_count:
            grid_cols += 1

        grid_rows = (tile_count + grid_cols - 1) // grid_cols
        normalized_tiles: list[Any] = []
        for index, tile in enumerate(top_tiles):
            if not isinstance(tile, dict):
                normalized_tiles.append(tile)
                continue

            normalized_tile = dict(tile)

            if not isinstance(normalized_tile.get("tile_coordinates"), dict):
                normalized_tile["tile_coordinates"] = _tile_coordinates_payload(
                    row=index // grid_cols,
                    col=index % grid_cols,
                    one_based_index=False,
                )

            if not isinstance(normalized_tile.get("bbox"), dict):
                inferred_bbox = _infer_tile_bbox(
                    row=index // grid_cols,
                    col=index % grid_cols,
                    one_based_index=False,
                    row_count=grid_rows,
                    col_count=grid_cols,
                )
                if inferred_bbox is not None:
                    normalized_tile["bbox"] = inferred_bbox

            normalized_tiles.append(normalized_tile)

        return normalized_tiles

    rows = [row for row, _ in parsed_coordinates.values()]
    cols = [col for _, col in parsed_coordinates.values()]
    one_based_index = min(rows + cols) >= 1
    row_count = max(rows) if one_based_index else max(rows) + 1
    col_count = max(cols) if one_based_index else max(cols) + 1

    normalized_tiles: list[Any] = []
    for index, tile in enumerate(top_tiles):
        if not isinstance(tile, dict):
            normalized_tiles.append(tile)
            continue

        normalized_tile = dict(tile)
        coordinates = parsed_coordinates.get(index)

        if coordinates is not None and not isinstance(normalized_tile.get("tile_coordinates"), dict):
            normalized_tile["tile_coordinates"] = _tile_coordinates_payload(
                row=coordinates[0],
                col=coordinates[1],
                one_based_index=one_based_index,
            )

        if not isinstance(normalized_tile.get("bbox"), dict) and coordinates is not None:
            inferred_bbox = _infer_tile_bbox(
                row=coordinates[0],
                col=coordinates[1],
                one_based_index=one_based_index,
                row_count=row_count,
                col_count=col_count,
            )
            if inferred_bbox is not None:
                normalized_tile["bbox"] = inferred_bbox

        normalized_tiles.append(normalized_tile)

    return normalized_tiles


def _artifact_tissue_composition(
    case_id: str,
    slide_id: str,
    artifact_record: _ArtifactPayloadRecord,
    section_payload: dict[str, Any],
) -> PathologyTissueCompositionResponse | None:
    try:
        return PathologyTissueCompositionResponse.model_validate(
            {
                "case_id": case_id,
                "slide_id": slide_id,
                "fractions": section_payload.get("fractions"),
                "qc": section_payload.get("qc"),
                "meta": build_pathology_metadata(_ARTIFACT_TISSUE_METHOD).model_dump(),
                "provenance": _build_artifact_provenance(
                    slide_id=slide_id,
                    section_payload=section_payload,
                    artifact_payload=artifact_record.payload,
                    artifact_path=artifact_record.path,
                ).model_dump(),
            }
        )
    except ValidationError:
        return None


def _artifact_heatmap(
    case_id: str,
    slide_id: str,
    artifact_record: _ArtifactPayloadRecord,
    section_payload: dict[str, Any],
) -> PathologyHeatmapResponse | None:
    try:
        return PathologyHeatmapResponse.model_validate(
            {
                "case_id": case_id,
                "slide_id": slide_id,
                "heatmap_uri": _heatmap_image_uri(slide_id),
                "slide_preview_uri": _slide_preview_uri(slide_id),
                "viewport_hint": section_payload.get("viewport_hint"),
                "meta": build_pathology_metadata(_ARTIFACT_HEATMAP_METHOD).model_dump(),
                "provenance": _build_artifact_provenance(
                    slide_id=slide_id,
                    section_payload=section_payload,
                    artifact_payload=artifact_record.payload,
                    artifact_path=artifact_record.path,
                ).model_dump(),
            }
        )
    except ValidationError:
        return None


def _artifact_evidence(
    case_id: str,
    slide_id: str,
    artifact_record: _ArtifactPayloadRecord,
    section_payload: dict[str, Any],
) -> PathologyEvidenceResponse | None:
    top_tiles = _normalize_evidence_tiles(section_payload.get("top_tiles"))
    try:
        return PathologyEvidenceResponse.model_validate(
            {
                "case_id": case_id,
                "slide_id": slide_id,
                "top_tiles": top_tiles,
                "meta": build_pathology_metadata(_ARTIFACT_EVIDENCE_METHOD).model_dump(),
                "provenance": _build_artifact_provenance(
                    slide_id=slide_id,
                    section_payload=section_payload,
                    artifact_payload=artifact_record.payload,
                    artifact_path=artifact_record.path,
                ).model_dump(),
            }
        )
    except ValidationError:
        return None


def get_tissue_composition(
    slide_id: str,
    *,
    strict_missing: bool | None = None,
) -> PathologyTissueCompositionResponse:
    case_id = derive_case_id_from_slide_id(slide_id)
    strict_mode = _strict_missing_enabled(strict_missing)

    artifact_records_seen = 0
    section_payloads_seen = 0

    for artifact_record in _iter_artifact_payload_records(slide_id, case_id):
        artifact_records_seen += 1
        section_payload = artifact_record.payload.get("tissue_composition")
        if not isinstance(section_payload, dict):
            continue
        section_payloads_seen += 1

        artifact_response = _artifact_tissue_composition(
            case_id,
            slide_id,
            artifact_record,
            section_payload,
        )
        if artifact_response is not None:
            return artifact_response

    _raise_if_strict_missing(
        strict_missing=strict_mode,
        section_key="tissue_composition",
        slide_id=slide_id,
        artifact_records_seen=artifact_records_seen,
        section_payloads_seen=section_payloads_seen,
    )

    seglung_response = _seglung_tissue_composition(case_id, slide_id)
    if seglung_response is not None:
        return seglung_response

    return _deterministic_tissue_composition(case_id, slide_id)


def get_heatmap(
    slide_id: str,
    *,
    strict_missing: bool | None = None,
) -> PathologyHeatmapResponse:
    case_id = derive_case_id_from_slide_id(slide_id)
    strict_mode = _strict_missing_enabled(strict_missing)

    artifact_records_seen = 0
    section_payloads_seen = 0

    for artifact_record in _iter_artifact_payload_records(slide_id, case_id):
        artifact_records_seen += 1
        section_payload = artifact_record.payload.get("heatmap")
        if not isinstance(section_payload, dict):
            continue
        section_payloads_seen += 1

        artifact_response = _artifact_heatmap(
            case_id,
            slide_id,
            artifact_record,
            section_payload,
        )
        if artifact_response is not None:
            return artifact_response

    _raise_if_strict_missing(
        strict_missing=strict_mode,
        section_key="heatmap",
        slide_id=slide_id,
        artifact_records_seen=artifact_records_seen,
        section_payloads_seen=section_payloads_seen,
    )

    seglung_response = _seglung_heatmap(case_id, slide_id)
    if seglung_response is not None:
        return seglung_response

    return _deterministic_heatmap(case_id, slide_id)


def get_evidence(
    slide_id: str,
    *,
    strict_missing: bool | None = None,
) -> PathologyEvidenceResponse:
    case_id = derive_case_id_from_slide_id(slide_id)
    strict_mode = _strict_missing_enabled(strict_missing)

    artifact_records_seen = 0
    section_payloads_seen = 0

    for artifact_record in _iter_artifact_payload_records(slide_id, case_id):
        artifact_records_seen += 1
        section_payload = artifact_record.payload.get("evidence")
        if not isinstance(section_payload, dict):
            continue
        section_payloads_seen += 1

        artifact_response = _artifact_evidence(
            case_id,
            slide_id,
            artifact_record,
            section_payload,
        )
        if artifact_response is not None:
            return artifact_response

    _raise_if_strict_missing(
        strict_missing=strict_mode,
        section_key="evidence",
        slide_id=slide_id,
        artifact_records_seen=artifact_records_seen,
        section_payloads_seen=section_payloads_seen,
    )

    seglung_response = _seglung_evidence(case_id, slide_id)
    if seglung_response is not None:
        return seglung_response

    return _deterministic_evidence(case_id, slide_id)
