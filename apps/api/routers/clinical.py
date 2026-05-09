from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from dependencies.db import get_db
from schemas.clinical import (
    ClinicalEligibilityResponse,
    ClinicalPatientSummaryResponse,
    ClinicalSurvivalBaselineResponse,
    ClinicalSurvivalMlpResponse,
    ClinicalSurvivalResponse,
    ClinicalTrialMatchResponse,
)
from services import (
    get_clinical_eligibility,
    get_clinical_patient_summary,
    get_clinical_survival,
    get_clinical_survival_baseline,
    get_clinical_trial_matches,
)
from services.survival_mlp import get_survival_mlp_prediction

router = APIRouter(prefix="/clinical", tags=["clinical"])


@router.get("/{case_id}/patient-summary", response_model=ClinicalPatientSummaryResponse)
def get_patient_summary(case_id: str, db: Session = Depends(get_db)) -> ClinicalPatientSummaryResponse:
    return get_clinical_patient_summary(case_id, db=db)


@router.get("/{case_id}/eligibility", response_model=ClinicalEligibilityResponse)
def get_patient_eligibility(case_id: str, db: Session = Depends(get_db)) -> ClinicalEligibilityResponse:
    return get_clinical_eligibility(case_id, db=db)


@router.get("/{case_id}/survival", response_model=ClinicalSurvivalResponse)
def get_survival(case_id: str, db: Session = Depends(get_db)) -> ClinicalSurvivalResponse:
    return get_clinical_survival(case_id, db=db)


@router.get("/{case_id}/survival-baseline", response_model=ClinicalSurvivalBaselineResponse)
def get_survival_baseline(case_id: str, db: Session = Depends(get_db)) -> ClinicalSurvivalBaselineResponse:
    return get_clinical_survival_baseline(case_id, db=db)


@router.get("/{case_id}/survival-mlp", response_model=ClinicalSurvivalMlpResponse)
def get_survival_mlp(case_id: str) -> ClinicalSurvivalMlpResponse:
    return get_survival_mlp_prediction(case_id)


@router.get("/{case_id}/trial-matches", response_model=ClinicalTrialMatchResponse)
def get_trial_matches(
    case_id: str,
    limit: int = Query(default=20, ge=1, le=50),
    recruiting_only: bool = Query(default=True),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> ClinicalTrialMatchResponse:
    return get_clinical_trial_matches(
        case_id,
        db=db,
        limit=limit,
        recruiting_only=recruiting_only,
        force_refresh=refresh,
    )
