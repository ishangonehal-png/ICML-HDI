from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from dependencies.db import get_db
from schemas.fusion import (
    FusionAttributionResponse,
    FusionScoreRequest,
    FusionScoreResponse,
    FusionSimilarCasesResponse,
)
from services import get_fusion_attribution, get_fusion_score, get_fusion_similar_cases

router = APIRouter(prefix="/fusion", tags=["fusion"])


@router.post("/{case_id}/score", response_model=FusionScoreResponse)
def score_case(
    case_id: str,
    payload: FusionScoreRequest,
    db: Session = Depends(get_db),
) -> FusionScoreResponse:
    return get_fusion_score(case_id, include_rna=payload.include_rna, db=db)


@router.get("/{case_id}/attribution", response_model=FusionAttributionResponse)
def get_case_attribution(
    case_id: str,
    include_rna: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> FusionAttributionResponse:
    return get_fusion_attribution(case_id, include_rna=include_rna, db=db)


@router.get("/{case_id}/similar-cases", response_model=FusionSimilarCasesResponse)
def get_similar_cases(
    case_id: str,
    include_rna: bool = Query(default=True),
    limit: int = Query(default=5, ge=1, le=10),
    db: Session = Depends(get_db),
) -> FusionSimilarCasesResponse:
    return get_fusion_similar_cases(case_id, include_rna=include_rna, limit=limit, db=db)
