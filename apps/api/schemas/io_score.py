from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .pathology import MethodMetadata

IOImmuneTier = Literal["Hot", "Warm", "Cold"]


class IOScoreComponent(BaseModel):
    name: str = Field(..., min_length=1)
    value: float | None = Field(default=None)
    weight: float = Field(..., ge=0.0, le=1.0)
    available: bool
    description: str = Field(..., min_length=1)

    model_config = ConfigDict(extra="forbid")


class IOImmuneScoreResponse(BaseModel):
    case_id: str = Field(..., min_length=1, max_length=64)
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    tier: IOImmuneTier | None = None
    provisional_score: float = Field(..., ge=0.0, le=1.0)
    refined_score: float | None = Field(default=None, ge=0.0, le=1.0)
    components: list[IOScoreComponent] = Field(default_factory=list)
    rna_available: bool
    missing_components: list[str] = Field(default_factory=list)
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")
