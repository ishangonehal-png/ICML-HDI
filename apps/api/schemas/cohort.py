from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CohortCaseSummary(BaseModel):
    case_id: str = Field(..., max_length=64)
    display_name: str = Field(..., max_length=128)
    stage: str | None = None
    smoking_status: str | None = None
    has_pathology: bool = True
    has_transcriptomics: bool = True
    has_clinical: bool = True

    model_config = ConfigDict(extra="forbid")
