from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from openai import OpenAI

from core.config import settings
from schemas.agent import AgentCitation

PUBMED_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


# ADDED: helper for human-readable percentages in repo-native summaries.
def _as_percent(value: float) -> str:
    return f"{value * 100:.0f}%"


# ADDED: helper so unavailable transcriptomic metrics render safely
def _metric_value(value: float | None, *, available: bool) -> str:
    if not available or value is None:
        return "NA"
    return f"{value:.3f}"


# CHANGED: this payload builder is now much richer and preserves the
# descriptive context that existed in the original hardcoded answer.
def _build_metric_payload(*, case_id: str, case_context: dict[str, Any]) -> dict[str, Any]:
    fusion_score = case_context["fusion_score"]
    fusion_attribution = case_context["fusion_attribution"]
    tissue = case_context["tissue"]
    evidence = case_context["evidence"]
    cyt = case_context["cyt"]
    gep = case_context["gep"]
    tide = case_context["tide"]
    transcriptomic_evidence = case_context["transcriptomic_evidence"]

    # ADDED: look up modality-specific details from fusion_score.modalities
    modality_by_name = {item.modality: item for item in fusion_score.modalities}
    pathology_modality = modality_by_name["pathology"]
    clinical_modality = modality_by_name["clinical"]
    transcriptomics_modality = modality_by_name["transcriptomics"]

    # ADDED: preserve dominant tissue narrative from the original answer style
    dominant_fractions = sorted(tissue.fractions, key=lambda item: item.fraction, reverse=True)
    dominant_summary = ", ".join(
        f"{fraction.tissue} ({_as_percent(fraction.fraction)})"
        for fraction in dominant_fractions[:2]
    ) if dominant_fractions else "no dominant tissue fractions"

    # ADDED: preserve top evidence tile narrative from the original answer style
    top_tile = max(evidence.top_tiles, key=lambda tile: tile.score) if evidence.top_tiles else None

    # ADDED: pathology sentence mirrors prior hardcoded descriptive answer
    if top_tile:
        pathology_sentence = (
            f"Pathology evidence shows {dominant_summary}; "
            f"top tile {top_tile.tile_id} scored {top_tile.score:.2f} ({top_tile.rationale})."
        )
    else:
        pathology_sentence = (
            f"Pathology evidence shows {dominant_summary} with no top evidence tile available."
        )

    # ADDED: clinical sentence mirrors prior hardcoded descriptive answer
    clinical_sentence = (
        f"Clinical minimum signal ({clinical_modality.data_source}) contributed "
        f"{clinical_modality.contribution_percent:.1f}%: {clinical_modality.summary}."
    )

    # ADDED: transcriptomics sentence mirrors prior hardcoded descriptive answer
    if transcriptomics_modality.available:
        transcriptomics_sentence = (
            "Transcriptomics signal was available and applied: "
            f"CYT={_metric_value(cyt.value, available=cyt.available)}, "
            f"GEP={_metric_value(gep.value, available=gep.available)}, "
            f"TIDE={_metric_value(tide.value, available=tide.available)}; "
            f"contribution={transcriptomics_modality.contribution_percent:.1f}% "
            f"({transcriptomics_modality.data_source})."
        )
    else:
        transcriptomics_sentence = (
            "Transcriptomics signal was unavailable, so fusion remained provisional: "
            f"{transcriptomics_modality.unavailable_reason or 'no RNA-derived features'}"
        )

    # ADDED: preserve largest-modality narrative from original answer
    top_modality = max(
        fusion_attribution.modalities,
        key=lambda modality: modality.contribution_percent,
    )

    # ADDED: explicit active score metric used by the current case mode
    active_score = (
        fusion_score.refined_score
        if fusion_score.mode_used == "refined"
        else fusion_score.provisional_score
    )

    # CHANGED: metrics now include an active fused score plus the original numerical signals
    metrics = [
        {
            "name": "fusion_active_score",
            "value": active_score,
            "definition": "Active multimodal research-only fused proxy score used for the current case summary",
            "range": "0-1",
            "direction": "higher = more favorable",
        },
        {
            "name": "fusion_provisional_score",
            "value": fusion_score.provisional_score,
            "definition": "Research-only multimodal provisional fused proxy score",
            "range": "0-1",
            "direction": "higher = more favorable",
        },
        {
            "name": "fusion_refined_score",
            "value": fusion_score.refined_score,
            "definition": "Research-only multimodal refined fused proxy score",
            "range": "0-1",
            "direction": "higher = more favorable",
        },
        {
            "name": "fusion_delta_score",
            "value": fusion_score.delta_score,
            "definition": "Difference between refined and provisional multimodal proxy score",
            "range": "continuous",
            "direction": "higher = transcriptomics increased the fused estimate",
        },
        {
            "name": "cyt_score",
            "value": cyt.value,
            "definition": "Cytolytic activity transcriptomic score",
            "range": "continuous",
            "direction": "higher = more inflamed",
        },
        {
            "name": "gep_score",
            "value": gep.value,
            "definition": "T-cell inflamed gene expression profile score",
            "range": "continuous",
            "direction": "higher = more inflamed",
        },
        {
            "name": "tide_score",
            "value": tide.value,
            "definition": "Tumor Immune Dysfunction and Exclusion score",
            "range": "continuous",
            "direction": "higher = more immune evasion",
        },
    ]

    # CHANGED: added repo_context so the LLM gets the same descriptive richness
    # as the original hardcoded backend answer, not just raw metrics
    return {
        "case_id": case_id,
        "metrics": metrics,
        "repo_context": {
            "fusion_mode": fusion_score.mode_used,
            "pathology_sentence": pathology_sentence,
            "clinical_sentence": clinical_sentence,
            "transcriptomics_sentence": transcriptomics_sentence,
            "largest_contribution_summary": (
                f"Largest active contribution came from {top_modality.modality} "
                f"({top_modality.contribution_percent:.1f}%)."
            ),
            "dominant_tissue_summary": dominant_summary,
            "top_tile": (
                {
                    "tile_id": top_tile.tile_id,
                    "score": top_tile.score,
                    "rationale": top_tile.rationale,
                }
                if top_tile else None
            ),
            "modalities": [
                {
                    "modality": item.modality,
                    "available": item.available,
                    "data_source": item.data_source,
                    "summary": item.summary,
                    "contribution_percent": item.contribution_percent,
                    "unavailable_reason": item.unavailable_reason,
                }
                for item in fusion_attribution.modalities
            ],
            "pathology_modality": {
                "available": pathology_modality.available,
                "data_source": pathology_modality.data_source,
                "summary": pathology_modality.summary,
                "contribution_percent": pathology_modality.contribution_percent,
            },
            "clinical_modality": {
                "available": clinical_modality.available,
                "data_source": clinical_modality.data_source,
                "summary": clinical_modality.summary,
                "contribution_percent": clinical_modality.contribution_percent,
            },
            "transcriptomics_modality": {
                "available": transcriptomics_modality.available,
                "data_source": transcriptomics_modality.data_source,
                "summary": transcriptomics_modality.summary,
                "contribution_percent": transcriptomics_modality.contribution_percent,
                "unavailable_reason": transcriptomics_modality.unavailable_reason,
            },
            # ADDED: lightweight transcriptomic evidence summary for future use
            "transcriptomic_evidence_summary": {
                "top_genes_count": len(transcriptomic_evidence.top_genes),
            },
        },
    }


def _build_repo_fallback_answer(agent_input: dict[str, Any]) -> str:
    """Deterministic no-network fallback that preserves repo-native answer style."""
    repo_context = agent_input.get("repo_context") or {}

    fusion_mode = repo_context.get("fusion_mode") or "unknown"
    pathology_sentence = repo_context.get("pathology_sentence") or "Pathology evidence unavailable."
    clinical_sentence = repo_context.get("clinical_sentence") or "Clinical evidence unavailable."
    transcriptomics_sentence = repo_context.get("transcriptomics_sentence") or "Transcriptomics evidence unavailable."
    contribution_sentence = (
        repo_context.get("largest_contribution_summary")
        or "Largest active contribution could not be determined."
    )

    return " ".join(
        [
            f"Fusion mode used: {fusion_mode}.",
            pathology_sentence,
            clinical_sentence,
            transcriptomics_sentence,
            contribution_sentence,
            "This is a research-only summary and not for clinical use.",
        ]
    )


def _search_pubmed(query: str, retmax: int = 6) -> list[str]:
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": retmax,
        "sort": "relevance",
    }
    with httpx.Client(timeout=20.0) as client:
        response = client.get(f"{PUBMED_EUTILS}/esearch.fcgi", params=params)
        response.raise_for_status()
        payload = response.json()
    return payload.get("esearchresult", {}).get("idlist", [])


def _fetch_pubmed_abstracts(pmids: list[str]) -> list[dict[str, Any]]:
    if not pmids:
        return []

    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{PUBMED_EUTILS}/efetch.fcgi", params=params)
        response.raise_for_status()
        xml_text = response.text

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    parsed_by_pmid: dict[str, dict[str, Any]] = {}
    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find(".//PMID")
        pmid_text = (
            pmid_el.text.strip()
            if pmid_el is not None and pmid_el.text and pmid_el.text.strip()
            else None
        )
        if pmid_text is None:
            continue

        title_el = article.find(".//ArticleTitle")
        title = (
            " ".join("".join(title_el.itertext()).split())
            if title_el is not None
            else ""
        )

        abstract_parts: list[str] = []
        for abstract_el in article.findall(".//AbstractText"):
            section_text = " ".join("".join(abstract_el.itertext()).split())
            if not section_text:
                continue
            label = (abstract_el.attrib.get("Label") or "").strip()
            if label:
                abstract_parts.append(f"{label}: {section_text}")
            else:
                abstract_parts.append(section_text)
        abstract = " ".join(abstract_parts).strip()

        snippet = " ".join(part for part in (title, abstract) if part).strip()
        if not snippet:
            continue

        parsed_by_pmid[pmid_text] = {
            "pmid": f"PMID:{pmid_text}",
            "snippet": snippet[:4000],
        }

    ordered: list[dict[str, Any]] = []
    for pmid in pmids:
        parsed = parsed_by_pmid.get(str(pmid).strip())
        if parsed is not None:
            ordered.append(parsed)
    return ordered


def _pubmed_source_from_value(value: str) -> str | None:
    token = (value or "").strip()
    if not token:
        return None
    match = re.search(r"\d+", token)
    if not match:
        return None
    pmid = match.group(0)
    return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"


def _safe_temp(requested: float) -> float:
    """GPT-5 family only supports temperature=1; other models honor the requested value."""
    model = settings.openai_model or ""
    if model.startswith("gpt-5"):
        return 1.0
    return requested


def _provider_available() -> bool:
    """True if an API key is available for the configured model."""
    import os as _os
    model = settings.openai_model or ""
    if model.startswith("gemini"):
        return bool(_os.environ.get("GEMINI_API_KEY"))
    return bool(settings.openai_api_key)


def _plan_pubmed_queries(client: OpenAI, *, question: str, agent_input: dict[str, Any]) -> list[str]:
    planner_system = """You write PubMed search queries.
Return JSON only.

Output:
{"queries": ["...", "...", "..."]}

Rules:
- Generate 2 to 4 queries.
- Use disease, endpoint, biomarker, mechanism, or therapy language when present.
- Do not use internal score names unless they are standard clinical terms.
"""

    planner_user = {
        "question": question,
        "agent_input": agent_input,
    }

    from services.llm_wrapper import chat as _llm_chat
    content = _llm_chat(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": planner_system},
            {"role": "user", "content": json.dumps(planner_user)},
        ],
        response_format={"type": "json_object"},
        temperature=_safe_temp(0.2),
    ) or "{}"
    parsed = json.loads(content)
    queries = parsed.get("queries", [])
    return [q for q in queries if isinstance(q, str) and q.strip()][:4]


def _extract_structured_evidence(client: OpenAI, *, question: str, abstracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not abstracts:
        return []

    extractor_system = """You are a biomedical evidence extraction engine.

Extract only explicit findings from the provided PubMed abstract snippets.

Return JSON only:
{
  "evidence": [
    {
      "pmid": string,
      "endpoint": string | null,
      "numeric_value": number | null,
      "value_text": string | null,
      "explicit_in_abstract": boolean,
      "summary": string
    }
  ]
}

Rules:
- Do not guess numbers.
- If the abstract does not explicitly contain the number, numeric_value must be null.
"""

    from services.llm_wrapper import chat as _llm_chat
    content = _llm_chat(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": extractor_system},
            {"role": "user", "content": json.dumps({"question": question, "abstracts": abstracts})},
        ],
        response_format={"type": "json_object"},
        temperature=_safe_temp(0.0),
    ) or "{}"
    parsed = json.loads(content)
    evidence = parsed.get("evidence", [])
    return evidence if isinstance(evidence, list) else []


def _need_pubmed(question: str) -> bool:
    text = (question or "").lower()
    keyword_pattern = re.compile(
        r"\b("
        r"literature|paper|papers|pubmed|study|studies|trial|trials|"
        r"guideline|guidelines|publication|publications"
        r")\b"
    )
    if keyword_pattern.search(text):
        return True

    # Keep evidence matching phrase-based so internal "what evidence was used?"
    # prompts do not accidentally trigger external literature retrieval.
    evidence_phrases = (
        "published evidence",
        "literature evidence",
        "external evidence",
        "evidence from studies",
        "evidence from the literature",
        "evidence from pubmed",
    )
    return any(phrase in text for phrase in evidence_phrases)


def run_llm_agent(
    *,
    case_id: str,
    question: str,
    case_context: dict[str, Any],
    context_for_llm: str | None = None,
) -> tuple[str, list[AgentCitation]]:
    agent_input = _build_metric_payload(case_id=case_id, case_context=case_context)

    if not _provider_available():
        return _build_repo_fallback_answer(agent_input), []

    # `client` is only needed for the OpenAI path. For Gemini we route through
    # the wrapper and skip OpenAI SDK usage entirely.
    client = None
    model = settings.openai_model or ""
    if not model.startswith("gemini"):
        try:
            from openai import OpenAI  # Imported lazily so API tests can run without optional SDK.
        except ModuleNotFoundError:
            return _build_repo_fallback_answer(agent_input), []
        client = OpenAI(api_key=settings.openai_api_key)

    try:

        structured_evidence: list[dict[str, Any]] = []
        pubmed_citations: list[AgentCitation] = []
        abstracts: list[dict[str, Any]] = []

        # Run PubMed RAG only when the user asks a literature-focused question.
        if _need_pubmed(question):
            queries = _plan_pubmed_queries(client, question=question, agent_input=agent_input)
            used_query = None
            pmids: list[str] = []
            for q in queries:
                pmids = _search_pubmed(q)
                if pmids:
                    used_query = q
                    break

            abstracts = _fetch_pubmed_abstracts(pmids)
            structured_evidence = _extract_structured_evidence(client, question=question, abstracts=abstracts)

            if used_query:
                pubmed_citations.append(
                    AgentCitation(
                        panel="literature",
                        field="pubmed_query",
                        source="pubmed://search",
                        value=used_query,
                    )
                )

            for item in structured_evidence:
                pmid = item.get("pmid")
                summary = item.get("summary")
                if isinstance(pmid, str):
                    source = _pubmed_source_from_value(pmid) or pmid
                    pubmed_citations.append(
                        AgentCitation(
                            panel="literature",
                            field="pubmed_evidence",
                            source=source,
                            value=summary if isinstance(summary, str) else None,
                        )
                    )

            # Add a no-relevant sentinel only when abstracts were actually fetched.
            if abstracts and not structured_evidence:
                pubmed_citations.append(
                    AgentCitation(
                        panel="literature",
                        field="pubmed_evidence",
                        source="pubmed://none",
                        value="No relevant literature found for this question.",
                    )
                )

    except Exception:
        # Keep the endpoint available even when upstream LLM/literature calls fail.
        return _build_repo_fallback_answer(agent_input), []

    # CHANGED: prompt now explicitly tells the model to use repo-native summaries
    reasoner_system = """You are a grounded biomedical reasoning assistant.

You receive:
- structured patient/case metrics
- repo-native multimodal context summaries
- optional structured literature evidence

Rules:
- Preserve and use the repo-native context summaries when answering.
- Do not invent what a metric means.
- If literature evidence does not contain explicit numeric baselines, say quantitative comparison is not possible from abstract-level evidence.
- Prefer repo-native case evidence over generic phrasing.
- Keep the answer concise but information-dense.
- Research-use only.
"""

    # CHANGED: pass metrics and repo_context separately so the LLM sees
    # the descriptive context clearly instead of having to infer it from one blob
    reasoner_user = {
        "question": question,
        "metrics": agent_input["metrics"],
        "repo_context": agent_input["repo_context"],
        "structured_evidence": structured_evidence,
        "context_for_llm": context_for_llm,
    }

    try:
        from services.llm_wrapper import chat as _llm_chat
        answer = _llm_chat(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": reasoner_system},
                {"role": "user", "content": json.dumps(reasoner_user)},
            ],
            temperature=_safe_temp(0.2),
        ) or "No answer generated."
        return answer, pubmed_citations
    except Exception:
        return _build_repo_fallback_answer(agent_input), pubmed_citations
