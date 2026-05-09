from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from dependencies.db import get_db
from schemas.io_score import IOImmuneScoreResponse
from schemas.io_similar import IOSimilarCasesResponse
from services import get_tissue_composition
from services.io_score import get_io_immune_score
from services.io_similar import get_io_similar_cases
from services.pathology_id_resolution import derive_short_case_id
from services.transcriptomics import get_cyt_signature, get_gep_signature, get_tide_signature

router = APIRouter(prefix="/io-immune", tags=["io-immune"])


@router.get("/{case_id}/score", response_model=IOImmuneScoreResponse)
def io_immune_score(
    case_id: str,
    db: Session = Depends(get_db),
) -> IOImmuneScoreResponse:
    slide_id = f"{derive_short_case_id(case_id)}-DX1"

    # Pathology signals
    til_fraction: float | None = None
    tissue = get_tissue_composition(slide_id)
    lymph = next(
        (f.fraction for f in tissue.fractions if "lymphocyte" in f.tissue.lower()),
        None,
    )
    til_fraction = lymph

    # Transcriptomics signals
    cyt_resp = get_cyt_signature(case_id, db=db)
    gep_resp = get_gep_signature(case_id, db=db)
    tide_resp = get_tide_signature(case_id, db=db)

    cyt_value = cyt_resp.value if cyt_resp.available else None
    gep_value = gep_resp.value if gep_resp.available else None
    tide_value = tide_resp.value if tide_resp.available else None

    return get_io_immune_score(
        case_id,
        til_fraction=til_fraction,
        cyt_value=cyt_value,
        gep_value=gep_value,
        tide_value=tide_value,
    )


@router.get("/{case_id}/similar-cases", response_model=IOSimilarCasesResponse)
def io_similar_cases(
    case_id: str,
    limit: int = Query(default=5, ge=1, le=10),
    db: Session = Depends(get_db),
) -> IOSimilarCasesResponse:
    return get_io_similar_cases(case_id, db=db, limit=limit)
