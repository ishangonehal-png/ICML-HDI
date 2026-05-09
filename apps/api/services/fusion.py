from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Case, ModalityResult
from schemas.fusion import (
    FusionAttributionResponse,
    FusionConfidenceInterval,
    FusionModality,
    FusionModalityContribution,
    FusionProvenance,
    FusionScoreResponse,
    FusionSimilarCase,
    FusionSimilarCasesResponse,
)
from schemas.pathology import MethodMetadata

from .pathology import PathologyDataUnavailableError, get_evidence, get_tissue_composition
from .pathology_id_resolution import derive_short_case_id
from .transcriptomics import (
    get_cyt_signature,
    get_gep_signature,
    get_tide_signature,
    get_transcriptomic_evidence,
)

_METHOD_VERSION = "hackathon-p0"
_METHOD_TIMESTAMP = "2026-03-06T00:00:00Z"

_PROVISIONAL_WEIGHTS: dict[FusionModality, float] = {
    "pathology": 0.58,
    "clinical": 0.42,
    "transcriptomics": 0.0,
}

_REFINED_WEIGHTS: dict[FusionModality, float] = {
    "pathology": 0.44,
    "clinical": 0.33,
    "transcriptomics": 0.23,
}

_TRANSCRIPTOMICS_SOURCE_PRIORITY: dict[str, int] = {
    "artifact": 0,
    "modality_result": 1,
    "counts_tsv": 2,
    "unavailable": 3,
}

_STAGE_SIGNAL = {
    "i": 0.45,
    "ii": 0.54,
    "iii": 0.63,
    "iv": 0.58,
    "unknown": 0.52,
}

_SMOKER_SIGNAL = {
    "never": 0.60,
    "former": 0.55,
    "current": 0.48,
    "unknown": 0.53,
}

_STAGE_PATTERN = re.compile(r"\b(IV|III|II|I)\b", re.IGNORECASE)


@dataclass(frozen=True)
class _ResolvedModality:
    available: bool
    signal: float | None
    data_source: str
    summary: str
    unavailable_reason: str | None
    provenance: list[FusionProvenance]


@dataclass(frozen=True)
class _FusionContext:
    case_id: str
    requested_mode: str
    mode_used: str
    rna_requested: bool
    rna_applied: bool
    provisional_score: float
    refined_score: float
    delta_score: float
    provisional_ci: FusionConfidenceInterval
    refined_ci: FusionConfidenceInterval
    active_score: float
    active_weights: dict[FusionModality, float]
    modalities: dict[FusionModality, _ResolvedModality]
    modality_contributions: list[FusionModalityContribution]
    provenance: list[FusionProvenance]


def build_fusion_metadata(method: str) -> MethodMetadata:
    return MethodMetadata(
        method=method,
        version=_METHOD_VERSION,
        timestamp=_METHOD_TIMESTAMP,
        proxy_estimate=True,
    )


def get_fusion_score(
    case_id: str,
    *,
    include_rna: bool,
    db: Session | None = None,
) -> FusionScoreResponse:
    context = _build_fusion_context(
        case_id,
        include_rna=include_rna,
        db=db,
        pathology_strict_missing=False,
    )

    return FusionScoreResponse(
        case_id=context.case_id,
        requested_mode=context.requested_mode,  # type: ignore[arg-type]
        mode_used=context.mode_used,  # type: ignore[arg-type]
        rna_requested=context.rna_requested,
        rna_applied=context.rna_applied,
        provisional_score=context.provisional_score,
        refined_score=context.refined_score,
        delta_score=context.delta_score,
        provisional_ci=context.provisional_ci,
        refined_ci=context.refined_ci,
        modalities=context.modality_contributions,
        provenance=context.provenance,
        meta=build_fusion_metadata(f"fusion-score-{context.mode_used}-v1"),
    )


def get_fusion_attribution(
    case_id: str,
    *,
    include_rna: bool,
    db: Session | None = None,
) -> FusionAttributionResponse:
    context = _build_fusion_context(
        case_id,
        include_rna=include_rna,
        db=db,
        pathology_strict_missing=False,
    )

    return FusionAttributionResponse(
        case_id=context.case_id,
        requested_mode=context.requested_mode,  # type: ignore[arg-type]
        mode_used=context.mode_used,  # type: ignore[arg-type]
        score=context.active_score,
        modalities=context.modality_contributions,
        provenance=context.provenance,
        meta=build_fusion_metadata(f"fusion-attribution-{context.mode_used}-v1"),
    )


def get_fusion_similar_cases(
    case_id: str,
    *,
    include_rna: bool,
    limit: int = 5,
    db: Session | None = None,
) -> FusionSimilarCasesResponse:
    context = _build_fusion_context(
        case_id,
        include_rna=include_rna,
        db=db,
        pathology_strict_missing=False,
    )
    requested_limit = min(max(limit, 1), 10)

    candidate_case_ids = _candidate_case_ids(case_id=context.case_id, limit=requested_limit, db=db)

    neighbors: list[FusionSimilarCase] = []
    index_signals = _modality_signals(context.modality_contributions)

    for candidate_case_id in candidate_case_ids:
        try:
            candidate = _build_fusion_context(candidate_case_id, include_rna=include_rna, db=db)
        except PathologyDataUnavailableError:
            # In strict pathology mode, skip neighbors lacking artifact-backed pathology data
            # instead of failing the entire similarity endpoint.
            continue

        candidate_signals = _modality_signals(candidate.modality_contributions)
        shared_modalities = [
            modality
            for modality in ("pathology", "clinical", "transcriptomics")
            if index_signals.get(modality) is not None and candidate_signals.get(modality) is not None
        ]

        score_delta = _round(candidate.active_score - context.active_score)
        score_distance = abs(score_delta)

        if shared_modalities:
            signal_distance = sum(
                abs((index_signals[modality] or 0.0) - (candidate_signals[modality] or 0.0))
                for modality in shared_modalities
            ) / len(shared_modalities)
        else:
            signal_distance = 0.5

        distance = (0.7 * score_distance) + (0.3 * signal_distance)
        similarity = _clip01(1.0 - distance)

        if shared_modalities:
            closest_modality = min(
                shared_modalities,
                key=lambda modality: abs((index_signals[modality] or 0.0) - (candidate_signals[modality] or 0.0)),
            )
            rationale = (
                f"Score delta {score_delta:+.3f}; closest agreement in {closest_modality} signal."
            )
        else:
            rationale = f"Score delta {score_delta:+.3f}; no shared modality signals were available."

        neighbors.append(
            FusionSimilarCase(
                case_id=candidate.case_id,
                similarity=_round(similarity),
                score=candidate.active_score,
                delta_vs_index=score_delta,
                shared_modalities=shared_modalities,
                rationale=rationale,
                provenance=[
                    FusionProvenance(
                        source=f"/v1/fusion/{candidate.case_id}/score",
                        field=f"{candidate.mode_used}_score",
                        note=f"score={candidate.active_score:.6f}",
                    ),
                    FusionProvenance(
                        source="fusion://similarity",
                        field="distance",
                        note=f"distance={distance:.6f}",
                    ),
                ],
            )
        )

    neighbors.sort(key=lambda item: (-item.similarity, abs(item.delta_vs_index), item.case_id))
    neighbors = neighbors[:requested_limit]

    provenance = _dedupe_provenance(
        [
            *context.provenance,
            FusionProvenance(
                source="fusion://similarity",
                field="policy",
                note="similarity = 1 - (0.7*score_distance + 0.3*signal_distance)",
            ),
            FusionProvenance(
                source="fusion://similarity",
                field="candidate_limit",
                note=str(requested_limit),
            ),
        ]
    )

    return FusionSimilarCasesResponse(
        case_id=context.case_id,
        requested_mode=context.requested_mode,  # type: ignore[arg-type]
        mode_used=context.mode_used,  # type: ignore[arg-type]
        index_score=context.active_score,
        neighbors=neighbors,
        provenance=provenance,
        meta=build_fusion_metadata(f"fusion-similar-cases-{context.mode_used}-v1"),
    )


def _build_fusion_context(
    case_id: str,
    *,
    include_rna: bool,
    db: Session | None,
    pathology_strict_missing: bool | None = None,
) -> _FusionContext:
    normalized_case_id = _normalize_case_id(case_id)

    pathology = _resolve_pathology_signal(
        normalized_case_id,
        strict_missing=pathology_strict_missing,
    )
    clinical = _resolve_clinical_minimum(normalized_case_id, db=db)
    transcriptomics = _resolve_transcriptomics_signal(normalized_case_id, db=db)

    modalities: dict[FusionModality, _ResolvedModality] = {
        "pathology": pathology,
        "clinical": clinical,
        "transcriptomics": transcriptomics,
    }

    provisional_score = _score_from_weights(_PROVISIONAL_WEIGHTS, modalities)
    transcriptomics_available = transcriptomics.available
    refined_score = (
        _score_from_weights(_REFINED_WEIGHTS, modalities)
        if transcriptomics_available
        else provisional_score
    )

    requested_mode = "refined" if include_rna else "provisional"
    mode_used = "refined" if include_rna and transcriptomics_available else "provisional"
    active_weights = _REFINED_WEIGHTS if mode_used == "refined" else _PROVISIONAL_WEIGHTS
    active_score = refined_score if mode_used == "refined" else provisional_score

    modality_contributions: list[FusionModalityContribution] = []
    for modality in ("pathology", "clinical", "transcriptomics"):
        resolved = modalities[modality]
        weight = active_weights[modality]
        used_in_score = bool(weight > 0 and resolved.available)

        weighted_contribution = 0.0
        contribution_percent = 0.0
        if used_in_score and resolved.signal is not None:
            weighted_contribution = weight * resolved.signal
            if active_score > 0:
                contribution_percent = (weighted_contribution / active_score) * 100.0

        required_for_requested_mode = modality in ("pathology", "clinical") or (
            include_rna and modality == "transcriptomics"
        )

        modality_contributions.append(
            FusionModalityContribution(
                modality=modality,
                available=resolved.available,
                required_for_requested_mode=required_for_requested_mode,
                used_in_score=used_in_score,
                data_source=resolved.data_source,
                signal=resolved.signal,
                weight=_round(weight),
                weighted_contribution=_round(weighted_contribution),
                contribution_percent=_round(contribution_percent),
                summary=resolved.summary,
                unavailable_reason=resolved.unavailable_reason,
                provenance=resolved.provenance,
            )
        )

    provisional_ci = _build_confidence_interval(
        provisional_score,
        pathology_source=pathology.data_source,
        clinical_source=clinical.data_source,
        transcriptomics_used=False,
    )
    refined_ci = _build_confidence_interval(
        refined_score,
        pathology_source=pathology.data_source,
        clinical_source=clinical.data_source,
        transcriptomics_used=transcriptomics_available,
    )

    provenance = _dedupe_provenance(
        [
            *pathology.provenance,
            *clinical.provenance,
            *transcriptomics.provenance,
            FusionProvenance(
                source="fusion://weights",
                field="provisional",
                note="pathology=0.58, clinical=0.42",
            ),
            FusionProvenance(
                source="fusion://weights",
                field="refined",
                note="pathology=0.44, clinical=0.33, transcriptomics=0.23",
            ),
            FusionProvenance(
                source="fusion://mode",
                field="selection",
                note=(
                    f"requested={requested_mode}; used={mode_used}; "
                    f"transcriptomics_available={transcriptomics_available}"
                ),
            ),
        ]
    )

    return _FusionContext(
        case_id=normalized_case_id,
        requested_mode=requested_mode,
        mode_used=mode_used,
        rna_requested=include_rna,
        rna_applied=mode_used == "refined",
        provisional_score=provisional_score,
        refined_score=refined_score,
        delta_score=_round(refined_score - provisional_score),
        provisional_ci=provisional_ci,
        refined_ci=refined_ci,
        active_score=active_score,
        active_weights=dict(active_weights),
        modalities=modalities,
        modality_contributions=modality_contributions,
        provenance=provenance,
    )


def _resolve_pathology_signal(case_id: str, *, strict_missing: bool | None) -> _ResolvedModality:
    slide_id = f"{derive_short_case_id(case_id)}-DX1"
    tissue = get_tissue_composition(slide_id, strict_missing=strict_missing)
    evidence = get_evidence(slide_id, strict_missing=strict_missing)

    fractions_by_tissue: dict[str, float] = {
        fraction.tissue.lower(): fraction.fraction
        for fraction in tissue.fractions
    }

    tumor_fraction = fractions_by_tissue.get("tumor", 0.0)
    lymphocyte_fraction = sum(
        value
        for tissue_name, value in fractions_by_tissue.items()
        if "lymph" in tissue_name
    )
    necrosis_fraction = fractions_by_tissue.get("necrosis", 0.0)
    top_tile_score = max((tile.score for tile in evidence.top_tiles), default=0.5)

    signal = _clip01(
        (0.25)
        + (0.45 * tumor_fraction)
        + (0.30 * lymphocyte_fraction)
        + (0.20 * top_tile_score)
        - (0.20 * necrosis_fraction)
    )

    method_tokens = " ".join([tissue.meta.method, evidence.meta.method]).lower()
    data_source = "artifact" if "artifact" in method_tokens else "deterministic"

    summary = (
        "tumor={tumor:.2f}, lymphocyte={lymphocyte:.2f}, "
        "necrosis={necrosis:.2f}, top_tile_score={top_tile:.2f}"
    ).format(
        tumor=tumor_fraction,
        lymphocyte=lymphocyte_fraction,
        necrosis=necrosis_fraction,
        top_tile=top_tile_score,
    )

    return _ResolvedModality(
        available=True,
        signal=_round(signal),
        data_source=data_source,
        summary=summary,
        unavailable_reason=None,
        provenance=[
            FusionProvenance(
                source=f"/v1/pathology/slides/{slide_id}/tissue-composition",
                field="fractions",
                note=f"method={tissue.meta.method}",
            ),
            FusionProvenance(
                source=f"/v1/pathology/slides/{slide_id}/evidence",
                field="top_tiles",
                note=f"method={evidence.meta.method}",
            ),
        ],
    )


def _resolve_transcriptomics_signal(case_id: str, *, db: Session | None) -> _ResolvedModality:
    cyt = get_cyt_signature(case_id, db=db)
    gep = get_gep_signature(case_id, db=db)
    tide = get_tide_signature(case_id, db=db)
    evidence = get_transcriptomic_evidence(case_id, db=db)

    weighted_components: list[tuple[str, float, float]] = []

    if cyt.available and cyt.value is not None:
        weighted_components.append(("cyt", _sigmoid(cyt.value), 0.30))
    if gep.available and gep.value is not None:
        weighted_components.append(("gep", _sigmoid(gep.value), 0.40))
    if tide.available and tide.value is not None:
        weighted_components.append(("tide", _sigmoid(-tide.value), 0.20))

    if evidence.available and evidence.top_genes:
        top_values = [gene.normalized_count for gene in evidence.top_genes[:3]]
        if top_values:
            evidence_signal = _sigmoid((sum(top_values) / len(top_values)) - 2.0)
            weighted_components.append(("evidence", evidence_signal, 0.10))

    if weighted_components:
        weight_sum = sum(component[2] for component in weighted_components)
        signal = sum(component[1] * component[2] for component in weighted_components) / weight_sum

        source = _best_transcriptomics_source(
            [
                cyt.data_source,
                gep.data_source,
                tide.data_source,
                evidence.data_source,
            ]
        )

        summary_parts = [
            f"cyt={_metric_summary(cyt.value, cyt.available)}",
            f"gep={_metric_summary(gep.value, gep.available)}",
            f"tide={_metric_summary(tide.value, tide.available)}",
            f"evidence_genes={len(evidence.top_genes)}",
        ]
        summary = ", ".join(summary_parts)

        return _ResolvedModality(
            available=True,
            signal=_round(signal),
            data_source=source,
            summary=summary,
            unavailable_reason=None,
            provenance=[
                FusionProvenance(
                    source=f"/v1/transcriptomics/{case_id}/cyt",
                    field="value",
                    note=f"data_source={cyt.data_source}",
                ),
                FusionProvenance(
                    source=f"/v1/transcriptomics/{case_id}/gep",
                    field="value",
                    note=f"data_source={gep.data_source}",
                ),
                FusionProvenance(
                    source=f"/v1/transcriptomics/{case_id}/tide?experimental=true",
                    field="value",
                    note=f"data_source={tide.data_source}",
                ),
                FusionProvenance(
                    source=f"/v1/transcriptomics/{case_id}/evidence",
                    field="top_genes",
                    note=f"data_source={evidence.data_source}",
                ),
            ],
        )

    reason = (
        cyt.unavailable_reason
        or gep.unavailable_reason
        or tide.unavailable_reason
        or evidence.unavailable_reason
        or "Transcriptomics features were unavailable for this case."
    )

    return _ResolvedModality(
        available=False,
        signal=None,
        data_source="unavailable",
        summary=f"transcriptomics unavailable: {reason}",
        unavailable_reason=reason,
        provenance=[
            FusionProvenance(
                source=f"/v1/transcriptomics/{case_id}/cyt",
                field="available",
                note=cyt.unavailable_reason,
            ),
            FusionProvenance(
                source=f"/v1/transcriptomics/{case_id}/gep",
                field="available",
                note=gep.unavailable_reason,
            ),
            FusionProvenance(
                source=f"/v1/transcriptomics/{case_id}/evidence",
                field="available",
                note=evidence.unavailable_reason,
            ),
        ],
    )


def _resolve_clinical_minimum(case_id: str, *, db: Session | None) -> _ResolvedModality:
    payload, payload_source = _load_clinical_payload(case_id, db=db)

    if payload is not None:
        stage_group, smoker_status, age_years = _extract_clinical_features(payload)
        data_source = payload_source
        provenance_source = "db:modality_results.clinical"
    else:
        stage_group, smoker_status, age_years = _deterministic_clinical_features(case_id)
        data_source = "deterministic_proxy"
        provenance_source = f"deterministic://clinical-minimum/{case_id}"

    stage_score = _STAGE_SIGNAL.get(stage_group, _STAGE_SIGNAL["unknown"])
    smoker_score = _SMOKER_SIGNAL.get(smoker_status, _SMOKER_SIGNAL["unknown"])

    age_clamped = min(max(age_years, 35), 90)
    age_score = _clip01(1.0 - ((age_clamped - 35) / 55.0))

    signal = _clip01((0.50 * stage_score) + (0.30 * smoker_score) + (0.20 * age_score))

    summary = (
        f"stage={stage_group.upper()}, smoker={smoker_status}, age={age_years}, "
        f"stage_signal={stage_score:.2f}, smoker_signal={smoker_score:.2f}"
    )

    return _ResolvedModality(
        available=True,
        signal=_round(signal),
        data_source=data_source,
        summary=summary,
        unavailable_reason=None,
        provenance=[
            FusionProvenance(
                source=provenance_source,
                field="clinical_minimum",
                note=summary,
            )
        ],
    )


def _load_clinical_payload(case_id: str, *, db: Session | None) -> tuple[dict[str, Any] | None, str]:
    if db is None:
        return None, "deterministic_proxy"

    candidate_case_ids = _candidate_case_identifiers(case_id)

    modality_statement = (
        select(ModalityResult)
        .where(
            ModalityResult.modality == "clinical",
            ModalityResult.case_id.in_(candidate_case_ids),
        )
        .order_by(ModalityResult.updated_at.desc(), ModalityResult.created_at.desc())
    )

    for modality_result in db.scalars(modality_statement).all():
        if isinstance(modality_result.payload, dict):
            return modality_result.payload, "modality_result"

    case_statement = (
        select(Case)
        .where(Case.case_id.in_(candidate_case_ids))
        .order_by(Case.case_id.asc())
    )
    for case_row in db.scalars(case_statement).all():
        if isinstance(case_row.record_metadata, dict) and case_row.record_metadata:
            return case_row.record_metadata, "case_metadata"

    return None, "deterministic_proxy"


def _extract_clinical_features(payload: Mapping[str, Any]) -> tuple[str, str, int]:
    stage_candidate = _first_not_none(
        _nested_get(payload, "stage"),
        _nested_get(payload, "pathologic_stage"),
        _nested_get(payload, "clinical_stage"),
        _nested_get(payload, "patient_summary", "stage"),
        _nested_get(payload, "summary", "stage"),
    )

    smoker_candidate = _first_not_none(
        _nested_get(payload, "smoking_status"),
        _nested_get(payload, "smoker_status"),
        _nested_get(payload, "tobacco_smoking_history"),
        _nested_get(payload, "patient_summary", "smoking_status"),
    )

    age_candidate = _first_not_none(
        _nested_get(payload, "age"),
        _nested_get(payload, "age_at_diagnosis"),
        _nested_get(payload, "age_at_initial_pathologic_diagnosis"),
        _nested_get(payload, "patient_summary", "age"),
        _nested_get(payload, "demographics", "age"),
    )

    stage_group = _normalize_stage_group(stage_candidate)
    smoker_status = _normalize_smoker_status(smoker_candidate)
    age_years = _parse_age(age_candidate) or 62

    return stage_group, smoker_status, age_years


def _deterministic_clinical_features(case_id: str) -> tuple[str, str, int]:
    seed = _stable_hash_int(case_id)

    stage_group = ("i", "ii", "iii", "iv")[seed % 4]
    smoker_status = ("never", "former", "current", "unknown")[(seed // 7) % 4]
    age_years = 45 + ((seed // 13) % 31)

    return stage_group, smoker_status, age_years


def _build_confidence_interval(
    score: float,
    *,
    pathology_source: str,
    clinical_source: str,
    transcriptomics_used: bool,
) -> FusionConfidenceInterval:
    width = 0.18

    if pathology_source == "artifact":
        width -= 0.015
    if clinical_source == "modality_result":
        width -= 0.010
    if clinical_source == "deterministic_proxy":
        width += 0.010
    if transcriptomics_used:
        width -= 0.035

    width = min(max(width, 0.06), 0.24)

    half_width = width / 2.0
    lower = _clip01(score - half_width)
    upper = _clip01(score + half_width)

    return FusionConfidenceInterval(lower=_round(lower), upper=_round(upper))


def _score_from_weights(
    weights: Mapping[FusionModality, float],
    modalities: Mapping[FusionModality, _ResolvedModality],
) -> float:
    total = 0.0
    for modality, weight in weights.items():
        signal = modalities[modality].signal
        if signal is None:
            signal = 0.5
        total += weight * signal

    return _round(_clip01(total))


def _candidate_case_ids(*, case_id: str, limit: int, db: Session | None) -> list[str]:
    candidates: list[str] = []
    case_identifiers = set(_candidate_case_identifiers(case_id))

    # FAISS pre-filter: prepend pathologically-similar cases from Bio_ClinicalBERT index
    faiss_candidates = _faiss_similar_case_ids(case_id, top_k=limit * 2)
    candidates.extend(faiss_candidates)

    if db is not None:
        candidates.extend(db.scalars(select(Case.case_id).order_by(Case.case_id)).all())

        modality_case_ids = db.scalars(
            select(ModalityResult.case_id).distinct().order_by(ModalityResult.case_id)
        ).all()
        candidates.extend(modality_case_ids)

    if len(candidates) < limit:
        candidates.extend(_synthetic_case_ids(case_id, count=max(limit * 2, 6)))

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        token = _normalize_case_id(candidate)
        if not token or token in seen or token in case_identifiers:
            continue
        seen.add(token)
        deduped.append(token)

    return deduped[: max(limit * 3, limit)]


def _faiss_similar_case_ids(case_id: str, *, top_k: int) -> list[str]:
    """Return case IDs from Bio_ClinicalBERT FAISS index similar to case_id.

    Returns an empty list (silently) if the index is not configured or not built.
    Requires CLINICAL_PATH_REPORT_FAISS_INDEX env var pointing to the .index file.
    """
    import os
    from pathlib import Path as _Path

    index_path_raw = os.getenv("CLINICAL_PATH_REPORT_FAISS_INDEX")
    if not index_path_raw:
        return []

    index_path = _Path(index_path_raw)
    ids_path = index_path.parent / "path_report_case_ids.json"

    if not index_path.is_file() or not ids_path.is_file():
        return []

    # Find this case's embedding by looking up its PDF text
    report_dir_raw = os.getenv("CLINICAL_REPORTS_DIR")
    if not report_dir_raw:
        return []

    report_dir = _Path(report_dir_raw)
    pdf_path: _Path | None = None
    for suffix in (".pdf", ".PDF"):
        candidate = report_dir / f"{case_id}{suffix}"
        if candidate.is_file():
            pdf_path = candidate
            break
        # Also try with _pathology_report suffix
        candidate2 = report_dir / f"{case_id}_pathology_report{suffix}"
        if candidate2.is_file():
            pdf_path = candidate2
            break

    if pdf_path is None:
        return []

    try:
        import faiss  # type: ignore[import-untyped]
        import numpy as np
        from transformers import AutoModel, AutoTokenizer  # type: ignore[import-untyped]
        import torch  # type: ignore[import-untyped]
        import fitz  # type: ignore[import-untyped]

        doc = fitz.open(str(pdf_path))
        text = "\n".join(p.get_text() for p in doc)[:4096]
        doc.close()

        if not text.strip():
            return []

        _MODEL_NAME = "emilyalsentzer/Bio_ClinicalBERT"
        tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
        model = AutoModel.from_pretrained(_MODEL_NAME)
        model.eval()

        encoded = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            out = model(**encoded)
        vec = out.last_hidden_state[:, 0, :].numpy().astype("float32")
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        index = faiss.read_index(str(index_path))
        case_ids: list[str] = json.loads(ids_path.read_text(encoding="utf-8"))

        _scores, indices = index.search(vec, top_k + 1)
        results: list[str] = []
        for idx in indices[0]:
            if 0 <= idx < len(case_ids) and case_ids[idx].upper() != case_id.upper():
                results.append(case_ids[idx])
        return results[:top_k]

    except Exception:
        return []


def _synthetic_case_ids(case_id: str, *, count: int) -> list[str]:
    short_case_id = derive_short_case_id(case_id)
    parts = short_case_id.split("-")
    synthetic: list[str] = []

    if len(parts) == 3 and parts[0].upper() == "TCGA" and parts[2].isdigit():
        center = parts[1]
        base_numeric = int(parts[2])
        for offset in range(1, count + 1):
            candidate_numeric = (base_numeric + (offset * 7)) % 10000
            synthetic.append(f"TCGA-{center}-{candidate_numeric:04d}")
        return synthetic

    seed = _stable_hash_int(short_case_id)
    for offset in range(1, count + 1):
        synthetic.append(f"{short_case_id}-SIM-{(seed + offset) % 10000:04d}")

    return synthetic


def _candidate_case_identifiers(case_id: str) -> list[str]:
    short_case_id = derive_short_case_id(case_id)
    return _dedupe([case_id, short_case_id])


def _metric_summary(value: float | None, available: bool) -> str:
    if not available or value is None:
        return "NA"
    return f"{value:.3f}"


def _best_transcriptomics_source(sources: Iterable[str]) -> str:
    deduped = _dedupe([source for source in sources if source])
    if not deduped:
        return "unavailable"

    deduped.sort(key=lambda source: (_TRANSCRIPTOMICS_SOURCE_PRIORITY.get(source, 99), source))
    return deduped[0]


def _modality_signals(
    modality_contributions: Iterable[FusionModalityContribution],
) -> dict[str, float | None]:
    return {
        contribution.modality: contribution.signal
        for contribution in modality_contributions
    }


def _normalize_stage_group(value: Any) -> str:
    if value is None:
        return "unknown"

    token = str(value).strip().upper()
    if not token:
        return "unknown"

    token = token.replace("STAGE", " ").replace("PATHOLOGIC", " ").strip()

    match = _STAGE_PATTERN.search(token)
    if match is None:
        return "unknown"

    stage = match.group(1).upper()
    if stage == "I":
        return "i"
    if stage == "II":
        return "ii"
    if stage == "III":
        return "iii"
    if stage == "IV":
        return "iv"
    return "unknown"


def _normalize_smoker_status(value: Any) -> str:
    if value is None:
        return "unknown"

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        code = int(value)
        if code == 1:
            return "never"
        if code == 2:
            return "former"
        if code in (3, 4):
            return "current"
        return "unknown"

    token = str(value).strip().lower()
    if not token:
        return "unknown"

    if "never" in token:
        return "never"
    if "former" in token or "quit" in token or "ex-" in token:
        return "former"
    if "current" in token or "smok" in token:
        return "current"
    if token in {"yes", "y", "true"}:
        return "current"
    if token in {"no", "n", "false"}:
        return "never"

    return "unknown"


def _parse_age(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None

    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None

    if parsed <= 0 or parsed > 120:
        return None

    return parsed


def _nested_get(payload: Mapping[str, Any], *path: str) -> Any:
    current: Any = payload
    for token in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(token)
    return current


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _normalize_case_id(case_id: str) -> str:
    normalized = case_id.strip()
    return normalized or case_id


def _clip01(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _round(value: float) -> float:
    return round(float(value), 6)


def _stable_hash_int(token: str) -> int:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _dedupe(values: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)

    return deduped


def _dedupe_provenance(entries: Iterable[FusionProvenance]) -> list[FusionProvenance]:
    deduped: list[FusionProvenance] = []
    seen: set[tuple[str, str, str | None]] = set()

    for entry in entries:
        key = (entry.source, entry.field, entry.note)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)

    return deduped
