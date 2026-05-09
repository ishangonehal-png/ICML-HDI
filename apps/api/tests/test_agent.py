from __future__ import annotations

import json


def test_agent_query_returns_multimodal_grounded_payload_without_transcriptomics(client) -> None:
    case_id = "TCGA-05-4244"
    response = client.post(
        "/v1/agent/query",
        json={
            "case_id": case_id,
            "question": "Summarize multimodal evidence for this case.",
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert set(payload) == {
        "case_id",
        "answer",
        "citations",
        "modalities",
        "acknowledged_missing_modalities",
        "meta",
    }
    assert payload["case_id"] == case_id
    assert isinstance(payload["answer"], str)
    assert payload["answer"].strip() != ""

    modalities = {item["modality"]: item for item in payload["modalities"]}
    assert modalities["pathology"]["available"] is True
    assert modalities["clinical"]["available"] is True
    assert modalities["fusion"]["available"] is True
    assert modalities["transcriptomics"]["available"] is False

    citation_panels = {citation["panel"] for citation in payload["citations"]}
    assert {"pathology", "transcriptomics", "clinical", "fusion"}.issubset(citation_panels)

    assert payload["acknowledged_missing_modalities"] == ["transcriptomics"]

    assert payload["meta"] == {
        "method": "agent-grounded-multimodal-v1",
        "version": "hackathon-p0",
        "timestamp": "2026-03-06T00:00:00Z",
        "proxy_estimate": True,
    }


def test_agent_query_uses_transcriptomics_when_available(
    monkeypatch,
    tmp_path,
    client,
) -> None:
    case_id = "TCGA-RNA-0001"

    counts_dir = tmp_path / "counts"
    counts_dir.mkdir(parents=True)
    (counts_dir / f"{case_id}.tsv").write_text(
        "gene_name\ttpm_unstranded\n"
        "GZMA\t12.0\n"
        "PRF1\t8.0\n"
        "CCL5\t15.0\n"
        "CD27\t9.0\n"
        "CD274\t7.0\n"
        "CD276\t3.0\n"
        "CD8A\t18.0\n"
        "CMKLR1\t4.0\n"
        "CXCL9\t22.0\n"
        "CXCR6\t10.0\n"
        "HLA-DQA1\t7.0\n"
        "HLA-DRB1\t8.0\n"
        "HLA-E\t9.0\n"
        "IDO1\t3.5\n"
        "LAG3\t5.0\n"
        "NKG7\t13.0\n"
        "PDCD1\t4.0\n"
        "PSMB10\t11.0\n"
        "STAT1\t10.0\n"
        "TIGIT\t6.0\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("TRANSCRIPTOMICS_COUNTS_DIR", str(counts_dir))

    response = client.post(
        "/v1/agent/query",
        json={
            "case_id": case_id,
            "question": "Did RNA evidence change the score?",
        },
    )

    assert response.status_code == 200
    payload = response.json()

    modalities = {item["modality"]: item for item in payload["modalities"]}
    assert modalities["transcriptomics"]["available"] is True
    assert payload["acknowledged_missing_modalities"] == []

    assert isinstance(payload["answer"], str)
    assert payload["answer"].strip() != ""
    assert any(
        citation["panel"] == "transcriptomics" and citation["field"] == "cyt"
        for citation in payload["citations"]
    )
    assert any(
        citation["panel"] == "fusion" and citation["field"] == "score"
        for citation in payload["citations"]
    )


def test_agent_query_uses_internal_non_strict_pathology_resolution(
    monkeypatch,
    client,
) -> None:
    case_id = "TCGA-05-4244"
    monkeypatch.delenv("PATHOLOGY_ARTIFACT_DIR", raising=False)
    monkeypatch.setenv("PATHOLOGY_STRICT_MISSING_DATA", "true")

    response = client.post(
        "/v1/agent/query",
        json={
            "case_id": case_id,
            "question": "Summarize evidence with strict pathology mode enabled.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    modalities = {item["modality"]: item for item in payload["modalities"]}
    assert modalities["pathology"]["available"] is True
    assert isinstance(payload["answer"], str)
    assert payload["answer"].strip() != ""


def test_agent_query_uses_artifact_backed_pathology_evidence_in_answer(
    monkeypatch,
    tmp_path,
    client,
) -> None:
    case_id = "TCGA-ART-0001"
    artifact_payload = {
        "evidence": {
            "top_tiles": [
                {
                    "tile_id": "tile_999",
                    "score": 0.97,
                    "rationale": "Artifact-derived immune-rich hotspot",
                }
            ]
        }
    }
    (tmp_path / f"{case_id}.json").write_text(json.dumps(artifact_payload), encoding="utf-8")
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(tmp_path))

    response = client.post(
        "/v1/agent/query",
        json={
            "case_id": case_id,
            "question": "What pathology evidence was used?",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["answer"], str)
    assert payload["answer"].strip() != ""
    assert any(
        citation["panel"] == "pathology"
        and citation["field"] == "top_tiles"
        and (citation.get("value") or "").startswith("tile_999")
        for citation in payload["citations"]
    )
