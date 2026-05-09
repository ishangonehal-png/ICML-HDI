from __future__ import annotations

from fastapi import APIRouter

from schemas.cohort import CohortCaseSummary
from services import list_overlapping_cohort_cases

router = APIRouter(prefix="/cohort", tags=["cohort"])


@router.get("/cases", response_model=list[CohortCaseSummary])
def list_cohort_cases() -> list[CohortCaseSummary]:
    return list_overlapping_cohort_cases()
