from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from dependencies.db import get_db
from models import AnalysisJob, JobEvent, ModalityResult, UploadSession
from schemas.analysis import (
    AnalysisJobCreateRequest,
    AnalysisJobDetailResponse,
    AnalysisJobResponse,
    JobEventResponse,
    ModalityResultResponse,
)
from services import (
    AnalysisQueueUnavailableError,
    enqueue_analysis_job,
    ensure_case_exists,
    list_overlapping_cohort_cases,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])


def _cached_case_modality_map() -> dict[str, dict[str, bool]]:
    case_map: dict[str, dict[str, bool]] = {}
    for case in list_overlapping_cohort_cases():
        case_map[case.case_id] = {
            "pathology": case.has_pathology,
            "transcriptomics": case.has_transcriptomics,
            "clinical": case.has_clinical,
            "fusion": case.has_pathology and (case.has_transcriptomics or case.has_clinical),
        }
    return case_map


def _to_job_response(job: AnalysisJob) -> AnalysisJobResponse:
    return AnalysisJobResponse(
        job_id=job.id,
        case_id=job.case_id,
        upload_session_id=job.upload_session_id,
        status=job.status,
        requested_modalities=job.requested_modalities,
        metadata=job.record_metadata,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post("/jobs", response_model=AnalysisJobResponse, status_code=status.HTTP_201_CREATED)
def create_analysis_job(
    payload: AnalysisJobCreateRequest,
    db: Session = Depends(get_db),
) -> AnalysisJobResponse:
    cohort = "mvp50"
    if payload.upload_session_id:
        upload_session = db.get(UploadSession, payload.upload_session_id)
        if upload_session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="upload_session_id not found",
            )

        if upload_session.case_id and upload_session.case_id != payload.case_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="case_id does not match upload session case_id",
            )

        if upload_session.case_id is None:
            upload_session.case_id = payload.case_id

        cohort = upload_session.cohort or cohort

    ensure_case_exists(
        db,
        case_id=payload.case_id,
        cohort=cohort,
        source="analysis.jobs",
    )

    cached_case_map = _cached_case_modality_map()
    cached_modalities = cached_case_map.get(payload.case_id)
    available_modalities = [
        modality
        for modality in payload.requested_modalities
        if cached_modalities and cached_modalities.get(modality.lower(), False)
    ]
    missing_modalities = [
        modality
        for modality in payload.requested_modalities
        if not cached_modalities or not cached_modalities.get(modality.lower(), False)
    ]
    served_from_cache = bool(cached_modalities) and len(missing_modalities) == 0

    if served_from_cache:
        job_status = "completed"
        result_summary = {
            "served_from_cache": True,
            "available_modalities": available_modalities,
            "missing_modalities": missing_modalities,
        }
        event_type = "job_cache_hit"
        event_message = "Analysis resolved immediately from cached DGX data."
    else:
        job_status = "queued"
        result_summary = {
            "served_from_cache": False,
            "completed_modalities": [],
            "available_modalities": available_modalities,
            "missing_modalities": missing_modalities,
        }
        event_type = "job_created"
        event_message = "Analysis job created and queued for asynchronous execution."

    job = AnalysisJob(
        case_id=payload.case_id,
        upload_session_id=payload.upload_session_id,
        status=job_status,
        requested_modalities=payload.requested_modalities,
        record_metadata=payload.metadata,
        result_summary=result_summary,
    )
    db.add(job)
    db.flush()

    db.add(
        JobEvent(
            job_id=job.id,
            event_type=event_type,
            message=event_message,
            created_at=datetime.now(UTC),
            payload={
                "requested_modalities": payload.requested_modalities,
                "research_use_only": True,
                "served_from_cache": served_from_cache,
            },
        )
    )

    db.commit()
    db.refresh(job)

    if not served_from_cache:
        try:
            enqueue_analysis_job(job.id)
        except AnalysisQueueUnavailableError as exc:
            job.status = "failed"
            job.error_message = (
                "Queue enqueue failed. Worker could not pick up this job. Please retry."
            )
            db.add(
                JobEvent(
                    job_id=job.id,
                    event_type="job_enqueue_failed",
                    message="Analysis queue unavailable while enqueueing job.",
                    created_at=datetime.now(UTC),
                    payload={
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="analysis queue unavailable; retry after queue service is healthy",
            ) from exc

        db.add(
            JobEvent(
                job_id=job.id,
                event_type="job_enqueued",
                message="Analysis job enqueued for worker processing.",
                created_at=datetime.now(UTC),
                payload={
                    "queue_backend": "redis",
                    "research_use_only": True,
                },
            )
        )
        db.commit()
        db.refresh(job)

    return _to_job_response(job)


@router.get("/jobs/{job_id}", response_model=AnalysisJobDetailResponse)
def get_analysis_job(job_id: UUID, db: Session = Depends(get_db)) -> AnalysisJobDetailResponse:
    job = db.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_id not found")

    events = db.scalars(
        select(JobEvent)
        .where(JobEvent.job_id == job.id)
        .order_by(JobEvent.created_at.asc(), JobEvent.id.asc())
    ).all()
    results = db.scalars(
        select(ModalityResult)
        .where(ModalityResult.job_id == job.id)
        .order_by(ModalityResult.created_at.asc(), ModalityResult.id.asc())
    ).all()

    base = _to_job_response(job)
    return AnalysisJobDetailResponse(
        **base.model_dump(),
        result_summary=job.result_summary,
        error_message=job.error_message,
        events=[
            JobEventResponse(
                event_type=event.event_type,
                message=event.message,
                payload=event.payload,
                created_at=event.created_at,
            )
            for event in events
        ],
        modality_results=[
            ModalityResultResponse(
                modality=result.modality,
                payload=result.payload,
                metadata=result.result_metadata,
                created_at=result.created_at,
            )
            for result in results
        ],
    )


@router.get("/jobs/{job_id}/artifacts")
def get_analysis_job_artifacts(job_id: UUID, db: Session = Depends(get_db)) -> dict[str, object]:
    job = db.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_id not found")

    modality_results = db.scalars(
        select(ModalityResult)
        .where(ModalityResult.job_id == job.id)
        .order_by(ModalityResult.created_at.asc(), ModalityResult.id.asc())
    ).all()

    return {
        "job_id": str(job.id),
        "case_id": job.case_id,
        "status": job.status,
        "available": job.status == "completed",
        "result_summary": job.result_summary,
        "modality_artifacts": [
            {
                "modality": result.modality,
                "metadata": result.result_metadata,
                "has_payload": bool(result.payload),
                "created_at": result.created_at,
                "updated_at": result.updated_at,
            }
            for result in modality_results
        ],
        "research_use_only": True,
    }
