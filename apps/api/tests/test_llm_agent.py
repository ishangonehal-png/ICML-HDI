from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import services.llm_agent as llm_agent


def _build_case_context() -> dict:
    fusion_modalities = [
        SimpleNamespace(
            modality="pathology",
            available=True,
            data_source="artifact",
            summary="Pathology signal available",
            contribution_percent=45.0,
            unavailable_reason=None,
        ),
        SimpleNamespace(
            modality="clinical",
            available=True,
            data_source="clinical_xml",
            summary="Clinical signal available",
            contribution_percent=35.0,
            unavailable_reason=None,
        ),
        SimpleNamespace(
            modality="transcriptomics",
            available=True,
            data_source="counts_tsv",
            summary="Transcriptomics signal available",
            contribution_percent=20.0,
            unavailable_reason=None,
        ),
    ]

    return {
        "fusion_score": SimpleNamespace(
            modalities=fusion_modalities,
            mode_used="refined",
            provisional_score=0.41,
            refined_score=0.58,
            delta_score=0.17,
        ),
        "fusion_attribution": SimpleNamespace(modalities=fusion_modalities),
        "tissue": SimpleNamespace(
            fractions=[
                SimpleNamespace(tissue="Tumor", fraction=0.62),
                SimpleNamespace(tissue="Stroma", fraction=0.25),
            ]
        ),
        "evidence": SimpleNamespace(
            top_tiles=[
                SimpleNamespace(
                    tile_id="tile_001",
                    score=0.88,
                    rationale="Immune-rich tumor interface",
                )
            ]
        ),
        "cyt": SimpleNamespace(value=0.63, available=True),
        "gep": SimpleNamespace(value=0.52, available=True),
        "tide": SimpleNamespace(value=0.47, available=True),
        "transcriptomic_evidence": SimpleNamespace(top_genes=["GZMA", "PRF1"]),
    }


def _install_fake_openai(monkeypatch, *, answer: str = "stub reasoned answer") -> None:
    class _FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=answer))]
            )

    class _FakeClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=_FakeCompletions())

    fake_module = types.SimpleNamespace(OpenAI=lambda api_key: _FakeClient())
    monkeypatch.setitem(sys.modules, "openai", fake_module)
    monkeypatch.setattr(
        llm_agent,
        "settings",
        SimpleNamespace(openai_api_key="test-key", openai_model="test-model"),
    )


def test_need_pubmed_requires_explicit_literature_intent() -> None:
    assert llm_agent._need_pubmed("What does literature say about expected outcomes?") is True
    assert llm_agent._need_pubmed("Summarize multimodal findings for this case.") is False
    assert llm_agent._need_pubmed("What pathology evidence was used in this summary?") is False
    assert llm_agent._need_pubmed("Please review the paperwork for this case.") is False


def test_fetch_pubmed_abstracts_parses_per_article_snippets_in_requested_order(monkeypatch) -> None:
    xml_payload = """
    <PubmedArticleSet>
      <PubmedArticle>
        <MedlineCitation>
          <PMID>111</PMID>
          <Article>
            <ArticleTitle>First title</ArticleTitle>
            <Abstract>
              <AbstractText Label="BACKGROUND">First abstract</AbstractText>
            </Abstract>
          </Article>
        </MedlineCitation>
      </PubmedArticle>
      <PubmedArticle>
        <MedlineCitation>
          <PMID>222</PMID>
          <Article>
            <ArticleTitle>Second title</ArticleTitle>
            <Abstract>
              <AbstractText>Second abstract</AbstractText>
            </Abstract>
          </Article>
        </MedlineCitation>
      </PubmedArticle>
    </PubmedArticleSet>
    """.strip()

    class _FakeResponse:
        text = xml_payload

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def get(self, *args, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr(llm_agent.httpx, "Client", _FakeClient)

    abstracts = llm_agent._fetch_pubmed_abstracts(["222", "111"])

    assert abstracts == [
        {
            "pmid": "PMID:222",
            "snippet": "Second title Second abstract",
        },
        {
            "pmid": "PMID:111",
            "snippet": "First title BACKGROUND: First abstract",
        },
    ]


def test_run_llm_agent_skips_pubmed_for_non_literature_questions(monkeypatch) -> None:
    _install_fake_openai(monkeypatch)

    def _planner_should_not_run(*args, **kwargs):
        raise AssertionError("PubMed planner should not run for non-literature prompt")

    monkeypatch.setattr(llm_agent, "_plan_pubmed_queries", _planner_should_not_run)

    answer, citations = llm_agent.run_llm_agent(
        case_id="TCGA-05-4244",
        question="Summarize multimodal findings for this case.",
        case_context=_build_case_context(),
    )

    assert answer == "stub reasoned answer"
    assert all(citation.panel != "literature" for citation in citations)


def test_run_llm_agent_does_not_emit_false_no_relevant_on_empty_abstract_fetch(monkeypatch) -> None:
    _install_fake_openai(monkeypatch)

    monkeypatch.setattr(llm_agent, "_plan_pubmed_queries", lambda *args, **kwargs: ["lung adc io trial"])
    monkeypatch.setattr(llm_agent, "_search_pubmed", lambda *args, **kwargs: ["12345"])
    monkeypatch.setattr(llm_agent, "_fetch_pubmed_abstracts", lambda *args, **kwargs: [])
    monkeypatch.setattr(llm_agent, "_extract_structured_evidence", lambda *args, **kwargs: [])

    answer, citations = llm_agent.run_llm_agent(
        case_id="TCGA-05-4244",
        question="What does literature say about expected outcomes?",
        case_context=_build_case_context(),
    )

    assert answer == "stub reasoned answer"
    assert any(c.field == "pubmed_query" for c in citations)
    assert not any(
        c.field == "pubmed_evidence" and c.value == "No relevant literature found for this question."
        for c in citations
    )


def test_run_llm_agent_emits_no_relevant_only_when_abstracts_were_checked(monkeypatch) -> None:
    _install_fake_openai(monkeypatch)

    monkeypatch.setattr(llm_agent, "_plan_pubmed_queries", lambda *args, **kwargs: ["lung adc io trial"])
    monkeypatch.setattr(llm_agent, "_search_pubmed", lambda *args, **kwargs: ["12345"])
    monkeypatch.setattr(
        llm_agent,
        "_fetch_pubmed_abstracts",
        lambda *args, **kwargs: [{"pmid": "PMID:12345", "title": "x", "abstract": "y"}],
    )
    monkeypatch.setattr(llm_agent, "_extract_structured_evidence", lambda *args, **kwargs: [])

    answer, citations = llm_agent.run_llm_agent(
        case_id="TCGA-05-4244",
        question="What does literature say about expected outcomes?",
        case_context=_build_case_context(),
    )

    assert answer == "stub reasoned answer"
    assert any(
        c.field == "pubmed_evidence" and c.value == "No relevant literature found for this question."
        for c in citations
    )


def test_run_llm_agent_uses_pubmed_urls_for_evidence_citations(monkeypatch) -> None:
    _install_fake_openai(monkeypatch)

    monkeypatch.setattr(llm_agent, "_plan_pubmed_queries", lambda *args, **kwargs: ["lung adc io trial"])
    monkeypatch.setattr(llm_agent, "_search_pubmed", lambda *args, **kwargs: ["12345"])
    monkeypatch.setattr(
        llm_agent,
        "_fetch_pubmed_abstracts",
        lambda *args, **kwargs: [{"pmid": "PMID:12345", "snippet": "abstract snippet"}],
    )
    monkeypatch.setattr(
        llm_agent,
        "_extract_structured_evidence",
        lambda *args, **kwargs: [{"pmid": "PMID:12345", "summary": "Matched survival evidence"}],
    )

    answer, citations = llm_agent.run_llm_agent(
        case_id="TCGA-05-4244",
        question="What does literature say about expected outcomes?",
        case_context=_build_case_context(),
    )

    assert answer == "stub reasoned answer"
    assert any(
        c.field == "pubmed_evidence"
        and c.source == "https://pubmed.ncbi.nlm.nih.gov/12345/"
        and c.value == "Matched survival evidence"
        for c in citations
    )
