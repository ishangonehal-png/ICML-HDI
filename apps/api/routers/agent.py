from __future__ import annotations
from services.agent_context import build_agent_context

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from dependencies.db import get_db
from schemas.agent import (
    AgentCitation,
    AgentContextResponse,
    AgentModalityAvailability,
    AgentQueryRequest,
    AgentQueryResponse,
)
from services.fusion import build_fusion_metadata
from services.llm_agent import run_llm_agent
router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/context/{case_id}", response_model=AgentContextResponse)
def get_agent_context(case_id: str, db: Session = Depends(get_db)) -> AgentContextResponse:
    """Return contextualized embedding-derived context for this case, for use in an agent or LLM."""
    return build_agent_context(case_id, db=db)


def _as_percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def _metric_value(value: float | None, *, available: bool) -> str:
    if not available or value is None:
        return "NA"
    return f"{value:.3f}"


@router.post("/query", response_model=AgentQueryResponse)
def query_agent(payload: AgentQueryRequest, db: Session = Depends(get_db)) -> AgentQueryResponse:
    case_id = payload.case_id.strip() or payload.case_id
    slide_id = f"{case_id}-DX1"

    # Single source of truth: build_agent_context fetches everything once
    result = build_agent_context(case_id, db=db, include_raw=True)
    response, case_context = result

    fusion_score = case_context["fusion_score"]
    fusion_attribution = case_context["fusion_attribution"]
    tissue = case_context["tissue"]
    evidence = case_context["evidence"]
    cyt = case_context["cyt"]
    gep = case_context["gep"]
    tide = case_context["tide"]
    transcriptomic_evidence = case_context["transcriptomic_evidence"]

    modality_by_name = {item.modality: item for item in fusion_score.modalities}
    pathology_modality = modality_by_name["pathology"]
    clinical_modality = modality_by_name["clinical"]
    transcriptomics_modality = modality_by_name["transcriptomics"]

    dominant_fractions = sorted(tissue.fractions, key=lambda item: item.fraction, reverse=True)
    dominant_summary = (
        ", ".join(
            f"{fraction.tissue} ({_as_percent(fraction.fraction)})"
            for fraction in dominant_fractions[:2]
        )
        if dominant_fractions
        else "no dominant tissue fractions"
    )
    top_tile = max(evidence.top_tiles, key=lambda tile: tile.score) if evidence.top_tiles else None
    top_modality = max(
        fusion_attribution.modalities,
        key=lambda modality: modality.contribution_percent,
    )

    answer, literature_citations = run_llm_agent(
        case_id=case_id,
        question=payload.question,
        case_context=case_context,
        context_for_llm=response.context_for_llm,
    )

    # UNCHANGED: preserve the repo's existing internal provenance citations
    citations: list[AgentCitation] = [
        AgentCitation(
            panel="pathology",
            field="tissue_composition",
            source=f"/v1/pathology/slides/{slide_id}/tissue-composition",
            value=dominant_summary,
        ),
        AgentCitation(
            panel="pathology",
            field="top_tiles",
            source=f"/v1/pathology/slides/{slide_id}/evidence",
            value=(
                f"{top_tile.tile_id}:{top_tile.score:.2f}" if top_tile else "none"
            ),
        ),
        AgentCitation(
            panel="clinical",
            field="clinical_minimum",
            source=clinical_modality.provenance[0].source if clinical_modality.provenance else "fusion://clinical-minimum",
            value=clinical_modality.summary,
        ),
        AgentCitation(
            panel="fusion",
            field="score",
            source=f"/v1/fusion/{case_id}/score",
            value=(
                f"mode={fusion_score.mode_used};provisional={fusion_score.provisional_score:.3f};"
                f"refined={fusion_score.refined_score:.3f};delta={fusion_score.delta_score:+.3f}"
            ),
        ),
        AgentCitation(
            panel="fusion",
            field="attribution",
            source=f"/v1/fusion/{case_id}/attribution",
            value=f"top={top_modality.modality}:{top_modality.contribution_percent:.1f}%",
        ),
    ]

    if transcriptomics_modality.available:
        citations.extend(
            [
                AgentCitation(
                    panel="transcriptomics",
                    field="cyt",
                    source=f"/v1/transcriptomics/{case_id}/cyt",
                    value=_metric_value(cyt.value, available=cyt.available),
                ),
                AgentCitation(
                    panel="transcriptomics",
                    field="gep",
                    source=f"/v1/transcriptomics/{case_id}/gep",
                    value=_metric_value(gep.value, available=gep.available),
                ),
                AgentCitation(
                    panel="transcriptomics",
                    field="tide",
                    source=f"/v1/transcriptomics/{case_id}/tide?experimental=true",
                    value=_metric_value(tide.value, available=tide.available),
                ),
                AgentCitation(
                    panel="transcriptomics",
                    field="evidence",
                    source=f"/v1/transcriptomics/{case_id}/evidence",
                    value=f"top_genes={len(transcriptomic_evidence.top_genes)}",
                ),
            ]
        )
    else:
        citations.append(
            AgentCitation(
                panel="transcriptomics",
                field="availability",
                source=f"/v1/transcriptomics/{case_id}/cyt",
                value=transcriptomics_modality.unavailable_reason,
            )
        )

    # ADDED: append literature / PubMed citations returned by the new agent service
    citations.extend(literature_citations)

    # UNCHANGED: keep modality availability for the UI exactly as before
    modalities = [
        AgentModalityAvailability(
            modality="pathology",
            available=pathology_modality.available,
            data_source=pathology_modality.data_source,
            summary=pathology_modality.summary,
        ),
        AgentModalityAvailability(
            modality="clinical",
            available=clinical_modality.available,
            data_source=clinical_modality.data_source,
            summary=clinical_modality.summary,
        ),
        AgentModalityAvailability(
            modality="transcriptomics",
            available=transcriptomics_modality.available,
            data_source=transcriptomics_modality.data_source,
            summary=transcriptomics_modality.summary,
        ),
        AgentModalityAvailability(
            modality="fusion",
            available=True,
            data_source=f"mode:{fusion_score.mode_used}",
            summary=(
                f"provisional={fusion_score.provisional_score:.3f}, "
                f"refined={fusion_score.refined_score:.3f}, "
                f"delta={fusion_score.delta_score:+.3f}"
            ),
        ),
    ]

    missing_modalities = [
        modality.modality
        for modality in modalities
        if not modality.available
    ]

    # UNCHANGED: same response shape, so the existing UI keeps working
    return AgentQueryResponse(
        case_id=case_id,
        answer=answer,
        citations=citations,
        modalities=modalities,
        acknowledged_missing_modalities=missing_modalities,
        meta=build_fusion_metadata("agent-grounded-multimodal-v1"),
    )
