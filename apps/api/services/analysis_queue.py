from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache

from redis import Redis
from redis.exceptions import RedisError

from core.config import settings


class AnalysisQueueUnavailableError(RuntimeError):
    """Raised when the Redis-backed analysis queue is unavailable."""


@dataclass(frozen=True)
class QueuedAnalysisJob:
    job_id: uuid.UUID
    enqueued_at: str | None
    attempts: int
    raw_payload: str


@lru_cache(maxsize=1)
def _redis_client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def _queue_key() -> str:
    return settings.analysis_queue_key


def _processing_key() -> str:
    return settings.analysis_queue_processing_key


def _dedupe_key(job_id: uuid.UUID) -> str:
    return f"{_queue_key()}:dedupe:{job_id}"


def _serialize_payload(job_id: uuid.UUID, *, attempts: int = 1) -> str:
    return json.dumps(
        {
            "job_id": str(job_id),
            "enqueued_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "attempts": max(1, attempts),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _parse_payload(raw_payload: str) -> QueuedAnalysisJob:
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        # Backward-compatible fallback if payload is a raw UUID string.
        return QueuedAnalysisJob(
            job_id=uuid.UUID(raw_payload),
            enqueued_at=None,
            attempts=1,
            raw_payload=raw_payload,
        )

    if not isinstance(payload, dict):
        raise ValueError("queue payload must be a JSON object")

    job_id_raw = payload.get("job_id")
    if not isinstance(job_id_raw, str):
        raise ValueError("queue payload missing job_id")

    attempts_raw = payload.get("attempts", 1)
    attempts = 1
    if isinstance(attempts_raw, int):
        attempts = max(1, attempts_raw)

    enqueued_at = payload.get("enqueued_at")
    if not isinstance(enqueued_at, str):
        enqueued_at = None

    return QueuedAnalysisJob(
        job_id=uuid.UUID(job_id_raw),
        enqueued_at=enqueued_at,
        attempts=attempts,
        raw_payload=raw_payload,
    )


def enqueue_analysis_job(job_id: uuid.UUID) -> None:
    client = _redis_client()
    dedupe_key = _dedupe_key(job_id)
    payload = _serialize_payload(job_id)
    dedupe_set = False

    try:
        dedupe_set = bool(
            client.set(
                dedupe_key,
                "1",
                nx=True,
                ex=max(60, settings.analysis_queue_dedupe_ttl_seconds),
            )
        )
        if not dedupe_set:
            return

        client.lpush(_queue_key(), payload)
    except RedisError as exc:
        if dedupe_set:
            try:
                client.delete(dedupe_key)
            except RedisError:
                pass
        raise AnalysisQueueUnavailableError(
            f"failed to enqueue analysis job {job_id}: {exc}"
        ) from exc


def dequeue_analysis_job(*, timeout_seconds: int | None = None) -> QueuedAnalysisJob | None:
    client = _redis_client()
    timeout = settings.analysis_worker_poll_timeout_seconds if timeout_seconds is None else timeout_seconds
    timeout = max(1, int(timeout))

    try:
        raw_payload = client.brpoplpush(_queue_key(), _processing_key(), timeout=timeout)
    except RedisError as exc:
        raise AnalysisQueueUnavailableError(f"failed to dequeue analysis job: {exc}") from exc

    if raw_payload is None:
        return None

    try:
        return _parse_payload(raw_payload)
    except (ValueError, TypeError) as exc:
        # Drop malformed payloads from inflight to prevent worker deadlock loops.
        try:
            client.lrem(_processing_key(), 1, raw_payload)
        except RedisError:
            pass
        raise AnalysisQueueUnavailableError(f"invalid queue payload: {exc}") from exc


def acknowledge_analysis_job(job: QueuedAnalysisJob) -> None:
    client = _redis_client()
    try:
        client.lrem(_processing_key(), 1, job.raw_payload)
        client.delete(_dedupe_key(job.job_id))
    except RedisError as exc:
        raise AnalysisQueueUnavailableError(f"failed to acknowledge analysis job {job.job_id}: {exc}") from exc


def requeue_analysis_job(job: QueuedAnalysisJob) -> None:
    client = _redis_client()
    try:
        removed = client.lrem(_processing_key(), 1, job.raw_payload)
        if removed:
            client.lpush(_queue_key(), job.raw_payload)
    except RedisError as exc:
        raise AnalysisQueueUnavailableError(f"failed to requeue analysis job {job.job_id}: {exc}") from exc


def requeue_inflight_analysis_jobs() -> int:
    client = _redis_client()
    moved = 0
    try:
        while True:
            payload = client.rpoplpush(_processing_key(), _queue_key())
            if payload is None:
                break
            moved += 1
    except RedisError as exc:
        raise AnalysisQueueUnavailableError(f"failed to requeue inflight jobs: {exc}") from exc
    return moved
