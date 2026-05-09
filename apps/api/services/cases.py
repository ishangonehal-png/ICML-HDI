from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Case


def ensure_case_exists(
    db: Session,
    *,
    case_id: str,
    cohort: str | None,
    source: str,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Create a case record when missing; no-op when it already exists."""
    existing_case = db.scalar(select(Case).where(Case.case_id == case_id))
    if existing_case is not None:
        return

    record_metadata: dict[str, Any] = {"source": source}
    if metadata:
        record_metadata.update(dict(metadata))

    db.add(
        Case(
            case_id=case_id,
            cohort=cohort,
            record_metadata=record_metadata,
        )
    )
