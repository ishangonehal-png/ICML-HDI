from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UploadInitRequest(BaseModel):
    case_id: str | None = Field(
        default=None,
        description="Canonical case identifier used to join modality outputs.",
        max_length=64,
    )
    cohort: str | None = Field(default="mvp50", max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator("case_id", "cohort")
    @classmethod
    def validate_optional_identifiers(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        if not normalized:
            raise ValueError("must be a non-empty string when provided")
        return normalized


class UploadInitResponse(BaseModel):
    upload_session_id: UUID
    case_id: str | None
    cohort: str | None
    status: str
    metadata: dict[str, Any]
    created_at: datetime
    research_use_only: bool = True
