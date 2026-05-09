from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .io_score import IOImmuneTier
from .pathology import MethodMetadata


class IOSimilarCase(BaseModel):
    case_id: str = Field(..., min_length=1, max_length=64)
    similarity: float = Field(..., ge=0.0, le=1.0)
    tier: IOImmuneTier | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    # IO signal z-scores
    gep_z: float | None = None
    cyt_z: float | None = None
    tide_z: float | None = None
    til_fraction: float | None = None
    # Demographics / staging
    age_at_diagnosis: float | None = None
    smoking: str | None = None
    stage: str | None = None
    rationale: str = Field(..., min_length=1)

    model_config = ConfigDict(extra="forbid")


class IOSimilarCasesResponse(BaseModel):
    case_id: str = Field(..., min_length=1, max_length=64)
    neighbors: list[IOSimilarCase] = Field(default_factory=list)
    feature_space: list[str] = Field(default_factory=list)
    rna_available: bool
    cohort_size: int = Field(..., ge=0)
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")
