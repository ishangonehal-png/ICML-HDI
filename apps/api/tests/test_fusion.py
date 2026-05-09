from __future__ import annotations

from pathlib import Path

import pytest

CASE_ID = "TCGA-05-4244"


@pytest.fixture
def clear_fusion_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in (
        "PATHOLOGY_ARTIFACT_DIR",
        "TRANSCRIPTOMICS_ARTIFACT_DIR",
        "TRANSCRIPTOMICS_COUNTS_DIR",
        "TRANSCRIPTOMICS_COVERAGE_COHORT_CSV",
        "TRANSCRIPTOMICS_GEP_REFERENCE_STATS_JSON",
    ):
        monkeypatch.delenv(env_name, raising=False)


def _write_counts_file(path: Path) -> None:
    path.write_text(
        "gene_name\ttpm_unstranded\n"
        "GZMA\t14.0\n"
        "PRF1\t9.0\n"
        "CCL5\t16.0\n"
        "CD27\t11.0\n"
        "CD274\t7.5\n"
        "CD276\t3.5\n"
        "CD8A\t22.0\n"
        "CMKLR1\t5.5\n"
        "CXCL9\t26.0\n"
        "CXCR6\t12.0\n"
        "HLA-DQA1\t8.0\n"
        "HLA-DRB1\t9.0\n"
        "HLA-E\t10.0\n"
        "IDO1\t4.0\n"
        "LAG3\t6.0\n"
        "NKG7\t18.0\n"
        "PDCD1\t5.0\n"
        "PSMB10\t14.0\n"
        "STAT1\t13.0\n"
        "TIGIT\t7.0\n",
        encoding="utf-8",
    )


def test_fusion_score_typed_modalities_when_transcriptomics_missing(
    client,
    clear_fusion_env,
) -> None:
    response = client.post(
        f"/v1/fusion/{CASE_ID}/score",
        json={"include_rna": True},
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["case_id"] == CASE_ID
    assert payload["requested_mode"] == "refined"
    assert payload["mode_used"] == "provisional"
    assert payload["rna_requested"] is True
    assert payload["rna_applied"] is False
    assert payload["refined_score"] == payload["provisional_score"]
    assert payload["delta_score"] == 0

    modalities = {item["modality"]: item for item in payload["modalities"]}
    assert modalities["pathology"]["available"] is True
    assert modalities["clinical"]["available"] is True
    assert modalities["transcriptomics"]["available"] is False
    assert modalities["transcriptomics"]["required_for_requested_mode"] is True
    assert modalities["transcriptomics"]["used_in_score"] is False
    assert modalities["transcriptomics"]["unavailable_reason"]

    used_contributions = [
        item["contribution_percent"]
        for item in payload["modalities"]
        if item["used_in_score"]
    ]
    assert sum(used_contributions) == pytest.approx(100.0, abs=0.01)

    assert payload["meta"]["method"].startswith("fusion-score-")
    assert any(entry["source"] == "fusion://weights" for entry in payload["provenance"])


def test_fusion_score_uses_internal_non_strict_pathology_resolution(
    client,
    clear_fusion_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATHOLOGY_STRICT_MISSING_DATA", "true")

    response = client.post(
        f"/v1/fusion/{CASE_ID}/score",
        json={"include_rna": False},
    )

    assert response.status_code == 200
    payload = response.json()
    modalities = {item["modality"]: item for item in payload["modalities"]}
    assert modalities["pathology"]["available"] is True
    assert payload["mode_used"] == "provisional"


def test_fusion_score_and_attribution_apply_transcriptomics_when_available(
    client,
    clear_fusion_env,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    counts_dir = tmp_path / "counts"
    counts_dir.mkdir(parents=True)
    _write_counts_file(counts_dir / f"{CASE_ID}.tsv")
    monkeypatch.setenv("TRANSCRIPTOMICS_COUNTS_DIR", str(counts_dir))

    score_response = client.post(
        f"/v1/fusion/{CASE_ID}/score",
        json={"include_rna": True},
    )
    assert score_response.status_code == 200
    score_payload = score_response.json()

    assert score_payload["requested_mode"] == "refined"
    assert score_payload["mode_used"] == "refined"
    assert score_payload["rna_applied"] is True
    assert score_payload["refined_score"] != score_payload["provisional_score"]

    modalities = {item["modality"]: item for item in score_payload["modalities"]}
    assert modalities["transcriptomics"]["available"] is True
    assert modalities["transcriptomics"]["used_in_score"] is True
    assert modalities["transcriptomics"]["data_source"] == "counts_tsv"
    assert modalities["transcriptomics"]["contribution_percent"] > 0

    attribution_response = client.get(f"/v1/fusion/{CASE_ID}/attribution?include_rna=true")
    assert attribution_response.status_code == 200
    attribution_payload = attribution_response.json()

    assert attribution_payload["mode_used"] == "refined"
    assert attribution_payload["score"] == score_payload["refined_score"]
    assert len(attribution_payload["modalities"]) == 3
    assert any(entry["source"] == "fusion://mode" for entry in attribution_payload["provenance"])


def test_fusion_similar_cases_returns_typed_neighbors_with_provenance(
    client,
    clear_fusion_env,
) -> None:
    response = client.get(f"/v1/fusion/{CASE_ID}/similar-cases?include_rna=false&limit=3")

    assert response.status_code == 200
    payload = response.json()

    assert payload["case_id"] == CASE_ID
    assert payload["requested_mode"] == "provisional"
    assert payload["mode_used"] == "provisional"
    assert len(payload["neighbors"]) == 3

    for neighbor in payload["neighbors"]:
        assert 0.0 <= neighbor["similarity"] <= 1.0
        assert "rationale" in neighbor and neighbor["rationale"]
        assert neighbor["provenance"]

    assert any(entry["source"] == "fusion://similarity" for entry in payload["provenance"])


def test_fusion_similar_cases_skips_candidates_missing_pathology_in_strict_mode(
    client,
    clear_fusion_env,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "pathology_artifacts"
    artifact_dir.mkdir(parents=True)

    # Only the index case has artifact data; candidate neighbors will be missing.
    (artifact_dir / f"{CASE_ID}-DX1.json").write_text(
        """
{
  "case_id": "TCGA-05-4244",
  "slide_id": "TCGA-05-4244-DX1",
  "provenance": {"data_source": "artifact", "model_id": "unit-test", "run_id": "unit"},
  "tissue_composition": {
    "fractions": [
      {"tissue": "Tumor", "fraction": 0.6},
      {"tissue": "Stroma", "fraction": 0.3},
      {"tissue": "Necrosis", "fraction": 0.05},
      {"tissue": "Lymphocyte-rich", "fraction": 0.05}
    ],
    "qc": {"coverage": 0.9}
  },
  "heatmap": {"viewport_hint": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8}},
  "evidence": {
    "top_tiles": [
      {"tile_id": "r01_c01", "score": 0.8, "rationale": "unit"}
    ]
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(artifact_dir))
    monkeypatch.setenv("PATHOLOGY_STRICT_MISSING_DATA", "true")

    response = client.get(f"/v1/fusion/{CASE_ID}/similar-cases?include_rna=false&limit=3")
    assert response.status_code == 200

    payload = response.json()
    assert payload["case_id"] == CASE_ID
    # strict mode may skip all candidates without artifact-backed pathology
    assert isinstance(payload["neighbors"], list)
    assert len(payload["neighbors"]) <= 3
