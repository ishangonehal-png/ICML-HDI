"""Initial Postgres core schema for P0 backend scaffold.

Revision ID: 0001_initial_core
Revises:
Create Date: 2026-03-05 14:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_initial_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("cohort", sa.String(length=64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id"),
    )
    op.create_index(op.f("ix_cases_case_id"), "cases", ["case_id"], unique=False)

    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=True),
        sa.Column("cohort", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_upload_sessions_case_id"), "upload_sessions", ["case_id"], unique=False)

    op.create_table(
        "analysis_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("upload_session_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_modalities", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["upload_session_id"], ["upload_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analysis_jobs_case_id"), "analysis_jobs", ["case_id"], unique=False)
    op.create_index(
        op.f("ix_analysis_jobs_upload_session_id"),
        "analysis_jobs",
        ["upload_session_id"],
        unique=False,
    )

    op.create_table(
        "files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=True),
        sa.Column("upload_session_id", sa.Uuid(), nullable=True),
        sa.Column("gdc_file_id", sa.String(length=64), nullable=True),
        sa.Column("file_name", sa.String(length=256), nullable=True),
        sa.Column("file_type", sa.String(length=64), nullable=True),
        sa.Column("storage_uri", sa.String(length=1024), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["upload_session_id"], ["upload_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_files_case_id"), "files", ["case_id"], unique=False)
    op.create_index(op.f("ix_files_gdc_file_id"), "files", ["gdc_file_id"], unique=False)
    op.create_index(op.f("ix_files_upload_session_id"), "files", ["upload_session_id"], unique=False)

    op.create_table(
        "job_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_job_events_job_id"), "job_events", ["job_id"], unique=False)

    op.create_table(
        "modality_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("modality", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_modality_results_case_id"), "modality_results", ["case_id"], unique=False)
    op.create_index(op.f("ix_modality_results_job_id"), "modality_results", ["job_id"], unique=False)
    op.create_index(op.f("ix_modality_results_modality"), "modality_results", ["modality"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_modality_results_modality"), table_name="modality_results")
    op.drop_index(op.f("ix_modality_results_job_id"), table_name="modality_results")
    op.drop_index(op.f("ix_modality_results_case_id"), table_name="modality_results")
    op.drop_table("modality_results")

    op.drop_index(op.f("ix_job_events_job_id"), table_name="job_events")
    op.drop_table("job_events")

    op.drop_index(op.f("ix_files_upload_session_id"), table_name="files")
    op.drop_index(op.f("ix_files_gdc_file_id"), table_name="files")
    op.drop_index(op.f("ix_files_case_id"), table_name="files")
    op.drop_table("files")

    op.drop_index(op.f("ix_analysis_jobs_upload_session_id"), table_name="analysis_jobs")
    op.drop_index(op.f("ix_analysis_jobs_case_id"), table_name="analysis_jobs")
    op.drop_table("analysis_jobs")

    op.drop_index(op.f("ix_upload_sessions_case_id"), table_name="upload_sessions")
    op.drop_table("upload_sessions")

    op.drop_index(op.f("ix_cases_case_id"), table_name="cases")
    op.drop_table("cases")
