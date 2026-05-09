from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from models import Case, UploadSession


def test_init_upload_session_creates_case_and_session(client, db) -> None:
    response = client.post(
        "/v1/uploads/init",
        json={
            "case_id": "TCGA-TEST-0001",
            "cohort": "mvp50",
            "metadata": {"requested_by": "pytest"},
        },
    )

    assert response.status_code == 201
    payload = response.json()

    assert payload["case_id"] == "TCGA-TEST-0001"
    assert payload["cohort"] == "mvp50"
    assert payload["status"] == "initialized"
    assert payload["metadata"] == {"requested_by": "pytest"}
    assert payload["research_use_only"] is True

    case = db.scalar(select(Case).where(Case.case_id == "TCGA-TEST-0001"))
    assert case is not None
    assert case.cohort == "mvp50"
    assert case.record_metadata["source"] == "uploads.init"
    assert case.record_metadata["requested_by"] == "pytest"

    upload_session = db.get(UploadSession, UUID(payload["upload_session_id"]))
    assert upload_session is not None
    assert upload_session.case_id == "TCGA-TEST-0001"
    assert upload_session.status == "initialized"


def test_init_upload_session_allows_missing_case_id(client, db) -> None:
    response = client.post(
        "/v1/uploads/init",
        json={
            "metadata": {"requested_by": "pytest"},
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["case_id"] is None

    all_cases = db.scalars(select(Case)).all()
    assert all_cases == []


def test_init_upload_session_rejects_blank_case_id(client) -> None:
    response = client.post(
        "/v1/uploads/init",
        json={
            "case_id": "   ",
            "cohort": "mvp50",
        },
    )

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(error["loc"] == ["body", "case_id"] for error in errors)
