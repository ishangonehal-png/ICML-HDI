from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from models import AnalysisJob, ModalityResult
from services.transcriptomics import get_transcriptomics_coverage_report

CASE_ID = "TCGA-05-4244"
CASE_ID_B = "TCGA-44-5555"

GEP_GENE_VALUES: dict[str, float] = {
    "CCL5": 16.0,
    "CD27": 11.0,
    "CD274": 7.5,
    "CD276": 3.5,
    "CD8A": 22.0,
    "CMKLR1": 5.5,
    "CXCL9": 26.0,
    "CXCR6": 12.0,
    "HLA-DQA1": 8.0,
    "HLA-DRB1": 9.0,
    "HLA-E": 10.0,
    "IDO1": 4.0,
    "LAG3": 6.0,
    "NKG7": 18.0,
    "PDCD1": 5.0,
    "PSMB10": 14.0,
    "STAT1": 13.0,
    "TIGIT": 7.0,
}


@pytest.fixture
def clear_transcriptomics_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in (
        "TRANSCRIPTOMICS_ARTIFACT_DIR",
        "TRANSCRIPTOMICS_COUNTS_DIR",
        "TRANSCRIPTOMICS_COVERAGE_COHORT_CSV",
        "TRANSCRIPTOMICS_GEP_REFERENCE_STATS_JSON",
        "TRANSCRIPTOMICS_GEP_REFERENCE_REQUIRED",
        "TRANSCRIPTOMICS_GEP_REFERENCE_ID",
    ):
        monkeypatch.delenv(env_name, raising=False)


def _write_counts_file(path: Path, *, include_cyt_genes: bool = True) -> None:
    rows = ["gene_name\ttpm_unstranded"]

    if include_cyt_genes:
        rows.extend(
            [
                "GZMA\t14.0",
                "PRF1\t9.0",
            ]
        )

    for gene, value in GEP_GENE_VALUES.items():
        rows.append(f"{gene}\t{value}")

    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_counts_file_with_pipe_delimited_gene_ids(path: Path) -> None:
    rows = ["gene_id\ttpm_unstranded"]

    gene_rows = [
        ("GZMA", 14.0),
        ("PRF1", 9.0),
        *list(GEP_GENE_VALUES.items()),
    ]

    for idx, (gene, value) in enumerate(gene_rows, start=1):
        rows.append(f"ENSG{idx:011d}|{gene}\t{value}")

    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_counts_file_missing_required_value_column(path: Path) -> None:
    rows = [
        "gene_name\tunexpected_value",
        "GZMA\t14.0",
        "PRF1\t9.0",
        "CXCL9\t26.0",
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _expected_cyt() -> float:
    return round(math.log2(math.sqrt((14.0 + 1e-6) * (9.0 + 1e-6))), 6)


def _expected_gep() -> float:
    transformed: list[float] = []
    for gene, tpm in GEP_GENE_VALUES.items():
        value = math.log2(tpm + 1.0)
        if gene == "CD276":
            value = -value
        transformed.append(value)
    return round(sum(transformed) / len(transformed), 6)


def test_transcriptomics_metrics_and_evidence_from_counts(
    client,
    clear_transcriptomics_env,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    counts_dir = tmp_path / "counts"
    counts_dir.mkdir(parents=True)
    _write_counts_file(counts_dir / f"{CASE_ID}.tsv")

    monkeypatch.setenv("TRANSCRIPTOMICS_COUNTS_DIR", str(counts_dir))

    cyt_response = client.get(f"/v1/transcriptomics/{CASE_ID}/cyt")
    assert cyt_response.status_code == 200
    cyt_payload = cyt_response.json()
    assert cyt_payload["available"] is True
    assert cyt_payload["availability_code"] == "available"
    assert cyt_payload["data_source"] == "counts_tsv"
    assert cyt_payload["value"] == pytest.approx(_expected_cyt(), abs=1e-6)

    gep_response = client.get(f"/v1/transcriptomics/{CASE_ID}/gep")
    assert gep_response.status_code == 200
    gep_payload = gep_response.json()
    assert gep_payload["available"] is True
    assert gep_payload["availability_code"] == "available"
    assert gep_payload["data_source"] == "counts_tsv"
    assert gep_payload["value"] == pytest.approx(_expected_gep(), abs=1e-6)
    assert gep_payload["gep_reference"] == {
        "required": False,
        "available": False,
        "valid": False,
        "reference_id": None,
        "reference_sha256": None,
        "source_path": None,
        "unavailable_reason": "TRANSCRIPTOMICS_GEP_REFERENCE_STATS_JSON is not configured.",
    }

    evidence_response = client.post(f"/v1/transcriptomics/{CASE_ID}/evidence")
    assert evidence_response.status_code == 200
    evidence_payload = evidence_response.json()
    assert evidence_payload["available"] is True
    assert evidence_payload["availability_code"] == "available"
    assert evidence_payload["data_source"] == "counts_tsv"
    assert evidence_payload["top_genes"]
    assert any(gene["symbol"] == "CXCL9" for gene in evidence_payload["top_genes"])
    assert evidence_payload["qc"]["has_rna_input"] is True
    assert evidence_payload["qc"]["gene_panel_size"] == 18
    assert evidence_payload["gep_reference"]["valid"] is False


def test_transcriptomics_metrics_support_pipe_delimited_ensembl_gene_ids(
    client,
    clear_transcriptomics_env,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    counts_dir = tmp_path / "counts"
    counts_dir.mkdir(parents=True)
    _write_counts_file_with_pipe_delimited_gene_ids(counts_dir / f"{CASE_ID}.tsv")

    monkeypatch.setenv("TRANSCRIPTOMICS_COUNTS_DIR", str(counts_dir))

    cyt_payload = client.get(f"/v1/transcriptomics/{CASE_ID}/cyt").json()
    assert cyt_payload["available"] is True
    assert cyt_payload["availability_code"] == "available"
    assert cyt_payload["data_source"] == "counts_tsv"
    assert cyt_payload["value"] == pytest.approx(_expected_cyt(), abs=1e-6)

    gep_payload = client.get(f"/v1/transcriptomics/{CASE_ID}/gep").json()
    assert gep_payload["available"] is True
    assert gep_payload["availability_code"] == "available"
    assert gep_payload["data_source"] == "counts_tsv"
    assert gep_payload["value"] == pytest.approx(_expected_gep(), abs=1e-6)

    evidence_payload = client.post(f"/v1/transcriptomics/{CASE_ID}/evidence").json()
    assert evidence_payload["available"] is True
    assert evidence_payload["availability_code"] == "available"
    assert any(gene["symbol"] == "CXCL9" for gene in evidence_payload["top_genes"])


def test_deg_volcano_returns_interactive_proxy_points_from_counts(
    client,
    clear_transcriptomics_env,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    counts_dir = tmp_path / "counts"
    counts_dir.mkdir(parents=True)
    _write_counts_file(counts_dir / f"{CASE_ID}.tsv")

    monkeypatch.setenv("TRANSCRIPTOMICS_COUNTS_DIR", str(counts_dir))

    response = client.get(f"/v1/transcriptomics/{CASE_ID}/deg-volcano?max_points=12")
    assert response.status_code == 200

    payload = response.json()
    assert payload["available"] is True
    assert payload["availability_code"] == "available"
    assert payload["data_source"] == "counts_tsv"
    assert payload["points"]
    assert payload["plot"] == {
        "x_axis_label": "log2 fold-change proxy",
        "y_axis_label": "-log10 p-value proxy",
        "x_threshold_abs": 1.0,
        "y_threshold": 1.3,
        "p_value_proxy": True,
        "proxy_note": "Research-only DEG-style proxy from normalized RNA expression; p-values are approximate and not for clinical use.",
        "total_genes_observed": 20,
        "returned_points": 12,
    }

    first_point = payload["points"][0]
    assert {"gene_symbol", "x", "y", "log2_fc_proxy", "p_value_proxy", "direction", "significant"} <= set(
        first_point
    )
    assert first_point["p_value_proxy"] > 0
    assert first_point["y"] >= 0


def test_deg_volcano_returns_typed_unavailable_without_inputs(
    client,
    clear_transcriptomics_env,
) -> None:
    response = client.get(f"/v1/transcriptomics/{CASE_ID}/deg-volcano")
    assert response.status_code == 200

    payload = response.json()
    assert payload["available"] is False
    assert payload["availability_code"] == "missing_input"
    assert payload["data_source"] == "unavailable"
    assert payload["points"] == []
    assert payload["plot"]["returned_points"] == 0


def test_transcriptomics_plots_include_bounded_raw_matrix_preview_from_counts(
    client,
    clear_transcriptomics_env,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    counts_dir = tmp_path / "counts"
    counts_dir.mkdir(parents=True)
    _write_counts_file(counts_dir / f"{CASE_ID}.tsv")
    monkeypatch.setenv("TRANSCRIPTOMICS_COUNTS_DIR", str(counts_dir))

    response = client.get(
        f"/v1/transcriptomics/{CASE_ID}/plots?max_raw_matrix_rows=5&max_volcano_points=10&max_ma_points=10"
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["available"] is True
    assert "raw_matrix_preview" in payload

    raw_matrix_preview = payload["raw_matrix_preview"]
    assert raw_matrix_preview["available"] is True
    assert raw_matrix_preview["data_source"] == "counts_tsv"
    assert raw_matrix_preview["total_genes_observed"] == 20
    assert raw_matrix_preview["returned_rows"] == 5
    assert raw_matrix_preview["preview_limit"] == 5
    assert raw_matrix_preview["truncated"] is True

    rows = raw_matrix_preview["rows"]
    assert len(rows) == 5
    assert rows[0]["gene_symbol"] == "CXCL9"
    assert rows[0]["rank"] == 1
    assert rows[0]["raw_value"] == pytest.approx(26.0, abs=1e-6)
    assert rows[0]["normalized_log2"] == pytest.approx(round(math.log2(27.0), 6), abs=1e-6)


def test_transcriptomics_returns_typed_unavailable_without_inputs(
    client,
    clear_transcriptomics_env,
) -> None:
    cyt_response = client.get(f"/v1/transcriptomics/{CASE_ID}/cyt")
    assert cyt_response.status_code == 200

    payload = cyt_response.json()
    assert payload["available"] is False
    assert payload["availability_code"] == "missing_input"
    assert payload["value"] is None
    assert payload["data_source"] == "unavailable"
    assert "No transcriptomics input" in payload["unavailable_reason"]


def test_transcriptomics_treats_unparseable_counts_as_present_but_unusable_input(
    client,
    clear_transcriptomics_env,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    counts_dir = tmp_path / "counts"
    counts_dir.mkdir(parents=True)
    _write_counts_file_missing_required_value_column(counts_dir / f"{CASE_ID}.tsv")
    monkeypatch.setenv("TRANSCRIPTOMICS_COUNTS_DIR", str(counts_dir))

    cyt_payload = client.get(f"/v1/transcriptomics/{CASE_ID}/cyt").json()
    assert cyt_payload["available"] is False
    assert cyt_payload["availability_code"] == "insufficient_gene_coverage"
    assert cyt_payload["data_source"] == "unavailable"

    gep_payload = client.get(f"/v1/transcriptomics/{CASE_ID}/gep").json()
    assert gep_payload["available"] is False
    assert gep_payload["availability_code"] == "insufficient_gene_coverage"
    assert gep_payload["data_source"] == "unavailable"

    tide_payload = client.get(f"/v1/transcriptomics/{CASE_ID}/tide?experimental=true").json()
    assert tide_payload["available"] is False
    assert tide_payload["availability_code"] == "precompute_missing"
    assert tide_payload["precompute"]["available"] is False

    evidence_payload = client.post(f"/v1/transcriptomics/{CASE_ID}/evidence").json()
    assert evidence_payload["available"] is False
    assert evidence_payload["availability_code"] == "evidence_unavailable"
    assert evidence_payload["qc"]["has_rna_input"] is True


def test_tide_requires_experimental_gate_and_reports_unavailable(
    client,
    clear_transcriptomics_env,
) -> None:
    blocked = client.get(f"/v1/transcriptomics/{CASE_ID}/tide")
    assert blocked.status_code == 400
    assert "experimental=true" in blocked.json()["detail"]

    enabled = client.get(f"/v1/transcriptomics/{CASE_ID}/tide?experimental=true")
    assert enabled.status_code == 200

    payload = enabled.json()
    assert payload["available"] is False
    assert payload["availability_code"] == "missing_input"
    assert payload["value"] is None
    assert payload["data_source"] == "unavailable"
    assert payload["precompute"] == {
        "required": True,
        "available": False,
        "data_source": "none",
        "unavailable_reason": "No transcriptomics input detected for this case.",
        "run_id": None,
        "generated_at": None,
    }
    assert "No transcriptomics input" in payload["unavailable_reason"]


def test_tide_reports_precompute_missing_when_rna_input_exists(
    client,
    clear_transcriptomics_env,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    counts_dir = tmp_path / "counts"
    counts_dir.mkdir(parents=True)
    _write_counts_file(counts_dir / f"{CASE_ID}.tsv")
    monkeypatch.setenv("TRANSCRIPTOMICS_COUNTS_DIR", str(counts_dir))

    payload = client.get(f"/v1/transcriptomics/{CASE_ID}/tide?experimental=true").json()

    assert payload["available"] is False
    assert payload["availability_code"] == "precompute_missing"
    assert payload["unavailable_reason"] == "No precomputed TIDE score is available for this case."
    assert payload["precompute"]["required"] is True
    assert payload["precompute"]["available"] is False
    assert payload["precompute"]["data_source"] == "none"


def test_transcriptomics_artifact_values_take_precedence(
    client,
    clear_transcriptomics_env,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "artifacts"
    counts_dir = tmp_path / "counts"
    artifact_dir.mkdir(parents=True)
    counts_dir.mkdir(parents=True)

    _write_counts_file(counts_dir / f"{CASE_ID}.tsv")

    artifact_payload = {
        "cyt": {"value": 0.871},
        "gep": {"value": 1.233},
        "tide": {"value": -0.417, "run_id": "tide-job-01", "generated_at": "2026-03-06T12:00:00Z"},
        "evidence": {
            "top_genes": [
                {"symbol": "CXCL9", "normalized_count": 3.55},
                {"symbol": "CD8A", "normalized_count": 3.11},
            ],
            "notes": ["Loaded from transcriptomics artifact."],
        },
    }
    (artifact_dir / f"{CASE_ID}.json").write_text(
        json.dumps(artifact_payload),
        encoding="utf-8",
    )

    monkeypatch.setenv("TRANSCRIPTOMICS_ARTIFACT_DIR", str(artifact_dir))
    monkeypatch.setenv("TRANSCRIPTOMICS_COUNTS_DIR", str(counts_dir))

    cyt_payload = client.get(f"/v1/transcriptomics/{CASE_ID}/cyt").json()
    assert cyt_payload["available"] is True
    assert cyt_payload["availability_code"] == "available"
    assert cyt_payload["data_source"] == "artifact"
    assert cyt_payload["value"] == pytest.approx(0.871, abs=1e-6)

    gep_payload = client.get(f"/v1/transcriptomics/{CASE_ID}/gep").json()
    assert gep_payload["available"] is True
    assert gep_payload["availability_code"] == "available"
    assert gep_payload["data_source"] == "artifact"
    assert gep_payload["value"] == pytest.approx(1.233, abs=1e-6)

    tide_payload = client.get(f"/v1/transcriptomics/{CASE_ID}/tide?experimental=true").json()
    assert tide_payload["available"] is True
    assert tide_payload["availability_code"] == "available"
    assert tide_payload["data_source"] == "artifact"
    assert tide_payload["value"] == pytest.approx(-0.417, abs=1e-6)
    assert tide_payload["precompute"]["required"] is True
    assert tide_payload["precompute"]["available"] is True
    assert tide_payload["precompute"]["data_source"] == "artifact"
    assert tide_payload["precompute"]["run_id"] == "tide-job-01"
    assert tide_payload["precompute"]["generated_at"] == "2026-03-06T12:00:00Z"

    evidence_payload = client.post(f"/v1/transcriptomics/{CASE_ID}/evidence").json()
    assert evidence_payload["available"] is True
    assert evidence_payload["availability_code"] == "available"
    assert evidence_payload["data_source"] == "artifact"
    assert evidence_payload["top_genes"][0]["symbol"] == "CXCL9"


def test_transcriptomics_modality_result_fallback(
    client,
    db,
    clear_transcriptomics_env,
) -> None:
    job = AnalysisJob(
        case_id=CASE_ID,
        status="completed",
        requested_modalities=["transcriptomics"],
        result_summary={},
    )
    db.add(job)
    db.flush()

    db.add(
        ModalityResult(
            job_id=job.id,
            case_id=CASE_ID,
            modality="transcriptomics",
            payload={
                "scores": {"cyt": 0.777, "gep": 0.222, "tide": -0.333},
                "evidence": {
                    "top_genes": [
                        {"symbol": "GZMA", "normalized_count": 2.7},
                        {"symbol": "PRF1", "normalized_count": 2.3},
                    ],
                    "notes": ["Loaded from modality result payload."],
                },
            },
        )
    )
    db.commit()

    cyt_payload = client.get(f"/v1/transcriptomics/{CASE_ID}/cyt").json()
    assert cyt_payload["available"] is True
    assert cyt_payload["availability_code"] == "available"
    assert cyt_payload["data_source"] == "modality_result"
    assert cyt_payload["value"] == pytest.approx(0.777, abs=1e-6)

    tide_payload = client.get(f"/v1/transcriptomics/{CASE_ID}/tide?experimental=true").json()
    assert tide_payload["available"] is True
    assert tide_payload["availability_code"] == "available"
    assert tide_payload["data_source"] == "modality_result"
    assert tide_payload["value"] == pytest.approx(-0.333, abs=1e-6)
    assert tide_payload["precompute"]["required"] is True
    assert tide_payload["precompute"]["available"] is True
    assert tide_payload["precompute"]["data_source"] == "modality_result"

    evidence_payload = client.post(f"/v1/transcriptomics/{CASE_ID}/evidence").json()
    assert evidence_payload["available"] is True
    assert evidence_payload["availability_code"] == "available"
    assert evidence_payload["data_source"] == "modality_result"
    assert evidence_payload["top_genes"][0]["symbol"] == "GZMA"


def test_gep_frozen_reference_required_returns_typed_unavailable_when_missing(
    client,
    clear_transcriptomics_env,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    counts_dir = tmp_path / "counts"
    counts_dir.mkdir(parents=True)
    _write_counts_file(counts_dir / f"{CASE_ID}.tsv")

    monkeypatch.setenv("TRANSCRIPTOMICS_COUNTS_DIR", str(counts_dir))
    monkeypatch.setenv("TRANSCRIPTOMICS_GEP_REFERENCE_REQUIRED", "true")

    payload = client.get(f"/v1/transcriptomics/{CASE_ID}/gep").json()

    assert payload["available"] is False
    assert payload["availability_code"] == "frozen_reference_unavailable"
    assert payload["data_source"] == "unavailable"
    assert payload["gep_reference"]["required"] is True
    assert payload["gep_reference"]["valid"] is False
    assert "required" in payload["unavailable_reason"].lower()


def test_gep_frozen_reference_governance_metadata_is_returned_when_configured(
    client,
    clear_transcriptomics_env,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    counts_dir = tmp_path / "counts"
    counts_dir.mkdir(parents=True)
    _write_counts_file(counts_dir / f"{CASE_ID}.tsv")

    reference_stats = {
        "metadata": {"reference_id": "luad-frozen-reference-v1"},
        "stats": {
            gene: {"mean": 0.0, "std": 1.0}
            for gene in GEP_GENE_VALUES
        },
    }
    reference_path = tmp_path / "gep_reference.json"
    reference_path.write_text(json.dumps(reference_stats), encoding="utf-8")

    monkeypatch.setenv("TRANSCRIPTOMICS_COUNTS_DIR", str(counts_dir))
    monkeypatch.setenv("TRANSCRIPTOMICS_GEP_REFERENCE_REQUIRED", "true")
    monkeypatch.setenv("TRANSCRIPTOMICS_GEP_REFERENCE_STATS_JSON", str(reference_path))

    payload = client.get(f"/v1/transcriptomics/{CASE_ID}/gep").json()

    assert payload["available"] is True
    assert payload["availability_code"] == "available"
    assert payload["gep_reference"]["required"] is True
    assert payload["gep_reference"]["available"] is True
    assert payload["gep_reference"]["valid"] is True
    assert payload["gep_reference"]["reference_id"] == "luad-frozen-reference-v1"
    assert payload["gep_reference"]["reference_sha256"] is not None
    assert payload["gep_reference"]["source_path"].endswith("/gep_reference.json")


def test_deg_volcano_retains_tiny_p_value_proxy_when_reference_z_is_extreme(
    client,
    clear_transcriptomics_env,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    counts_dir = tmp_path / "counts"
    counts_dir.mkdir(parents=True)
    _write_counts_file(counts_dir / f"{CASE_ID}.tsv")

    reference_stats = {
        "metadata": {"reference_id": "luad-frozen-reference-v1"},
        "stats": {
            # Tiny std forces very large |z| and tiny p-value proxies.
            gene: {"mean": 0.0, "std": 1e-3}
            for gene in GEP_GENE_VALUES
        },
    }
    reference_path = tmp_path / "gep_reference.json"
    reference_path.write_text(json.dumps(reference_stats), encoding="utf-8")

    monkeypatch.setenv("TRANSCRIPTOMICS_COUNTS_DIR", str(counts_dir))
    monkeypatch.setenv("TRANSCRIPTOMICS_GEP_REFERENCE_REQUIRED", "true")
    monkeypatch.setenv("TRANSCRIPTOMICS_GEP_REFERENCE_STATS_JSON", str(reference_path))

    payload = client.get(f"/v1/transcriptomics/{CASE_ID}/deg-volcano?max_points=50").json()

    assert payload["available"] is True
    assert payload["points"]

    capped_points = [point for point in payload["points"] if point["y"] >= 12.0]
    assert capped_points, "expected at least one capped y point for tiny p-value proxies"
    # Regression guard: capped points should never serialize as p_value_proxy=1.0.
    assert all(0 < point["p_value_proxy"] < 1 for point in capped_points)


def test_transcriptomics_coverage_route_reports_per_case_missingness(
    client,
    clear_transcriptomics_env,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    counts_dir = tmp_path / "counts"
    artifact_dir = tmp_path / "artifacts"
    counts_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)

    _write_counts_file(counts_dir / f"{CASE_ID}.tsv")

    (artifact_dir / f"{CASE_ID}.json").write_text(
        '{"tide": {"value": -0.12}}',
        encoding="utf-8",
    )

    cohort_csv = tmp_path / "coverage.csv"
    cohort_csv.write_text(
        "case_id,patient_id\n"
        f"uuid-a,{CASE_ID}\n"
        f"uuid-b,{CASE_ID_B}\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("TRANSCRIPTOMICS_COUNTS_DIR", str(counts_dir))
    monkeypatch.setenv("TRANSCRIPTOMICS_ARTIFACT_DIR", str(artifact_dir))
    monkeypatch.setenv("TRANSCRIPTOMICS_COVERAGE_COHORT_CSV", str(cohort_csv))

    response = client.get("/v1/transcriptomics/coverage")
    assert response.status_code == 200

    payload = response.json()
    assert payload["summary"] == {
        "cases_total": 2,
        "cases_with_rna_input": 1,
        "cases_with_full_mvp_coverage": 1,
        "cases_missing_mvp_coverage": 1,
        "cases_with_tide": 1,
        "cases_missing_tide_precompute": 0,
        "cases_with_gep_reference_valid": 0,
        "cases_missing_gep_reference": 0,
    }

    cases = {entry["case_id"]: entry for entry in payload["cases"]}

    case_a = cases[CASE_ID]
    assert case_a["mvp_ready"] is True
    assert case_a["cyt_available"] is True
    assert case_a["gep_available"] is True
    assert case_a["evidence_available"] is True
    assert case_a["tide_available"] is True
    assert case_a["tide_precompute_available"] is True
    assert case_a["tide_unavailable_reason"] is None
    assert case_a["gep_reference_required"] is False
    assert case_a["gep_reference_valid"] is False
    assert case_a["release_gate_blockers"] == []
    assert case_a["missing_components"] == []

    case_b = cases[CASE_ID_B]
    assert case_b["mvp_ready"] is False
    assert case_b["has_rna_input"] is False
    assert case_b["tide_precompute_available"] is False
    assert "No transcriptomics input" in case_b["tide_unavailable_reason"]
    assert case_b["gep_reference_required"] is False
    assert case_b["gep_reference_valid"] is False
    assert set(case_b["missing_components"]) == {
        "rna_input",
        "cyt",
        "gep",
        "evidence",
        "tide_experimental",
    }
    assert set(case_b["release_gate_blockers"]) == {
        "missing_rna_input",
        "missing_cyt",
        "missing_gep",
        "missing_evidence",
    }


def test_transcriptomics_coverage_service_uses_explicit_case_ids(clear_transcriptomics_env) -> None:
    report = get_transcriptomics_coverage_report(case_ids=[CASE_ID, CASE_ID, CASE_ID_B])

    assert report.summary.cases_total == 2
    assert [case.case_id for case in report.cases] == sorted([CASE_ID, CASE_ID_B])
    assert all("rna_input" in case.missing_components for case in report.cases)


def test_transcriptomics_coverage_counts_unparseable_counts_as_rna_input_present(
    client,
    clear_transcriptomics_env,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    counts_dir = tmp_path / "counts"
    counts_dir.mkdir(parents=True)
    _write_counts_file_missing_required_value_column(counts_dir / f"{CASE_ID}.tsv")
    monkeypatch.setenv("TRANSCRIPTOMICS_COUNTS_DIR", str(counts_dir))

    payload = client.get(f"/v1/transcriptomics/coverage?case_id={CASE_ID}").json()
    assert payload["summary"]["cases_total"] == 1

    case_payload = payload["cases"][0]
    assert case_payload["case_id"] == CASE_ID
    assert case_payload["has_rna_input"] is True
    assert "rna_input" not in case_payload["missing_components"]
    assert "missing_rna_input" not in case_payload["release_gate_blockers"]
