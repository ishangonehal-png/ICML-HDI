from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from models import UploadSession
import routers.analysis as analysis_router


@pytest.fixture(autouse=True)
def stub_queue_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis_router, "list_overlapping_cohort_cases", lambda: [])
    monkeypatch.setattr(analysis_router, "enqueue_analysis_job", lambda _job_id: None)


def test_create_and_get_analysis_job(client) -> None:
    upload_response = client.post(
        "/v1/uploads/init",
        json={"case_id": "TCGA-TEST-ANALYSIS", "cohort": "mvp50"},
    )
    assert upload_response.status_code == 201
    upload_session_id = upload_response.json()["upload_session_id"]

    create_response = client.post(
        "/v1/analysis/jobs",
        json={
            "case_id": "TCGA-TEST-ANALYSIS",
            "upload_session_id": upload_session_id,
            "requested_modalities": ["pathology", "clinical"],
            "metadata": {"requested_by": "pytest"},
        },
    )

    assert create_response.status_code == 201
    create_payload = create_response.json()

    assert create_payload["case_id"] == "TCGA-TEST-ANALYSIS"
    assert create_payload["upload_session_id"] == upload_session_id
    assert create_payload["status"] == "queued"
    assert create_payload["requested_modalities"] == ["pathology", "clinical"]
    assert create_payload["metadata"] == {"requested_by": "pytest"}
    assert create_payload["research_use_only"] is True

    job_id = create_payload["job_id"]
    detail_response = client.get(f"/v1/analysis/jobs/{job_id}")

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()

    assert detail_payload["job_id"] == job_id
    assert detail_payload["status"] == "queued"
    assert detail_payload["result_summary"] == {
        "served_from_cache": False,
        "completed_modalities": [],
        "available_modalities": [],
        "missing_modalities": ["pathology", "clinical"],
    }
    assert detail_payload["error_message"] is None
    assert detail_payload["modality_results"] == []

    assert len(detail_payload["events"]) == 2
    events_by_type = {event["event_type"]: event for event in detail_payload["events"]}
    assert set(events_by_type.keys()) == {"job_created", "job_enqueued"}
    assert events_by_type["job_created"]["payload"]["requested_modalities"] == ["pathology", "clinical"]
    assert events_by_type["job_created"]["payload"]["research_use_only"] is True


def test_create_analysis_job_uses_cache_when_case_available(client, monkeypatch) -> None:
    monkeypatch.setattr(
        analysis_router,
        "list_overlapping_cohort_cases",
        lambda: [
            SimpleNamespace(
                case_id="TCGA-CACHED-0001",
                has_pathology=True,
                has_transcriptomics=True,
                has_clinical=True,
            )
        ],
    )

    response = client.post(
        "/v1/analysis/jobs",
        json={
            "case_id": "TCGA-CACHED-0001",
            "requested_modalities": ["pathology", "transcriptomics", "clinical", "fusion"],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "completed"

    detail_response = client.get(f"/v1/analysis/jobs/{payload['job_id']}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["status"] == "completed"
    assert detail_payload["result_summary"]["served_from_cache"] is True
    assert len(detail_payload["events"]) == 1
    assert detail_payload["events"][0]["event_type"] == "job_cache_hit"


def test_create_analysis_job_queues_when_cached_case_is_missing_requested_modalities(
    client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        analysis_router,
        "list_overlapping_cohort_cases",
        lambda: [
            SimpleNamespace(
                case_id="TCGA-CACHED-PARTIAL-0001",
                has_pathology=True,
                has_transcriptomics=False,
                has_clinical=True,
            )
        ],
    )

    response = client.post(
        "/v1/analysis/jobs",
        json={
            "case_id": "TCGA-CACHED-PARTIAL-0001",
            "requested_modalities": ["pathology", "transcriptomics"],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "queued"

    detail_response = client.get(f"/v1/analysis/jobs/{payload['job_id']}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["status"] == "queued"
    assert detail_payload["result_summary"]["served_from_cache"] is False
    assert detail_payload["result_summary"]["available_modalities"] == ["pathology"]
    assert detail_payload["result_summary"]["missing_modalities"] == ["transcriptomics"]
    event_types = [event["event_type"] for event in detail_payload["events"]]
    assert set(event_types) == {"job_created", "job_enqueued"}


def test_create_analysis_job_rejects_unknown_upload_session(client) -> None:
    response = client.post(
        "/v1/analysis/jobs",
        json={
            "case_id": "TCGA-TEST-ANALYSIS",
            "upload_session_id": str(uuid4()),
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "upload_session_id not found"}


def test_create_analysis_job_rejects_case_id_mismatch_with_upload_session(client) -> None:
    upload_response = client.post(
        "/v1/uploads/init",
        json={"case_id": "TCGA-CASE-A", "cohort": "mvp50"},
    )
    assert upload_response.status_code == 201
    upload_session_id = upload_response.json()["upload_session_id"]

    response = client.post(
        "/v1/analysis/jobs",
        json={
            "case_id": "TCGA-CASE-B",
            "upload_session_id": upload_session_id,
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "case_id does not match upload session case_id"}


def test_create_analysis_job_backfills_upload_session_case_id_when_missing(client, db) -> None:
    upload_response = client.post(
        "/v1/uploads/init",
        json={"metadata": {"requested_by": "pytest"}},
    )
    assert upload_response.status_code == 201
    upload_session_id = upload_response.json()["upload_session_id"]

    create_response = client.post(
        "/v1/analysis/jobs",
        json={
            "case_id": "TCGA-CASE-BACKFILL",
            "upload_session_id": upload_session_id,
        },
    )

    assert create_response.status_code == 201

    upload_session = db.get(UploadSession, UUID(upload_session_id))
    assert upload_session is not None
    assert upload_session.case_id == "TCGA-CASE-BACKFILL"


def test_create_analysis_job_rejects_blank_case_id(client) -> None:
    response = client.post(
        "/v1/analysis/jobs",
        json={
            "case_id": "   ",
        },
    )

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(error["loc"] == ["body", "case_id"] for error in errors)


def test_create_analysis_job_rejects_unknown_modality(client) -> None:
    response = client.post(
        "/v1/analysis/jobs",
        json={
            "case_id": "TCGA-TEST-ANALYSIS",
            "requested_modalities": ["pathology", "unsupported"],
        },
    )

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(error["loc"] == ["body", "requested_modalities"] for error in errors)


def test_create_analysis_job_returns_503_when_enqueue_fails(client, monkeypatch) -> None:
    def _raise_queue_error(_job_id):
        raise analysis_router.AnalysisQueueUnavailableError("redis down")

    monkeypatch.setattr(analysis_router, "enqueue_analysis_job", _raise_queue_error)

    response = client.post(
        "/v1/analysis/jobs",
        json={
            "case_id": "TCGA-TEST-QUEUE-FAIL",
            "requested_modalities": ["pathology"],
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "analysis queue unavailable; retry after queue service is healthy"


def test_get_analysis_job_returns_404_for_unknown_job(client) -> None:
    response = client.get(f"/v1/analysis/jobs/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "job_id not found"}


def test_get_analysis_job_artifacts_returns_non_stub_payload(client) -> None:
    create_response = client.post(
        "/v1/analysis/jobs",
        json={
            "case_id": "TCGA-TEST-ARTIFACTS",
            "requested_modalities": ["pathology"],
        },
    )
    assert create_response.status_code == 201
    job_id = create_response.json()["job_id"]

    response = client.get(f"/v1/analysis/jobs/{job_id}/artifacts")
    assert response.status_code == 200
    payload = response.json()

    assert payload["job_id"] == job_id
    assert payload["status"] == "queued"
    assert payload["available"] is False
    assert payload["research_use_only"] is True
    assert payload["modality_artifacts"] == []
