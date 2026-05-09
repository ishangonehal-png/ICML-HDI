from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.pathology import MethodMetadata

AgentModality = Literal["pathology", "transcriptomics", "clinical", "fusion", "literature"]


class AgentQueryRequest(BaseModel):
    case_id: str = Field(..., min_length=1, max_length=64)
    question: str = Field(..., min_length=1)

    model_config = ConfigDict(extra="forbid")


class AgentCitation(BaseModel):
    panel: AgentModality
    field: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    value: str | None = None

    model_config = ConfigDict(extra="forbid")


class AgentModalityAvailability(BaseModel):
    modality: AgentModality
    available: bool
    data_source: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)

    model_config = ConfigDict(extra="forbid")


class AgentQueryResponse(BaseModel):
    case_id: str = Field(..., min_length=1, max_length=64)
    answer: str = Field(..., min_length=1)
    citations: list[AgentCitation]
    modalities: list[AgentModalityAvailability]
    acknowledged_missing_modalities: list[AgentModality]
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")


class AgentContextResponse(BaseModel):
    """Structured context derived from embeddings and services for feeding into an agent or LLM."""

    case_id: str = Field(..., min_length=1, max_length=64)
    context_for_llm: str = Field(
        ...,
        min_length=1,
        description="Formatted text blob of all contextualized signals for use in an agent/LLM prompt.",
    )
    fusion_score: float = Field(..., ge=0.0, le=1.0)
    fusion_mode_used: Literal["provisional", "refined"] = "provisional"
    pathology_summary: str = Field(..., min_length=1)
    clinical_summary: str = Field(default="")
    transcriptomics_summary: str = Field(default="")
    survival_baseline_summary: str = Field(default="")
    similar_cases: list[dict[str, str | float]] = Field(
        default_factory=list,
        description="List of similar case entries (case_id, similarity, rationale) for retrieval context.",
    )
    meta: MethodMetadata

    model_config = ConfigDict(extra="forbid")
