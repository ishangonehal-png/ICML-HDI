from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .pathology import MethodMetadata


ClinicalDataSource = Literal[
    "artifact",
    "modality_result",
    "clinical_xml",
    "case_metadata",
    "unavailable",
]

ClinicalEligibilityStatus = Literal["met", "not_met", "unknown"]
ClinicalEligibilityLabel = Literal["eligible", "ineligible", "indeterminate"]
ClinicalRiskGroup = Literal["low", "intermediate", "high"]


class ClinicalProvenance(BaseModel):
    data_source: ClinicalDataSource
    source_paths: list[str] = Field(default_factory=list)
    source_records: list[str] = Field(default_factory=list)
    extracted_fields: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class PathReportFields(BaseModel):
    """Structured fields extracted from pathology report text via Claude."""

    grade: str | None = None
    margins: str | None = None
    lymph_nodes_positive: int | None = Field(default=None, ge=0)
    lymph_nodes_total: int | None = Field(default=None, ge=0)
    lvi: str | None = None
    tumor_size_cm: float | None = Field(default=None, ge=0)
    histologic_pattern: str | None = None
    ihc_pdl1_tps: str | None = None
    til_comment: str | None = None
    raw_highlights: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ClinicalPatientSummaryResponse(BaseModel):
    case_id: str
    stage: str | None = None
    smoking_status: str | None = None
    age_at_diagnosis: int | None = Field(default=None, ge=0)
    diagnosis: str | None = None
    sex: str | None = None
    vital_status: str | None = None
    report_highlights: list[str] = Field(default_factory=list)
    # Enriched XML fields
    pack_years: float | None = Field(default=None, ge=0)
    tnm_t: str | None = None
    tnm_n: str | None = None
    tnm_m: str | None = None
    histologic_subtype: str | None = None
    days_to_new_tumor_event: int | None = Field(default=None, ge=0)
    # Claude-extracted path report fields
    path_report_fields: PathReportFields | None = None
    available: bool
    data_source: ClinicalDataSource
    unavailable_reason: str | None = None
    provenance: ClinicalProvenance
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_availability_consistency(self) -> "ClinicalPatientSummaryResponse":
        has_payload_fields = any(
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

        if self.available and not has_payload_fields:
            raise ValueError("available=true requires at least one populated summary field")

        if not self.available and self.data_source == "unavailable" and self.unavailable_reason is None:
            raise ValueError("unavailable clinical summary requires unavailable_reason")

        return self


class ClinicalEligibilityCriterion(BaseModel):
    criterion: str
    status: ClinicalEligibilityStatus
    observed_value: str | None = None
    rationale: str

    model_config = ConfigDict(extra="forbid")


class ClinicalEligibilityResponse(BaseModel):
    case_id: str
    eligible_trials: int | None = Field(default=None, ge=0)
    eligibility_label: ClinicalEligibilityLabel | None = None
    rationale: list[str] = Field(default_factory=list)
    criteria: list[ClinicalEligibilityCriterion] = Field(default_factory=list)
    available: bool
    data_source: ClinicalDataSource
    unavailable_reason: str | None = None
    provenance: ClinicalProvenance
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_availability_consistency(self) -> "ClinicalEligibilityResponse":
        if self.available:
            if self.eligible_trials is None:
                raise ValueError("available=true requires eligible_trials")
            if self.eligibility_label is None:
                raise ValueError("available=true requires eligibility_label")

        if not self.available and self.data_source == "unavailable" and self.unavailable_reason is None:
            raise ValueError("unavailable clinical eligibility requires unavailable_reason")

        return self


class ClinicalSurvivalBaselineResponse(BaseModel):
    case_id: str
    risk_group: ClinicalRiskGroup | None = None
    baseline_months: int | None = Field(default=None, ge=0)
    confidence_interval: tuple[int, int] | None = None
    prognostic_factors: list[str] = Field(default_factory=list)
    available: bool
    data_source: ClinicalDataSource
    unavailable_reason: str | None = None
    provenance: ClinicalProvenance
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_availability_consistency(self) -> "ClinicalSurvivalBaselineResponse":
        if self.available:
            if self.baseline_months is None:
                raise ValueError("available=true requires baseline_months")
            if self.risk_group is None:
                raise ValueError("available=true requires risk_group")
            if self.confidence_interval is None:
                raise ValueError("available=true requires confidence_interval")

        if self.confidence_interval is not None:
            lower, upper = self.confidence_interval
            if lower > upper:
                raise ValueError("confidence_interval lower bound must be <= upper bound")

        if not self.available and self.data_source == "unavailable" and self.unavailable_reason is None:
            raise ValueError("unavailable clinical survival baseline requires unavailable_reason")

        return self


class ClinicalSurvivalMlpResponse(BaseModel):
    """Survival MLP (pathology + RNA + metadata) prediction for a case."""

    case_id: str
    available: bool
    horizon_years: int | None = None
    probability: float | None = Field(default=None, ge=0, le=1)
    predicted_class: int | None = Field(default=None, ge=0, le=1)
    data_source: str = "survival_mlp"
    unavailable_reason: str | None = None
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")


class KMStratum(BaseModel):
    """One arm of a Kaplan-Meier curve (e.g. high/mid/low immunotherapy score tier)."""

    label: str
    time_points: list[float] = Field(default_factory=list)  # months
    survival_rates: list[float] = Field(default_factory=list)  # 0–1
    n_at_risk: list[int] = Field(default_factory=list)
    n_events: int = 0
    n_total: int = 0
    median_survival_months: float | None = None

    model_config = ConfigDict(extra="forbid")


class ClinicalSurvivalResponse(BaseModel):
    case_id: str
    # Patient-level Cox model predictions
    survival_prob_1yr: float | None = Field(default=None, ge=0, le=1)
    survival_prob_2yr: float | None = Field(default=None, ge=0, le=1)
    survival_prob_5yr: float | None = Field(default=None, ge=0, le=1)
    ci_1yr: tuple[float, float] | None = None
    ci_5yr: tuple[float, float] | None = None
    median_survival_months: float | None = Field(default=None, ge=0)
    patient_score_tier: Literal["high", "intermediate", "low"] | None = None
    # Population KM curves for the dashboard
    km_strata: list[KMStratum] = Field(default_factory=list)
    # Cox model metadata
    cox_features_used: list[str] = Field(default_factory=list)
    concordance_index: float | None = Field(default=None, ge=0, le=1)
    model_version: str = "unavailable"
    available: bool
    data_source: ClinicalDataSource
    unavailable_reason: str | None = None
    provenance: ClinicalProvenance
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_km_strata(self) -> "ClinicalSurvivalResponse":
        for stratum in self.km_strata:
            if len(stratum.time_points) != len(stratum.survival_rates):
                raise ValueError(
                    f"KM stratum {stratum.label!r}: time_points and survival_rates must have equal length"
                )
        return self


class ClinicalTrialMatchItem(BaseModel):
    title: str
    nct_id: str
    status: str
    phase: str | None = None
    match_score: int = Field(ge=0)
    match_reasons: list[str] = Field(default_factory=list)
    rationale: str
    study_url: str

    model_config = ConfigDict(extra="forbid")


class ClinicalTrialMatchResponse(BaseModel):
    case_id: str
    available: bool
    trials: list[ClinicalTrialMatchItem] = Field(default_factory=list)
    data_source: ClinicalDataSource
    unavailable_reason: str | None = None
    query_terms: list[str] = Field(default_factory=list)
    provenance: ClinicalProvenance
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_availability_consistency(self) -> "ClinicalTrialMatchResponse":
        if self.available and self.unavailable_reason is not None:
            raise ValueError("available=true cannot include unavailable_reason")
        if not self.available and self.unavailable_reason is None:
            raise ValueError("available=false requires unavailable_reason")
        return self
