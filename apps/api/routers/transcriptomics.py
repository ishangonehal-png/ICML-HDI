from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from dependencies.db import get_db
from schemas.transcriptomics import (
    TranscriptomicsCoverageResponse,
    TranscriptomicsDegVolcanoResponse,
    TranscriptomicsEvidenceResponse,
    TranscriptomicsMetricResponse,
    TranscriptomicsPlotsResponse,
)
from services import (
    get_cyt_signature,
    get_deg_volcano,
    get_gep_signature,
    get_tide_signature,
    get_transcriptomic_evidence,
    get_transcriptomics_coverage_report,
    get_transcriptomics_plots,
)

router = APIRouter(prefix="/transcriptomics", tags=["transcriptomics"])


@router.get("/coverage", response_model=TranscriptomicsCoverageResponse)
def get_transcriptomics_coverage(
    case_id: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> TranscriptomicsCoverageResponse:
    return get_transcriptomics_coverage_report(db=db, case_ids=case_id)


@router.get("/{case_id}/cyt", response_model=TranscriptomicsMetricResponse)
def get_cyt(case_id: str, db: Session = Depends(get_db)) -> TranscriptomicsMetricResponse:
    return get_cyt_signature(case_id, db=db)


@router.get("/{case_id}/gep", response_model=TranscriptomicsMetricResponse)
def get_gep(case_id: str, db: Session = Depends(get_db)) -> TranscriptomicsMetricResponse:
    return get_gep_signature(case_id, db=db)


@router.get("/{case_id}/deg-volcano", response_model=TranscriptomicsDegVolcanoResponse)
def get_deg_volcano_plot(
    case_id: str,
    max_points: int = Query(default=1200, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> TranscriptomicsDegVolcanoResponse:
    return get_deg_volcano(case_id, db=db, max_points=max_points)


@router.get("/{case_id}/plots", response_model=TranscriptomicsPlotsResponse)
def get_plots(
    case_id: str,
    max_volcano_points: int = Query(default=800, ge=1, le=5000),
    max_ma_points: int = Query(default=500, ge=1, le=2000),
    max_raw_matrix_rows: int = Query(default=120, ge=1, le=500),
    db: Session = Depends(get_db),
) -> TranscriptomicsPlotsResponse:
    """Unified sequencing plots: volcano, MA plot, top genes bar, signature scores, heatmap, raw matrix preview."""
    return get_transcriptomics_plots(
        case_id,
        db=db,
        max_volcano_points=max_volcano_points,
        max_ma_points=max_ma_points,
        max_raw_matrix_rows=max_raw_matrix_rows,
    )


@router.get("/{case_id}/tide", response_model=TranscriptomicsMetricResponse)
def get_tide(
    case_id: str,
    experimental: bool = False,
    db: Session = Depends(get_db),
) -> TranscriptomicsMetricResponse:
    if not experimental:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TIDE endpoint is experimental; pass experimental=true to enable.",
        )

    return get_tide_signature(case_id, db=db)


@router.post("/{case_id}/evidence", response_model=TranscriptomicsEvidenceResponse)
def get_evidence(case_id: str, db: Session = Depends(get_db)) -> TranscriptomicsEvidenceResponse:
    return get_transcriptomic_evidence(case_id, db=db)
