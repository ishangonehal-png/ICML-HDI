from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Mapping, Sequence
from xml.etree import ElementTree

import httpx

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Case, File, ModalityResult
from schemas.clinical import (
    ClinicalDataSource,
    ClinicalEligibilityCriterion,
    ClinicalEligibilityLabel,
    ClinicalEligibilityResponse,
    ClinicalPatientSummaryResponse,
    ClinicalProvenance,
    ClinicalSurvivalBaselineResponse,
    ClinicalSurvivalResponse,
    ClinicalTrialMatchItem,
    ClinicalTrialMatchResponse,
    KMStratum,
    PathReportFields,
)
from schemas.pathology import MethodMetadata
from services.pathology_id_resolution import (
    derive_short_case_id,
    enumerate_candidate_identifiers,
    iter_artifact_json_paths,
    resolve_best_matching_file,
)

_METHOD_VERSION = "hackathon-p0"
_METHOD_TIMESTAMP = "2026-03-06T00:00:00Z"

_EMPTY_SENTINELS = {"", "na", "n/a", "none", "null", "unknown", "not reported", "not available"}

_STAGE_PATTERN = re.compile(r"(?:stage\s*)?([ivx]+|[1-4])\s*([abc]?)", re.IGNORECASE)
_ECOG_PATTERN = re.compile(r"\becog\s*[:=]?\s*([0-4])\b", re.IGNORECASE)

_CLINICAL_TRIALS_API_URL = "https://clinicaltrials.gov/api/v2/studies"
_CLINICAL_TRIALS_TIMEOUT_SECONDS = 8.0
_CLINICAL_TRIALS_CACHE_TTL_SECONDS = 300
_CLINICAL_TRIALS_FETCH_MULTIPLIER = 3
_CLINICAL_TRIALS_FETCH_CAP = 60
_RECRUITING_STATUSES = {
    "RECRUITING",
    "NOT_YET_RECRUITING",
    "ENROLLING_BY_INVITATION",
    "ACTIVE_NOT_RECRUITING",
}


@dataclass
class _ClinicalFeatures:
    stage: str | None = None
    smoking_status: str | None = None
    age_at_diagnosis: int | None = None
    diagnosis: str | None = None
    sex: str | None = None
    vital_status: str | None = None
    ecog_score: int | None = None
    days_to_death: int | None = None
    days_to_last_follow_up: int | None = None
    report_highlights: list[str] = field(default_factory=list)
    # Enriched fields from TCGA clinical XML
    pack_years: float | None = None
    tnm_t: str | None = None
    tnm_n: str | None = None
    tnm_m: str | None = None
    histologic_subtype: str | None = None
    days_to_new_tumor_event: int | None = None
    # Structured path report fields (from Claude extraction cache)
    path_report_grade: str | None = None
    path_report_margins: str | None = None
    path_report_lymph_nodes_positive: int | None = None
    path_report_lymph_nodes_total: int | None = None
    path_report_lvi: str | None = None
    path_report_tumor_size_cm: float | None = None

    def has_summary_data(self) -> bool:
        return any(
            value is not None
            for value in (
                self.stage,
                self.smoking_status,
                self.age_at_diagnosis,
                self.diagnosis,
                self.sex,
                self.vital_status,
            )
        ) or bool(self.report_highlights)

    def has_any_data(self) -> bool:
        return self.has_summary_data() or any(
            value is not None
            for value in (
                self.ecog_score,
                self.days_to_death,
                self.days_to_last_follow_up,
                self.pack_years,
                self.tnm_t,
                self.histologic_subtype,
                self.days_to_new_tumor_event,
            )
        )

    def extracted_fields(self) -> list[str]:
        fields: list[str] = []
        if self.stage is not None:
            fields.append("stage")
        if self.smoking_status is not None:
            fields.append("smoking_status")
        if self.age_at_diagnosis is not None:
            fields.append("age_at_diagnosis")
        if self.diagnosis is not None:
            fields.append("diagnosis")
        if self.sex is not None:
            fields.append("sex")
        if self.vital_status is not None:
            fields.append("vital_status")
        if self.ecog_score is not None:
            fields.append("ecog_score")
        if self.days_to_death is not None:
            fields.append("days_to_death")
        if self.days_to_last_follow_up is not None:
            fields.append("days_to_last_follow_up")
        if self.report_highlights:
            fields.append("report_highlights")
        if self.pack_years is not None:
            fields.append("pack_years")
        if self.tnm_t is not None:
            fields.append("tnm_t")
        if self.tnm_n is not None:
            fields.append("tnm_n")
        if self.tnm_m is not None:
            fields.append("tnm_m")
        if self.histologic_subtype is not None:
            fields.append("histologic_subtype")
        if self.days_to_new_tumor_event is not None:
            fields.append("days_to_new_tumor_event")
        if self.path_report_grade is not None:
            fields.append("path_report_grade")
        if self.path_report_margins is not None:
            fields.append("path_report_margins")
        if self.path_report_lymph_nodes_positive is not None:
            fields.append("path_report_lymph_nodes")
        if self.path_report_lvi is not None:
            fields.append("path_report_lvi")
        if self.path_report_tumor_size_cm is not None:
            fields.append("path_report_tumor_size_cm")
        return fields


@dataclass
class _ResolvedCase:
    case_id: str
    data_source: ClinicalDataSource
    features: _ClinicalFeatures
    payload: Mapping[str, Any]
    source_paths: list[str] = field(default_factory=list)
    source_records: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _EligibilityComputation:
    available: bool
    eligible_trials: int | None
    label: ClinicalEligibilityLabel | None
    rationale: list[str]
    criteria: list[ClinicalEligibilityCriterion]
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class _SurvivalComputation:
    available: bool
    risk_group: str | None
    baseline_months: int | None
    confidence_interval: tuple[int, int] | None
    prognostic_factors: list[str]
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class _TrialQueryTerms:
    condition: str
    stage: str | None
    smoking: str | None

    def as_list(self) -> list[str]:
        terms = [self.condition]
        if self.stage:
            terms.append(self.stage)
        if self.smoking:
            terms.append(self.smoking)
        return terms


@dataclass(frozen=True)
class _TrialCacheEntry:
    expires_at: float
    response: ClinicalTrialMatchResponse


_TRIAL_MATCH_CACHE: dict[tuple[str, bool], _TrialCacheEntry] = {}


def build_clinical_metadata(method: str) -> MethodMetadata:
    return MethodMetadata(
        method=method,
        version=_METHOD_VERSION,
        timestamp=_METHOD_TIMESTAMP,
        proxy_estimate=True,
    )


def get_clinical_patient_summary(
    case_id: str,
    *,
    db: Session | None = None,
) -> ClinicalPatientSummaryResponse:
    resolved = _resolve_case(case_id, db=db)
    features = resolved.features

    if not features.has_summary_data():
        unavailable_reason = _summary_unavailable_reason(resolved)
        return ClinicalPatientSummaryResponse(
            case_id=case_id,
            stage=None,
            smoking_status=None,
            age_at_diagnosis=None,
            diagnosis=None,
            sex=None,
            vital_status=None,
            report_highlights=[],
            available=False,
            data_source=resolved.data_source,
            unavailable_reason=unavailable_reason,
            provenance=_build_provenance(
                resolved,
                extra_notes=["Summary fields missing from resolved clinical source."],
            ),
            meta=build_clinical_metadata(f"clinical-summary-{resolved.data_source}-v1"),
        )

    path_report_fields = None
    if any(
        v is not None
        for v in (
            features.path_report_grade,
            features.path_report_margins,
            features.path_report_lymph_nodes_positive,
            features.path_report_lymph_nodes_total,
            features.path_report_lvi,
            features.path_report_tumor_size_cm,
        )
    ):
        path_report_fields = PathReportFields(
            grade=features.path_report_grade,
            margins=features.path_report_margins,
            lymph_nodes_positive=features.path_report_lymph_nodes_positive,
            lymph_nodes_total=features.path_report_lymph_nodes_total,
            lvi=features.path_report_lvi,
            tumor_size_cm=features.path_report_tumor_size_cm,
            raw_highlights=features.report_highlights[:5],
        )

    return ClinicalPatientSummaryResponse(
        case_id=case_id,
        stage=features.stage,
        smoking_status=features.smoking_status,
        age_at_diagnosis=features.age_at_diagnosis,
        diagnosis=features.diagnosis,
        sex=features.sex,
        vital_status=features.vital_status,
        report_highlights=features.report_highlights,
        pack_years=features.pack_years,
        tnm_t=features.tnm_t,
        tnm_n=features.tnm_n,
        tnm_m=features.tnm_m,
        histologic_subtype=features.histologic_subtype,
        days_to_new_tumor_event=features.days_to_new_tumor_event,
        path_report_fields=path_report_fields,
        available=True,
        data_source=resolved.data_source,
        unavailable_reason=None,
        provenance=_build_provenance(resolved),
        meta=build_clinical_metadata(f"clinical-summary-{resolved.data_source}-v1"),
    )


def get_clinical_eligibility(
    case_id: str,
    *,
    db: Session | None = None,
) -> ClinicalEligibilityResponse:
    resolved = _resolve_case(case_id, db=db)

    precomputed = _extract_precomputed_eligibility(resolved.payload)
    if precomputed is not None:
        return ClinicalEligibilityResponse(
            case_id=case_id,
            eligible_trials=precomputed.eligible_trials,
            eligibility_label=precomputed.label,
            rationale=precomputed.rationale,
            criteria=precomputed.criteria,
            available=precomputed.available,
            data_source=resolved.data_source,
            unavailable_reason=precomputed.unavailable_reason,
            provenance=_build_provenance(
                resolved,
                extra_notes=["Eligibility returned from precomputed payload section."],
            ),
            meta=build_clinical_metadata(f"clinical-eligibility-{resolved.data_source}-v1"),
        )

    computed = _compute_eligibility(resolved.features)
    return ClinicalEligibilityResponse(
        case_id=case_id,
        eligible_trials=computed.eligible_trials,
        eligibility_label=computed.label,
        rationale=computed.rationale,
        criteria=computed.criteria,
        available=computed.available,
        data_source=resolved.data_source,
        unavailable_reason=computed.unavailable_reason,
        provenance=_build_provenance(resolved),
        meta=build_clinical_metadata(f"clinical-eligibility-{resolved.data_source}-v1"),
    )


def get_clinical_survival_baseline(
    case_id: str,
    *,
    db: Session | None = None,
) -> ClinicalSurvivalBaselineResponse:
    resolved = _resolve_case(case_id, db=db)

    precomputed = _extract_precomputed_survival(resolved.payload)
    if precomputed is not None:
        return ClinicalSurvivalBaselineResponse(
            case_id=case_id,
            risk_group=precomputed.risk_group,
            baseline_months=precomputed.baseline_months,
            confidence_interval=precomputed.confidence_interval,
            prognostic_factors=precomputed.prognostic_factors,
            available=precomputed.available,
            data_source=resolved.data_source,
            unavailable_reason=precomputed.unavailable_reason,
            provenance=_build_provenance(
                resolved,
                extra_notes=["Survival baseline returned from precomputed payload section."],
            ),
            meta=build_clinical_metadata(f"clinical-survival-{resolved.data_source}-v1"),
        )

    computed = _compute_survival_baseline(resolved.features)
    return ClinicalSurvivalBaselineResponse(
        case_id=case_id,
        risk_group=computed.risk_group,
        baseline_months=computed.baseline_months,
        confidence_interval=computed.confidence_interval,
        prognostic_factors=computed.prognostic_factors,
        available=computed.available,
        data_source=resolved.data_source,
        unavailable_reason=computed.unavailable_reason,
        provenance=_build_provenance(resolved),
        meta=build_clinical_metadata(f"clinical-survival-{resolved.data_source}-v1"),
    )


def clear_clinical_trial_match_cache() -> None:
    _TRIAL_MATCH_CACHE.clear()


def get_clinical_trial_matches(
    case_id: str,
    *,
    db: Session | None = None,
    limit: int = 20,
    recruiting_only: bool = True,
    force_refresh: bool = False,
) -> ClinicalTrialMatchResponse:
    normalized_limit = max(1, min(limit, 50))
    normalized_case_id = case_id.strip() or case_id
    cache_key = (normalized_case_id, recruiting_only)

    now = time.monotonic()
    cached = _TRIAL_MATCH_CACHE.get(cache_key)
    if not force_refresh and cached is not None and cached.expires_at > now:
        if len(cached.response.trials) <= normalized_limit:
            return cached.response
        return cached.response.model_copy(update={"trials": cached.response.trials[:normalized_limit]})

    resolved = _resolve_case(normalized_case_id, db=db)
    query_terms = _build_trial_query_terms(resolved.features)
    if query_terms is None:
        return ClinicalTrialMatchResponse(
            case_id=normalized_case_id,
            available=False,
            trials=[],
            data_source=resolved.data_source,
            unavailable_reason="Clinical trial query unavailable because diagnosis/stage/smoking features were not resolved.",
            query_terms=[],
            provenance=_build_provenance(
                resolved,
                extra_notes=["Trial matching requires diagnosis plus stage/smoking clinical features."],
            ),
            meta=build_clinical_metadata(f"clinical-trial-matches-{resolved.data_source}-v1"),
        )

    fetch_size = max(normalized_limit, 1)
    fetch_size = min(_CLINICAL_TRIALS_FETCH_CAP, max(fetch_size * _CLINICAL_TRIALS_FETCH_MULTIPLIER, 12))

    try:
        studies = _fetch_clinical_trials_studies(query_terms, page_size=fetch_size, recruiting_only=recruiting_only)
    except Exception as exc:  # noqa: BLE001 - translate external failures into typed unavailable payload
        return ClinicalTrialMatchResponse(
            case_id=normalized_case_id,
            available=False,
            trials=[],
            data_source=resolved.data_source,
            unavailable_reason=f"ClinicalTrials.gov unavailable: {type(exc).__name__}",
            query_terms=query_terms.as_list(),
            provenance=_build_provenance(
                resolved,
                extra_notes=["External ClinicalTrials.gov request failed."],
            ),
            meta=build_clinical_metadata(f"clinical-trial-matches-{resolved.data_source}-v1"),
        )

    trial_items = _score_and_rank_trial_matches(studies, resolved.features, recruiting_only=recruiting_only)
    cached_response = ClinicalTrialMatchResponse(
        case_id=normalized_case_id,
        available=True,
        trials=trial_items,
        data_source=resolved.data_source,
        unavailable_reason=None,
        query_terms=query_terms.as_list(),
        provenance=_build_provenance(
            resolved,
            extra_notes=[
                "Trial matches use normalized condition/stage/smoking terms only (no patient identifiers transmitted)."
            ],
        ),
        meta=build_clinical_metadata(f"clinical-trial-matches-{resolved.data_source}-v1"),
    )

    ttl_seconds = _resolve_trial_cache_ttl_seconds()
    _TRIAL_MATCH_CACHE[cache_key] = _TrialCacheEntry(
        expires_at=now + ttl_seconds,
        response=cached_response,
    )

    if len(cached_response.trials) <= normalized_limit:
        return cached_response
    return cached_response.model_copy(update={"trials": cached_response.trials[:normalized_limit]})
def get_clinical_survival(
    case_id: str,
    *,
    db: Session | None = None,
) -> ClinicalSurvivalResponse:
    """Cox PH model-backed survival predictions + KM strata for the dashboard.

    Falls back to a deterministic unavailable response when the model artifacts
    (produced by ``scripts/fit_survival_model.py``) are not present on disk.
    """
    import pickle  # noqa: PLC0415

    resolved = _resolve_case(case_id, db=db)
    features = resolved.features
    provenance = _build_provenance(resolved)

    # --- locate model artifacts ------------------------------------------------
    model_dir_raw = os.getenv("CLINICAL_SURVIVAL_MODEL_DIR")
    if not model_dir_raw:
        return ClinicalSurvivalResponse(
            case_id=case_id,
            available=False,
            data_source=resolved.data_source,
            unavailable_reason="CLINICAL_SURVIVAL_MODEL_DIR not configured",
            provenance=provenance,
            meta=build_clinical_metadata("clinical-survival-cox-v1"),
        )

    model_dir = Path(model_dir_raw)

    # Prefer RNA-augmented model when available; fall back to clinical-only.
    rna_model_path = model_dir / "cox_rna_model.pkl"
    rna_km_path = model_dir / "cox_rna_strata.json"
    clinical_model_path = model_dir / "cox_model.pkl"
    clinical_km_path = model_dir / "km_strata.json"

    use_rna_model = rna_model_path.is_file() and rna_km_path.is_file()
    cox_path = rna_model_path if use_rna_model else clinical_model_path
    km_path = rna_km_path if use_rna_model else clinical_km_path
    model_version = "cox-ph-rna-v1" if use_rna_model else "cox-ph-clinical-v1"
    stats_filename = "cox_rna_stats.json" if use_rna_model else "cohort_stats.json"

    if not cox_path.is_file() or not km_path.is_file():
        return ClinicalSurvivalResponse(
            case_id=case_id,
            available=False,
            data_source=resolved.data_source,
            unavailable_reason="Cox model artifacts not found; run scripts/fit_survival_model.py first",
            provenance=provenance,
            meta=build_clinical_metadata("clinical-survival-cox-v1"),
        )

    # --- load KM strata (always available once artifacts exist) ----------------
    km_raw = _load_json_object(km_path)
    km_strata: list[KMStratum] = []
    for label, stratum_data in (km_raw or {}).items():
        if not isinstance(stratum_data, dict):
            continue
        km_strata.append(
            KMStratum(
                label=label,
                time_points=stratum_data.get("time_points", []),
                survival_rates=stratum_data.get("survival_rates", []),
                n_at_risk=stratum_data.get("n_at_risk", []),
                n_events=stratum_data.get("n_events", 0),
                n_total=stratum_data.get("n_total", 0),
                median_survival_months=stratum_data.get("median_survival_months"),
            )
        )

    concordance_index: float | None = None
    cohort_stats_path = model_dir / stats_filename
    if cohort_stats_path.is_file():
        cohort_stats = _load_json_object(cohort_stats_path) or {}
        concordance_index = cohort_stats.get("concordance_index")

    # --- load Cox model and compute patient predictions -----------------------
    try:
        with cox_path.open("rb") as fh:
            cox_model = pickle.load(fh)  # noqa: S301 — trusted local artifact
    except Exception:
        return ClinicalSurvivalResponse(
            case_id=case_id,
            km_strata=km_strata,
            concordance_index=concordance_index,
            model_version=model_version,
            available=False,
            data_source=resolved.data_source,
            unavailable_reason="Failed to load Cox model artifact from disk",
            provenance=provenance,
            meta=build_clinical_metadata("clinical-survival-cox-v1"),
        )

    patient_row = _build_cox_patient_row(features)
    if patient_row is None:
        return ClinicalSurvivalResponse(
            case_id=case_id,
            km_strata=km_strata,
            concordance_index=concordance_index,
            model_version=model_version,
            available=False,
            data_source=resolved.data_source,
            unavailable_reason="Insufficient clinical features to build Cox patient vector (need stage/age/smoking)",
            provenance=provenance,
            meta=build_clinical_metadata("clinical-survival-cox-v1"),
        )

    # Augment patient row with RNA scores when using the RNA model.
    if use_rna_model:
        try:
            from services.transcriptomics import get_cyt_signature, get_gep_signature, get_tide_signature  # noqa: PLC0415
            cyt = get_cyt_signature(case_id, db=db)
            gep = get_gep_signature(case_id, db=db)
            tide = get_tide_signature(case_id, db=db)
            if cyt.available and cyt.value is not None:
                patient_row["cyt_score"] = float(cyt.value)
            if gep.available and gep.value is not None:
                patient_row["gep_score"] = float(gep.value)
            if tide.available and tide.value is not None:
                patient_row["tide_score"] = float(tide.value)
        except Exception:
            pass  # RNA scores unavailable; model handles missing columns via zero-fill below

    try:
        import pandas as pd  # noqa: PLC0415

        patient_df = pd.DataFrame([patient_row])
        # Align to the columns the model was trained on; zero-fill any absent RNA columns.
        model_cols = cox_model.params_.index.tolist()
        for col in model_cols:
            if col not in patient_df.columns:
                patient_df[col] = 0.0
        patient_df = patient_df[model_cols]

        sf = cox_model.predict_survival_function(patient_df)
        timeline = sf.index.tolist()

        def _survival_at(months: float) -> float | None:
            nearest = min(timeline, key=lambda t: abs(t - months), default=None)
            if nearest is None:
                return None
            return float(sf.loc[nearest].iloc[0])

        survival_prob_1yr = _survival_at(12.0)
        survival_prob_2yr = _survival_at(24.0)
        survival_prob_5yr = _survival_at(60.0)

        median_val = cox_model.predict_median(patient_df).iloc[0]
        median_months = float(median_val) if median_val is not None else None

        partial_hazard = float(cox_model.predict_partial_hazard(patient_df).iloc[0])
        if partial_hazard < 0.8:
            tier: Literal["high", "intermediate", "low"] = "high"
        elif partial_hazard < 1.5:
            tier = "intermediate"
        else:
            tier = "low"

    except Exception:
        return ClinicalSurvivalResponse(
            case_id=case_id,
            km_strata=km_strata,
            concordance_index=concordance_index,
            model_version=model_version,
            available=False,
            data_source=resolved.data_source,
            unavailable_reason="Cox model prediction failed; see server logs",
            provenance=provenance,
            meta=build_clinical_metadata("clinical-survival-cox-v1"),
        )

    return ClinicalSurvivalResponse(
        case_id=case_id,
        survival_prob_1yr=survival_prob_1yr,
        survival_prob_2yr=survival_prob_2yr,
        survival_prob_5yr=survival_prob_5yr,
        median_survival_months=median_months,
        patient_score_tier=tier,
        km_strata=km_strata,
        cox_features_used=list(patient_row.keys()),
        concordance_index=concordance_index,
        model_version=model_version,
        available=True,
        data_source=resolved.data_source,
        provenance=provenance,
        meta=build_clinical_metadata("clinical-survival-cox-v1"),
    )


def _build_cox_patient_row(features: _ClinicalFeatures) -> dict[str, float] | None:
    """Convert _ClinicalFeatures to a flat numeric dict for Cox model prediction.

    Returns None if the minimum required features (stage + age) are absent.
    """
    stage_ordinal = {
        "I": 1.0, "IA": 1.0, "IB": 1.0,
        "II": 2.0, "IIA": 2.0, "IIB": 2.0,
        "III": 3.0, "IIIA": 3.0, "IIIB": 3.0,
        "IV": 4.0,
    }
    smoking_ordinal = {"never": 0.0, "former": 1.0, "current": 2.0}

    stage_val = None
    if features.stage:
        raw_stage = features.stage.strip().upper()
        stage_val = stage_ordinal.get(raw_stage)
        if stage_val is None and raw_stage.startswith("STAGE "):
            stage_val = stage_ordinal.get(raw_stage.replace("STAGE ", "", 1).strip())
        if stage_val is None:
            normalized_stage = _normalize_stage(features.stage)
            if normalized_stage:
                normalized_token = normalized_stage.upper().replace("STAGE ", "", 1).strip()
                stage_val = stage_ordinal.get(normalized_token)
        if stage_val is None:
            bucket = _stage_bucket(features.stage)
            if bucket is not None:
                stage_val = stage_ordinal.get(bucket)

    age_val = float(features.age_at_diagnosis) if features.age_at_diagnosis is not None else None

    if stage_val is None or age_val is None:
        return None

    row: dict[str, float] = {
        "stage_ordinal": stage_val,
        "age_at_diagnosis": age_val,
        "smoking_ordinal": smoking_ordinal.get(
            (features.smoking_status or "").lower().split()[0], 1.0
        ),
        "is_female": 1.0 if (features.sex or "").lower() == "female" else 0.0,
        "pack_years": features.pack_years if features.pack_years is not None else 25.0,
    }

    # Histologic subtype one-hot (acinar is reference category)
    for subtype in ("lepidic", "micropapillary", "papillary", "solid", "mucinous"):
        row[f"subtype_{subtype}"] = 1.0 if features.histologic_subtype == subtype else 0.0

    return row


def _resolve_case(case_id: str, *, db: Session | None) -> _ResolvedCase:
    normalized_case_id = case_id.strip() or case_id
    identifiers = _candidate_identifiers(normalized_case_id)

    resolvers: list[Callable[[], _ResolvedCase | None]] = [
        lambda: _resolve_from_artifacts(normalized_case_id, identifiers),
        lambda: _resolve_from_modality_results(normalized_case_id, identifiers, db=db),
        lambda: _resolve_from_xml_and_reports(normalized_case_id, identifiers),
        lambda: _resolve_from_case_metadata(normalized_case_id, identifiers, db=db),
    ]

    for resolver in resolvers:
        resolved = resolver()
        if resolved is not None and resolved.data_source != "unavailable":
            return resolved

    return _ResolvedCase(
        case_id=normalized_case_id,
        data_source="unavailable",
        features=_ClinicalFeatures(),
        payload={},
        source_paths=[],
        source_records=[],
        notes=[
            "No artifact/modality-result/XML/case-metadata clinical sources were resolved for this case."
        ],
    )


def _resolve_from_artifacts(case_id: str, identifiers: Sequence[str]) -> _ResolvedCase | None:
    artifact_dir_raw = os.getenv("CLINICAL_ARTIFACT_DIR")
    if not artifact_dir_raw:
        return None

    artifact_dir = Path(artifact_dir_raw)
    if not artifact_dir.is_dir():
        return None

    for artifact_path in iter_artifact_json_paths(artifact_dir, identifiers):
        payload = _load_json_object(artifact_path)
        if payload is None:
            continue

        features = _extract_features_from_mapping(payload)
        source_paths = [artifact_path.as_posix()]
        notes = ["Resolved clinical artifact payload."]

        # Some artifact bundles are intentionally sparse (for example missing stage or
        # survival fields) while XML/report sources still contain those values.
        # Enrich missing fields from XML/report when available, while keeping artifact
        # as the primary source/preference.
        enrichment = _resolve_from_xml_and_reports(case_id, identifiers)
        if enrichment is not None:
            features = _merge_features(features, enrichment.features)
            payload = _merge_payloads(payload, enrichment.payload)
            source_paths = _dedupe_preserve_order(source_paths + enrichment.source_paths)
            notes.append("Enriched missing clinical fields from XML/report sources.")

        if not features.has_any_data() and not _payload_has_precomputed_sections(payload):
            continue

        return _ResolvedCase(
            case_id=case_id,
            data_source="artifact",
            features=features,
            payload=payload,
            source_paths=source_paths,
            source_records=[],
            notes=notes,
        )

    return None


def _resolve_from_modality_results(
    case_id: str,
    identifiers: Sequence[str],
    *,
    db: Session | None,
) -> _ResolvedCase | None:
    if db is None or not identifiers:
        return None

    statement = (
        select(ModalityResult)
        .where(ModalityResult.modality == "clinical")
        .where(ModalityResult.case_id.in_(list(identifiers)))
        .order_by(ModalityResult.updated_at.desc(), ModalityResult.created_at.desc())
    )
    results = db.scalars(statement).all()

    for result in results:
        payload = _coerce_mapping(result.payload)
        if payload is None:
            continue

        features = _extract_features_from_mapping(payload)
        if not features.has_any_data() and not _payload_has_precomputed_sections(payload):
            continue

        return _ResolvedCase(
            case_id=case_id,
            data_source="modality_result",
            features=features,
            payload=payload,
            source_paths=[],
            source_records=[str(result.id)],
            notes=["Resolved clinical payload from modality_results row."],
        )

    return None


def _resolve_from_xml_and_reports(case_id: str, identifiers: Sequence[str]) -> _ResolvedCase | None:
    xml_dir_raw = os.getenv("CLINICAL_XML_DIR")
    if not xml_dir_raw:
        return None

    xml_dir = Path(xml_dir_raw)
    if not xml_dir.is_dir():
        return None

    xml_path = resolve_best_matching_file(xml_dir, identifiers, suffixes=(".xml",))
    if xml_path is None:
        return None

    xml_payload = _parse_xml_file(xml_path)
    features = _extract_features_from_mapping(xml_payload)
    source_paths = [xml_path.as_posix()]
    notes = ["Parsed TCGA clinical XML source."]

    report_text = _load_report_text_for_case(identifiers)
    if report_text is not None:
        report_features = _extract_features_from_report_text(report_text)
        features = _merge_features(features, report_features)
        notes.append("Parsed report-text highlights and ECOG hints.")

        report_path = _resolve_report_path(identifiers)
        if report_path is not None:
            source_paths.append(report_path.as_posix())

    path_report_cache = _load_path_report_cache(identifiers)
    if path_report_cache is not None:
        cache_features = _extract_features_from_mapping(path_report_cache)
        features = _merge_features(features, cache_features)
        notes.append("Merged Claude-extracted path report fields from cache.")

    if not features.has_any_data() and not _payload_has_precomputed_sections(xml_payload):
        return None

    return _ResolvedCase(
        case_id=case_id,
        data_source="clinical_xml",
        features=features,
        payload=xml_payload,
        source_paths=source_paths,
        source_records=[],
        notes=notes,
    )


def _resolve_from_case_metadata(
    case_id: str,
    identifiers: Sequence[str],
    *,
    db: Session | None,
) -> _ResolvedCase | None:
    if db is None or not identifiers:
        return None

    case_statement = select(Case).where(Case.case_id.in_(list(identifiers)))
    cases = db.scalars(case_statement).all()
    if not cases:
        return None

    ranking = {identifier: rank for rank, identifier in enumerate(identifiers)}
    selected_case = sorted(cases, key=lambda case: ranking.get(case.case_id, 999_999))[0]

    features = _extract_features_from_mapping(selected_case.record_metadata)
    payload: dict[str, Any] = dict(selected_case.record_metadata)
    source_records = [str(selected_case.id)]
    notes = ["Loaded clinical fields from case metadata."]

    file_statement = select(File).where(File.case_id == selected_case.case_id)
    files = db.scalars(file_statement).all()
    for file in files:
        file_payload = _coerce_mapping(file.record_metadata)
        if file_payload is None:
            continue

        file_features = _extract_features_from_mapping(file_payload)
        features = _merge_features(features, file_features)
        payload = _merge_payloads(payload, file_payload)
        source_records.append(str(file.id))

        storage_uri = (file.storage_uri or "").strip()
        if not storage_uri:
            continue
        if not storage_uri.startswith(("/", "./", "../", "~")):
            continue

        candidate_path = Path(storage_uri).expanduser()
        if not candidate_path.is_file() or candidate_path.suffix.lower() not in {".txt", ".md", ".text"}:
            continue

        report_text = _safe_read_text(candidate_path)
        if report_text is None:
            continue

        report_features = _extract_features_from_report_text(report_text)
        features = _merge_features(features, report_features)
        if candidate_path.as_posix() not in notes:
            notes.append(f"Parsed local report text from storage URI: {candidate_path.as_posix()}")

    if not features.has_any_data() and not _payload_has_precomputed_sections(payload):
        return None

    return _ResolvedCase(
        case_id=case_id,
        data_source="case_metadata",
        features=features,
        payload=payload,
        source_paths=[],
        source_records=source_records,
        notes=notes,
    )


def _extract_precomputed_eligibility(payload: Mapping[str, Any]) -> _EligibilityComputation | None:
    section = _coerce_mapping(_resolve_path(payload, "eligibility"))
    if section is None:
        if _resolve_path(payload, "eligible_trials") is None and _resolve_path(payload, "eligibility_label") is None:
            return None
        section = payload

    available_flag = _coerce_bool(_resolve_path(section, "available"))
    if available_flag is False:
        reason = _coerce_str(_resolve_path(section, "unavailable_reason"))
        return _EligibilityComputation(
            available=False,
            eligible_trials=None,
            label=None,
            rationale=_coerce_str_list(_resolve_path(section, "rationale")),
            criteria=[],
            unavailable_reason=reason or "Precomputed eligibility section marked unavailable.",
        )

    eligible_trials = _coerce_int(_resolve_path(section, "eligible_trials"))
    if eligible_trials is None:
        return None

    label = _normalize_eligibility_label(_resolve_path(section, "eligibility_label"))
    if label is None:
        if eligible_trials >= 2:
            label = "eligible"
        elif eligible_trials <= 0:
            label = "ineligible"
        else:
            label = "indeterminate"

    rationale = _coerce_str_list(_resolve_path(section, "rationale"))
    criteria = _parse_precomputed_criteria(_resolve_path(section, "criteria"))

    return _EligibilityComputation(
        available=True,
        eligible_trials=max(0, eligible_trials),
        label=label,
        rationale=rationale,
        criteria=criteria,
        unavailable_reason=None,
    )


def _extract_precomputed_survival(payload: Mapping[str, Any]) -> _SurvivalComputation | None:
    section = _coerce_mapping(_resolve_path(payload, "survival_baseline"))
    if section is None:
        if _resolve_path(payload, "baseline_months") is None and _resolve_path(payload, "risk_group") is None:
            return None
        section = payload

    available_flag = _coerce_bool(_resolve_path(section, "available"))
    if available_flag is False:
        reason = _coerce_str(_resolve_path(section, "unavailable_reason"))
        return _SurvivalComputation(
            available=False,
            risk_group=None,
            baseline_months=None,
            confidence_interval=None,
            prognostic_factors=_coerce_str_list(_resolve_path(section, "prognostic_factors")),
            unavailable_reason=reason or "Precomputed survival section marked unavailable.",
        )

    baseline_months = _coerce_int(_resolve_path(section, "baseline_months"))
    risk_group = _normalize_risk_group(_resolve_path(section, "risk_group"))
    confidence_interval = _coerce_int_pair(_resolve_path(section, "confidence_interval"))

    if baseline_months is None or risk_group is None or confidence_interval is None:
        return None

    return _SurvivalComputation(
        available=True,
        risk_group=risk_group,
        baseline_months=max(0, baseline_months),
        confidence_interval=confidence_interval,
        prognostic_factors=_coerce_str_list(_resolve_path(section, "prognostic_factors")),
        unavailable_reason=None,
    )


def _compute_eligibility(features: _ClinicalFeatures) -> _EligibilityComputation:
    stage_bucket = _stage_bucket(features.stage)

    criteria: list[ClinicalEligibilityCriterion] = []
    known_fields = 0
    met_criteria = 0
    blocking_not_met = False

    if stage_bucket is None:
        criteria.append(
            ClinicalEligibilityCriterion(
                criterion="advanced_stage",
                status="unknown",
                observed_value=None,
                rationale="Stage unavailable; cannot determine disease-stage inclusion criterion.",
            )
        )
    else:
        known_fields += 1
        stage_met = stage_bucket in {"II", "III", "IV"}
        if stage_met:
            met_criteria += 1
        criteria.append(
            ClinicalEligibilityCriterion(
                criterion="advanced_stage",
                status="met" if stage_met else "not_met",
                observed_value=features.stage,
                rationale="Broad immunotherapy pre-screen proxy expects Stage II-IV disease.",
            )
        )

    if features.age_at_diagnosis is None:
        criteria.append(
            ClinicalEligibilityCriterion(
                criterion="adult_age_window",
                status="unknown",
                observed_value=None,
                rationale="Age unavailable; cannot validate adult age window criterion.",
            )
        )
    else:
        known_fields += 1
        age_met = 18 <= features.age_at_diagnosis <= 85
        if age_met:
            met_criteria += 1
        else:
            blocking_not_met = True
        criteria.append(
            ClinicalEligibilityCriterion(
                criterion="adult_age_window",
                status="met" if age_met else "not_met",
                observed_value=f"{features.age_at_diagnosis} years",
                rationale="Rule-based proxy uses age 18-85 as broad inclusion range.",
            )
        )

    if features.ecog_score is None:
        criteria.append(
            ClinicalEligibilityCriterion(
                criterion="performance_status",
                status="unknown",
                observed_value=None,
                rationale="ECOG unavailable; performance-status criterion cannot be fully evaluated.",
            )
        )
    else:
        known_fields += 1
        ecog_met = features.ecog_score <= 1
        if ecog_met:
            met_criteria += 1
        else:
            blocking_not_met = True
        criteria.append(
            ClinicalEligibilityCriterion(
                criterion="performance_status",
                status="met" if ecog_met else "not_met",
                observed_value=f"ECOG {features.ecog_score}",
                rationale="Heuristic pre-screen favors ECOG 0-1.",
            )
        )

    smoking = features.smoking_status
    if smoking is None:
        criteria.append(
            ClinicalEligibilityCriterion(
                criterion="smoking_history_documented",
                status="unknown",
                observed_value=None,
                rationale="Smoking history unavailable; cannot apply smoking-history proxy signal.",
            )
        )
    else:
        known_fields += 1
        smoking_met = smoking in {"Current smoker", "Former smoker", "Never smoker"}
        if smoking_met:
            met_criteria += 1
        criteria.append(
            ClinicalEligibilityCriterion(
                criterion="smoking_history_documented",
                status="met" if smoking_met else "unknown",
                observed_value=smoking,
                rationale="Documented smoking history improves trial pre-screen confidence.",
            )
        )

    if known_fields == 0:
        return _EligibilityComputation(
            available=False,
            eligible_trials=None,
            label=None,
            rationale=[],
            criteria=criteria,
            unavailable_reason="No clinical eligibility features available.",
        )

    if blocking_not_met:
        label: ClinicalEligibilityLabel = "ineligible"
        eligible_trials = 0
    elif met_criteria >= 3:
        label = "eligible"
        eligible_trials = 2
    else:
        label = "indeterminate"
        eligible_trials = 1

    rationale = [
        f"Rule-based proxy evaluated {known_fields} populated clinical criteria.",
        f"{met_criteria} criterion/criteria met; classification: {label}.",
        "Eligibility output is a research-only heuristic and requires manual trial review.",
    ]

    return _EligibilityComputation(
        available=True,
        eligible_trials=eligible_trials,
        label=label,
        rationale=rationale,
        criteria=criteria,
        unavailable_reason=None,
    )


def _compute_survival_baseline(features: _ClinicalFeatures) -> _SurvivalComputation:
    observed_months = _days_to_months(features.days_to_death)
    follow_up_months = _days_to_months(features.days_to_last_follow_up)
    stage_bucket = _stage_bucket(features.stage)

    prognostic_factors: list[str] = []

    baseline_months: int | None = None
    if observed_months is not None:
        baseline_months = max(1, round(observed_months))
        prognostic_factors.append("Observed days_to_death used as baseline anchor.")
    elif stage_bucket is not None:
        stage_baseline = {
            "I": 60,
            "II": 42,
            "III": 26,
            "IV": 12,
        }
        baseline_months = stage_baseline[stage_bucket]
        prognostic_factors.append(f"Stage-adjusted baseline derived from {features.stage}.")

        if features.age_at_diagnosis is not None:
            if features.age_at_diagnosis >= 75:
                baseline_months -= 8
                prognostic_factors.append("Age ≥ 75 decreases baseline by 8 months.")
            elif features.age_at_diagnosis >= 65:
                baseline_months -= 4
                prognostic_factors.append("Age 65-74 decreases baseline by 4 months.")

        if features.ecog_score is not None:
            if features.ecog_score >= 3:
                baseline_months -= 12
                prognostic_factors.append("ECOG ≥ 3 decreases baseline by 12 months.")
            elif features.ecog_score == 2:
                baseline_months -= 6
                prognostic_factors.append("ECOG 2 decreases baseline by 6 months.")

        if features.smoking_status == "Current smoker":
            baseline_months -= 5
            prognostic_factors.append("Current smoker status decreases baseline by 5 months.")
        elif features.smoking_status == "Former smoker":
            baseline_months -= 2
            prognostic_factors.append("Former smoker status decreases baseline by 2 months.")

        baseline_months = max(1, baseline_months)
    elif follow_up_months is not None:
        baseline_months = max(1, round(follow_up_months))
        prognostic_factors.append("Used days_to_last_follow_up as censoring-based baseline proxy.")

    if baseline_months is None:
        return _SurvivalComputation(
            available=False,
            risk_group=None,
            baseline_months=None,
            confidence_interval=None,
            prognostic_factors=[],
            unavailable_reason="No stage or follow-up survival fields available.",
        )

    if baseline_months >= 40:
        risk_group = "low"
    elif baseline_months >= 20:
        risk_group = "intermediate"
    else:
        risk_group = "high"

    ci_width = max(4, round(baseline_months * 0.2))
    confidence_interval = (max(1, baseline_months - ci_width), baseline_months + ci_width)

    if not prognostic_factors:
        prognostic_factors.append("Baseline derived from default rule set.")

    return _SurvivalComputation(
        available=True,
        risk_group=risk_group,
        baseline_months=baseline_months,
        confidence_interval=confidence_interval,
        prognostic_factors=prognostic_factors,
        unavailable_reason=None,
    )


def _build_trial_query_terms(features: _ClinicalFeatures) -> _TrialQueryTerms | None:
    condition = _condition_term_from_features(features)
    stage = _stage_query_term(features.stage)
    smoking = _smoking_query_term(features.smoking_status)

    if condition is None:
        return None

    if stage is None and smoking is None:
        return None

    return _TrialQueryTerms(condition=condition, stage=stage, smoking=smoking)


def _condition_term_from_features(features: _ClinicalFeatures) -> str | None:
    diagnosis = (features.diagnosis or "").strip().lower()
    if not diagnosis:
        return None

    if "lung" in diagnosis:
        return "lung cancer"
    if "breast" in diagnosis:
        return "breast cancer"
    if "colorectal" in diagnosis or "colon" in diagnosis:
        return "colorectal cancer"

    tokens = [token for token in re.split(r"\s+", diagnosis) if token]
    if not tokens:
        return None

    return " ".join(tokens[:4])


def _stage_query_term(stage: str | None) -> str | None:
    if not stage:
        return None

    stage_match = _STAGE_PATTERN.search(stage)
    if stage_match is None:
        return None

    major = _normalize_stage_major(stage_match.group(1).upper())
    if major is None:
        return None

    suffix = (stage_match.group(2) or "").lower()
    return f"stage {major.lower()}{suffix}"


def _smoking_query_term(smoking_status: str | None) -> str | None:
    if smoking_status is None:
        return None

    lowered = smoking_status.lower()
    if "never" in lowered:
        return "never smoker"
    if "former" in lowered:
        return "former smoker"
    if "current" in lowered:
        return "current smoker"
    return "smoker"


def _resolve_trial_cache_ttl_seconds() -> int:
    raw = os.getenv("CLINICAL_TRIAL_MATCH_CACHE_TTL_SECONDS", "")
    try:
        value = int(raw)
    except ValueError:
        value = _CLINICAL_TRIALS_CACHE_TTL_SECONDS
    return max(30, value)


def _fetch_clinical_trials_studies(
    query_terms: _TrialQueryTerms,
    *,
    page_size: int,
    recruiting_only: bool,
) -> list[Mapping[str, Any]]:
    params: dict[str, str | int] = {
        "query.cond": query_terms.condition,
        "pageSize": page_size,
        "format": "json",
    }

    query_term_parts = [part for part in (query_terms.stage, query_terms.smoking) if part]
    if query_term_parts:
        params["query.term"] = " ".join(query_term_parts)

    if recruiting_only:
        params["filter.overallStatus"] = ",".join(sorted(_RECRUITING_STATUSES))

    response = httpx.get(
        _CLINICAL_TRIALS_API_URL,
        params=params,
        timeout=_CLINICAL_TRIALS_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    payload = response.json()
    mapping = _coerce_mapping(payload)
    if mapping is None:
        return []

    studies_raw = mapping.get("studies")
    if not isinstance(studies_raw, list):
        return []

    return [entry for entry in studies_raw if isinstance(entry, Mapping)]


def _score_and_rank_trial_matches(
    studies: Sequence[Mapping[str, Any]],
    features: _ClinicalFeatures,
    *,
    recruiting_only: bool,
) -> list[ClinicalTrialMatchItem]:
    diagnosis_hint = (features.diagnosis or "").lower()
    stage_hint = _stage_query_term(features.stage)
    smoking_hint = _smoking_query_term(features.smoking_status)

    scored_rows: list[tuple[int, int, str, str, ClinicalTrialMatchItem]] = []

    for study in studies:
        protocol = _coerce_mapping(study.get("protocolSection")) or {}
        identification = _coerce_mapping(protocol.get("identificationModule")) or {}
        status_module = _coerce_mapping(protocol.get("statusModule")) or {}
        design_module = _coerce_mapping(protocol.get("designModule")) or {}
        conditions_module = _coerce_mapping(protocol.get("conditionsModule")) or {}
        eligibility_module = _coerce_mapping(protocol.get("eligibilityModule")) or {}

        title = _coerce_str(identification.get("briefTitle")) or _coerce_str(identification.get("officialTitle"))
        nct_id = _coerce_str(identification.get("nctId"))
        if title is None or nct_id is None:
            continue

        status = _coerce_str(status_module.get("overallStatus")) or "UNKNOWN"
        phases = _coerce_str_list(design_module.get("phases"))
        phase = ", ".join(_normalize_phase_label(item) for item in phases) if phases else None

        conditions = _coerce_str_list(conditions_module.get("conditions"))
        eligibility_criteria = _coerce_str(eligibility_module.get("eligibilityCriteria"))

        text_blob_parts = [title, *(conditions or []), eligibility_criteria or ""]
        searchable = " ".join(part.lower() for part in text_blob_parts if part)

        score = 0
        reasons: list[str] = []

        if "lung" in diagnosis_hint and "lung" in searchable:
            score += 5
            reasons.append("Condition aligned with lung cancer focus.")
        elif diagnosis_hint and any(token in searchable for token in diagnosis_hint.split()[:2]):
            score += 3
            reasons.append("Condition keywords overlap with extracted diagnosis.")

        if "adenocarcinoma" in diagnosis_hint and "adenocarcinoma" in searchable:
            score += 2
            reasons.append("Adenocarcinoma terminology present in study record.")

        if stage_hint and stage_hint in searchable:
            score += 3
            reasons.append(f"Eligibility text references {stage_hint}.")
        elif stage_hint and "metastatic" in searchable and "stage iv" in stage_hint:
            score += 2
            reasons.append("Metastatic language aligns with advanced-stage profile.")

        if smoking_hint and smoking_hint in searchable:
            score += 2
            reasons.append(f"Smoking-history term matched: {smoking_hint}.")
        elif smoking_hint and "smoker" in searchable:
            score += 1
            reasons.append("General smoking criterion detected.")

        if status in _RECRUITING_STATUSES:
            score += 1
            reasons.append("Currently in recruiting-adjacent status.")

        if phase and ("3" in phase or "2" in phase):
            score += 1
            reasons.append("Late-phase study provides actionable enrollment context.")

        if recruiting_only and status not in _RECRUITING_STATUSES:
            continue

        rationale = reasons[0] if reasons else "Broad disease-term match from normalized clinical context."
        row = ClinicalTrialMatchItem(
            title=title,
            nct_id=nct_id,
            status=status,
            phase=phase,
            match_score=max(score, 0),
            match_reasons=reasons[:3],
            rationale=rationale,
            study_url=f"https://clinicaltrials.gov/study/{nct_id}",
        )

        status_rank = 0 if status in _RECRUITING_STATUSES else 1
        scored_rows.append((row.match_score, status_rank, row.title.lower(), row.nct_id, row))

    scored_rows.sort(key=lambda entry: (-entry[0], entry[1], entry[2], entry[3]))
    return [entry[4] for entry in scored_rows]


def _normalize_phase_label(value: str) -> str:
    normalized = value.strip().upper()
    if normalized.startswith("EARLY_PHASE"):
        return "Early Phase"
    if normalized.startswith("PHASE") and len(normalized) > 5:
        return f"Phase {normalized[5:]}"
    if normalized == "NA":
        return "N/A"
    return value


def _build_provenance(
    resolved: _ResolvedCase,
    *,
    extra_notes: Iterable[str] | None = None,
) -> ClinicalProvenance:
    notes = list(resolved.notes)
    if extra_notes:
        notes.extend(extra_notes)

    return ClinicalProvenance(
        data_source=resolved.data_source,
        source_paths=sorted(dict.fromkeys(resolved.source_paths)),
        source_records=sorted(dict.fromkeys(resolved.source_records)),
        extracted_fields=resolved.features.extracted_fields(),
        notes=notes,
    )


def _summary_unavailable_reason(resolved: _ResolvedCase) -> str:
    if resolved.data_source == "unavailable":
        return "No clinical source found (artifact, modality_result, XML, or case metadata)."
    return "Clinical source resolved, but patient-summary fields were missing."


def _candidate_identifiers(case_id: str) -> list[str]:
    identifiers: list[str] = []
    seen: set[str] = set()

    for candidate in enumerate_candidate_identifiers(case_id):
        normalized = candidate.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        identifiers.append(normalized)

    short_case = derive_short_case_id(case_id)
    if short_case and short_case not in seen:
        seen.add(short_case)
        identifiers.append(short_case)

    return identifiers


def _load_json_object(path: Path) -> Mapping[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None

    return _coerce_mapping(payload)


def _parse_xml_file(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return {}

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

    payload: dict[str, Any] = {}

    stage = _first_non_empty(
        tag_values.get(key)
        for key in (
            "tumor_stage",
            "pathologic_stage",
            "clinical_stage",
            "ajcc_pathologic_stage",
            "ajcc_clinical_stage",
        )
    )
    if stage is not None:
        payload["stage"] = stage

    smoking = _first_non_empty(
        tag_values.get(key)
        for key in (
            "tobacco_smoking_status",
            "tobacco_smoking_history",
            "smoking_status",
        )
    )
    if smoking is not None:
        payload["smoking_status"] = smoking

    age_years = _first_non_empty(
        tag_values.get(key)
        for key in (
            "age_at_initial_pathologic_diagnosis",
            "age_at_diagnosis",
            "age",
        )
    )
    if age_years is not None:
        payload["age_at_diagnosis"] = age_years

    age_days = _first_non_empty(
        tag_values.get(key)
        for key in (
            "age_at_diagnosis_days",
            "age_at_initial_pathologic_diagnosis_days",
        )
    )
    if age_days is not None:
        payload["age_at_diagnosis_days"] = age_days

    diagnosis = _first_non_empty(
        tag_values.get(key)
        for key in (
            "primary_diagnosis",
            "histological_type",
            "disease_type",
        )
    )
    if diagnosis is not None:
        payload["diagnosis"] = diagnosis

    sex = _first_non_empty(tag_values.get(key) for key in ("gender", "sex"))
    if sex is not None:
        payload["sex"] = sex

    vital_status = _first_non_empty(tag_values.get(key) for key in ("vital_status",))
    if vital_status is not None:
        payload["vital_status"] = vital_status

    ecog = _first_non_empty(
        tag_values.get(key)
        for key in (
            "ecog_performance_status",
            "performance_status_ecog",
            "performance_status",
        )
    )
    if ecog is not None:
        payload["ecog_score"] = ecog

    days_to_death = _first_non_empty(tag_values.get(key) for key in ("days_to_death",))
    if days_to_death is not None:
        payload["days_to_death"] = days_to_death

    days_to_last_follow_up = _first_non_empty(
        tag_values.get(key)
        for key in ("days_to_last_followup", "days_to_last_follow_up")
    )
    if days_to_last_follow_up is not None:
        payload["days_to_last_follow_up"] = days_to_last_follow_up

    pack_years = _first_non_empty(
        tag_values.get(key)
        for key in ("number_pack_years_smoked", "pack_years", "pack_years_smoked")
    )
    if pack_years is not None:
        payload["pack_years"] = pack_years

    tnm_t = _first_non_empty(
        tag_values.get(key)
        for key in ("pathologic_t", "ajcc_pathologic_t", "clinical_t")
    )
    if tnm_t is not None:
        payload["tnm_t"] = tnm_t

    tnm_n = _first_non_empty(
        tag_values.get(key)
        for key in ("pathologic_n", "ajcc_pathologic_n", "clinical_n")
    )
    if tnm_n is not None:
        payload["tnm_n"] = tnm_n

    tnm_m = _first_non_empty(
        tag_values.get(key)
        for key in ("pathologic_m", "ajcc_pathologic_m", "clinical_m")
    )
    if tnm_m is not None:
        payload["tnm_m"] = tnm_m

    histologic_subtype = _first_non_empty(
        tag_values.get(key)
        for key in (
            "histological_type",
            "histologic_subtype",
            "morphology",
            "primary_histology",
        )
    )
    if histologic_subtype is not None:
        payload["histologic_subtype"] = histologic_subtype

    days_to_new_tumor_event = _first_non_empty(
        tag_values.get(key)
        for key in (
            "days_to_new_tumor_event_after_initial_treatment",
            "days_to_new_tumor_event",
            "days_to_first_recurrence",
        )
    )
    if days_to_new_tumor_event is not None:
        payload["days_to_new_tumor_event"] = days_to_new_tumor_event

    return payload


def _load_report_text_for_case(identifiers: Sequence[str]) -> str | None:
    report_path = _resolve_report_path(identifiers)
    if report_path is None:
        return None
    return _safe_read_text(report_path)


def _resolve_report_path(identifiers: Sequence[str]) -> Path | None:
    report_dir_raw = os.getenv("CLINICAL_REPORTS_DIR")
    if not report_dir_raw:
        return None

    report_dir = Path(report_dir_raw)
    if not report_dir.is_dir():
        return None

    return resolve_best_matching_file(
        report_dir,
        identifiers,
        suffixes=(".txt", ".md", ".text"),
    )


def _load_path_report_cache(identifiers: Sequence[str]) -> dict[str, Any] | None:
    """Load Claude-extracted path report fields from JSON cache if available."""
    cache_dir_raw = os.getenv("CLINICAL_PATH_REPORT_FIELDS_DIR")
    if not cache_dir_raw:
        return None

    cache_dir = Path(cache_dir_raw)
    if not cache_dir.is_dir():
        return None

    for identifier in identifiers:
        candidate = cache_dir / f"{identifier}.json"
        if candidate.is_file():
            data = _load_json_object(candidate)
            if data:
                # Prefix keys with path_report_ so _extract_features_from_mapping picks them up
                return {f"path_report_{k}" if not k.startswith("path_report_") else k: v for k, v in data.items()}

    return None


def _safe_read_text(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return text


def _extract_features_from_mapping(payload: Mapping[str, Any]) -> _ClinicalFeatures:
    stage = _normalize_stage(
        _pick_string(
            payload,
            "stage",
            "tumor_stage",
            "patient_summary.stage",
            "summary.stage",
            "clinical.stage",
        )
    )

    smoking_status = _normalize_smoking_status(
        _pick_string(
            payload,
            "smoking_status",
            "tobacco_smoking_status",
            "patient_summary.smoking_status",
            "summary.smoking_status",
            "clinical.smoking_status",
        )
    )

    age_years = _coerce_age_years(
        _pick_scalar(
            payload,
            "age_at_diagnosis",
            "age_at_diagnosis_years",
            "age_years",
            "patient_summary.age_at_diagnosis",
            "summary.age_at_diagnosis",
        )
    )
    if age_years is None:
        age_years = _coerce_age_years(
            _pick_scalar(
                payload,
                "age_at_diagnosis_days",
                "patient_summary.age_at_diagnosis_days",
                "summary.age_at_diagnosis_days",
            ),
            assume_days=True,
        )

    diagnosis = _normalize_diagnosis(
        _pick_string(
            payload,
            "diagnosis",
            "primary_diagnosis",
            "patient_summary.diagnosis",
            "summary.diagnosis",
            "clinical.diagnosis",
        )
    )

    sex = _normalize_sex(
        _pick_string(
            payload,
            "sex",
            "gender",
            "patient_summary.sex",
            "patient_summary.gender",
            "summary.sex",
            "summary.gender",
        )
    )

    vital_status = _normalize_vital_status(
        _pick_string(
            payload,
            "vital_status",
            "patient_summary.vital_status",
            "summary.vital_status",
            "clinical.vital_status",
        )
    )

    ecog_score = _coerce_int(
        _pick_scalar(
            payload,
            "ecog_score",
            "ecog",
            "patient_summary.ecog_score",
            "summary.ecog_score",
            "performance_status",
            "performance_status_ecog",
        )
    )

    days_to_death = _coerce_int(
        _pick_scalar(
            payload,
            "days_to_death",
            "patient_summary.days_to_death",
            "summary.days_to_death",
        )
    )

    days_to_last_follow_up = _coerce_int(
        _pick_scalar(
            payload,
            "days_to_last_follow_up",
            "days_to_last_followup",
            "patient_summary.days_to_last_follow_up",
            "summary.days_to_last_follow_up",
        )
    )

    report_highlights = _pick_string_list(
        payload,
        "report_highlights",
        "patient_summary.report_highlights",
        "summary.report_highlights",
    )

    if not report_highlights:
        report_text = _pick_string(
            payload,
            "report_text",
            "clinical_report_text",
            "patient_summary.report_text",
            "summary.report_text",
        )
        if report_text is not None:
            report_highlights = _extract_highlights_from_text(report_text)

    pack_years = _coerce_float(
        _pick_scalar(payload, "pack_years", "number_pack_years_smoked", "pack_years_smoked")
    )

    tnm_t = _pick_string(payload, "tnm_t", "pathologic_t", "ajcc_pathologic_t")
    tnm_n = _pick_string(payload, "tnm_n", "pathologic_n", "ajcc_pathologic_n")
    tnm_m = _pick_string(payload, "tnm_m", "pathologic_m", "ajcc_pathologic_m")

    histologic_subtype = _normalize_histologic_subtype(
        _pick_string(
            payload,
            "histologic_subtype",
            "histological_type",
            "morphology",
            "primary_histology",
        )
    )

    days_to_new_tumor_event = _coerce_int(
        _pick_scalar(
            payload,
            "days_to_new_tumor_event",
            "days_to_new_tumor_event_after_initial_treatment",
            "days_to_first_recurrence",
        )
    )

    path_report_grade = _pick_string(payload, "path_report_grade", "grade")
    path_report_margins = _pick_string(payload, "path_report_margins", "margins")
    path_report_lvi = _pick_string(payload, "path_report_lvi", "lvi")
    path_report_lymph_nodes_positive = _coerce_int(
        _pick_scalar(payload, "path_report_lymph_nodes_positive", "lymph_nodes_positive")
    )
    path_report_lymph_nodes_total = _coerce_int(
        _pick_scalar(payload, "path_report_lymph_nodes_total", "lymph_nodes_total")
    )
    path_report_tumor_size_cm = _coerce_float(
        _pick_scalar(payload, "path_report_tumor_size_cm", "tumor_size_cm")
    )

    return _ClinicalFeatures(
        stage=stage,
        smoking_status=smoking_status,
        age_at_diagnosis=age_years,
        diagnosis=diagnosis,
        sex=sex,
        vital_status=vital_status,
        ecog_score=ecog_score,
        days_to_death=days_to_death,
        days_to_last_follow_up=days_to_last_follow_up,
        report_highlights=report_highlights,
        pack_years=pack_years,
        tnm_t=tnm_t,
        tnm_n=tnm_n,
        tnm_m=tnm_m,
        histologic_subtype=histologic_subtype,
        days_to_new_tumor_event=days_to_new_tumor_event,
        path_report_grade=path_report_grade,
        path_report_margins=path_report_margins,
        path_report_lymph_nodes_positive=path_report_lymph_nodes_positive,
        path_report_lymph_nodes_total=path_report_lymph_nodes_total,
        path_report_lvi=path_report_lvi,
        path_report_tumor_size_cm=path_report_tumor_size_cm,
    )


def _extract_features_from_report_text(report_text: str) -> _ClinicalFeatures:
    highlights = _extract_highlights_from_text(report_text)

    stage = _normalize_stage(_extract_stage_from_text(report_text))
    smoking_status = _normalize_smoking_status(_extract_smoking_from_text(report_text))
    diagnosis = _normalize_diagnosis(_extract_diagnosis_from_text(report_text))

    ecog_score = None
    ecog_match = _ECOG_PATTERN.search(report_text)
    if ecog_match is not None:
        ecog_score = _coerce_int(ecog_match.group(1))

    return _ClinicalFeatures(
        stage=stage,
        smoking_status=smoking_status,
        diagnosis=diagnosis,
        ecog_score=ecog_score,
        report_highlights=highlights,
    )


def _extract_highlights_from_text(report_text: str) -> list[str]:
    lines = [line.strip() for line in report_text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return []

    keywords = (
        "adenocarcinoma",
        "stage",
        "ecog",
        "smoker",
        "metasta",
        "invasion",
        "tumor",
    )

    highlighted = [
        line
        for line in lines
        if any(keyword in line.lower() for keyword in keywords)
    ]

    selected = highlighted[:3] if highlighted else lines[:3]
    return _dedupe_preserve_order(_truncate_lines(selected, max_chars=220))


def _extract_stage_from_text(report_text: str) -> str | None:
    match = _STAGE_PATTERN.search(report_text)
    if match is None:
        return None

    major_token = match.group(1).upper()
    substage = (match.group(2) or "").upper()
    major = _normalize_stage_major(major_token)
    if major is None:
        return None

    return f"Stage {major}{substage}" if substage else f"Stage {major}"


def _extract_smoking_from_text(report_text: str) -> str | None:
    lowered = report_text.lower()
    if "never smoker" in lowered or "never smoked" in lowered:
        return "Never smoker"
    if "former smoker" in lowered or "ex-smoker" in lowered or "quit smoking" in lowered:
        return "Former smoker"
    if "current smoker" in lowered or "actively smoking" in lowered:
        return "Current smoker"
    return None


def _extract_diagnosis_from_text(report_text: str) -> str | None:
    lowered = report_text.lower()
    if "adenocarcinoma" in lowered:
        return "Lung adenocarcinoma"
    if "squamous" in lowered:
        return "Lung squamous cell carcinoma"
    return None


def _merge_features(base: _ClinicalFeatures, overlay: _ClinicalFeatures) -> _ClinicalFeatures:
    def _first(a: Any, b: Any) -> Any:
        return a if a is not None else b

    return _ClinicalFeatures(
        stage=base.stage or overlay.stage,
        smoking_status=base.smoking_status or overlay.smoking_status,
        age_at_diagnosis=_first(base.age_at_diagnosis, overlay.age_at_diagnosis),
        diagnosis=base.diagnosis or overlay.diagnosis,
        sex=base.sex or overlay.sex,
        vital_status=base.vital_status or overlay.vital_status,
        ecog_score=_first(base.ecog_score, overlay.ecog_score),
        days_to_death=_first(base.days_to_death, overlay.days_to_death),
        days_to_last_follow_up=_first(base.days_to_last_follow_up, overlay.days_to_last_follow_up),
        report_highlights=_dedupe_preserve_order(base.report_highlights + overlay.report_highlights),
        pack_years=_first(base.pack_years, overlay.pack_years),
        tnm_t=base.tnm_t or overlay.tnm_t,
        tnm_n=base.tnm_n or overlay.tnm_n,
        tnm_m=base.tnm_m or overlay.tnm_m,
        histologic_subtype=base.histologic_subtype or overlay.histologic_subtype,
        days_to_new_tumor_event=_first(base.days_to_new_tumor_event, overlay.days_to_new_tumor_event),
        path_report_grade=base.path_report_grade or overlay.path_report_grade,
        path_report_margins=base.path_report_margins or overlay.path_report_margins,
        path_report_lymph_nodes_positive=_first(
            base.path_report_lymph_nodes_positive, overlay.path_report_lymph_nodes_positive
        ),
        path_report_lymph_nodes_total=_first(
            base.path_report_lymph_nodes_total, overlay.path_report_lymph_nodes_total
        ),
        path_report_lvi=base.path_report_lvi or overlay.path_report_lvi,
        path_report_tumor_size_cm=_first(base.path_report_tumor_size_cm, overlay.path_report_tumor_size_cm),
    )


def _merge_payloads(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if key not in merged:
            merged[key] = value
            continue

        if isinstance(merged[key], Mapping) and isinstance(value, Mapping):
            merged[key] = _merge_payloads(_coerce_mapping(merged[key]) or {}, _coerce_mapping(value) or {})
    return merged


def _payload_has_precomputed_sections(payload: Mapping[str, Any]) -> bool:
    return _extract_precomputed_eligibility(payload) is not None or _extract_precomputed_survival(payload) is not None


def _pick_scalar(payload: Mapping[str, Any], *paths: str) -> Any:
    for path in paths:
        value = _resolve_path(payload, path)
        if value is None:
            continue
        if isinstance(value, str) and _is_empty_string(value):
            continue
        return value
    return None


def _pick_string(payload: Mapping[str, Any], *paths: str) -> str | None:
    value = _pick_scalar(payload, *paths)
    return _coerce_str(value)


def _pick_string_list(payload: Mapping[str, Any], *paths: str) -> list[str]:
    for path in paths:
        value = _resolve_path(payload, path)
        text_list = _coerce_str_list(value)
        if text_list:
            return text_list
    return []


def _resolve_path(payload: Mapping[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for key in dotted_path.split("."):
        mapping = _coerce_mapping(current)
        if mapping is None:
            return None
        if key not in mapping:
            return None
        current = mapping[key]
    return current


def _coerce_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return None


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        return None

    stripped = value.strip()
    if _is_empty_string(stripped):
        return None
    return stripped


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        normalized = _coerce_str(value)
        return [normalized] if normalized else []

    if not isinstance(value, list):
        return []

    items: list[str] = []
    for entry in value:
        normalized = _coerce_str(entry)
        if normalized is None:
            continue
        items.append(normalized)

    return _dedupe_preserve_order(items)


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if _is_empty_string(stripped):
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _coerce_int(value: Any) -> int | None:
    as_float = _coerce_float(value)
    if as_float is None:
        return None
    return int(round(as_float))


def _coerce_int_pair(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None

    first = _coerce_int(value[0])
    second = _coerce_int(value[1])
    if first is None or second is None:
        return None

    lower = min(first, second)
    upper = max(first, second)
    return (lower, upper)


def _coerce_age_years(value: Any, *, assume_days: bool = False) -> int | None:
    numeric_value = _coerce_float(value)
    if numeric_value is None:
        return None

    if assume_days or numeric_value > 140:
        numeric_value = numeric_value / 365.25

    age = int(round(numeric_value))
    if age < 0:
        return None
    return age


def _parse_precomputed_criteria(value: Any) -> list[ClinicalEligibilityCriterion]:
    if not isinstance(value, list):
        return []

    parsed: list[ClinicalEligibilityCriterion] = []
    for entry in value:
        mapping = _coerce_mapping(entry)
        if mapping is None:
            continue

        criterion = _coerce_str(mapping.get("criterion")) or _coerce_str(mapping.get("name"))
        if criterion is None:
            continue

        status_raw = _coerce_str(mapping.get("status"))
        status = _normalize_eligibility_status(status_raw)
        observed_value = _coerce_str(mapping.get("observed_value")) or _coerce_str(mapping.get("value"))
        rationale = _coerce_str(mapping.get("rationale")) or "Precomputed criterion"

        parsed.append(
            ClinicalEligibilityCriterion(
                criterion=criterion,
                status=status,
                observed_value=observed_value,
                rationale=rationale,
            )
        )

    return parsed


def _normalize_stage(value: Any) -> str | None:
    text = _coerce_str(value)
    if text is None:
        return None

    match = _STAGE_PATTERN.search(text)
    if match is None:
        return text

    major = _normalize_stage_major(match.group(1).upper())
    if major is None:
        return text

    substage = (match.group(2) or "").upper()
    return f"Stage {major}{substage}" if substage else f"Stage {major}"


def _normalize_stage_major(token: str) -> str | None:
    roman_lookup = {
        "I": "I",
        "II": "II",
        "III": "III",
        "IV": "IV",
    }

    if token in roman_lookup:
        return roman_lookup[token]

    numeric_lookup = {
        "1": "I",
        "2": "II",
        "3": "III",
        "4": "IV",
    }
    return numeric_lookup.get(token)


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


def _normalize_diagnosis(value: Any) -> str | None:
    text = _coerce_str(value)
    if text is None:
        return None

    lowered = text.lower()
    if "adenocarcinoma" in lowered:
        return "Lung adenocarcinoma"
    if "squamous" in lowered:
        return "Lung squamous cell carcinoma"
    return text


def _normalize_sex(value: Any) -> str | None:
    text = _coerce_str(value)
    if text is None:
        return None

    lowered = text.lower()
    if lowered in {"male", "m"}:
        return "Male"
    if lowered in {"female", "f"}:
        return "Female"
    return text


def _normalize_vital_status(value: Any) -> str | None:
    text = _coerce_str(value)
    if text is None:
        return None

    lowered = text.lower()
    if lowered in {"alive", "living"}:
        return "Alive"
    if lowered in {"dead", "deceased"}:
        return "Dead"
    return text


def _normalize_eligibility_status(value: str | None) -> str:
    if value is None:
        return "unknown"

    lowered = value.strip().lower()
    if lowered in {"met", "pass", "passed", "eligible", "true", "yes"}:
        return "met"
    if lowered in {"not_met", "not met", "fail", "failed", "false", "no", "ineligible"}:
        return "not_met"
    return "unknown"


def _normalize_eligibility_label(value: Any) -> ClinicalEligibilityLabel | None:
    text = _coerce_str(value)
    if text is None:
        return None

    lowered = text.lower()
    if lowered in {"eligible", "met"}:
        return "eligible"
    if lowered in {"ineligible", "not_eligible", "not eligible"}:
        return "ineligible"
    if lowered in {"indeterminate", "unknown", "partial"}:
        return "indeterminate"
    return None


def _normalize_histologic_subtype(value: Any) -> str | None:
    text = _coerce_str(value)
    if text is None:
        return None

    lowered = text.lower()
    if "acinar" in lowered:
        return "acinar"
    if "lepidic" in lowered:
        return "lepidic"
    if "micropapillary" in lowered:
        return "micropapillary"
    if "papillary" in lowered:
        return "papillary"
    if "solid" in lowered:
        return "solid"
    if "mucinous" in lowered or "colloid" in lowered:
        return "mucinous"
    if "adenocarcinoma" in lowered:
        return "adenocarcinoma_nos"
    return text.strip()


def _normalize_risk_group(value: Any) -> str | None:
    text = _coerce_str(value)
    if text is None:
        return None

    lowered = text.lower()
    if lowered in {"low", "intermediate", "high"}:
        return lowered
    return None


def _stage_bucket(stage: str | None) -> str | None:
    if stage is None:
        return None

    match = _STAGE_PATTERN.search(stage)
    if match is None:
        return None

    return _normalize_stage_major(match.group(1).upper())


def _days_to_months(days: int | None) -> float | None:
    if days is None:
        return None
    if days <= 0:
        return None
    return days / 30.4375


def _truncate_lines(lines: list[str], *, max_chars: int) -> list[str]:
    truncated: list[str] = []
    for line in lines:
        if len(line) <= max_chars:
            truncated.append(line)
        else:
            truncated.append(line[: max_chars - 1].rstrip() + "…")
    return truncated


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _is_empty_string(value: str) -> bool:
    return value.strip().lower() in _EMPTY_SENTINELS


def _first_non_empty(values: Iterable[str | None]) -> str | None:
    for value in values:
        normalized = _coerce_str(value)
        if normalized is not None:
            return normalized
    return None
