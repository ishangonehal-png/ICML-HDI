from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree

from schemas.cohort import CohortCaseSummary
from .pathology_id_resolution import iter_artifact_json_paths, resolve_best_matching_file

_CASE_ID_PATTERN = re.compile(r"(TCGA-[A-Z0-9]{2}-[A-Z0-9]{4})", re.IGNORECASE)
_STAGE_PATTERN = re.compile(r"(?:stage\s*)?(i{1,3}|iv|[1-4])\s*([abc])?", re.IGNORECASE)
_DEFAULT_WSI_GLOB = "*.svs"
_DEFAULT_ARTIFACT_GLOB = "*.json"


def _extract_case_id(value: str) -> str | None:
    match = _CASE_ID_PATTERN.search(value)
    if match is None:
        return None
    return match.group(1).upper()


def _env_path(var_name: str) -> Path | None:
    configured = os.getenv(var_name, "").strip()
    if not configured:
        return None
    return Path(configured)


def _iter_embedding_case_ids(embeddings_dir: Path) -> set[str]:
    case_ids: set[str] = set()
    if not embeddings_dir.exists() or not embeddings_dir.is_dir():
        return case_ids

    for candidate in embeddings_dir.iterdir():
        if not candidate.is_file():
            continue
        if candidate.name.startswith("."):
            continue
        if "coords" in candidate.name.lower():
            continue

        case_id = _extract_case_id(candidate.name)
        if case_id:
            case_ids.add(case_id)

    return case_ids


def _iter_slide_case_ids(slides_root: Path) -> set[str]:
    case_ids: set[str] = set()
    if not slides_root.exists() or not slides_root.is_dir():
        return case_ids

    for slide_path in slides_root.rglob(_DEFAULT_WSI_GLOB):
        if not slide_path.is_file():
            continue
        case_id = _extract_case_id(slide_path.name)
        if case_id:
            case_ids.add(case_id)

    return case_ids


def _iter_artifact_case_ids(artifact_dir: Path) -> set[str]:
    case_ids: set[str] = set()
    if not artifact_dir.exists() or not artifact_dir.is_dir():
        return case_ids

    for artifact_path in artifact_dir.rglob(_DEFAULT_ARTIFACT_GLOB):
        if not artifact_path.is_file():
            continue
        case_id = _extract_case_id(artifact_path.stem)
        if case_id:
            case_ids.add(case_id)

    return case_ids


def _iter_case_ids_from_paths(paths: list[Path | None]) -> set[str]:
    case_ids: set[str] = set()
    for root in paths:
        if root is None or not root.exists() or not root.is_dir():
            continue

        for candidate in root.rglob("*"):
            if not candidate.is_file():
                continue
            case_id = _extract_case_id(candidate.name)
            if case_id:
                case_ids.add(case_id)

    return case_ids


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        text = str(value).strip()
    else:
        return None
    return text or None


def _resolve_path(payload: Mapping[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _pick_string(payload: Mapping[str, Any], *paths: str) -> str | None:
    for path in paths:
        text = _coerce_str(_resolve_path(payload, path))
        if text is not None:
            return text
    return None


def _normalize_stage(value: Any) -> str | None:
    text = _coerce_str(value)
    if text is None:
        return None

    match = _STAGE_PATTERN.search(text)
    if match is None:
        return text

    token = match.group(1).upper()
    major = {
        "I": "I",
        "II": "II",
        "III": "III",
        "IV": "IV",
        "1": "I",
        "2": "II",
        "3": "III",
        "4": "IV",
    }.get(token)
    if major is None:
        return text

    substage = (match.group(2) or "").upper()
    return f"Stage {major}{substage}" if substage else f"Stage {major}"


def _normalize_smoking_status(value: Any) -> str | None:
    text = _coerce_str(value)
    if text is None:
        return None

    lowered = text.lower()
    if lowered in {"1", "never smoker", "never smoked", "lifelong non-smoker"}:
        return "Never smoker"
    if lowered in {"2", "current smoker", "current"}:
        return "Current smoker"
    if lowered in {"3", "4", "former smoker", "former", "ex-smoker", "reformed smoker"}:
        return "Former smoker"
    if "never" in lowered and "smok" in lowered:
        return "Never smoker"
    if "former" in lowered and "smok" in lowered:
        return "Former smoker"
    if "current" in lowered and "smok" in lowered:
        return "Current smoker"

    return text


def _load_json_mapping(path: Path) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _extract_stage_and_smoking_from_mapping(payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    stage = _normalize_stage(
        _pick_string(
            payload,
            "patient_summary.stage",
            "summary.stage",
            "clinical.stage",
            "stage",
            "tumor_stage",
            "pathologic_stage",
            "clinical_stage",
            "ajcc_pathologic_stage",
            "ajcc_clinical_stage",
        )
    )
    smoking = _normalize_smoking_status(
        _pick_string(
            payload,
            "patient_summary.smoking_status",
            "summary.smoking_status",
            "clinical.smoking_status",
            "smoking_status",
            "tobacco_smoking_status",
            "tobacco_smoking_history",
        )
    )
    return stage, smoking


def _extract_stage_and_smoking_from_xml(path: Path) -> tuple[str | None, str | None]:
    try:
        root = ElementTree.fromstring(path.read_text(encoding="utf-8"))
    except (OSError, ElementTree.ParseError):
        return None, None

    tag_values: dict[str, str] = {}
    for node in root.iter():
        text = (node.text or "").strip()
        if not text:
            continue
        tag = node.tag
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        normalized_tag = tag.strip().lower()
        if not normalized_tag or normalized_tag in tag_values:
            continue
        tag_values[normalized_tag] = text

    stage = _normalize_stage(
        next(
            (
                tag_values.get(key)
                for key in (
                    "pathologic_stage",
                    "ajcc_pathologic_stage",
                    "clinical_stage",
                    "ajcc_clinical_stage",
                    "tumor_stage",
                    "stage",
                )
                if tag_values.get(key)
            ),
            None,
        )
    )

    smoking = _normalize_smoking_status(
        next(
            (
                tag_values.get(key)
                for key in (
                    "tobacco_smoking_status",
                    "tobacco_smoking_history",
                    "smoking_status",
                )
                if tag_values.get(key)
            ),
            None,
        )
    )
    return stage, smoking


def _resolve_case_clinical_metadata(
    case_id: str,
    *,
    clinical_artifact_dir: Path | None,
    clinical_xml_dir: Path | None,
) -> tuple[str | None, str | None]:
    stage: str | None = None
    smoking_status: str | None = None

    if clinical_artifact_dir is not None and clinical_artifact_dir.is_dir():
        for artifact_path in iter_artifact_json_paths(clinical_artifact_dir, [case_id]):
            payload = _load_json_mapping(artifact_path)
            if payload is None:
                continue
            artifact_stage, artifact_smoking = _extract_stage_and_smoking_from_mapping(payload)
            if stage is None:
                stage = artifact_stage
            if smoking_status is None:
                smoking_status = artifact_smoking
            if stage is not None and smoking_status is not None:
                break

    if (stage is None or smoking_status is None) and clinical_xml_dir is not None and clinical_xml_dir.is_dir():
        xml_path = resolve_best_matching_file(clinical_xml_dir, [case_id], suffixes=(".xml",))
        if xml_path is not None:
            xml_stage, xml_smoking = _extract_stage_and_smoking_from_xml(xml_path)
            if stage is None:
                stage = xml_stage
            if smoking_status is None:
                smoking_status = xml_smoking

    return stage, smoking_status


def _build_case_summaries(
    case_ids: list[str],
    *,
    transcriptomics_case_ids: set[str],
    clinical_case_ids: set[str],
    clinical_artifact_dir: Path | None,
    clinical_xml_dir: Path | None,
) -> list[CohortCaseSummary]:
    summaries: list[CohortCaseSummary] = []
    for case_id in case_ids:
        stage, smoking_status = _resolve_case_clinical_metadata(
            case_id,
            clinical_artifact_dir=clinical_artifact_dir,
            clinical_xml_dir=clinical_xml_dir,
        )
        summaries.append(
            CohortCaseSummary(
                case_id=case_id,
                display_name=case_id,
                stage=stage,
                smoking_status=smoking_status,
                has_pathology=True,
                has_transcriptomics=case_id in transcriptomics_case_ids,
                has_clinical=case_id in clinical_case_ids,
            )
        )

    return summaries


def list_overlapping_cohort_cases() -> list[CohortCaseSummary]:
    transcriptomics_case_ids = _iter_case_ids_from_paths(
        [
            _env_path("TRANSCRIPTOMICS_ARTIFACT_DIR"),
            _env_path("TRANSCRIPTOMICS_COUNTS_DIR"),
        ]
    )
    clinical_artifact_dir = _env_path("CLINICAL_ARTIFACT_DIR")
    clinical_xml_dir = _env_path("CLINICAL_XML_DIR")
    clinical_case_ids = _iter_case_ids_from_paths(
        [
            clinical_artifact_dir,
            clinical_xml_dir,
            _env_path("CLINICAL_REPORTS_DIR"),
        ]
    )

    embeddings_dir = _env_path("ENSO_EMBEDDINGS_DIR")
    slides_root = _env_path("PATHOLOGY_WSI_DIR")

    if embeddings_dir is not None and slides_root is not None:
        embedded_case_ids = _iter_embedding_case_ids(embeddings_dir)
        slide_case_ids = _iter_slide_case_ids(slides_root)
        overlap_case_ids = sorted(embedded_case_ids & slide_case_ids)
        if overlap_case_ids:
            return _build_case_summaries(
                overlap_case_ids,
                transcriptomics_case_ids=transcriptomics_case_ids,
                clinical_case_ids=clinical_case_ids,
                clinical_artifact_dir=clinical_artifact_dir,
                clinical_xml_dir=clinical_xml_dir,
            )

    # Fallback: if Enso overlap is unavailable, still provide pathology-backed case list
    # from artifact bundles so the UI remains usable without mock data.
    artifact_dir = _env_path("PATHOLOGY_ARTIFACT_DIR")
    if artifact_dir is None:
        return []

    artifact_case_ids = sorted(_iter_artifact_case_ids(artifact_dir))
    if not artifact_case_ids:
        return []

    return _build_case_summaries(
        artifact_case_ids,
        transcriptomics_case_ids=transcriptomics_case_ids,
        clinical_case_ids=clinical_case_ids,
        clinical_artifact_dir=clinical_artifact_dir,
        clinical_xml_dir=clinical_xml_dir,
    )
