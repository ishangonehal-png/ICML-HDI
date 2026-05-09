from __future__ import annotations

import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core.config import settings
import db.session as db_session
from models import AnalysisJob, JobEvent, ModalityResult
from services.clinical import (
    get_clinical_eligibility,
    get_clinical_patient_summary,
    get_clinical_survival_baseline,
)
from services.fusion import get_fusion_attribution, get_fusion_score, get_fusion_similar_cases
from services.pathology import get_evidence, get_heatmap, get_tissue_composition
from services.transcriptomics import (
    get_cyt_signature,
    get_gep_signature,
    get_tide_signature,
    get_transcriptomic_evidence,
)

from .analysis_queue import (
    AnalysisQueueUnavailableError,
    QueuedAnalysisJob,
    acknowledge_analysis_job,
    dequeue_analysis_job,
    requeue_analysis_job,
    requeue_inflight_analysis_jobs,
)

logger = logging.getLogger(__name__)

_KNOWN_MODALITIES = ("pathology", "transcriptomics", "clinical", "fusion")


@dataclass(frozen=True)
class _ModalityExecutionResult:
    payload: dict[str, Any]
    metadata: dict[str, Any]
    message: str


def _worker_name() -> str:
    host = socket.gethostname() or "unknown-host"
    return f"{host}:{os.getpid()}"


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _append_event(
    db: Session,
    *,
    job_id: uuid.UUID,
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    db.add(
        JobEvent(
            job_id=job_id,
            event_type=event_type,
            message=message,
            created_at=datetime.now(UTC),
            payload=payload or {},
        )
    )


def _normalize_requested_modalities(requested_modalities: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in requested_modalities:
        modality = raw.strip().lower()
        if modality not in _KNOWN_MODALITIES:
            continue
        if modality in seen:
            continue
        ordered.append(modality)
        seen.add(modality)

    if ordered:
        return ordered
    return list(_KNOWN_MODALITIES)


def _existing_result(
    db: Session,
    *,
    job_id: uuid.UUID,
    modality: str,
) -> ModalityResult | None:
    return db.scalar(
        select(ModalityResult).where(
            ModalityResult.job_id == job_id,
            ModalityResult.modality == modality,
        )
    )


def _upsert_result(
    db: Session,
    *,
    job: AnalysisJob,
    modality: str,
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    existing = _existing_result(db, job_id=job.id, modality=modality)
    if existing is None:
        db.add(
            ModalityResult(
                job_id=job.id,
                case_id=job.case_id,
                modality=modality,
                payload=payload,
                result_metadata=metadata,
            )
        )
        return

    existing.payload = payload
    existing.result_metadata = metadata


def _pathology_payload(case_id: str) -> _ModalityExecutionResult:
    slide_id = f"{case_id}-DX1"
    tissue = get_tissue_composition(slide_id)
    heatmap = get_heatmap(slide_id)
    evidence = get_evidence(slide_id)
    sources = {
        "tissue": tissue.provenance.data_source,
        "heatmap": heatmap.provenance.data_source,
        "evidence": evidence.provenance.data_source,
    }
    return _ModalityExecutionResult(
        payload={
            "slide_id": slide_id,
            "tissue_composition": tissue.model_dump(mode="json"),
            "heatmap": heatmap.model_dump(mode="json"),
            "evidence": evidence.model_dump(mode="json"),
        },
        metadata={
            "modality": "pathology",
            "data_sources": sources,
            "computed_at": _iso_now(),
        },
        message=(
            "Pathology completed "
            f"(tissue={sources['tissue']}, heatmap={sources['heatmap']}, evidence={sources['evidence']})."
        ),
    )


def _transcriptomics_payload(case_id: str, db: Session) -> _ModalityExecutionResult:
    cyt = get_cyt_signature(case_id, db=db)
    gep = get_gep_signature(case_id, db=db)
    tide = get_tide_signature(case_id, db=db)
    evidence = get_transcriptomic_evidence(case_id, db=db)
    sources = {
        "cyt": cyt.data_source,
        "gep": gep.data_source,
        "tide": tide.data_source,
        "evidence": evidence.data_source,
    }
    return _ModalityExecutionResult(
        payload={
            "cyt": cyt.model_dump(mode="json"),
            "gep": gep.model_dump(mode="json"),
            "tide": tide.model_dump(mode="json"),
            "evidence": evidence.model_dump(mode="json"),
        },
        metadata={
            "modality": "transcriptomics",
            "data_sources": sources,
            "computed_at": _iso_now(),
        },
        message=(
            "Transcriptomics completed "
            f"(cyt={sources['cyt']}, gep={sources['gep']}, tide={sources['tide']}, evidence={sources['evidence']})."
        ),
    )


def _clinical_payload(case_id: str, db: Session) -> _ModalityExecutionResult:
    summary = get_clinical_patient_summary(case_id, db=db)
    eligibility = get_clinical_eligibility(case_id, db=db)
    survival = get_clinical_survival_baseline(case_id, db=db)
    sources = {
        "summary": summary.data_source,
        "eligibility": eligibility.data_source,
        "survival": survival.data_source,
    }
    return _ModalityExecutionResult(
        payload={
            "patient_summary": summary.model_dump(mode="json"),
            "eligibility": eligibility.model_dump(mode="json"),
            "survival_baseline": survival.model_dump(mode="json"),
        },
        metadata={
            "modality": "clinical",
            "data_sources": sources,
            "computed_at": _iso_now(),
        },
        message=(
            "Clinical completed "
            f"(summary={sources['summary']}, eligibility={sources['eligibility']}, survival={sources['survival']})."
        ),
    )


def _fusion_payload(case_id: str, db: Session) -> _ModalityExecutionResult:
    score = get_fusion_score(case_id, include_rna=True, db=db)
    attribution = get_fusion_attribution(case_id, include_rna=True, db=db)
    similar_cases = get_fusion_similar_cases(case_id, include_rna=True, db=db, limit=5)
    return _ModalityExecutionResult(
        payload={
            "score": score.model_dump(mode="json"),
            "attribution": attribution.model_dump(mode="json"),
            "similar_cases": similar_cases.model_dump(mode="json"),
        },
        metadata={
            "modality": "fusion",
            "mode_used": score.mode_used,
            "rna_applied": score.rna_applied,
            "computed_at": _iso_now(),
        },
        message=(
            "Fusion completed "
            f"(mode={score.mode_used}, rna_applied={str(score.rna_applied).lower()})."
        ),
    )


def _process_modality(modality: str, *, case_id: str, db: Session) -> _ModalityExecutionResult:
    if modality == "pathology":
        return _pathology_payload(case_id)
    if modality == "transcriptomics":
        return _transcriptomics_payload(case_id, db)
    if modality == "clinical":
        return _clinical_payload(case_id, db)
    if modality == "fusion":
        return _fusion_payload(case_id, db)
    raise ValueError(f"unsupported modality '{modality}'")


def process_analysis_job(
    job_id: uuid.UUID,
    *,
    worker_name: str | None = None,
) -> bool:
    name = worker_name or _worker_name()

    with db_session.SessionLocal() as db:
        claimed = db.execute(
            update(AnalysisJob)
            .where(AnalysisJob.id == job_id, AnalysisJob.status == "queued")
            .values(status="running", error_message=None)
        )
        if claimed.rowcount != 1:
            db.rollback()
            return False

        job = db.get(AnalysisJob, job_id)
        if job is None:
            db.rollback()
            return False

        _append_event(
            db,
            job_id=job.id,
            event_type="job_started",
            message="Worker picked up queued job and started processing.",
            payload={"worker": name},
        )
        db.commit()

        requested = _normalize_requested_modalities(job.requested_modalities)
        completed_modalities: list[str] = []
        failed_modality: str | None = None

        try:
            for modality in requested:
                if _existing_result(db, job_id=job.id, modality=modality) is not None:
                    completed_modalities.append(modality)
                    _append_event(
                        db,
                        job_id=job.id,
                        event_type="modality_skipped",
                        message=f"{modality.capitalize()} already had a persisted result; skipped recompute.",
                        payload={
                            "modality": modality,
                            "status": "completed",
                            "worker": name,
                            "idempotent": True,
                        },
                    )
                    db.commit()
                    continue

                _append_event(
                    db,
                    job_id=job.id,
                    event_type="modality_started",
                    message=f"{modality.capitalize()} started.",
                    payload={"modality": modality, "status": "running", "worker": name},
                )
                db.commit()

                failed_modality = modality
                result = _process_modality(modality, case_id=job.case_id, db=db)
                _upsert_result(
                    db,
                    job=job,
                    modality=modality,
                    payload=result.payload,
                    metadata=result.metadata,
                )
                completed_modalities.append(modality)
                _append_event(
                    db,
                    job_id=job.id,
                    event_type="modality_completed",
                    message=result.message,
                    payload={
                        "modality": modality,
                        "status": "completed",
                        "worker": name,
                        "metadata": result.metadata,
                    },
                )
                failed_modality = None
                db.commit()

            missing_modalities = [entry for entry in requested if entry not in completed_modalities]
            job.status = "completed"
            job.error_message = None
            job.result_summary = {
                "served_from_cache": False,
                "completed_modalities": completed_modalities,
                "missing_modalities": missing_modalities,
                "worker": name,
                "completed_at": _iso_now(),
            }
            _append_event(
                db,
                job_id=job.id,
                event_type="job_completed",
                message="All requested modalities completed successfully.",
                payload={
                    "completed_modalities": completed_modalities,
                    "missing_modalities": missing_modalities,
                    "worker": name,
                },
            )
            db.commit()
            return True
        except Exception as exc:
            db.rollback()
            failed_job = db.get(AnalysisJob, job_id)
            if failed_job is not None:
                failed_job.status = "failed"
                failed_job.error_message = str(exc)
                failed_job.result_summary = {
                    "served_from_cache": False,
                    "completed_modalities": completed_modalities,
                    "failed_modality": failed_modality,
                    "worker": name,
                    "failed_at": _iso_now(),
                }

                if failed_modality is not None:
                    _append_event(
                        db,
                        job_id=failed_job.id,
                        event_type="modality_failed",
                        message=f"{failed_modality.capitalize()} failed: {exc}",
                        payload={
                            "modality": failed_modality,
                            "status": "failed",
                            "worker": name,
                            "error_type": type(exc).__name__,
                        },
                    )

                _append_event(
                    db,
                    job_id=failed_job.id,
                    event_type="job_failed",
                    message=f"Analysis failed: {exc}",
                    payload={
                        "failed_modality": failed_modality,
                        "worker": name,
                        "error_type": type(exc).__name__,
                    },
                )
                db.commit()
            logger.exception("analysis worker failed for job %s", job_id)
            return False


def run_worker(*, worker_name: str | None = None, process_once: bool = False) -> None:
    name = worker_name or _worker_name()
    logger.info("analysis worker starting (worker=%s)", name)

    if settings.analysis_worker_requeue_inflight_on_start:
        try:
            moved = requeue_inflight_analysis_jobs()
            if moved:
                logger.info("requeued %s inflight analysis jobs on startup", moved)
        except AnalysisQueueUnavailableError:
            logger.exception("unable to requeue inflight jobs on startup")

    while True:
        queued_job: QueuedAnalysisJob | None = None
        try:
            queued_job = dequeue_analysis_job()
            if queued_job is None:
                if process_once:
                    return
                continue

            process_analysis_job(queued_job.job_id, worker_name=name)
            acknowledge_analysis_job(queued_job)
            if process_once:
                return
        except AnalysisQueueUnavailableError:
            logger.exception("analysis queue unavailable")
            if process_once:
                return
            time.sleep(1.0)
        except KeyboardInterrupt:
            logger.info("analysis worker stopping on keyboard interrupt")
            raise
        except Exception:
            logger.exception("unexpected analysis worker failure")
            if queued_job is not None:
                try:
                    requeue_analysis_job(queued_job)
                except AnalysisQueueUnavailableError:
                    logger.exception("failed requeueing job after unexpected worker error")
            if process_once:
                return
