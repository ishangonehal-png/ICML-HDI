from __future__ import annotations

from uuid import UUID

import pytest

import routers.analysis as analysis_router
import services.analysis_worker as analysis_worker


@pytest.fixture(autouse=True)
def stub_queue_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis_router, "list_overlapping_cohort_cases", lambda: [])
    monkeypatch.setattr(analysis_router, "enqueue_analysis_job", lambda _job_id: None)


def test_worker_processes_queued_job_end_to_end(client) -> None:
    create_response = client.post(
        "/v1/analysis/jobs",
        json={
            "case_id": "TCGA-WORKER-0001",
            "requested_modalities": ["pathology", "transcriptomics", "clinical", "fusion"],
        },
    )
    assert create_response.status_code == 201
    job_id = UUID(create_response.json()["job_id"])

    processed = analysis_worker.process_analysis_job(job_id, worker_name="pytest-worker")
    assert processed is True

    detail_response = client.get(f"/v1/analysis/jobs/{job_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()

    assert detail_payload["status"] == "completed"
    completed_modalities = {
        result["modality"] for result in detail_payload["modality_results"]
    }
    assert completed_modalities == {"pathology", "transcriptomics", "clinical", "fusion"}

    event_types = [event["event_type"] for event in detail_payload["events"]]
    assert "job_started" in event_types
    assert event_types.count("modality_started") == 4
    assert event_types.count("modality_completed") == 4
    assert event_types[-1] == "job_completed"


def test_worker_marks_job_failed_on_modality_exception(client, monkeypatch) -> None:
    create_response = client.post(
        "/v1/analysis/jobs",
        json={
            "case_id": "TCGA-WORKER-0002",
            "requested_modalities": ["pathology"],
        },
    )
    assert create_response.status_code == 201
    job_id = UUID(create_response.json()["job_id"])

    def _boom(*_args, **_kwargs):
        raise RuntimeError("forced modality failure")

    monkeypatch.setattr(analysis_worker, "_pathology_payload", _boom)

    processed = analysis_worker.process_analysis_job(job_id, worker_name="pytest-worker")
    assert processed is False

    detail_response = client.get(f"/v1/analysis/jobs/{job_id}")
    assert detail_response.status_code == 200
    payload = detail_response.json()

    assert payload["status"] == "failed"
    assert payload["error_message"] == "forced modality failure"
    event_types = [event["event_type"] for event in payload["events"]]
    assert "modality_failed" in event_types
    assert event_types[-1] == "job_failed"


def test_run_worker_requeues_job_on_unexpected_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    queued_job = analysis_worker.QueuedAnalysisJob(
        job_id=UUID("00000000-0000-0000-0000-000000000123"),
        enqueued_at="2026-03-08T00:00:00Z",
        attempts=1,
        raw_payload='{"job_id":"00000000-0000-0000-0000-000000000123","attempts":1}',
    )

    monkeypatch.setattr(analysis_worker, "requeue_inflight_analysis_jobs", lambda: 0)
    monkeypatch.setattr(analysis_worker, "dequeue_analysis_job", lambda: queued_job)

    def _raise_unexpected(*_args, **_kwargs):
        raise RuntimeError("worker blew up")

    monkeypatch.setattr(analysis_worker, "process_analysis_job", _raise_unexpected)

    acknowledged: list[UUID] = []
    requeued: list[UUID] = []
    monkeypatch.setattr(
        analysis_worker,
        "acknowledge_analysis_job",
        lambda job: acknowledged.append(job.job_id),
    )
    monkeypatch.setattr(
        analysis_worker,
        "requeue_analysis_job",
        lambda job: requeued.append(job.job_id),
    )

    analysis_worker.run_worker(worker_name="pytest-worker", process_once=True)

    assert requeued == [queued_job.job_id]
    assert acknowledged == []


def test_run_worker_acknowledges_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    queued_job = analysis_worker.QueuedAnalysisJob(
        job_id=UUID("00000000-0000-0000-0000-000000000456"),
        enqueued_at="2026-03-08T00:00:00Z",
        attempts=1,
        raw_payload='{"job_id":"00000000-0000-0000-0000-000000000456","attempts":1}',
    )

    monkeypatch.setattr(analysis_worker, "requeue_inflight_analysis_jobs", lambda: 0)
    monkeypatch.setattr(analysis_worker, "dequeue_analysis_job", lambda: queued_job)
    monkeypatch.setattr(analysis_worker, "process_analysis_job", lambda *_args, **_kwargs: True)

    acknowledged: list[UUID] = []
    requeued: list[UUID] = []
    monkeypatch.setattr(
        analysis_worker,
        "acknowledge_analysis_job",
        lambda job: acknowledged.append(job.job_id),
    )
    monkeypatch.setattr(
        analysis_worker,
        "requeue_analysis_job",
        lambda job: requeued.append(job.job_id),
    )

    analysis_worker.run_worker(worker_name="pytest-worker", process_once=True)

    assert acknowledged == [queued_job.job_id]
    assert requeued == []
