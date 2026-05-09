from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COVERAGE_SCRIPT = REPO_ROOT / "scripts" / "audit_luad_embedding_coverage.py"
VALIDATION_SCRIPT = REPO_ROOT / "scripts" / "validate_pathology_artifacts.py"

MANIFEST_FIELDS = [
    "slide_id",
]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _write_manifest(path: Path, slide_ids: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS, delimiter="\t")
        writer.writeheader()
        for slide_id in slide_ids:
            writer.writerow({"slide_id": slide_id})


def _write_valid_artifact(path: Path, *, slide_id: str, case_id: str) -> None:
    payload = {
        "slide_id": slide_id,
        "case_id": case_id,
        "tissue_composition": {
            "fractions": [
                {"tissue": "Tumor", "fraction": 0.6},
                {"tissue": "Stroma", "fraction": 0.25},
                {"tissue": "Necrosis", "fraction": 0.1},
                {"tissue": "Lymphocyte-rich", "fraction": 0.05},
            ],
            "qc": {"coverage": 0.91, "artifact_warning": "none"},
        },
        "heatmap": {
            "viewport_hint": {
                "x": 0.1,
                "y": 0.2,
                "width": 0.3,
                "height": 0.4,
            }
        },
        "evidence": {
            "top_tiles": [
                {
                    "tile_id": "tile_1",
                    "score": 0.9,
                    "rationale": "Tumor-rich tile",
                }
            ]
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_coverage_audit_reports_missing_orphans_and_artifact_presence(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.tsv"
    embeddings_dir = tmp_path / "embeddings"
    artifacts_dir = tmp_path / "artifacts"
    out_csv = tmp_path / "coverage.csv"
    out_json = tmp_path / "coverage.json"

    embeddings_dir.mkdir(parents=True)
    artifacts_dir.mkdir(parents=True)

    slide_1_full = "TCGA-01-0001-01Z-00-DX1.svs"
    slide_2_full = "TCGA-02-0002-01Z-00-DX1.svs"
    _write_manifest(manifest_path, [slide_1_full, slide_2_full])

    # Empty npy payloads are sufficient for presence accounting in this audit.
    (embeddings_dir / "TCGA-01-0001-01Z-00-DX1.emb.npy").write_bytes(b"")
    (embeddings_dir / "TCGA-01-0001-01Z-00-DX1.emb_coords.npy").write_bytes(b"")
    (embeddings_dir / "TCGA-99-9999-01Z-00-DX1.emb.npy").write_bytes(b"")

    nested_artifact_dir = artifacts_dir / "nested"
    nested_artifact_dir.mkdir(parents=True)
    _write_valid_artifact(
        nested_artifact_dir / "TCGA-01-0001-01Z-00-DX1.json",
        slide_id="TCGA-01-0001-01Z-00-DX1",
        case_id="TCGA-01-0001",
    )

    result = _run(
        [
            sys.executable,
            str(COVERAGE_SCRIPT),
            "--manifest",
            str(manifest_path),
            "--embeddings-dir",
            str(embeddings_dir),
            "--artifacts-dir",
            str(artifacts_dir),
            "--out-csv",
            str(out_csv),
            "--out-json",
            str(out_json),
        ]
    )

    assert result.returncode == 0, result.stderr

    report = json.loads(out_json.read_text(encoding="utf-8"))
    summary = report["summary"]

    assert summary["slides_total"] == 2
    assert summary["slides_with_embeddings"] == 1
    assert summary["slides_missing_embeddings"] == 1
    assert summary["slides_missing_embedding_ids"] == ["TCGA-02-0002-DX1"]
    assert summary["slides_with_artifacts"] == 1
    assert summary["slides_missing_artifacts"] == 1
    assert summary["orphan_embedding_count"] == 1
    assert summary["orphan_embedding_ids"] == ["TCGA-99-9999-DX1"]
    assert summary["rows_digest_sha256"]
    assert len(summary["rows_digest_sha256"]) == 64

    with out_csv.open("r", encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))

    assert "has_complete_artifact" in header
    assert "artifact_has_tissue_composition" in header


def test_coverage_audit_strict_mode_fails_on_gaps(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.tsv"
    embeddings_dir = tmp_path / "embeddings"
    artifacts_dir = tmp_path / "artifacts"

    embeddings_dir.mkdir(parents=True)
    artifacts_dir.mkdir(parents=True)

    _write_manifest(manifest_path, ["TCGA-01-0001-01Z-00-DX1.svs"])

    result = _run(
        [
            sys.executable,
            str(COVERAGE_SCRIPT),
            "--manifest",
            str(manifest_path),
            "--embeddings-dir",
            str(embeddings_dir),
            "--artifacts-dir",
            str(artifacts_dir),
            "--strict",
        ]
    )

    assert result.returncode != 0
    assert "slides_missing_embeddings" in result.stderr
    assert "slides_missing_artifacts" in result.stderr


def test_validate_pathology_artifacts_passes_with_valid_bundle(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.tsv"
    artifacts_dir = tmp_path / "artifacts"
    report_json = tmp_path / "validation.json"

    artifacts_dir.mkdir(parents=True)

    _write_manifest(manifest_path, ["TCGA-01-0001-01Z-00-DX1.svs"])
    _write_valid_artifact(
        artifacts_dir / "TCGA-01-0001-01Z-00-DX1.json",
        slide_id="TCGA-01-0001-01Z-00-DX1",
        case_id="TCGA-01-0001",
    )

    result = _run(
        [
            sys.executable,
            str(VALIDATION_SCRIPT),
            "--manifest",
            str(manifest_path),
            "--artifacts-dir",
            str(artifacts_dir),
            "--out-json",
            str(report_json),
        ]
    )

    assert result.returncode == 0, result.stderr

    report = json.loads(report_json.read_text(encoding="utf-8"))
    summary = report["summary"]

    assert summary["artifacts_total"] == 1
    assert summary["artifacts_valid_json"] == 1
    assert summary["artifacts_with_all_sections"] == 1
    assert summary["error_count"] == 0


def test_validate_pathology_artifacts_fails_on_schema_errors_and_orphans(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.tsv"
    artifacts_dir = tmp_path / "artifacts"
    report_json = tmp_path / "validation.json"

    artifacts_dir.mkdir(parents=True)

    _write_manifest(manifest_path, ["TCGA-01-0001-01Z-00-DX1.svs"])

    # malformed JSON object shape
    (artifacts_dir / "TCGA-01-0001-01Z-00-DX1.json").write_text("[]", encoding="utf-8")

    # orphan + invalid section payload
    orphan_payload = {
        "slide_id": "TCGA-99-9999-01Z-00-DX1",
        "tissue_composition": {"fractions": [], "qc": {"coverage": 2.0}},
    }
    (artifacts_dir / "TCGA-99-9999-01Z-00-DX1.json").write_text(
        json.dumps(orphan_payload),
        encoding="utf-8",
    )

    result = _run(
        [
            sys.executable,
            str(VALIDATION_SCRIPT),
            "--manifest",
            str(manifest_path),
            "--artifacts-dir",
            str(artifacts_dir),
            "--out-json",
            str(report_json),
            "--fail-on-orphan-artifacts",
        ]
    )

    assert result.returncode != 0

    report = json.loads(report_json.read_text(encoding="utf-8"))
    summary = report["summary"]

    assert summary["orphan_artifact_count"] >= 1
    assert summary["error_count"] >= 1
