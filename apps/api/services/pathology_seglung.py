from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .pathology_id_resolution import iter_artifact_json_paths

_SEGLUNG_DIR_ENV = "PATHOLOGY_SEGLUNG_DIR"

_BACKGROUND_LABELS = {
    "background",
    "bg",
    "empty",
    "other",
    "unknown",
    "normal",
}

_TISSUE_LABEL_MAP: dict[str, str] = {
    "tumor": "Tumor",
    "tumour": "Tumor",
    "malignant": "Tumor",
    "neoplastic": "Tumor",
    "stroma": "Stroma",
    "fibrosis": "Stroma",
    "necrosis": "Necrosis",
    "necrotic": "Necrosis",
    "lymphocyte": "Lymphocyte-rich",
    "lymphocytes": "Lymphocyte-rich",
    "lymphocyte-rich": "Lymphocyte-rich",
    "immune": "Lymphocyte-rich",
    "inflammation": "Lymphocyte-rich",
}


@dataclass(frozen=True)
class SegLungResolvedData:
    source_path: Path
    source_sha256: str | None
    source_updated_at: str | None
    model_id: str | None
    run_id: str | None
    tissue_fractions: list[dict[str, Any]]
    tissue_coverage: float
    artifact_warning: str | None
    viewport_hint: dict[str, float] | None
    evidence_tiles: list[dict[str, Any]]


@dataclass(frozen=True)
class _MaskResolution:
    labels: list[list[str]]
    coverage: float


def resolve_seglung_slide_data(slide_id: str, case_id: str) -> SegLungResolvedData | None:
    directory = _seglung_directory()
    if directory is None:
        return None

    for artifact_path in iter_artifact_json_paths(directory, (slide_id, case_id)):
        payload = _read_json_object(artifact_path)
        if payload is None:
            continue

        section = _segmentation_section(payload)
        if section is None:
            continue

        mask_resolution = _parse_label_mask(section)
        tissue_fractions, coverage = _derive_tissue_fractions(section, mask_resolution)
        viewport_hint = _derive_viewport_hint(section, mask_resolution)
        evidence_tiles = _derive_evidence_tiles(section, viewport_hint)

        if not tissue_fractions and viewport_hint is None and not evidence_tiles:
            continue

        artifact_warning = _derive_artifact_warning(section)
        explicit_coverage = _coerce_float(
            _first_not_none(
                section.get("coverage"),
                section.get("tissue_coverage"),
                section.get("coverage_fraction"),
            )
        )

        resolved_coverage = _clamp_01(explicit_coverage)
        if resolved_coverage is None:
            resolved_coverage = coverage if coverage is not None else 1.0

        model_id = _first_non_empty_str(
            section,
            "model_id",
            "model_name",
            "model",
            "tile_encoder_model_id",
        )
        run_id = _first_non_empty_str(
            section,
            "run_id",
            "job_id",
            "inference_run_id",
        )

        return SegLungResolvedData(
            source_path=artifact_path,
            source_sha256=_sha256_file(artifact_path),
            source_updated_at=_timestamp_iso(artifact_path),
            model_id=model_id,
            run_id=run_id,
            tissue_fractions=tissue_fractions,
            tissue_coverage=resolved_coverage,
            artifact_warning=artifact_warning,
            viewport_hint=viewport_hint,
            evidence_tiles=evidence_tiles,
        )

    return None


def _seglung_directory() -> Path | None:
    configured = os.getenv(_SEGLUNG_DIR_ENV, "").strip()
    if not configured:
        return None

    directory = Path(configured).expanduser()
    if not directory.is_dir():
        return None

    return directory


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    return payload


def _segmentation_section(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    candidates = (
        payload.get("seglung"),
        payload.get("segmentation"),
        payload.get("pathology_segmentation"),
        payload,
    )

    for candidate in candidates:
        if isinstance(candidate, Mapping):
            return candidate

    return None


def _derive_tissue_fractions(
    section: Mapping[str, Any],
    mask_resolution: _MaskResolution | None,
) -> tuple[list[dict[str, Any]], float | None]:
    explicit_fraction_candidates = (
        section.get("tissue_fractions"),
        section.get("fractions"),
    )

    for candidate in explicit_fraction_candidates:
        parsed = _parse_fraction_payload(candidate)
        if parsed:
            return _fractions_from_counts(parsed), 1.0

    count_payload_candidates = (
        section.get("class_pixel_counts"),
        section.get("pixel_counts"),
        section.get("class_counts"),
        section.get("tissue_pixel_counts"),
    )
    for candidate in count_payload_candidates:
        parsed_counts = _parse_counts_payload(candidate)
        if parsed_counts:
            return _fractions_from_counts(parsed_counts), None

    if mask_resolution is not None:
        flattened_counts: Counter[str] = Counter()
        for row in mask_resolution.labels:
            flattened_counts.update(row)

        filtered_counts: dict[str, float] = {}
        for label, count in flattened_counts.items():
            tissue = _canonical_tissue_label(label)
            if tissue is None:
                continue
            filtered_counts[tissue] = filtered_counts.get(tissue, 0.0) + float(count)

        if filtered_counts:
            return _fractions_from_counts(filtered_counts), mask_resolution.coverage

    return [], None


def _parse_fraction_payload(candidate: Any) -> dict[str, float]:
    parsed: dict[str, float] = {}

    if isinstance(candidate, Mapping):
        for raw_tissue, raw_value in candidate.items():
            tissue = _canonical_tissue_label(str(raw_tissue))
            value = _coerce_float(raw_value)
            if tissue is None or value is None or value <= 0:
                continue
            parsed[tissue] = parsed.get(tissue, 0.0) + value
        return parsed

    if not isinstance(candidate, list):
        return parsed

    for item in candidate:
        if not isinstance(item, Mapping):
            continue

        tissue_raw = _first_not_none(item.get("tissue"), item.get("label"), item.get("class"))
        tissue = _canonical_tissue_label(str(tissue_raw or ""))

        value = _coerce_float(
            _first_not_none(
                item.get("fraction"),
                item.get("ratio"),
                item.get("value"),
                item.get("pixel_fraction"),
                item.get("count"),
            )
        )
        if tissue is None or value is None or value <= 0:
            continue

        parsed[tissue] = parsed.get(tissue, 0.0) + value

    return parsed


def _parse_counts_payload(candidate: Any) -> dict[str, float]:
    if not isinstance(candidate, Mapping):
        return {}

    parsed: dict[str, float] = {}
    for raw_tissue, raw_value in candidate.items():
        tissue = _canonical_tissue_label(str(raw_tissue))
        value = _coerce_float(raw_value)
        if tissue is None or value is None or value <= 0:
            continue
        parsed[tissue] = parsed.get(tissue, 0.0) + value

    return parsed


def _fractions_from_counts(counts: Mapping[str, float]) -> list[dict[str, Any]]:
    total = sum(max(value, 0.0) for value in counts.values())
    if total <= 0:
        return []

    fractions = [
        {
            "tissue": tissue,
            "fraction": round(max(value, 0.0) / total, 6),
        }
        for tissue, value in counts.items()
        if value > 0
    ]
    fractions.sort(key=lambda item: (-item["fraction"], item["tissue"]))
    return fractions


def _parse_label_mask(section: Mapping[str, Any]) -> _MaskResolution | None:
    raw_mask = _first_not_none(
        section.get("mask"),
        section.get("segmentation_map"),
        section.get("label_map_grid"),
    )
    if not isinstance(raw_mask, list) or not raw_mask:
        return None

    legend = _legend_mapping(section)

    labels: list[list[str]] = []
    total = 0
    foreground = 0

    for row in raw_mask:
        if not isinstance(row, list):
            continue

        parsed_row: list[str] = []
        for raw_label in row:
            label = _resolve_label_token(raw_label, legend)
            parsed_row.append(label)
            total += 1
            if _canonical_tissue_label(label) is not None:
                foreground += 1

        if parsed_row:
            labels.append(parsed_row)

    if not labels:
        return None

    coverage = 1.0 if total == 0 else round(foreground / total, 6)
    return _MaskResolution(labels=labels, coverage=coverage)


def _legend_mapping(section: Mapping[str, Any]) -> dict[str, str]:
    candidate = _first_not_none(
        section.get("label_legend"),
        section.get("label_map"),
        section.get("class_map"),
    )
    if not isinstance(candidate, Mapping):
        return {}

    legend: dict[str, str] = {}
    for key, value in candidate.items():
        if value is None:
            continue
        legend[str(key)] = str(value)

    return legend


def _resolve_label_token(raw_label: Any, legend: Mapping[str, str]) -> str:
    if isinstance(raw_label, (int, float)) and not isinstance(raw_label, bool):
        token = str(int(raw_label)) if float(raw_label).is_integer() else str(raw_label)
        return legend.get(token, token)

    token = str(raw_label)
    return legend.get(token, token)


def _derive_viewport_hint(
    section: Mapping[str, Any],
    mask_resolution: _MaskResolution | None,
) -> dict[str, float] | None:
    dimension_hint = _dimensions(section)

    for candidate in (
        section.get("viewport_hint"),
        section.get("heatmap_viewport_hint"),
        section.get("roi"),
        section.get("bounding_box"),
        section.get("bbox"),
        section.get("tumor_bbox"),
    ):
        parsed = _parse_bbox(candidate, dimensions=dimension_hint)
        if parsed is not None:
            return parsed

    if mask_resolution is None:
        return None

    row_count = len(mask_resolution.labels)
    col_count = max((len(row) for row in mask_resolution.labels), default=0)
    if row_count <= 0 or col_count <= 0:
        return None

    min_row = row_count
    max_row = -1
    min_col = col_count
    max_col = -1

    for row_index, row in enumerate(mask_resolution.labels):
        for col_index, label in enumerate(row):
            if _canonical_tissue_label(label) is None:
                continue
            min_row = min(min_row, row_index)
            max_row = max(max_row, row_index)
            min_col = min(min_col, col_index)
            max_col = max(max_col, col_index)

    if max_row < min_row or max_col < min_col:
        return None

    x = min_col / col_count
    y = min_row / row_count
    width = (max_col - min_col + 1) / col_count
    height = (max_row - min_row + 1) / row_count
    return _clamp_bbox(x=x, y=y, width=width, height=height)


def _dimensions(section: Mapping[str, Any]) -> tuple[float, float] | None:
    candidates: list[Mapping[str, Any]] = []
    if isinstance(section.get("dimensions"), Mapping):
        candidates.append(section["dimensions"])
    candidates.append(section)

    for candidate in candidates:
        width = _coerce_float(
            _first_not_none(
                candidate.get("width"),
                candidate.get("slide_width"),
                candidate.get("image_width"),
            )
        )
        height = _coerce_float(
            _first_not_none(
                candidate.get("height"),
                candidate.get("slide_height"),
                candidate.get("image_height"),
            )
        )

        if width is None or height is None or width <= 0 or height <= 0:
            continue

        return width, height

    return None


def _parse_bbox(candidate: Any, *, dimensions: tuple[float, float] | None) -> dict[str, float] | None:
    if not isinstance(candidate, Mapping):
        return None

    x = _coerce_float(candidate.get("x"))
    y = _coerce_float(candidate.get("y"))
    width = _coerce_float(candidate.get("width"))
    height = _coerce_float(candidate.get("height"))

    if x is None or y is None or width is None or height is None:
        x0 = _coerce_float(_first_not_none(candidate.get("x0"), candidate.get("left")))
        y0 = _coerce_float(_first_not_none(candidate.get("y0"), candidate.get("top")))
        x1 = _coerce_float(_first_not_none(candidate.get("x1"), candidate.get("right")))
        y1 = _coerce_float(_first_not_none(candidate.get("y1"), candidate.get("bottom")))
        if x0 is not None and y0 is not None and x1 is not None and y1 is not None:
            x = x0
            y = y0
            width = x1 - x0
            height = y1 - y0

    if x is None or y is None or width is None or height is None:
        return None

    if dimensions is not None and max(x, y, width, height) > 1.0:
        slide_width, slide_height = dimensions
        if slide_width > 0 and slide_height > 0:
            x = x / slide_width
            width = width / slide_width
            y = y / slide_height
            height = height / slide_height

    return _clamp_bbox(x=x, y=y, width=width, height=height)


def _clamp_bbox(*, x: float, y: float, width: float, height: float) -> dict[str, float] | None:
    if not all(math.isfinite(value) for value in (x, y, width, height)):
        return None

    x = min(max(x, 0.0), 1.0)
    y = min(max(y, 0.0), 1.0)
    width = max(width, 0.0)
    height = max(height, 0.0)

    if width <= 0 or height <= 0:
        return None

    if x + width > 1.0:
        width = max(1.0 - x, 0.0)
    if y + height > 1.0:
        height = max(1.0 - y, 0.0)

    if width <= 0 or height <= 0:
        return None

    return {
        "x": round(x, 6),
        "y": round(y, 6),
        "width": round(width, 6),
        "height": round(height, 6),
    }


def _derive_evidence_tiles(
    section: Mapping[str, Any],
    viewport_hint: dict[str, float] | None,
) -> list[dict[str, Any]]:
    candidates = _first_not_none(
        section.get("evidence_tiles"),
        section.get("top_tiles"),
        section.get("hotspots"),
    )

    parsed_tiles: list[dict[str, Any]] = []
    if isinstance(candidates, list):
        for index, candidate in enumerate(candidates):
            tile = _parse_evidence_tile(candidate, index=index)
            if tile is not None:
                parsed_tiles.append(tile)

    if parsed_tiles:
        parsed_tiles.sort(key=lambda tile: (-tile["score"], tile["tile_id"]))
        return parsed_tiles[:8]

    if viewport_hint is None:
        return []

    return [
        {
            "tile_id": "seglung_tile_001",
            "score": 0.8,
            "rationale": "SegLungTCGA hotspot derived from segmentation ROI.",
            "bbox": viewport_hint,
        }
    ]


def _parse_evidence_tile(candidate: Any, *, index: int) -> dict[str, Any] | None:
    if not isinstance(candidate, Mapping):
        return None

    tile_id = _first_non_empty_str(candidate, "tile_id", "id")
    if tile_id is None:
        tile_id = f"seglung_tile_{index + 1:03d}"

    score = _coerce_float(
        _first_not_none(
            candidate.get("score"),
            candidate.get("confidence"),
            candidate.get("probability"),
            candidate.get("weight"),
        )
    )
    if score is None:
        score = max(0.1, 1.0 - (index * 0.1))

    rationale = _first_non_empty_str(candidate, "rationale", "label", "class", "description")
    if rationale is None:
        rationale = "SegLungTCGA segmentation hotspot"

    bbox = _parse_bbox(
        _first_not_none(candidate.get("bbox"), candidate),
        dimensions=None,
    )

    parsed: dict[str, Any] = {
        "tile_id": tile_id,
        "score": round(_clamp_01(score) or 0.0, 6),
        "rationale": rationale,
    }
    if bbox is not None:
        parsed["bbox"] = bbox

    tile_coordinates = candidate.get("tile_coordinates")
    if isinstance(tile_coordinates, Mapping):
        parsed["tile_coordinates"] = {
            "row": int(_coerce_float(tile_coordinates.get("row")) or 0),
            "col": int(_coerce_float(tile_coordinates.get("col")) or 0),
            "one_based_index": bool(tile_coordinates.get("one_based_index", False)),
        }

    return parsed


def _derive_artifact_warning(section: Mapping[str, Any]) -> str | None:
    explicit_warning = _first_non_empty_str(section, "artifact_warning", "warning")
    if explicit_warning is not None:
        return explicit_warning

    warnings = section.get("warnings")
    if not isinstance(warnings, list):
        return None

    parsed = [str(item).strip() for item in warnings if str(item).strip()]
    if not parsed:
        return None

    return "; ".join(parsed)


def _canonical_tissue_label(label: str) -> str | None:
    normalized = label.strip().lower().replace("_", "-")
    if not normalized:
        return None

    if normalized in _BACKGROUND_LABELS:
        return None

    mapped = _TISSUE_LABEL_MAP.get(normalized)
    if mapped is not None:
        return mapped

    token = normalized.replace("-", " ").strip()
    if not token:
        return None

    return token.title()


def _first_non_empty_str(mapping: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(parsed):
        return None

    return parsed


def _clamp_01(value: float | None) -> float | None:
    if value is None:
        return None

    if not math.isfinite(value):
        return None

    return min(max(value, 0.0), 1.0)


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _sha256_file(path: Path) -> str | None:
    try:
        payload = path.read_bytes()
    except OSError:
        return None

    return hashlib.sha256(payload).hexdigest()


def _timestamp_iso(path: Path) -> str | None:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None

    return datetime.fromtimestamp(mtime, tz=UTC).isoformat().replace("+00:00", "Z")
