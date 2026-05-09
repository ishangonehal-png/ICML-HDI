"""Build structured agent context from embeddings and services for feeding into an agent or LLM."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Union

from sqlalchemy.orm import Session

from schemas.agent import AgentContextResponse
from schemas.pathology import MethodMetadata

# CHANGED: import directly from concrete modules instead of importing from the
# package-level services namespace. This avoids a circular import during
# services/__init__.py initialization.
from .fusion import (
    build_fusion_metadata,
    get_fusion_attribution,
    get_fusion_score,
    get_fusion_similar_cases,
)
from .clinical import (
    get_clinical_patient_summary,
    get_clinical_survival_baseline,
)
try:
    from .survival_mlp import get_survival_mlp_prediction
except Exception:  # pragma: no cover - optional module in some deploy snapshots
    def get_survival_mlp_prediction(case_id: str):
        return SimpleNamespace(
            available=False,
            probability=None,
            predicted_class="unknown",
            horizon_years=3,
            unavailable_reason="Survival MLP model unavailable in this deployment.",
        )
from .pathology import (
    get_evidence,
    get_tissue_composition,
)
from .transcriptomics import (
    get_cyt_signature,
    get_gep_signature,
    get_tide_signature,
    get_transcriptomic_evidence,
    get_transcriptomics_plots,
)


def _as_percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def _metric_value(value: float | None, *, available: bool) -> str:
    if not available or value is None:
        return "NA"
    return f"{value:.3f}"


def build_agent_context(
    case_id: str, *, db: Session | None = None, include_raw: bool = False
) -> Union[AgentContextResponse, tuple[AgentContextResponse, dict]]:
    """
    Assemble all contextualized signals (fusion, pathology, transcriptomics, clinical,
    survival, similar cases) into a single structured context suitable for an agent or LLM.

    When include_raw is True, also returns the raw case_context dict (fusion_score,
    tissue, evidence, cyt, gep, tide, etc.) for use by POST /agent/query so the same
    fetch feeds both the context response and the LLM/citations.
    """
    case_id = (case_id or "").strip()
    slide_id = f"{case_id}-DX1"

    fusion_score = get_fusion_score(case_id, include_rna=True, db=db)
    fusion_attribution = get_fusion_attribution(case_id, include_rna=True, db=db)
    similar_cases_resp = get_fusion_similar_cases(case_id, include_rna=True, limit=5, db=db)

    tissue = get_tissue_composition(slide_id, strict_missing=False)
    evidence = get_evidence(slide_id, strict_missing=False)

    cyt = get_cyt_signature(case_id, db=db)
    gep = get_gep_signature(case_id, db=db)
    tide = get_tide_signature(case_id, db=db)
    transcriptomic_evidence = get_transcriptomic_evidence(case_id, db=db)

    clinical_summary_resp = get_clinical_patient_summary(case_id, db=db)
    survival_resp = get_clinical_survival_baseline(case_id, db=db)

    modality_by_name = {m.modality: m for m in fusion_score.modalities}
    pathology_mod = modality_by_name.get("pathology")
    clinical_mod = modality_by_name.get("clinical")
    transcriptomics_mod = modality_by_name.get("transcriptomics")

    dominant_fractions = sorted(tissue.fractions, key=lambda x: x.fraction, reverse=True)
    if dominant_fractions:
        pathology_summary = ", ".join(
            f"{f.tissue} ({_as_percent(f.fraction)})" for f in dominant_fractions[:3]
        )
    else:
        pathology_summary = "no tissue fractions available"

    if evidence.top_tiles:
        top = max(evidence.top_tiles, key=lambda t: t.score)
        pathology_summary += f"; top evidence tile {top.tile_id} score {top.score:.2f} ({top.rationale})"
    else:
        pathology_summary += "; no top evidence tiles"

    clinical_summary_str = ""
    if clinical_summary_resp.available:
        parts = []
        if clinical_summary_resp.stage:
            parts.append(f"stage {clinical_summary_resp.stage}")
        if clinical_summary_resp.smoking_status:
            parts.append(clinical_summary_resp.smoking_status)
        if clinical_summary_resp.age_at_diagnosis is not None:
            parts.append(f"age at Dx {clinical_summary_resp.age_at_diagnosis}")
        if clinical_summary_resp.diagnosis:
            parts.append(clinical_summary_resp.diagnosis)
        if clinical_summary_resp.report_highlights:
            parts.append("; ".join(clinical_summary_resp.report_highlights[:3]))
        clinical_summary_str = ". ".join(parts) if parts else "Structured summary available; no key fields extracted."
    else:
        clinical_summary_str = clinical_summary_resp.unavailable_reason or "Clinical summary unavailable."

    transcriptomics_summary_str = ""
    if transcriptomics_mod and transcriptomics_mod.available:
        transcriptomics_summary_str = (
            f"CYT={_metric_value(cyt.value, available=cyt.available)}, "
            f"GEP={_metric_value(gep.value, available=gep.available)}, "
            f"TIDE={_metric_value(tide.value, available=tide.available)}; "
            f"contribution {transcriptomics_mod.contribution_percent:.1f}%. "
            f"Top genes: {len(transcriptomic_evidence.top_genes)}."
        )
    else:
        transcriptomics_summary_str = (
            transcriptomics_mod.unavailable_reason if transcriptomics_mod else "Transcriptomics unavailable."
        )

    # RNA plots summary for LLM: volcano (top DEGs), top genes, signature bars (text version of UI plots)
    rna_plots_summary_str = ""
    transcriptomics_plots = None
    try:
        transcriptomics_plots = get_transcriptomics_plots(case_id, db=db)
        if transcriptomics_plots.available:
            parts = []
            if transcriptomics_plots.volcano and transcriptomics_plots.volcano.points:
                up = [p for p in transcriptomics_plots.volcano.points if p.direction == "up"][:5]
                down = [p for p in transcriptomics_plots.volcano.points if p.direction == "down"][:5]
                if up:
                    parts.append(
                        "Volcano upregulated: " + ", ".join(
                            f"{p.gene_symbol} log2FC={p.log2_fc_proxy:.2f} p={p.p_value_proxy:.2e}"
                            for p in up
                        )
                    )
                if down:
                    parts.append(
                        "Volcano downregulated: " + ", ".join(
                            f"{p.gene_symbol} log2FC={p.log2_fc_proxy:.2f} p={p.p_value_proxy:.2e}"
                            for p in down
                        )
                    )
            if transcriptomics_plots.top_genes_bar:
                parts.append(
                    "Top genes (normalized): " + ", ".join(
                        f"{g.symbol}={g.normalized_count:.1f}" for g in transcriptomics_plots.top_genes_bar[:10]
                    )
                )
            if transcriptomics_plots.signature_scores:
                scores_str = ", ".join(
                    f"{s.label}={s.value:.2f}" for s in transcriptomics_plots.signature_scores if s.available and s.value is not None
                )
                if scores_str:
                    parts.append(f"Signature scores: {scores_str}")
            if parts:
                rna_plots_summary_str = " RNA plots: " + "; ".join(parts) + "."
    except Exception:
        rna_plots_summary_str = ""

    survival_summary_str = ""
    if survival_resp.available and survival_resp.risk_group and survival_resp.baseline_months is not None:
        ci = survival_resp.confidence_interval
        ci_str = f"{ci[0]}-{ci[1]} mo" if ci else "N/A"
        survival_summary_str = (
            f"Risk group {survival_resp.risk_group}; baseline {survival_resp.baseline_months} mo (CI {ci_str})."
        )
    else:
        survival_summary_str = survival_resp.unavailable_reason or "Survival baseline unavailable."

    survival_mlp_resp = get_survival_mlp_prediction(case_id)
    if survival_mlp_resp.available and survival_mlp_resp.probability is not None:
        survival_mlp_summary_str = (
            f"Survival MLP (RNA+metadata, {survival_mlp_resp.horizon_years}yr): "
            f"P(survived)={survival_mlp_resp.probability:.2f}, predicted_class={survival_mlp_resp.predicted_class}."
        )
    else:
        survival_mlp_summary_str = survival_mlp_resp.unavailable_reason or "Survival MLP unavailable."

    active_score = (
        fusion_score.refined_score
        if fusion_score.mode_used == "refined"
        else fusion_score.provisional_score
    )
    top_mod = max(fusion_attribution.modalities, key=lambda m: m.contribution_percent)

    similar_entries: list[dict[str, str | float]] = []
    for neighbor in similar_cases_resp.neighbors:
        similar_entries.append({
            "case_id": neighbor.case_id,
            "similarity": neighbor.similarity,
            "score": neighbor.score,
            "delta_vs_index": neighbor.delta_vs_index,
            "rationale": neighbor.rationale,
        })

    context_for_llm = (
        f"Case: {case_id}. "
        f"Fusion score ({fusion_score.mode_used}): {active_score:.3f} "
        f"(provisional={fusion_score.provisional_score:.3f}, refined={fusion_score.refined_score:.3f}, "
        f"delta={fusion_score.delta_score:+.3f}). "
        f"Pathology: {pathology_summary}. "
        f"Clinical: {clinical_summary_str} "
        f"Transcriptomics: {transcriptomics_summary_str}{rna_plots_summary_str} "
        f"Survival: {survival_summary_str} "
        f"Survival MLP: {survival_mlp_summary_str} "
        f"Largest contribution: {top_mod.modality} ({top_mod.contribution_percent:.1f}%). "
    )
    if similar_entries:
        context_for_llm += "Similar cases: "
        context_for_llm += "; ".join(
            f"{e['case_id']} (similarity={e['similarity']:.2f}, {e['rationale']})"
            for e in similar_entries[:5]
        )
        context_for_llm += ". "
    context_for_llm += "Research-only proxy; not for clinical use."

    response = AgentContextResponse(
        case_id=case_id,
        context_for_llm=context_for_llm,
        fusion_score=active_score,
        fusion_mode_used=fusion_score.mode_used,
        pathology_summary=pathology_summary,
        clinical_summary=clinical_summary_str,
        transcriptomics_summary=transcriptomics_summary_str,
        survival_baseline_summary=survival_summary_str,
        similar_cases=similar_entries,
        meta=build_fusion_metadata("agent-context-v1"),
    )
    if include_raw:
        raw_context = {
            "fusion_score": fusion_score,
            "fusion_attribution": fusion_attribution,
            "tissue": tissue,
            "evidence": evidence,
            "cyt": cyt,
            "gep": gep,
            "tide": tide,
            "transcriptomic_evidence": transcriptomic_evidence,
            "transcriptomics_plots": transcriptomics_plots,
        }
        return (response, raw_context)
    return response
