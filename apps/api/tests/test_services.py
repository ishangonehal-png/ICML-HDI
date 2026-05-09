from __future__ import annotations

from sqlalchemy import select

from models import Case
from services.cases import ensure_case_exists
from services.responses import research_stub_response


def test_ensure_case_exists_creates_new_case_with_merged_metadata(db) -> None:
    ensure_case_exists(
        db,
        case_id="TCGA-HELPER-0001",
        cohort="mvp50",
        source="pytest",
        metadata={"note": "bootstrap"},
    )
    db.commit()

    case = db.scalar(select(Case).where(Case.case_id == "TCGA-HELPER-0001"))
    assert case is not None
    assert case.cohort == "mvp50"
    assert case.record_metadata == {"source": "pytest", "note": "bootstrap"}


def test_ensure_case_exists_is_idempotent_for_existing_case(db) -> None:
    ensure_case_exists(
        db,
        case_id="TCGA-HELPER-0002",
        cohort="mvp50",
        source="first-call",
        metadata={"origin": "initial"},
    )
    db.commit()

    ensure_case_exists(
        db,
        case_id="TCGA-HELPER-0002",
        cohort="other-cohort",
        source="second-call",
        metadata={"origin": "second"},
    )
    db.commit()

    cases = db.scalars(select(Case).where(Case.case_id == "TCGA-HELPER-0002")).all()
    assert len(cases) == 1
    assert cases[0].cohort == "mvp50"
    assert cases[0].record_metadata == {"source": "first-call", "origin": "initial"}


def test_research_stub_response_shapes_payload_with_extra_fields() -> None:
    payload = research_stub_response(
        id_key="case_id",
        id_value="TCGA-STUB-0001",
        message="Pathology endpoint scaffolded",
        extra={"modality": "pathology"},
    )

    assert payload == {
        "case_id": "TCGA-STUB-0001",
        "status": "stub",
        "message": "Pathology endpoint scaffolded",
        "research_use_only": True,
        "modality": "pathology",
    }
