from __future__ import annotations

import json
import textwrap
from pathlib import Path


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stub", encoding="utf-8")


def test_list_cohort_cases_returns_embedding_slide_overlap(client, monkeypatch, tmp_path: Path) -> None:
    embeddings_dir = tmp_path / "embeddings" / "level0"
    slides_dir = tmp_path / "slides" / "full475"
    transcriptomics_dir = tmp_path / "transcriptomics" / "artifacts"
    clinical_dir = tmp_path / "clinical" / "artifacts"

    _touch(embeddings_dir / "TCGA-05-4244-01Z-00-DX1.embedding.npy")
    _touch(embeddings_dir / "TCGA-49-4488-01Z-00-DX1.embedding.npy")
    _touch(embeddings_dir / "TCGA-44-A47F-01Z-00-DX1.embedding.npy")
    _touch(embeddings_dir / "TCGA-05-4244-01Z-00-DX1.coords.npy")

    _touch(slides_dir / "uuid-a" / "TCGA-05-4244-01Z-00-DX1.abc.svs")
    _touch(slides_dir / "uuid-b" / "TCGA-49-4488-01Z-00-DX1.def.svs")
    _touch(slides_dir / "uuid-c" / "TCGA-55-1234-01Z-00-DX1.xyz.svs")

    _touch(transcriptomics_dir / "TCGA-05-4244-rna.json")
    _touch(clinical_dir / "TCGA-05-4244-clinical.json")

    monkeypatch.setenv("ENSO_EMBEDDINGS_DIR", str(embeddings_dir))
    monkeypatch.setenv("PATHOLOGY_WSI_DIR", str(slides_dir))
    monkeypatch.setenv("TRANSCRIPTOMICS_ARTIFACT_DIR", str(transcriptomics_dir))
    monkeypatch.setenv("CLINICAL_ARTIFACT_DIR", str(clinical_dir))

    response = client.get("/v1/cohort/cases")
    assert response.status_code == 200

    payload = response.json()
    assert [entry["case_id"] for entry in payload] == ["TCGA-05-4244", "TCGA-49-4488"]
    assert all(entry["has_pathology"] for entry in payload)
    by_case = {entry["case_id"]: entry for entry in payload}
    assert by_case["TCGA-05-4244"]["has_transcriptomics"] is True
    assert by_case["TCGA-05-4244"]["has_clinical"] is True
    assert by_case["TCGA-49-4488"]["has_transcriptomics"] is False
    assert by_case["TCGA-49-4488"]["has_clinical"] is False


def test_list_cohort_cases_falls_back_to_pathology_artifacts(client, monkeypatch, tmp_path: Path) -> None:
    artifact_dir = tmp_path / "pathology_artifacts"
    _touch(artifact_dir / "TCGA-05-4244-DX1.json")
    _touch(artifact_dir / "TCGA-49-4488-DX1.json")
    _touch(artifact_dir / "notes.json")

    monkeypatch.delenv("ENSO_EMBEDDINGS_DIR", raising=False)
    monkeypatch.delenv("PATHOLOGY_WSI_DIR", raising=False)
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(artifact_dir))

    response = client.get("/v1/cohort/cases")
    assert response.status_code == 200

    payload = response.json()
    assert [entry["case_id"] for entry in payload] == ["TCGA-05-4244", "TCGA-49-4488"]
    assert all(entry["has_pathology"] for entry in payload)
    assert all(not entry["has_transcriptomics"] for entry in payload)
    assert all(not entry["has_clinical"] for entry in payload)


def test_list_cohort_cases_enriches_stage_and_smoking_from_clinical_artifact(
    client,
    monkeypatch,
    tmp_path: Path,
) -> None:
    pathology_artifact_dir = tmp_path / "pathology_artifacts"
    clinical_artifact_dir = tmp_path / "clinical" / "artifacts"

    _touch(pathology_artifact_dir / "TCGA-05-4244-DX1.json")

    clinical_artifact_dir.mkdir(parents=True, exist_ok=True)
    (clinical_artifact_dir / "TCGA-05-4244-clinical.json").write_text(
        json.dumps({"patient_summary": {"stage": "stage iiib", "smoking_status": "former smoker"}}),
        encoding="utf-8",
    )

    monkeypatch.delenv("ENSO_EMBEDDINGS_DIR", raising=False)
    monkeypatch.delenv("PATHOLOGY_WSI_DIR", raising=False)
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(pathology_artifact_dir))
    monkeypatch.setenv("CLINICAL_ARTIFACT_DIR", str(clinical_artifact_dir))

    response = client.get("/v1/cohort/cases")
    assert response.status_code == 200

    payload = response.json()
    assert [entry["case_id"] for entry in payload] == ["TCGA-05-4244"]
    assert payload[0]["stage"] == "Stage IIIB"
    assert payload[0]["smoking_status"] == "Former smoker"


def test_list_cohort_cases_falls_back_to_xml_stage_when_artifact_stage_missing(
    client,
    monkeypatch,
    tmp_path: Path,
) -> None:
    pathology_artifact_dir = tmp_path / "pathology_artifacts"
    clinical_artifact_dir = tmp_path / "clinical" / "artifacts"
    clinical_xml_dir = tmp_path / "clinical" / "xml"

    _touch(pathology_artifact_dir / "TCGA-05-4244-DX1.json")

    clinical_artifact_dir.mkdir(parents=True, exist_ok=True)
    (clinical_artifact_dir / "TCGA-05-4244-clinical.json").write_text(
        json.dumps({"patient_summary": {"stage": None, "smoking_status": "current smoker"}}),
        encoding="utf-8",
    )

    clinical_xml_dir.mkdir(parents=True, exist_ok=True)
    (clinical_xml_dir / "nationwidechildrens.org_clinical.TCGA-05-4244.xml").write_text(
        textwrap.dedent(
            """
            <clinical_patient>
              <pathologic_stage>stage iib</pathologic_stage>
              <clinical_stage>stage iia</clinical_stage>
            </clinical_patient>
            """
        ).strip(),
        encoding="utf-8",
    )

    monkeypatch.delenv("ENSO_EMBEDDINGS_DIR", raising=False)
    monkeypatch.delenv("PATHOLOGY_WSI_DIR", raising=False)
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(pathology_artifact_dir))
    monkeypatch.setenv("CLINICAL_ARTIFACT_DIR", str(clinical_artifact_dir))
    monkeypatch.setenv("CLINICAL_XML_DIR", str(clinical_xml_dir))

    response = client.get("/v1/cohort/cases")
    assert response.status_code == 200

    payload = response.json()
    assert [entry["case_id"] for entry in payload] == ["TCGA-05-4244"]
    assert payload[0]["stage"] == "Stage IIB"
    assert payload[0]["smoking_status"] == "Current smoker"


def test_list_cohort_cases_returns_empty_when_paths_missing(client, monkeypatch) -> None:
    monkeypatch.delenv("ENSO_EMBEDDINGS_DIR", raising=False)
    monkeypatch.delenv("PATHOLOGY_WSI_DIR", raising=False)
    monkeypatch.delenv("PATHOLOGY_ARTIFACT_DIR", raising=False)

    response = client.get("/v1/cohort/cases")
    assert response.status_code == 200
    assert response.json() == []
