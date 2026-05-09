from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_transcriptomics_coverage_gate.py"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _write_coverage_json(
    path: Path,
    *,
    summary_overrides: dict[str, int] | None = None,
    cases: list[dict[str, object]] | None = None,
) -> None:
    summary = {
        "cases_total": 2,
        "cases_with_rna_input": 2,
        "cases_with_full_mvp_coverage": 2,
        "cases_missing_mvp_coverage": 0,
        "cases_with_tide": 2,
        "cases_missing_tide_precompute": 0,
        "cases_with_gep_reference_valid": 2,
        "cases_missing_gep_reference": 0,
    }
    if summary_overrides:
        summary.update(summary_overrides)

    payload = {
        "summary": summary,
        "cases": cases
        if cases is not None
        else [
            {
                "case_id": "TCGA-01-0001",
                "release_gate_blockers": [],
            },
            {
                "case_id": "TCGA-02-0002",
                "release_gate_blockers": [],
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_release_gate_script_passes_when_thresholds_are_satisfied(tmp_path: Path) -> None:
    coverage_json = tmp_path / "coverage.json"
    _write_coverage_json(coverage_json)

    result = _run(
        [
            sys.executable,
            str(SCRIPT),
            "--coverage-json",
            str(coverage_json),
            "--expected-cases-total",
            "2",
            "--max-missing-mvp-coverage",
            "0",
            "--max-missing-tide-precompute",
            "0",
            "--max-missing-gep-reference",
            "0",
            "--fail-on-release-blockers",
        ]
    )

    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout


def test_release_gate_script_fails_when_tide_precompute_threshold_exceeded(tmp_path: Path) -> None:
    coverage_json = tmp_path / "coverage.json"
    _write_coverage_json(
        coverage_json,
        summary_overrides={"cases_missing_tide_precompute": 1},
    )

    result = _run(
        [
            sys.executable,
            str(SCRIPT),
            "--coverage-json",
            str(coverage_json),
            "--max-missing-tide-precompute",
            "0",
        ]
    )

    assert result.returncode != 0
    assert "cases_missing_tide_precompute" in result.stderr


def test_release_gate_script_fails_on_case_blockers_when_flag_enabled(tmp_path: Path) -> None:
    coverage_json = tmp_path / "coverage.json"
    _write_coverage_json(
        coverage_json,
        cases=[
            {"case_id": "TCGA-01-0001", "release_gate_blockers": ["missing_tide_precompute"]},
            {"case_id": "TCGA-02-0002", "release_gate_blockers": []},
        ],
    )

    result = _run(
        [
            sys.executable,
            str(SCRIPT),
            "--coverage-json",
            str(coverage_json),
            "--fail-on-release-blockers",
        ]
    )

    assert result.returncode != 0
    assert "release_gate_blockers" in result.stderr


def test_release_gate_script_strict_mode_defaults_to_zero_thresholds(tmp_path: Path) -> None:
    coverage_json = tmp_path / "coverage.json"
    _write_coverage_json(
        coverage_json,
        summary_overrides={"cases_missing_mvp_coverage": 1},
    )

    result = _run(
        [
            sys.executable,
            str(SCRIPT),
            "--coverage-json",
            str(coverage_json),
            "--strict",
        ]
    )

    assert result.returncode != 0
    assert "cases_missing_mvp_coverage" in result.stderr
