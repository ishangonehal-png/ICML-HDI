from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    cohort: Mapped[str | None] = mapped_column(String(64), nullable=True)
    record_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    files: Mapped[list[File]] = relationship(back_populates="case")
    upload_sessions: Mapped[list[UploadSession]] = relationship(back_populates="case")


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("cases.case_id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    cohort: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="initialized", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    record_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    case: Mapped[Case | None] = relationship(back_populates="upload_sessions")
    files: Mapped[list[File]] = relationship(back_populates="upload_session")
    analysis_jobs: Mapped[list[AnalysisJob]] = relationship(back_populates="upload_session")


class File(Base):
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("cases.case_id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    upload_session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("upload_sessions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    gdc_file_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    record_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    case: Mapped[Case | None] = relationship(back_populates="files")
    upload_session: Mapped[UploadSession | None] = relationship(back_populates="files")


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    upload_session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("upload_sessions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    requested_modalities: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    record_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    upload_session: Mapped[UploadSession | None] = relationship(back_populates="analysis_jobs")
    job_events: Mapped[list[JobEvent]] = relationship(back_populates="job", cascade="all, delete-orphan")
    modality_results: Mapped[list[ModalityResult]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    job: Mapped[AnalysisJob] = relationship(back_populates="job_events")


class ModalityResult(Base):
    __tablename__ = "modality_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    case_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    modality: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    job: Mapped[AnalysisJob] = relationship(back_populates="modality_results")
