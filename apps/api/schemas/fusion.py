from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .pathology import MethodMetadata

FusionMode = Literal["provisional", "refined"]
FusionModality = Literal["pathology", "clinical", "transcriptomics"]


class FusionScoreRequest(BaseModel):
    include_rna: bool = Field(default=True)

    model_config = ConfigDict(extra="forbid")


class FusionProvenance(BaseModel):
    source: str = Field(..., min_length=1)
    field: str = Field(..., min_length=1)
    note: str | None = None

    model_config = ConfigDict(extra="forbid")


class FusionConfidenceInterval(BaseModel):
    lower: float = Field(..., ge=0.0, le=1.0)
    upper: float = Field(..., ge=0.0, le=1.0)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_bounds(self) -> "FusionConfidenceInterval":
        if self.upper < self.lower:
            raise ValueError("upper must be greater than or equal to lower")
        return self


class FusionModalityContribution(BaseModel):
    modality: FusionModality
    available: bool
    required_for_requested_mode: bool
    used_in_score: bool
    data_source: str = Field(..., min_length=1)
    signal: float | None = Field(default=None, ge=0.0, le=1.0)
    weight: float = Field(..., ge=0.0, le=1.0)
    weighted_contribution: float = Field(..., ge=0.0, le=1.0)
    contribution_percent: float = Field(..., ge=0.0, le=100.0)
    summary: str = Field(..., min_length=1)
    unavailable_reason: str | None = None
    provenance: list[FusionProvenance] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_semantics(self) -> "FusionModalityContribution":
        if self.available and self.signal is None:
            raise ValueError("available modality must include a signal")
        if not self.available and self.signal is not None:
            raise ValueError("unavailable modality must not include a signal")
        if self.used_in_score and not self.available:
            raise ValueError("used_in_score=true requires available=true")
        if self.used_in_score and self.weight <= 0:
            raise ValueError("used_in_score=true requires weight > 0")
        return self


class FusionScoreResponse(BaseModel):
    case_id: str = Field(..., min_length=1, max_length=64)
    requested_mode: FusionMode
    mode_used: FusionMode
    rna_requested: bool
    rna_applied: bool
    provisional_score: float = Field(..., ge=0.0, le=1.0)
    refined_score: float = Field(..., ge=0.0, le=1.0)
    delta_score: float = Field(..., ge=-1.0, le=1.0)
    provisional_ci: FusionConfidenceInterval
    refined_ci: FusionConfidenceInterval
    modalities: list[FusionModalityContribution]
    provenance: list[FusionProvenance] = Field(default_factory=list)
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")


class FusionAttributionResponse(BaseModel):
    case_id: str = Field(..., min_length=1, max_length=64)
    requested_mode: FusionMode
    mode_used: FusionMode
    score: float = Field(..., ge=0.0, le=1.0)
    modalities: list[FusionModalityContribution]
    provenance: list[FusionProvenance] = Field(default_factory=list)
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")


class FusionSimilarCase(BaseModel):
    case_id: str = Field(..., min_length=1, max_length=64)
    similarity: float = Field(..., ge=0.0, le=1.0)
    score: float = Field(..., ge=0.0, le=1.0)
    delta_vs_index: float = Field(..., ge=-1.0, le=1.0)
    shared_modalities: list[FusionModality] = Field(default_factory=list)
    rationale: str = Field(..., min_length=1)
    provenance: list[FusionProvenance] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class FusionSimilarCasesResponse(BaseModel):
    case_id: str = Field(..., min_length=1, max_length=64)
    requested_mode: FusionMode
    mode_used: FusionMode
    index_score: float = Field(..., ge=0.0, le=1.0)
    neighbors: list[FusionSimilarCase] = Field(default_factory=list)
    provenance: list[FusionProvenance] = Field(default_factory=list)
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")
