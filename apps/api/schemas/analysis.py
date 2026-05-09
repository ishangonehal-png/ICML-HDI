from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_ALLOWED_MODALITIES = ("pathology", "transcriptomics", "clinical", "fusion")


class AnalysisJobCreateRequest(BaseModel):
    case_id: str = Field(..., max_length=64)
    upload_session_id: UUID | None = None
    requested_modalities: list[str] = Field(
        default_factory=lambda: ["pathology", "clinical", "transcriptomics", "fusion"],
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("case_id must be a non-empty string")
        return normalized

    @field_validator("requested_modalities")
    @classmethod
    def validate_requested_modalities(cls, value: list[str]) -> list[str]:
        if not value:
            return list(_ALLOWED_MODALITIES)

        normalized: list[str] = []
        seen: set[str] = set()
        for raw in value:
            modality = raw.strip().lower()
            if modality not in _ALLOWED_MODALITIES:
                allowed = ", ".join(_ALLOWED_MODALITIES)
                raise ValueError(f"requested_modalities contains unsupported modality '{raw}'. Allowed: {allowed}")
            if modality in seen:
                continue
            normalized.append(modality)
            seen.add(modality)

        if not normalized:
            raise ValueError("requested_modalities must include at least one supported modality")

        return normalized


class JobEventResponse(BaseModel):
    event_type: str
    message: str
    payload: dict[str, Any]
    created_at: datetime


class ModalityResultResponse(BaseModel):
    modality: str
    payload: dict[str, Any]
    metadata: dict[str, Any]
    created_at: datetime


class AnalysisJobResponse(BaseModel):
    job_id: UUID
    case_id: str
    upload_session_id: UUID | None
    status: str
    requested_modalities: list[str]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    research_use_only: bool = True


class AnalysisJobDetailResponse(AnalysisJobResponse):
    result_summary: dict[str, Any]
    error_message: str | None
    events: list[JobEventResponse]
    modality_results: list[ModalityResultResponse]
