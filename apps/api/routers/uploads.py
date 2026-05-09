from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from dependencies.db import get_db
from models import UploadSession
from schemas.uploads import UploadInitRequest, UploadInitResponse
from services import ensure_case_exists, research_stub_response

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("/init", response_model=UploadInitResponse, status_code=status.HTTP_201_CREATED)
def init_upload_session(payload: UploadInitRequest, db: Session = Depends(get_db)) -> UploadInitResponse:
    if payload.case_id:
        ensure_case_exists(
            db,
            case_id=payload.case_id,
            cohort=payload.cohort,
            source="uploads.init",
            metadata=payload.metadata,
        )

    upload_session = UploadSession(
        case_id=payload.case_id,
        cohort=payload.cohort,
        status="initialized",
        record_metadata=payload.metadata,
    )

    db.add(upload_session)
    db.commit()
    db.refresh(upload_session)

    return UploadInitResponse(
        upload_session_id=upload_session.id,
        case_id=upload_session.case_id,
        cohort=upload_session.cohort,
        status=upload_session.status,
        metadata=upload_session.record_metadata,
        created_at=upload_session.created_at,
    )


@router.post("/files")
def attach_upload_files(payload: dict[str, Any]) -> dict[str, Any]:
    upload_session_id = str(payload.get("upload_session_id", "unknown"))
    return research_stub_response(
        id_key="upload_session_id",
        id_value=upload_session_id,
        message="Upload file attachment endpoint scaffolded for research-only metadata ingestion.",
        extra={"received_fields": sorted(payload.keys())},
    )
