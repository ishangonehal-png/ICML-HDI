from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Case, File, ModalityResult
from schemas.pathology import MethodMetadata
from schemas.transcriptomics import (
    GepReferenceGovernance,
    TranscriptomicsCaseCoverage,
    TranscriptomicsCoverageResponse,
    TranscriptomicsCoverageSummary,
    TranscriptomicsDataSource,
    TranscriptomicsDegVolcanoPlotConfig,
    TranscriptomicsDegVolcanoPoint,
    TranscriptomicsDegVolcanoResponse,
    TranscriptomicsEvidenceGene,
    TranscriptomicsEvidenceQc,
    TranscriptomicsEvidenceResponse,
    TranscriptomicsExpressionHeatmap,
    TranscriptomicsHeatmapRow,
    TranscriptomicsMaPlotPoint,
    TranscriptomicsMetricResponse,
    TranscriptomicsPlotsResponse,
    TranscriptomicsPrecomputeStatus,
    TranscriptomicsRawExpressionMatrixPreview,
    TranscriptomicsRawExpressionMatrixRow,
    TranscriptomicsSignatureScoreBar,
)

from .pathology_id_resolution import (
    derive_short_case_id,
    iter_artifact_json_paths,
    resolve_best_matching_file,
)

_METHOD_VERSION = "hackathon-p0"
_METHOD_TIMESTAMP = "2026-03-06T00:00:00Z"

_ARTIFACT_DIR_ENV = "TRANSCRIPTOMICS_ARTIFACT_DIR"
_COUNTS_DIR_ENV = "TRANSCRIPTOMICS_COUNTS_DIR"
_COVERAGE_COHORT_ENV = "TRANSCRIPTOMICS_COVERAGE_COHORT_CSV"
_GEP_REFERENCE_STATS_ENV = "TRANSCRIPTOMICS_GEP_REFERENCE_STATS_JSON"
_GEP_REFERENCE_REQUIRED_ENV = "TRANSCRIPTOMICS_GEP_REFERENCE_REQUIRED"
_GEP_REFERENCE_ID_ENV = "TRANSCRIPTOMICS_GEP_REFERENCE_ID"

_RNA_FILE_HINTS = (
    "rna",
    "transcript",
    "gene expression",
    "star",
    "counts",
    "tpm",
)

_CYT_GENES = ("GZMA", "PRF1")
_GEP18_GENES = (
    "CCL5",
    "CD27",
    "CD274",
    "CD276",
    "CD8A",
    "CMKLR1",
    "CXCL9",
    "CXCR6",
    "HLA-DQA1",
    "HLA-DRB1",
    "HLA-E",
    "IDO1",
    "LAG3",
    "NKG7",
    "PDCD1",
    "PSMB10",
    "STAT1",
    "TIGIT",
)
_GEP_MIN_GENES = 12
_TOP_GENE_LIMIT = 8
_EPSILON = 1e-6

_VOLCANO_MAX_POINTS_DEFAULT = 1200
_VOLCANO_MAX_POINTS_MIN = 1
_VOLCANO_MAX_POINTS_MAX = 5000
_VOLCANO_X_THRESHOLD_ABS = 1.0
_VOLCANO_Y_THRESHOLD = 1.3

_RAW_MATRIX_PREVIEW_LIMIT_DEFAULT = 120
_RAW_MATRIX_PREVIEW_LIMIT_MIN = 1
_RAW_MATRIX_PREVIEW_LIMIT_MAX = 500

_COUNTS_SUFFIXES = (".tsv", ".csv", ".txt")

_SOURCE_PRIORITY: dict[str, int] = {
    "artifact": 0,
    "modality_result": 1,
    "counts_tsv": 2,
    "unavailable": 3,
    "none": 4,
}


@dataclass(frozen=True)
class _ResolvedPrecompute:
    required: bool
    available: bool
    data_source: str
    unavailable_reason: str | None = None
    run_id: str | None = None
    generated_at: str | None = None


@dataclass(frozen=True)
class _GepReferenceGovernance:
    required: bool
    available: bool
    valid: bool
    reference_id: str | None = None
    reference_sha256: str | None = None
    source_path: str | None = None
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class _LoadedGepReference:
    stats: dict[str, tuple[float, float]]
    governance: _GepReferenceGovernance


@dataclass(frozen=True)
class _ResolvedMetric:
    value: float | None
    source: TranscriptomicsDataSource
    availability_code: str
    unavailable_reason: str | None = None
    precompute: _ResolvedPrecompute | None = None
    gep_reference: _GepReferenceGovernance | None = None

    @property
    def available(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class _ResolvedEvidence:
    top_genes: list[TranscriptomicsEvidenceGene]
    notes: list[str]
    source: TranscriptomicsDataSource
    availability_code: str
    unavailable_reason: str | None
    qc: TranscriptomicsEvidenceQc
    gep_reference: _GepReferenceGovernance | None = None

    @property
    def available(self) -> bool:
        return bool(self.top_genes)


@dataclass(frozen=True)
class _ResolvedCase:
    case_id: str
    has_rna_input: bool
    expression_map: dict[str, float]
    expression_source: TranscriptomicsDataSource
    cyt: _ResolvedMetric
    gep: _ResolvedMetric
    tide: _ResolvedMetric
    evidence: _ResolvedEvidence
    gep_reference: _GepReferenceGovernance


def build_transcriptomics_metadata(method: str) -> MethodMetadata:
    return MethodMetadata(
        method=method,
        version=_METHOD_VERSION,
        timestamp=_METHOD_TIMESTAMP,
        proxy_estimate=True,
    )


def get_cyt_signature(case_id: str, *, db: Session | None = None) -> TranscriptomicsMetricResponse:
    resolved = _resolve_case(case_id, db=db)
    return _build_metric_response(case_id=case_id, metric_name="cyt", metric=resolved.cyt)


def get_gep_signature(case_id: str, *, db: Session | None = None) -> TranscriptomicsMetricResponse:
    resolved = _resolve_case(case_id, db=db)
    return _build_metric_response(case_id=case_id, metric_name="gep", metric=resolved.gep)


def get_tide_signature(case_id: str, *, db: Session | None = None) -> TranscriptomicsMetricResponse:
    resolved = _resolve_case(case_id, db=db)
    return _build_metric_response(case_id=case_id, metric_name="tide", metric=resolved.tide)


def get_transcriptomic_evidence(case_id: str, *, db: Session | None = None) -> TranscriptomicsEvidenceResponse:
    resolved = _resolve_case(case_id, db=db)
    evidence = resolved.evidence
    method = f"transcriptomics-evidence-{evidence.source}-v1"

    return TranscriptomicsEvidenceResponse(
        case_id=case_id,
        top_genes=evidence.top_genes,
        notes=evidence.notes,
        available=evidence.available,
        data_source=evidence.source,
        availability_code=evidence.availability_code,
        unavailable_reason=evidence.unavailable_reason,
        qc=evidence.qc,
        gep_reference=_as_gep_reference_governance_model(evidence.gep_reference),
        meta=build_transcriptomics_metadata(method),
    )


def get_deg_volcano(
    case_id: str,
    *,
    db: Session | None = None,
    max_points: int = _VOLCANO_MAX_POINTS_DEFAULT,
) -> TranscriptomicsDegVolcanoResponse:
    resolved = _resolve_case(case_id, db=db)

    normalized_max_points = int(max_points)
    normalized_max_points = max(_VOLCANO_MAX_POINTS_MIN, normalized_max_points)
    normalized_max_points = min(_VOLCANO_MAX_POINTS_MAX, normalized_max_points)

    expression_map = resolved.expression_map
    if not expression_map:
        availability_code = "missing_input" if not resolved.has_rna_input else "evidence_unavailable"
        unavailable_reason = (
            "No transcriptomics input detected for this case."
            if not resolved.has_rna_input
            else "RNA input exists, but expression rows required for DEG proxy are unavailable."
        )

        return TranscriptomicsDegVolcanoResponse(
            case_id=case_id,
            available=False,
            data_source="unavailable",
            availability_code=availability_code,
            unavailable_reason=unavailable_reason,
            points=[],
            plot=_empty_volcano_plot_config(total_genes_observed=0, returned_points=0),
            gep_reference=_as_gep_reference_governance_model(resolved.gep_reference),
            meta=build_transcriptomics_metadata("transcriptomics-deg-volcano-unavailable-v1"),
        )

    reference_data = _load_gep_reference_data()
    points = _build_deg_volcano_points(
        expression_map,
        reference_stats=reference_data.stats,
        max_points=normalized_max_points,
    )

    return TranscriptomicsDegVolcanoResponse(
        case_id=case_id,
        available=bool(points),
        data_source=resolved.expression_source if points else "unavailable",
        availability_code="available" if points else "evidence_unavailable",
        unavailable_reason=None if points else "No DEG proxy points could be computed from expression input.",
        points=points,
        plot=_empty_volcano_plot_config(
            total_genes_observed=len(expression_map),
            returned_points=len(points),
        ),
        gep_reference=_as_gep_reference_governance_model(reference_data.governance),
        meta=build_transcriptomics_metadata(
            f"transcriptomics-deg-volcano-{resolved.expression_source}-v1"
        ),
    )


def get_transcriptomics_plots(
    case_id: str,
    *,
    db: Session | None = None,
    max_volcano_points: int = 800,
    max_ma_points: int = 500,
    max_raw_matrix_rows: int = _RAW_MATRIX_PREVIEW_LIMIT_DEFAULT,
) -> TranscriptomicsPlotsResponse:
    """
    Unified sequencing plots for cancer transcriptomics (standard visualizations).
    Returns volcano, MA plot, top genes bar, signature scores bar, expression heatmap,
    and a bounded raw matrix preview.
    """
    resolved = _resolve_case(case_id, db=db)
    ref_data = _load_gep_reference_data()

    volcano = get_deg_volcano(case_id, db=db, max_points=max_volcano_points)
    ma_plot = _build_ma_plot_points(
        resolved.expression_map,
        ref_data.stats,
        max_points=max_ma_points,
    )
    top_genes_bar = list(resolved.evidence.top_genes)
    signature_scores = [
        TranscriptomicsSignatureScoreBar(
            label="CYT",
            value=resolved.cyt.value,
            available=resolved.cyt.available,
        ),
        TranscriptomicsSignatureScoreBar(
            label="GEP",
            value=resolved.gep.value,
            available=resolved.gep.available,
        ),
        TranscriptomicsSignatureScoreBar(
            label="TIDE",
            value=resolved.tide.value,
            available=resolved.tide.available,
        ),
    ]
    normalized_raw_matrix_rows = int(max_raw_matrix_rows)
    normalized_raw_matrix_rows = max(_RAW_MATRIX_PREVIEW_LIMIT_MIN, normalized_raw_matrix_rows)
    normalized_raw_matrix_rows = min(_RAW_MATRIX_PREVIEW_LIMIT_MAX, normalized_raw_matrix_rows)
    raw_matrix_preview = _build_raw_expression_matrix_preview(
        resolved.expression_map,
        source=resolved.expression_source,
        has_rna_input=resolved.has_rna_input,
        max_rows=normalized_raw_matrix_rows,
    )
    if top_genes_bar:
        heatmap = TranscriptomicsExpressionHeatmap(
            gene_symbols=[g.symbol for g in top_genes_bar],
            rows=[
                TranscriptomicsHeatmapRow(
                    label=case_id,
                    values=[g.normalized_count for g in top_genes_bar],
                )
            ],
            available=True,
        )
    else:
        heatmap = TranscriptomicsExpressionHeatmap(available=False)

    any_data = (
        resolved.has_rna_input
        and (
            volcano.available
            or ma_plot
            or top_genes_bar
            or any(s.available for s in signature_scores)
            or raw_matrix_preview.available
        )
    )

    return TranscriptomicsPlotsResponse(
        case_id=case_id,
        available=any_data,
        volcano=volcano if volcano.available else None,
        ma_plot=ma_plot,
        top_genes_bar=top_genes_bar,
        signature_scores=signature_scores,
        expression_heatmap=heatmap,
        raw_matrix_preview=raw_matrix_preview,
        meta=build_transcriptomics_metadata("transcriptomics-plots-v1"),
    )


def get_transcriptomics_coverage_report(
    *,
    db: Session | None = None,
    case_ids: list[str] | None = None,
) -> TranscriptomicsCoverageResponse:
    resolved_case_ids = _resolve_coverage_case_ids(db=db, case_ids=case_ids)

    case_reports: list[TranscriptomicsCaseCoverage] = []
    for case_id in resolved_case_ids:
        resolved = _resolve_case(case_id, db=db)
        missing_components = _missing_components_for_case(resolved)
        mvp_ready = all(
            component not in missing_components
            for component in ("rna_input", "cyt", "gep", "evidence")
        )

        release_gate_blockers = _release_gate_blockers_for_case(
            resolved,
            missing_components=missing_components,
        )
        case_reports.append(
            TranscriptomicsCaseCoverage(
                case_id=case_id,
                has_rna_input=resolved.has_rna_input,
                cyt_available=resolved.cyt.available,
                gep_available=resolved.gep.available,
                tide_available=resolved.tide.available,
                tide_precompute_available=bool(
                    resolved.tide.precompute is not None and resolved.tide.precompute.available
                ),
                tide_unavailable_reason=resolved.tide.unavailable_reason,
                evidence_available=resolved.evidence.available,
                missing_components=missing_components,
                mvp_ready=mvp_ready,
                gep_reference_valid=resolved.gep_reference.valid,
                gep_reference_required=resolved.gep_reference.required,
                gep_reference_id=resolved.gep_reference.reference_id,
                release_gate_blockers=release_gate_blockers,
                primary_data_source=_primary_data_source_for_case(resolved),
            )
        )

    summary = TranscriptomicsCoverageSummary(
        cases_total=len(case_reports),
        cases_with_rna_input=sum(1 for case in case_reports if case.has_rna_input),
        cases_with_full_mvp_coverage=sum(1 for case in case_reports if case.mvp_ready),
        cases_missing_mvp_coverage=sum(1 for case in case_reports if not case.mvp_ready),
        cases_with_tide=sum(1 for case in case_reports if case.tide_available),
        cases_missing_tide_precompute=sum(
            1
            for case in case_reports
            if case.has_rna_input and not case.tide_precompute_available
        ),
        cases_with_gep_reference_valid=sum(1 for case in case_reports if case.gep_reference_valid),
        cases_missing_gep_reference=sum(
            1
            for case in case_reports
            if case.gep_reference_required and not case.gep_reference_valid
        ),
    )

    return TranscriptomicsCoverageResponse(
        summary=summary,
        cases=case_reports,
        meta=build_transcriptomics_metadata("transcriptomics-coverage-audit-v1"),
    )


def _resolve_case(case_id: str, *, db: Session | None) -> _ResolvedCase:
    normalized_case_id = case_id.strip()
    gep_reference_data = _load_gep_reference_data()
    gep_reference = gep_reference_data.governance

    if not normalized_case_id:
        unavailable = _ResolvedMetric(
            value=None,
            source="unavailable",
            availability_code="invalid_case_id",
            unavailable_reason="case_id is required.",
            gep_reference=gep_reference,
        )
        tide_unavailable = _ResolvedMetric(
            value=None,
            source="unavailable",
            availability_code="invalid_case_id",
            unavailable_reason="case_id is required.",
            precompute=_ResolvedPrecompute(
                required=True,
                available=False,
                data_source="none",
                unavailable_reason="case_id is required.",
            ),
            gep_reference=gep_reference,
        )
        evidence = _ResolvedEvidence(
            top_genes=[],
            notes=["No case_id was provided."],
            source="unavailable",
            availability_code="invalid_case_id",
            unavailable_reason="case_id is required.",
            qc=TranscriptomicsEvidenceQc(
                has_rna_input=False,
                gene_panel_size=len(_GEP18_GENES),
                genes_present=0,
                missing_genes=list(_GEP18_GENES),
            ),
            gep_reference=gep_reference,
        )
        return _ResolvedCase(
            case_id=normalized_case_id,
            has_rna_input=False,
            expression_map={},
            expression_source="unavailable",
            cyt=unavailable,
            gep=unavailable,
            tide=tide_unavailable,
            evidence=evidence,
            gep_reference=gep_reference,
        )

    identifiers = _candidate_identifiers(normalized_case_id, db=db)
    artifact_payloads = _load_artifact_payloads(identifiers)
    modality_payloads = _load_modality_payloads(identifiers, db=db)

    expression_from_artifact = _extract_expression_from_payloads(artifact_payloads)
    expression_from_modality = _extract_expression_from_payloads(modality_payloads)
    expression_from_counts, has_counts_file_input = _load_expression_from_counts_directory(
        identifiers,
        db=db,
    )

    expression_map, expression_source = _choose_expression_source(
        artifact_expression=expression_from_artifact,
        modality_expression=expression_from_modality,
        counts_expression=expression_from_counts,
    )

    has_rna_input = (
        bool(expression_map)
        or has_counts_file_input
        or _has_rna_file_record(identifiers, db=db)
        or _payloads_indicate_transcriptomics_input([*artifact_payloads, *modality_payloads])
    )

    cyt = _resolve_cyt(
        artifact_payloads=artifact_payloads,
        modality_payloads=modality_payloads,
        expression_map=expression_map,
        expression_source=expression_source,
        has_rna_input=has_rna_input,
        gep_reference=gep_reference,
    )

    gep, missing_gep_genes = _resolve_gep(
        artifact_payloads=artifact_payloads,
        modality_payloads=modality_payloads,
        expression_map=expression_map,
        expression_source=expression_source,
        has_rna_input=has_rna_input,
        gep_reference_data=gep_reference_data,
    )

    tide = _resolve_tide(
        artifact_payloads=artifact_payloads,
        modality_payloads=modality_payloads,
        has_rna_input=has_rna_input,
        gep_reference=gep_reference,
    )

    evidence = _resolve_evidence(
        artifact_payloads=artifact_payloads,
        modality_payloads=modality_payloads,
        expression_map=expression_map,
        expression_source=expression_source,
        has_rna_input=has_rna_input,
        missing_gep_genes=missing_gep_genes,
        gep_reference=gep_reference,
    )

    final_has_rna_input = has_rna_input or cyt.available or gep.available or tide.available or evidence.available
    if final_has_rna_input != evidence.qc.has_rna_input:
        evidence = _with_evidence_qc_has_rna_input(evidence, has_rna_input=final_has_rna_input)

    return _ResolvedCase(
        case_id=normalized_case_id,
        has_rna_input=final_has_rna_input,
        expression_map=expression_map,
        expression_source=expression_source,
        cyt=cyt,
        gep=gep,
        tide=tide,
        evidence=evidence,
        gep_reference=gep_reference,
    )


def _build_metric_response(
    *,
    case_id: str,
    metric_name: str,
    metric: _ResolvedMetric,
) -> TranscriptomicsMetricResponse:
    return TranscriptomicsMetricResponse(
        case_id=case_id,
        value=metric.value,
        available=metric.available,
        data_source=metric.source,
        availability_code=metric.availability_code,
        unavailable_reason=metric.unavailable_reason,
        precompute=_as_precompute_model(metric.precompute),
        gep_reference=_as_gep_reference_governance_model(metric.gep_reference),
        meta=build_transcriptomics_metadata(f"transcriptomics-{metric_name}-{metric.source}-v1"),
    )


def _as_precompute_model(precompute: _ResolvedPrecompute | None) -> TranscriptomicsPrecomputeStatus | None:
    if precompute is None:
        return None

    return TranscriptomicsPrecomputeStatus(
        required=precompute.required,
        available=precompute.available,
        data_source=precompute.data_source,
        unavailable_reason=precompute.unavailable_reason,
        run_id=precompute.run_id,
        generated_at=precompute.generated_at,
    )


def _as_gep_reference_governance_model(
    governance: _GepReferenceGovernance | None,
) -> GepReferenceGovernance | None:
    if governance is None:
        return None

    return GepReferenceGovernance(
        required=governance.required,
        available=governance.available,
        valid=governance.valid,
        reference_id=governance.reference_id,
        reference_sha256=governance.reference_sha256,
        source_path=governance.source_path,
        unavailable_reason=governance.unavailable_reason,
    )


def _default_gep_reference_governance() -> _GepReferenceGovernance:
    return _GepReferenceGovernance(
        required=False,
        available=False,
        valid=False,
    )


def _payloads_indicate_transcriptomics_input(payloads: Iterable[dict[str, Any]]) -> bool:
    for payload in payloads:
        if _extract_metric_from_payload(payload, "cyt") is not None:
            return True
        if _extract_metric_from_payload(payload, "gep") is not None:
            return True
        if _extract_metric_from_payload(payload, "tide") is not None:
            return True
        if _extract_expression_from_payload(payload):
            return True
        if _extract_evidence_from_payload(
            payload,
            source="artifact",
            gep_reference=_default_gep_reference_governance(),
        ) is not None:
            return True
    return False


def _with_evidence_qc_has_rna_input(
    evidence: _ResolvedEvidence,
    *,
    has_rna_input: bool,
) -> _ResolvedEvidence:
    return _ResolvedEvidence(
        top_genes=evidence.top_genes,
        notes=evidence.notes,
        source=evidence.source,
        availability_code=evidence.availability_code,
        unavailable_reason=evidence.unavailable_reason,
        qc=TranscriptomicsEvidenceQc(
            has_rna_input=has_rna_input,
            gene_panel_size=evidence.qc.gene_panel_size,
            genes_present=evidence.qc.genes_present,
            missing_genes=evidence.qc.missing_genes,
        ),
        gep_reference=evidence.gep_reference,
    )


def _resolve_cyt(
    *,
    artifact_payloads: list[dict[str, Any]],
    modality_payloads: list[dict[str, Any]],
    expression_map: dict[str, float],
    expression_source: TranscriptomicsDataSource,
    has_rna_input: bool,
    gep_reference: _GepReferenceGovernance,
) -> _ResolvedMetric:
    artifact_value = _extract_metric_from_payloads(artifact_payloads, "cyt")
    if artifact_value is not None:
        return _ResolvedMetric(
            value=artifact_value,
            source="artifact",
            availability_code="available",
            gep_reference=gep_reference,
        )

    modality_value = _extract_metric_from_payloads(modality_payloads, "cyt")
    if modality_value is not None:
        return _ResolvedMetric(
            value=modality_value,
            source="modality_result",
            availability_code="available",
            gep_reference=gep_reference,
        )

    computed_value, missing_genes = _compute_cyt_from_expression(expression_map)
    if computed_value is not None:
        return _ResolvedMetric(
            value=computed_value,
            source=expression_source,
            availability_code="available",
            gep_reference=gep_reference,
        )

    if not has_rna_input:
        return _ResolvedMetric(
            value=None,
            source="unavailable",
            availability_code="missing_input",
            unavailable_reason="No transcriptomics input detected for this case.",
            gep_reference=gep_reference,
        )

    missing_token = ", ".join(missing_genes)
    return _ResolvedMetric(
        value=None,
        source="unavailable",
        availability_code="insufficient_gene_coverage",
        unavailable_reason=f"CYT requires {_CYT_GENES[0]} and {_CYT_GENES[1]} expression (missing: {missing_token}).",
        gep_reference=gep_reference,
    )


def _resolve_gep(
    *,
    artifact_payloads: list[dict[str, Any]],
    modality_payloads: list[dict[str, Any]],
    expression_map: dict[str, float],
    expression_source: TranscriptomicsDataSource,
    has_rna_input: bool,
    gep_reference_data: _LoadedGepReference,
) -> tuple[_ResolvedMetric, list[str]]:
    governance = gep_reference_data.governance

    artifact_value = _extract_metric_from_payloads(artifact_payloads, "gep")
    if artifact_value is not None:
        return (
            _ResolvedMetric(
                value=artifact_value,
                source="artifact",
                availability_code="available",
                gep_reference=governance,
            ),
            [],
        )

    modality_value = _extract_metric_from_payloads(modality_payloads, "gep")
    if modality_value is not None:
        return (
            _ResolvedMetric(
                value=modality_value,
                source="modality_result",
                availability_code="available",
                gep_reference=governance,
            ),
            [],
        )

    missing_genes = [gene for gene in _GEP18_GENES if gene not in expression_map]
    if governance.required and not governance.valid:
        return (
            _ResolvedMetric(
                value=None,
                source="unavailable",
                availability_code="frozen_reference_unavailable",
                unavailable_reason=governance.unavailable_reason
                or "Frozen GEP reference is required but unavailable.",
                gep_reference=governance,
            ),
            missing_genes,
        )

    computed_value, missing_genes, observed_gene_count = _compute_gep_from_expression(
        expression_map,
        reference_stats=gep_reference_data.stats,
    )
    if computed_value is not None:
        return (
            _ResolvedMetric(
                value=computed_value,
                source=expression_source,
                availability_code="available",
                gep_reference=governance,
            ),
            missing_genes,
        )

    if not has_rna_input:
        return (
            _ResolvedMetric(
                value=None,
                source="unavailable",
                availability_code="missing_input",
                unavailable_reason="No transcriptomics input detected for this case.",
                gep_reference=governance,
            ),
            list(_GEP18_GENES),
        )

    return (
        _ResolvedMetric(
            value=None,
            source="unavailable",
            availability_code="insufficient_gene_coverage",
            unavailable_reason=(
                "Insufficient GEP gene coverage: "
                f"{observed_gene_count}/{len(_GEP18_GENES)} observed "
                f"(minimum {_GEP_MIN_GENES})."
            ),
            gep_reference=governance,
        ),
        missing_genes,
    )


def _resolve_tide(
    *,
    artifact_payloads: list[dict[str, Any]],
    modality_payloads: list[dict[str, Any]],
    has_rna_input: bool,
    gep_reference: _GepReferenceGovernance,
) -> _ResolvedMetric:
    artifact_resolution = _extract_tide_metric_resolution_from_payloads(
        artifact_payloads,
        source="artifact",
    )
    if artifact_resolution is not None:
        value, run_id, generated_at = artifact_resolution
        return _ResolvedMetric(
            value=value,
            source="artifact",
            availability_code="available",
            precompute=_ResolvedPrecompute(
                required=True,
                available=True,
                data_source="artifact",
                run_id=run_id,
                generated_at=generated_at,
            ),
            gep_reference=gep_reference,
        )

    modality_resolution = _extract_tide_metric_resolution_from_payloads(
        modality_payloads,
        source="modality_result",
    )
    if modality_resolution is not None:
        value, run_id, generated_at = modality_resolution
        return _ResolvedMetric(
            value=value,
            source="modality_result",
            availability_code="available",
            precompute=_ResolvedPrecompute(
                required=True,
                available=True,
                data_source="modality_result",
                run_id=run_id,
                generated_at=generated_at,
            ),
            gep_reference=gep_reference,
        )

    if not has_rna_input:
        reason = "No transcriptomics input detected for this case."
        availability_code = "missing_input"
    else:
        reason = "No precomputed TIDE score is available for this case."
        availability_code = "precompute_missing"

    return _ResolvedMetric(
        value=None,
        source="unavailable",
        availability_code=availability_code,
        unavailable_reason=reason,
        precompute=_ResolvedPrecompute(
            required=True,
            available=False,
            data_source="none",
            unavailable_reason=reason,
        ),
        gep_reference=gep_reference,
    )


def _resolve_evidence(
    *,
    artifact_payloads: list[dict[str, Any]],
    modality_payloads: list[dict[str, Any]],
    expression_map: dict[str, float],
    expression_source: TranscriptomicsDataSource,
    has_rna_input: bool,
    missing_gep_genes: list[str],
    gep_reference: _GepReferenceGovernance,
) -> _ResolvedEvidence:
    artifact_evidence = _extract_evidence_from_payloads(
        artifact_payloads,
        source="artifact",
        gep_reference=gep_reference,
    )
    if artifact_evidence is not None:
        return artifact_evidence

    modality_evidence = _extract_evidence_from_payloads(
        modality_payloads,
        source="modality_result",
        gep_reference=gep_reference,
    )
    if modality_evidence is not None:
        # If transcriptomic expression is available (for example from STAR counts),
        # prefer recomputed evidence over stale/unavailable modality payloads.
        if modality_evidence.available or not expression_map:
            return modality_evidence

    if expression_map:
        top_genes = _build_top_genes_from_expression(expression_map)
        notes = [
            "Evidence derived from STAR-count TPM using log2(TPM+1) normalization.",
            "Scores are research-only transcriptomic proxies for demo use.",
        ]
        if missing_gep_genes:
            notes.append(
                f"Missing {len(missing_gep_genes)} of {len(_GEP18_GENES)} GEP genes in the current input."
            )

        return _ResolvedEvidence(
            top_genes=top_genes,
            notes=notes,
            source=expression_source,
            availability_code="available",
            unavailable_reason=None,
            qc=TranscriptomicsEvidenceQc(
                has_rna_input=True,
                gene_panel_size=len(_GEP18_GENES),
                genes_present=len(_GEP18_GENES) - len(missing_gep_genes),
                missing_genes=missing_gep_genes,
            ),
            gep_reference=gep_reference,
        )

    if not has_rna_input:
        reason = "No transcriptomics input detected for this case."
        availability_code = "missing_input"
    else:
        reason = "RNA input exists, but no transcriptomic evidence could be generated."
        availability_code = "evidence_unavailable"

    return _ResolvedEvidence(
        top_genes=[],
        notes=[reason],
        source="unavailable",
        availability_code=availability_code,
        unavailable_reason=reason,
        qc=TranscriptomicsEvidenceQc(
            has_rna_input=has_rna_input,
            gene_panel_size=len(_GEP18_GENES),
            genes_present=0,
            missing_genes=list(_GEP18_GENES),
        ),
        gep_reference=gep_reference,
    )


def _extract_metric_from_payloads(payloads: Iterable[dict[str, Any]], metric_name: str) -> float | None:
    for payload in payloads:
        value = _extract_metric_from_payload(payload, metric_name)
        if value is not None:
            return value
    return None


def _extract_metric_from_payload(payload: Mapping[str, Any], metric_name: str) -> float | None:
    candidates: list[Any] = [
        payload.get(metric_name),
        payload.get(f"{metric_name}_score"),
        _nested_get(payload, "scores", metric_name),
        _nested_get(payload, "signatures", metric_name),
        _nested_get(payload, "transcriptomics", metric_name),
    ]

    for candidate in candidates:
        value = _coerce_metric_candidate(candidate)
        if value is not None:
            return value

    return None


def _coerce_metric_candidate(candidate: Any) -> float | None:
    if isinstance(candidate, Mapping):
        nested_candidates = (
            candidate.get("value"),
            candidate.get("score"),
            candidate.get("normalized_value"),
        )
        for nested in nested_candidates:
            coerced = _coerce_float(nested)
            if coerced is not None:
                return coerced
        return None

    return _coerce_float(candidate)


def _first_non_empty_string_from_mappings(
    mappings: Iterable[Mapping[str, Any]],
    keys: Iterable[str],
) -> str | None:
    for mapping in mappings:
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _extract_tide_metric_resolution_from_payloads(
    payloads: Iterable[dict[str, Any]],
    *,
    source: str,
) -> tuple[float, str | None, str | None] | None:
    for payload in payloads:
        resolution = _extract_tide_metric_resolution_from_payload(payload, source=source)
        if resolution is not None:
            return resolution
    return None


def _extract_tide_metric_resolution_from_payload(
    payload: Mapping[str, Any],
    *,
    source: str,
) -> tuple[float, str | None, str | None] | None:
    value = _extract_metric_from_payload(payload, "tide")
    if value is None:
        return None

    tide_mappings: list[Mapping[str, Any]] = []
    for candidate in (
        payload.get("tide"),
        _nested_get(payload, "scores", "tide"),
        _nested_get(payload, "transcriptomics", "tide"),
        payload.get("provenance"),
    ):
        if isinstance(candidate, Mapping):
            tide_mappings.append(candidate)

    run_id = _first_non_empty_string_from_mappings(
        tide_mappings,
        (
            "run_id",
            "tide_run_id",
            "job_id",
            "inference_run_id",
        ),
    )
    generated_at = _first_non_empty_string_from_mappings(
        tide_mappings,
        (
            "generated_at",
            "computed_at",
            "timestamp",
        ),
    )

    # include source token for deterministic traceability when provenance is absent
    if run_id is None:
        run_id = f"{source}:unknown-run"

    return value, run_id, generated_at


def _compute_cyt_from_expression(expression_map: Mapping[str, float]) -> tuple[float | None, list[str]]:
    missing_genes = [gene for gene in _CYT_GENES if gene not in expression_map]
    if missing_genes:
        return None, missing_genes

    gzma = expression_map[_CYT_GENES[0]]
    prf1 = expression_map[_CYT_GENES[1]]

    cyt = math.log2(math.sqrt((gzma + _EPSILON) * (prf1 + _EPSILON)))
    return _round_float(cyt), []


def _compute_gep_from_expression(
    expression_map: Mapping[str, float],
    *,
    reference_stats: Mapping[str, tuple[float, float]],
) -> tuple[float | None, list[str], int]:

    transformed_values: list[float] = []
    missing_genes: list[str] = []

    for gene in _GEP18_GENES:
        tpm = expression_map.get(gene)
        if tpm is None:
            missing_genes.append(gene)
            continue

        transformed = math.log2(tpm + 1.0)
        stats = reference_stats.get(gene)
        if stats is not None:
            mean, std = stats
            if std > 0:
                transformed = (transformed - mean) / std

        # CD276 is inversely weighted in signed-mean proxy variants.
        if gene == "CD276":
            transformed = -transformed

        transformed_values.append(transformed)

    observed_gene_count = len(transformed_values)
    if observed_gene_count < _GEP_MIN_GENES:
        return None, missing_genes, observed_gene_count

    gep = sum(transformed_values) / observed_gene_count
    return _round_float(gep), missing_genes, observed_gene_count


def _empty_volcano_plot_config(
    *,
    total_genes_observed: int,
    returned_points: int,
) -> TranscriptomicsDegVolcanoPlotConfig:
    return TranscriptomicsDegVolcanoPlotConfig(
        x_axis_label="log2 fold-change proxy",
        y_axis_label="-log10 p-value proxy",
        x_threshold_abs=_VOLCANO_X_THRESHOLD_ABS,
        y_threshold=_VOLCANO_Y_THRESHOLD,
        p_value_proxy=True,
        proxy_note=(
            "Research-only DEG-style proxy from normalized RNA expression; "
            "p-values are approximate and not for clinical use."
        ),
        total_genes_observed=total_genes_observed,
        returned_points=returned_points,
    )


def _build_deg_volcano_points(
    expression_map: Mapping[str, float],
    *,
    reference_stats: Mapping[str, tuple[float, float]],
    max_points: int,
) -> list[TranscriptomicsDegVolcanoPoint]:
    if not expression_map:
        return []

    transformed_values = [math.log2(value + 1.0) for value in expression_map.values() if value >= 0.0]
    if not transformed_values:
        return []

    sorted_values = sorted(transformed_values)
    median_transformed = sorted_values[len(sorted_values) // 2]
    abs_deviations = sorted(abs(value - median_transformed) for value in transformed_values)
    mad = abs_deviations[len(abs_deviations) // 2] if abs_deviations else 0.0

    robust_std = 1.4826 * mad
    if robust_std <= 1e-6:
        mean_value = sum(transformed_values) / len(transformed_values)
        variance = sum((value - mean_value) ** 2 for value in transformed_values) / max(len(transformed_values), 1)
        robust_std = math.sqrt(max(variance, 1e-6))

    points: list[TranscriptomicsDegVolcanoPoint] = []
    for gene_symbol, raw_tpm in expression_map.items():
        transformed = math.log2(raw_tpm + 1.0)

        reference_z: float | None = None
        log2_fc_proxy = transformed - median_transformed

        stats = reference_stats.get(gene_symbol)
        if stats is not None:
            mean, std = stats
            log2_fc_proxy = transformed - mean
            if std > 0:
                reference_z = log2_fc_proxy / std

        if reference_z is None:
            reference_z = log2_fc_proxy / max(robust_std, 1e-6)

        p_value_proxy = math.erfc(abs(reference_z) / math.sqrt(2.0))
        p_value_proxy = min(max(p_value_proxy, 1e-12), 1.0)
        y_proxy = -math.log10(p_value_proxy)

        direction: str
        if log2_fc_proxy >= _VOLCANO_X_THRESHOLD_ABS:
            direction = "up"
        elif log2_fc_proxy <= -_VOLCANO_X_THRESHOLD_ABS:
            direction = "down"
        else:
            direction = "neutral"

        significant = abs(log2_fc_proxy) >= _VOLCANO_X_THRESHOLD_ABS and y_proxy >= _VOLCANO_Y_THRESHOLD

        rounded_p_value = _round_float(p_value_proxy)
        if rounded_p_value is None:
            rounded_p_value = 1.0
        # Keep tiny probabilities tiny (avoid serializing as 1.0 due falsy `or` fallback).
        rounded_p_value = max(rounded_p_value, 1e-12)

        points.append(
            TranscriptomicsDegVolcanoPoint(
                gene_symbol=gene_symbol,
                x=_round_float(log2_fc_proxy) or 0.0,
                y=_round_float(y_proxy) or 0.0,
                log2_fc_proxy=_round_float(log2_fc_proxy) or 0.0,
                p_value_proxy=rounded_p_value,
                raw_tpm=_round_float(raw_tpm) or 0.0,
                reference_z=_round_float(reference_z) if reference_z is not None else None,
                direction=direction,
                significant=significant,
            )
        )

    return _downsample_volcano_points(points, max_points=max_points)


def _downsample_volcano_points(
    points: list[TranscriptomicsDegVolcanoPoint],
    *,
    max_points: int,
) -> list[TranscriptomicsDegVolcanoPoint]:
    if len(points) <= max_points:
        return sorted(points, key=lambda point: (-point.y, -abs(point.x), point.gene_symbol))

    selected: list[TranscriptomicsDegVolcanoPoint] = []
    selected_genes: set[str] = set()

    significant_points = sorted(
        (point for point in points if point.significant),
        key=lambda point: (-point.y, -abs(point.x), point.gene_symbol),
    )

    significant_budget = min(len(significant_points), max(100, max_points // 4))
    for point in significant_points[:significant_budget]:
        selected.append(point)
        selected_genes.add(point.gene_symbol)

    remaining_budget = max_points - len(selected)
    if remaining_budget > 0:
        candidates = [point for point in points if point.gene_symbol not in selected_genes]
        candidates.sort(key=lambda point: (point.x, point.y, point.gene_symbol))

        if candidates:
            step = len(candidates) / remaining_budget
            used_indices: set[int] = set()

            for idx in range(remaining_budget):
                candidate_index = min(int(idx * step), len(candidates) - 1)
                while candidate_index in used_indices and candidate_index + 1 < len(candidates):
                    candidate_index += 1
                if candidate_index in used_indices:
                    continue
                used_indices.add(candidate_index)
                selected.append(candidates[candidate_index])

    selected.sort(key=lambda point: (-point.y, -abs(point.x), point.gene_symbol))
    return selected[:max_points]


def _build_ma_plot_points(
    expression_map: Mapping[str, float],
    reference_stats: Mapping[str, tuple[float, float]],
    *,
    max_points: int = 500,
) -> list[TranscriptomicsMaPlotPoint]:
    """Build MA-plot points: A = mean log2 expression, M = log2FC proxy (standard cancer transcriptomics)."""
    if not expression_map:
        return []

    transformed_values = [math.log2(v + 1.0) for v in expression_map.values() if v >= 0.0]
    if not transformed_values:
        return []

    sorted_vals = sorted(transformed_values)
    median_log2 = sorted_vals[len(sorted_vals) // 2]

    points: list[TranscriptomicsMaPlotPoint] = []
    for gene_symbol, raw_tpm in expression_map.items():
        log2_this = math.log2(raw_tpm + 1.0)
        ref_mean_std = reference_stats.get(gene_symbol)
        if ref_mean_std is not None:
            ref_mean, ref_std = ref_mean_std
            mean_expr_log2 = (log2_this + ref_mean) / 2.0
            log2_fc = log2_this - ref_mean
        else:
            mean_expr_log2 = (log2_this + median_log2) / 2.0
            log2_fc = log2_this - median_log2

        significant = abs(log2_fc) >= _VOLCANO_X_THRESHOLD_ABS
        points.append(
            TranscriptomicsMaPlotPoint(
                gene_symbol=gene_symbol,
                mean_expr_log2=_round_float(mean_expr_log2) or 0.0,
                log2_fc=_round_float(log2_fc) or 0.0,
                significant=significant,
            )
        )

    points.sort(key=lambda p: (-abs(p.log2_fc), p.gene_symbol))
    return points[:max_points]


def _read_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _sha256_file(path: Path) -> str | None:
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(payload).hexdigest()


def _extract_reference_stats_mapping(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("stats", "reference_stats", "genes"):
        candidate = payload.get(key)
        if isinstance(candidate, Mapping):
            return candidate
    return payload


def _parse_gep_reference_stats(payload: Mapping[str, Any]) -> dict[str, tuple[float, float]]:
    reference: dict[str, tuple[float, float]] = {}
    stats_mapping = _extract_reference_stats_mapping(payload)

    for raw_gene, stats_payload in stats_mapping.items():
        gene = _normalize_gene_symbol(str(raw_gene))
        if not gene:
            continue

        if isinstance(stats_payload, Mapping):
            mean = _coerce_float(stats_payload.get("mean"))
            std = _coerce_float(stats_payload.get("std"))
        elif isinstance(stats_payload, list) and len(stats_payload) >= 2:
            mean = _coerce_float(stats_payload[0])
            std = _coerce_float(stats_payload[1])
        else:
            continue

        if mean is None or std is None:
            continue

        reference[gene] = (mean, std)

    return reference


def _load_gep_reference_data() -> _LoadedGepReference:
    required = _read_bool_env(_GEP_REFERENCE_REQUIRED_ENV, False)
    configured_reference_id = os.getenv(_GEP_REFERENCE_ID_ENV, "").strip() or None

    path_value = os.getenv(_GEP_REFERENCE_STATS_ENV, "").strip()
    if not path_value:
        if required:
            governance = _GepReferenceGovernance(
                required=True,
                available=False,
                valid=False,
                reference_id=configured_reference_id,
                unavailable_reason=(
                    f"{_GEP_REFERENCE_STATS_ENV} is required but not configured."
                ),
            )
        else:
            governance = _GepReferenceGovernance(
                required=False,
                available=False,
                valid=False,
                reference_id=configured_reference_id,
                unavailable_reason=f"{_GEP_REFERENCE_STATS_ENV} is not configured.",
            )

        return _LoadedGepReference(stats={}, governance=governance)

    path = Path(path_value)
    payload = _read_json_object(path)
    if payload is None:
        governance = _GepReferenceGovernance(
            required=required,
            available=path.exists(),
            valid=False,
            reference_id=configured_reference_id,
            source_path=path.resolve(strict=False).as_posix(),
            unavailable_reason="Failed to load GEP reference stats JSON payload.",
        )
        return _LoadedGepReference(stats={}, governance=governance)

    parsed_stats = _parse_gep_reference_stats(payload)
    file_digest = _sha256_file(path)

    payload_reference_id = None
    for key in ("reference_id", "reference", "id"):
        candidate = payload.get(key)
        if isinstance(candidate, str) and candidate.strip():
            payload_reference_id = candidate.strip()
            break

    metadata_block = payload.get("metadata")
    if payload_reference_id is None and isinstance(metadata_block, Mapping):
        for key in ("reference_id", "id"):
            candidate = metadata_block.get(key)
            if isinstance(candidate, str) and candidate.strip():
                payload_reference_id = candidate.strip()
                break

    resolved_reference_id = configured_reference_id or payload_reference_id
    if resolved_reference_id is None and file_digest is not None:
        resolved_reference_id = f"sha256:{file_digest[:16]}"

    is_valid = bool(parsed_stats)
    unavailable_reason = None
    if not is_valid:
        unavailable_reason = "GEP reference stats payload does not include valid mean/std entries."

    governance = _GepReferenceGovernance(
        required=required,
        available=True,
        valid=is_valid,
        reference_id=resolved_reference_id,
        reference_sha256=file_digest,
        source_path=path.resolve(strict=False).as_posix(),
        unavailable_reason=unavailable_reason,
    )

    return _LoadedGepReference(stats=parsed_stats, governance=governance)


def _extract_evidence_from_payloads(
    payloads: Iterable[dict[str, Any]],
    *,
    source: TranscriptomicsDataSource,
    gep_reference: _GepReferenceGovernance,
) -> _ResolvedEvidence | None:
    for payload in payloads:
        resolved = _extract_evidence_from_payload(
            payload,
            source=source,
            gep_reference=gep_reference,
        )
        if resolved is not None:
            return resolved
    return None


def _extract_evidence_from_payload(
    payload: Mapping[str, Any],
    *,
    source: TranscriptomicsDataSource,
    gep_reference: _GepReferenceGovernance,
) -> _ResolvedEvidence | None:
    evidence_block = payload.get("evidence")
    if not isinstance(evidence_block, Mapping):
        evidence_block = payload

    top_gene_candidates = [
        _nested_get(evidence_block, "top_genes"),
        payload.get("top_genes"),
    ]

    parsed_genes: list[TranscriptomicsEvidenceGene] = []
    for candidate in top_gene_candidates:
        parsed_genes = _parse_evidence_gene_list(candidate)
        if parsed_genes:
            break

    notes = _parse_notes(evidence_block)

    missing_genes_candidate = _nested_get(evidence_block, "missing_genes")
    missing_genes = _parse_string_list(missing_genes_candidate)

    if not parsed_genes and not notes and not missing_genes:
        return None

    if not notes:
        notes = ["Evidence loaded from precomputed transcriptomics payload."]

    genes_present = len(_GEP18_GENES) - len(missing_genes)
    if genes_present < 0:
        genes_present = 0

    return _ResolvedEvidence(
        top_genes=parsed_genes,
        notes=notes,
        source=source,
        availability_code="available" if parsed_genes else "evidence_unavailable",
        unavailable_reason=None if parsed_genes else "No transcriptomic evidence genes were provided.",
        qc=TranscriptomicsEvidenceQc(
            has_rna_input=bool(parsed_genes),
            gene_panel_size=len(_GEP18_GENES),
            genes_present=genes_present,
            missing_genes=missing_genes,
        ),
        gep_reference=gep_reference,
    )


def _build_top_genes_from_expression(expression_map: Mapping[str, float]) -> list[TranscriptomicsEvidenceGene]:
    panel_genes = sorted(set(_GEP18_GENES).union(_CYT_GENES))

    scored: list[TranscriptomicsEvidenceGene] = []
    for gene in panel_genes:
        raw_tpm = expression_map.get(gene)
        if raw_tpm is None:
            continue

        normalized = math.log2(raw_tpm + 1.0)
        scored.append(
            TranscriptomicsEvidenceGene(
                symbol=gene,
                normalized_count=_round_float(normalized) or 0.0,
                raw_tpm=_round_float(raw_tpm),
            )
        )

    scored.sort(key=lambda gene: (-gene.normalized_count, gene.symbol))
    return scored[:_TOP_GENE_LIMIT]


def _build_raw_expression_matrix_preview(
    expression_map: Mapping[str, float],
    *,
    source: TranscriptomicsDataSource,
    has_rna_input: bool,
    max_rows: int,
) -> TranscriptomicsRawExpressionMatrixPreview:
    normalized_limit = max(_RAW_MATRIX_PREVIEW_LIMIT_MIN, int(max_rows))
    normalized_limit = min(_RAW_MATRIX_PREVIEW_LIMIT_MAX, normalized_limit)

    if not expression_map:
        unavailable_reason = (
            "RNA input exists, but raw expression matrix rows are unavailable."
            if has_rna_input
            else "No transcriptomics input detected for this case."
        )
        return TranscriptomicsRawExpressionMatrixPreview(
            available=False,
            data_source="unavailable",
            unavailable_reason=unavailable_reason,
            total_genes_observed=0,
            returned_rows=0,
            preview_limit=normalized_limit,
            truncated=False,
            rows=[],
        )

    ranked_genes = sorted(
        expression_map.items(),
        key=lambda item: (-item[1], item[0]),
    )

    rows: list[TranscriptomicsRawExpressionMatrixRow] = []
    for rank, (gene_symbol, raw_value) in enumerate(ranked_genes[:normalized_limit], start=1):
        rows.append(
            TranscriptomicsRawExpressionMatrixRow(
                gene_symbol=gene_symbol,
                raw_value=_round_float(raw_value) or 0.0,
                normalized_log2=_round_float(math.log2(raw_value + 1.0)) or 0.0,
                rank=rank,
            )
        )

    return TranscriptomicsRawExpressionMatrixPreview(
        available=bool(rows),
        data_source=source if rows else "unavailable",
        unavailable_reason=None if rows else "Raw expression matrix preview could not be constructed.",
        total_genes_observed=len(ranked_genes),
        returned_rows=len(rows),
        preview_limit=normalized_limit,
        truncated=len(ranked_genes) > len(rows),
        rows=rows,
    )


def _choose_expression_source(
    *,
    artifact_expression: dict[str, float],
    modality_expression: dict[str, float],
    counts_expression: dict[str, float],
) -> tuple[dict[str, float], TranscriptomicsDataSource]:
    if artifact_expression:
        return artifact_expression, "artifact"
    if modality_expression:
        return modality_expression, "modality_result"
    if counts_expression:
        return counts_expression, "counts_tsv"
    return {}, "unavailable"


def _extract_expression_from_payloads(payloads: Iterable[dict[str, Any]]) -> dict[str, float]:
    for payload in payloads:
        expression = _extract_expression_from_payload(payload)
        if expression:
            return expression
    return {}


def _extract_expression_from_payload(payload: Mapping[str, Any]) -> dict[str, float]:
    explicit_blocks = [
        payload.get("expression"),
        payload.get("gene_expression"),
        _nested_get(payload, "evidence", "expression"),
    ]

    for block in explicit_blocks:
        expression = _parse_expression_block(block)
        if expression:
            return expression

    list_blocks = [
        payload.get("genes"),
        payload.get("gene_panel"),
        _nested_get(payload, "expression_rows"),
    ]

    for block in list_blocks:
        expression = _parse_expression_row_list(block)
        if expression:
            return expression

    return {}


def _parse_expression_block(block: Any) -> dict[str, float]:
    if not isinstance(block, Mapping):
        return {}

    expression: dict[str, float] = {}
    for raw_gene, raw_value in block.items():
        symbol = _normalize_gene_symbol(str(raw_gene))
        if not symbol:
            continue

        if isinstance(raw_value, Mapping):
            candidate_values = (
                raw_value.get("tpm_unstranded"),
                raw_value.get("tpm"),
                raw_value.get("raw_tpm"),
                raw_value.get("value"),
            )
            value = None
            for candidate in candidate_values:
                value = _coerce_float(candidate)
                if value is not None:
                    break
        else:
            value = _coerce_float(raw_value)

        if value is None:
            continue

        _update_expression_value(expression, symbol=symbol, value=value)

    return expression


def _parse_expression_row_list(block: Any) -> dict[str, float]:
    if not isinstance(block, list):
        return {}

    expression: dict[str, float] = {}
    for item in block:
        if not isinstance(item, Mapping):
            continue

        raw_symbol = (
            item.get("symbol")
            or item.get("gene")
            or item.get("gene_name")
            or item.get("gene_symbol")
        )
        symbol = _normalize_gene_symbol(str(raw_symbol or ""))
        if not symbol:
            continue

        candidate_values = (
            item.get("tpm_unstranded"),
            item.get("tpm"),
            item.get("raw_tpm"),
            item.get("normalized_count"),
            item.get("value"),
        )
        value = None
        for candidate in candidate_values:
            value = _coerce_float(candidate)
            if value is not None:
                break

        if value is None:
            continue

        _update_expression_value(expression, symbol=symbol, value=value)

    return expression


def _load_artifact_payloads(identifiers: Iterable[str]) -> list[dict[str, Any]]:
    artifact_dir = _artifact_directory()
    if artifact_dir is None:
        return []

    payloads: list[dict[str, Any]] = []
    for artifact_path in iter_artifact_json_paths(artifact_dir, identifiers):
        payload = _read_json_object(artifact_path)
        if payload is not None:
            payloads.append(payload)

    return payloads


def _load_modality_payloads(identifiers: Iterable[str], *, db: Session | None) -> list[dict[str, Any]]:
    if db is None:
        return []

    normalized_identifiers = _dedupe_preserve_order(identifiers)
    if not normalized_identifiers:
        return []

    statement = (
        select(ModalityResult)
        .where(
            ModalityResult.case_id.in_(normalized_identifiers),
            ModalityResult.modality == "transcriptomics",
        )
        .order_by(ModalityResult.updated_at.desc(), ModalityResult.created_at.desc())
    )

    payloads: list[dict[str, Any]] = []
    for result in db.scalars(statement).all():
        payload = result.payload
        if isinstance(payload, dict):
            payloads.append(payload)

    return payloads


def _load_expression_from_counts_directory(
    identifiers: Iterable[str],
    *,
    db: Session | None,
) -> tuple[dict[str, float], bool]:
    counts_dir = _counts_directory()
    if counts_dir is None:
        return {}, False

    resolution_identifiers = _dedupe_preserve_order(identifiers)
    if db is not None and resolution_identifiers:
        file_rows = db.scalars(select(File).where(File.case_id.in_(resolution_identifiers))).all()
        for file_row in file_rows:
            for candidate in (file_row.file_name, file_row.gdc_file_id):
                if not candidate:
                    continue
                resolution_identifiers.extend(_identifier_tokens_from_string(candidate))

    resolved_counts_path = resolve_best_matching_file(
        counts_dir,
        _dedupe_preserve_order(resolution_identifiers),
        suffixes=_COUNTS_SUFFIXES,
    )
    if resolved_counts_path is None:
        return {}, False

    return _parse_counts_file(resolved_counts_path), True


def _parse_counts_file(path: Path) -> dict[str, float]:
    delimiter = _detect_delimiter(path)

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            filtered_rows = (
                line for line in handle if line.strip() and not line.lstrip().startswith("#")
            )
            reader = csv.DictReader(filtered_rows, delimiter=delimiter)
            fieldnames = list(reader.fieldnames or [])
            if not fieldnames:
                return {}

            lower_to_original = {field.strip().lower(): field for field in fieldnames if field}

            symbol_column = _first_existing_column(
                lower_to_original,
                (
                    "gene_name",
                    "gene_symbol",
                    "symbol",
                    "gene",
                    "gene_id",
                ),
            )
            value_column = _first_existing_column(
                lower_to_original,
                (
                    "tpm_unstranded",
                    "tpm",
                    "fpkm_uq_unstranded",
                    "fpkm_unstranded",
                ),
            )

            if symbol_column is None or value_column is None:
                return {}

            expression: dict[str, float] = {}
            for row in reader:
                symbol = _normalize_gene_symbol(str(row.get(symbol_column, "")))
                if not symbol:
                    continue

                value = _coerce_float(row.get(value_column))
                if value is None:
                    continue

                _update_expression_value(expression, symbol=symbol, value=value)

            return expression
    except (OSError, UnicodeError, csv.Error):
        return {}


def _has_rna_file_record(identifiers: Iterable[str], *, db: Session | None) -> bool:
    if db is None:
        return False

    normalized_identifiers = _dedupe_preserve_order(identifiers)
    if not normalized_identifiers:
        return False

    file_rows = db.scalars(select(File).where(File.case_id.in_(normalized_identifiers))).all()
    return any(_is_rna_file(file_row) for file_row in file_rows)


def _is_rna_file(file_row: File) -> bool:
    file_name = (file_row.file_name or "").strip().lower()
    file_type = (file_row.file_type or "").strip().lower()

    metadata_tokens: list[str] = []
    if isinstance(file_row.record_metadata, Mapping):
        for key in ("modality", "workflow_type", "data_type"):
            value = file_row.record_metadata.get(key)
            if isinstance(value, str):
                metadata_tokens.append(value.lower())

    searchable_tokens = " ".join([file_name, file_type, *metadata_tokens])
    if not searchable_tokens:
        return False

    if any(hint in searchable_tokens for hint in _RNA_FILE_HINTS):
        return True

    return file_name.endswith((".tsv", ".csv", ".txt")) and "rna" in file_name


def _resolve_coverage_case_ids(*, db: Session | None, case_ids: list[str] | None) -> list[str]:
    discovered_ids: list[str] = []

    if case_ids:
        discovered_ids.extend(case_ids)

    if not discovered_ids:
        discovered_ids.extend(_load_case_ids_from_coverage_csv())

        if db is not None:
            discovered_ids.extend(db.scalars(select(Case.case_id).order_by(Case.case_id)).all())

        discovered_ids.extend(_discover_case_ids_from_artifact_directory())
        discovered_ids.extend(_discover_case_ids_from_counts_directory())

    deduped = _dedupe_preserve_order(discovered_ids)
    deduped.sort()
    return deduped


def _load_case_ids_from_coverage_csv() -> list[str]:
    coverage_csv = _coverage_cohort_csv()
    if coverage_csv is None or not coverage_csv.is_file():
        return []

    delimiter = _detect_delimiter(coverage_csv)

    case_ids: list[str] = []
    with coverage_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        for row in reader:
            patient_id = (row.get("patient_id") or "").strip()
            case_id = (row.get("case_id") or "").strip()
            candidate = patient_id or case_id
            if candidate:
                case_ids.append(candidate)

    return _dedupe_preserve_order(case_ids)


def _discover_case_ids_from_artifact_directory() -> list[str]:
    artifact_dir = _artifact_directory()
    if artifact_dir is None or not artifact_dir.is_dir():
        return []

    discovered: list[str] = []
    for artifact_path in sorted(artifact_dir.rglob("*.json")):
        candidate = derive_short_case_id(artifact_path.name)
        if "TCGA-" not in candidate.upper():
            continue
        discovered.append(candidate)

    return _dedupe_preserve_order(discovered)


def _discover_case_ids_from_counts_directory() -> list[str]:
    counts_dir = _counts_directory()
    if counts_dir is None or not counts_dir.is_dir():
        return []

    discovered: list[str] = []
    for suffix in _COUNTS_SUFFIXES:
        for counts_path in sorted(counts_dir.rglob(f"*{suffix}")):
            candidate = derive_short_case_id(counts_path.name)
            if "TCGA-" not in candidate.upper():
                continue
            discovered.append(candidate)

    return _dedupe_preserve_order(discovered)


def _missing_components_for_case(resolved: _ResolvedCase) -> list[str]:
    missing: list[str] = []
    if not resolved.has_rna_input:
        missing.append("rna_input")
    if not resolved.cyt.available:
        missing.append("cyt")
    if not resolved.gep.available:
        missing.append("gep")
    if not resolved.evidence.available:
        missing.append("evidence")
    if not resolved.tide.available:
        missing.append("tide_experimental")
    if resolved.gep_reference.required and not resolved.gep_reference.valid:
        missing.append("gep_reference")
    return missing


def _release_gate_blockers_for_case(
    resolved: _ResolvedCase,
    *,
    missing_components: list[str],
) -> list[str]:
    blockers: list[str] = []

    if "rna_input" in missing_components:
        blockers.append("missing_rna_input")

    if "cyt" in missing_components:
        blockers.append("missing_cyt")
    if "gep" in missing_components:
        blockers.append("missing_gep")
    if "evidence" in missing_components:
        blockers.append("missing_evidence")

    tide_precompute = resolved.tide.precompute
    if resolved.has_rna_input and (tide_precompute is None or not tide_precompute.available):
        blockers.append("missing_tide_precompute")

    if resolved.gep_reference.required and not resolved.gep_reference.valid:
        blockers.append("invalid_gep_reference")

    return blockers


def _primary_data_source_for_case(resolved: _ResolvedCase) -> str:
    sources: list[str] = []

    for source in (
        resolved.cyt.source,
        resolved.gep.source,
        resolved.tide.source,
        resolved.evidence.source,
    ):
        if source != "unavailable":
            sources.append(source)

    if not sources:
        return "none"

    sources.sort(key=lambda source: (_SOURCE_PRIORITY.get(source, 99), source))
    return sources[0]


def _candidate_identifiers(case_id: str, *, db: Session | None) -> list[str]:
    identifiers = [case_id, derive_short_case_id(case_id)]

    if db is not None:
        normalized = _dedupe_preserve_order(identifiers)

        case_rows = db.scalars(select(Case).where(Case.case_id.in_(normalized))).all()
        for case_row in case_rows:
            identifiers.append(case_row.case_id)
            if isinstance(case_row.record_metadata, Mapping):
                for key in ("patient_id", "tcga_case_id", "case_id"):
                    value = case_row.record_metadata.get(key)
                    if isinstance(value, str):
                        identifiers.extend(_identifier_tokens_from_string(value))

        file_rows = db.scalars(select(File).where(File.case_id.in_(normalized))).all()
        for file_row in file_rows:
            if file_row.case_id:
                identifiers.extend(_identifier_tokens_from_string(file_row.case_id))
            if file_row.file_name:
                identifiers.extend(_identifier_tokens_from_string(file_row.file_name))
            if file_row.gdc_file_id:
                identifiers.extend(_identifier_tokens_from_string(file_row.gdc_file_id))

    return _dedupe_preserve_order(identifiers)


def _identifier_tokens_from_string(value: str) -> list[str]:
    token = value.strip()
    if not token:
        return []

    path_token = Path(token).name
    stem_token = Path(path_token).stem

    candidates = [token, path_token, stem_token, derive_short_case_id(token)]
    return _dedupe_preserve_order(candidates)


def _artifact_directory() -> Path | None:
    value = os.getenv(_ARTIFACT_DIR_ENV, "").strip()
    if not value:
        return None
    return Path(value)


def _counts_directory() -> Path | None:
    value = os.getenv(_COUNTS_DIR_ENV, "").strip()
    if not value:
        return None
    return Path(value)


def _coverage_cohort_csv() -> Path | None:
    value = os.getenv(_COVERAGE_COHORT_ENV, "").strip()
    if not value:
        return None
    return Path(value)


def _parse_evidence_gene_list(candidate: Any) -> list[TranscriptomicsEvidenceGene]:
    if not isinstance(candidate, list):
        return []

    parsed: list[TranscriptomicsEvidenceGene] = []
    for item in candidate:
        if not isinstance(item, Mapping):
            continue

        symbol_raw = (
            item.get("symbol")
            or item.get("gene")
            or item.get("gene_symbol")
            or item.get("name")
        )
        symbol = _normalize_gene_symbol(str(symbol_raw or ""))
        if not symbol:
            continue

        normalized_count = _coerce_float(
            _first_not_none(
                item.get("normalized_count"),
                item.get("log2_tpm_plus_one"),
                item.get("score"),
                item.get("value"),
            )
        )

        raw_tpm = _coerce_float(
            _first_not_none(
                item.get("raw_tpm"),
                item.get("tpm_unstranded"),
                item.get("tpm"),
            )
        )

        if normalized_count is None and raw_tpm is not None:
            normalized_count = math.log2(raw_tpm + 1.0)

        if normalized_count is None:
            continue

        parsed.append(
            TranscriptomicsEvidenceGene(
                symbol=symbol,
                normalized_count=_round_float(normalized_count) or 0.0,
                raw_tpm=_round_float(raw_tpm) if raw_tpm is not None else None,
            )
        )

    parsed.sort(key=lambda gene: (-gene.normalized_count, gene.symbol))
    return parsed[:_TOP_GENE_LIMIT]


def _parse_notes(payload: Mapping[str, Any]) -> list[str]:
    notes_candidate = payload.get("notes")
    return _parse_string_list(notes_candidate)


def _parse_string_list(candidate: Any) -> list[str]:
    if not isinstance(candidate, list):
        return []

    parsed = [str(item).strip() for item in candidate if str(item).strip()]
    return _dedupe_preserve_order(parsed)


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _parse_expression_value(value: Any) -> float | None:
    parsed = _coerce_float(value)
    if parsed is None:
        return None
    if parsed < 0:
        return None
    return parsed


def _update_expression_value(expression: dict[str, float], *, symbol: str, value: float) -> None:
    parsed_value = _parse_expression_value(value)
    if parsed_value is None:
        return

    previous = expression.get(symbol)
    if previous is None or parsed_value > previous:
        expression[symbol] = parsed_value


def _nested_get(payload: Mapping[str, Any], *path: str) -> Any:
    current: Any = payload
    for token in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(token)
    return current


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        content = path.read_text(encoding="utf-8")
        parsed = json.loads(content)
    except (OSError, json.JSONDecodeError):
        return None

    if isinstance(parsed, dict):
        return parsed
    return None


def _detect_delimiter(path: Path) -> str:
    if path.suffix.lower() == ".tsv":
        return "\t"

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(4096)
    except (OSError, UnicodeError):
        return ","

    if "\t" in sample and sample.count("\t") >= sample.count(","):
        return "\t"

    return ","


def _first_existing_column(
    lower_to_original: Mapping[str, str],
    candidates: Iterable[str],
) -> str | None:
    for candidate in candidates:
        if candidate in lower_to_original:
            return lower_to_original[candidate]
    return None


def _normalize_gene_symbol(value: str) -> str:
    token = value.strip().upper()
    if not token:
        return ""

    if "|" in token:
        parts = [part.strip() for part in token.split("|") if part.strip()]
        if parts:
            token = parts[0]
            if token.startswith("ENSG"):
                # Support common STAR/GDC "ENSG...|SYMBOL" rows by preferring
                # the first non-Ensembl segment when available.
                fallback_symbol = next((part for part in parts[1:] if not part.startswith("ENSG")), None)
                if fallback_symbol:
                    token = fallback_symbol

    if token.startswith("ENSG") and "." in token:
        token = token.split(".", 1)[0].strip()

    return token.replace(" ", "")


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None

    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(candidate):
        return None

    return _round_float(candidate)


def _round_float(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()

    for raw_value in values:
        normalized = str(raw_value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)

    return deduped
