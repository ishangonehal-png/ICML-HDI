from __future__ import annotations

import csv
import json
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_SCRIPT = REPO_ROOT / "scripts" / "validate_matched_cohort.py"
LOCK_SCRIPT = REPO_ROOT / "scripts" / "lock_mvp50_manifest.py"

COHORT_FIELDS = [
    "project_id",
    "case_id",
    "patient_id",
    "selected_rna_file_id",
    "selected_rna_file_name",
    "selected_slide_file_id",
    "selected_slide_file_name",
    "selected_clinical_supplement_file_id",
    "selected_clinical_supplement_file_name",
    "selected_clinical_xml_file_id",
    "selected_clinical_xml_file_name",
    "selected_pathology_report_file_id",
    "selected_pathology_report_file_name",
]

MANIFEST_FIELDS = ["id", "filename", "md5", "size", "state"]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _write_cohort(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COHORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_cohort_with_bom_header(path: Path, row: dict[str, str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        headers = list(COHORT_FIELDS)
        headers[0] = f"\ufeff{headers[0]}"
        writer.writerow(headers)
        writer.writerow([row.get(field, "") for field in COHORT_FIELDS])


def _write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _cohort_row(
    *,
    case_id: str,
    patient_id: str,
    file_suffix: str,
    rna_file_id: str,
) -> dict[str, str]:
    return {
        "project_id": "TCGA-LUAD",
        "case_id": case_id,
        "patient_id": patient_id,
        "selected_rna_file_id": rna_file_id,
        "selected_rna_file_name": f"{file_suffix}.tsv" if rna_file_id else "",
        "selected_slide_file_id": f"slide-{file_suffix}",
        "selected_slide_file_name": f"{file_suffix}.svs",
        "selected_clinical_supplement_file_id": f"txt-{file_suffix}",
        "selected_clinical_supplement_file_name": f"{file_suffix}.txt",
        "selected_clinical_xml_file_id": f"xml-{file_suffix}",
        "selected_clinical_xml_file_name": f"{file_suffix}.xml",
        "selected_pathology_report_file_id": f"pdf-{file_suffix}",
        "selected_pathology_report_file_name": f"{file_suffix}.pdf",
    }


def _manifest_rows_for_suffixes(*suffixes: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for suffix in suffixes:
        rows.extend(
            [
                {
                    "id": f"rna-{suffix}",
                    "filename": f"{suffix}.tsv",
                    "md5": f"md5-rna-{suffix}",
                    "size": "1",
                    "state": "live",
                },
                {
                    "id": f"slide-{suffix}",
                    "filename": f"{suffix}.svs",
                    "md5": f"md5-slide-{suffix}",
                    "size": "2",
                    "state": "live",
                },
                {
                    "id": f"txt-{suffix}",
                    "filename": f"{suffix}.txt",
                    "md5": f"md5-txt-{suffix}",
                    "size": "3",
                    "state": "live",
                },
                {
                    "id": f"xml-{suffix}",
                    "filename": f"{suffix}.xml",
                    "md5": f"md5-xml-{suffix}",
                    "size": "4",
                    "state": "live",
                },
                {
                    "id": f"pdf-{suffix}",
                    "filename": f"{suffix}.pdf",
                    "md5": f"md5-pdf-{suffix}",
                    "size": "5",
                    "state": "live",
                },
            ]
        )
    return rows


def test_validate_deduplicates_required_modalities(tmp_path: Path) -> None:
    cohort_csv = tmp_path / "cohort.csv"
    report_json = tmp_path / "report.json"

    _write_cohort(
        cohort_csv,
        [
            _cohort_row(
                case_id="case-1",
                patient_id="TCGA-01-0001",
                file_suffix="rna-case-1",
                rna_file_id="",  # intentionally missing RNA to test preview output
            )
        ],
    )

    result = _run(
        [
            sys.executable,
            str(VALIDATE_SCRIPT),
            "--cohort-csv",
            str(cohort_csv),
            "--required-modalities",
            "rna,rna",
            "--report-json",
            str(report_json),
            "--max-missing-preview",
            "10",
        ]
    )

    assert result.returncode == 0, result.stderr
    assert "missing=[rna]" in result.stdout
    assert "missing=[rna, rna]" not in result.stdout

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["required_modalities"] == ["rna"]


def test_validate_normalizes_required_modalities_case_and_aliases(tmp_path: Path) -> None:
    cohort_csv = tmp_path / "cohort.csv"
    report_json = tmp_path / "report.json"

    _write_cohort(
        cohort_csv,
        [
            _cohort_row(
                case_id="case-1",
                patient_id="TCGA-01-0001",
                file_suffix="alpha",
                rna_file_id="",  # missing RNA only
            )
        ],
    )

    result = _run(
        [
            sys.executable,
            str(VALIDATE_SCRIPT),
            "--cohort-csv",
            str(cohort_csv),
            "--required-modalities",
            "RNA,he-slide,RNA",
            "--report-json",
            str(report_json),
            "--max-missing-preview",
            "10",
        ]
    )

    assert result.returncode == 0, result.stderr
    assert "missing=[rna]" in result.stdout

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["required_modalities"] == ["rna", "he_slide"]


def test_validate_handles_bom_prefixed_headers(tmp_path: Path) -> None:
    cohort_csv = tmp_path / "cohort.csv"

    _write_cohort_with_bom_header(
        cohort_csv,
        _cohort_row(
            case_id="case-1",
            patient_id="TCGA-01-0001",
            file_suffix="alpha",
            rna_file_id="rna-alpha",
        ),
    )

    result = _run(
        [
            sys.executable,
            str(VALIDATE_SCRIPT),
            "--cohort-csv",
            str(cohort_csv),
            "--fail-on-missing",
        ]
    )

    assert result.returncode == 0, result.stderr
    assert "Complete cases: 1" in result.stdout


def test_lock_allow_incomplete_uses_row_level_completeness(tmp_path: Path) -> None:
    cohort_csv = tmp_path / "cohort.csv"
    manifest_tsv = tmp_path / "manifest.tsv"

    _write_cohort(
        cohort_csv,
        [
            _cohort_row(
                case_id="case-1",
                patient_id="TCGA-01-0001",
                file_suffix="alpha",
                rna_file_id="rna-alpha",
            ),
            _cohort_row(
                case_id="",
                patient_id="TCGA-01-0002",
                file_suffix="beta",
                rna_file_id="",  # incomplete row should never be selected
            ),
        ],
    )

    manifest_rows = _manifest_rows_for_suffixes("alpha", "beta")
    # Remove RNA for beta so the row remains incomplete even with manifest present.
    manifest_rows = [r for r in manifest_rows if r["id"] != "rna-beta"]
    _write_manifest(manifest_tsv, manifest_rows)

    result = _run(
        [
            sys.executable,
            str(LOCK_SCRIPT),
            "--cohort-csv",
            str(cohort_csv),
            "--manifest-tsv",
            str(manifest_tsv),
            "--output-root",
            str(tmp_path / "out"),
            "--lock-name",
            "lock",
            "--subset-size",
            "2",
            "--allow-incomplete",
        ]
    )

    assert result.returncode != 0
    combined = f"{result.stdout}\n{result.stderr}"
    assert "Only 1 complete cases available, need 2." in combined


def test_lock_allow_incomplete_selects_from_complete_rows_only(tmp_path: Path) -> None:
    cohort_csv = tmp_path / "cohort.csv"
    manifest_tsv = tmp_path / "manifest.tsv"
    out_dir = tmp_path / "out"

    _write_cohort(
        cohort_csv,
        [
            _cohort_row(
                case_id="case-1",
                patient_id="TCGA-01-0001",
                file_suffix="alpha",
                rna_file_id="rna-alpha",
            ),
            _cohort_row(
                case_id="case-2",
                patient_id="TCGA-01-0002",
                file_suffix="beta",
                rna_file_id="",  # incomplete row
            ),
        ],
    )

    manifest_rows = _manifest_rows_for_suffixes("alpha", "beta")
    manifest_rows = [r for r in manifest_rows if r["id"] != "rna-beta"]
    _write_manifest(manifest_tsv, manifest_rows)

    result = _run(
        [
            sys.executable,
            str(LOCK_SCRIPT),
            "--cohort-csv",
            str(cohort_csv),
            "--manifest-tsv",
            str(manifest_tsv),
            "--output-root",
            str(out_dir),
            "--lock-name",
            "lock",
            "--subset-size",
            "1",
            "--allow-incomplete",
            "--seed",
            "allow-incomplete-seed",
        ]
    )

    assert result.returncode == 0, result.stderr

    provenance = json.loads((out_dir / "lock" / "provenance_manifest.json").read_text(encoding="utf-8"))
    assert provenance["selection"]["case_ids_in_lock_order"] == ["case-1"]


def test_lock_fails_on_duplicate_manifest_ids(tmp_path: Path) -> None:
    cohort_csv = tmp_path / "cohort.csv"
    manifest_tsv = tmp_path / "manifest.tsv"

    _write_cohort(
        cohort_csv,
        [
            _cohort_row(
                case_id="case-1",
                patient_id="TCGA-01-0001",
                file_suffix="alpha",
                rna_file_id="rna-alpha",
            )
        ],
    )

    rows = _manifest_rows_for_suffixes("alpha")
    rows.append(
        {
            "id": "rna-alpha",
            "filename": "alpha-alt.tsv",
            "md5": "md5-rna-alpha-dup",
            "size": "999",
            "state": "live",
        }
    )
    _write_manifest(manifest_tsv, rows)

    result = _run(
        [
            sys.executable,
            str(LOCK_SCRIPT),
            "--cohort-csv",
            str(cohort_csv),
            "--manifest-tsv",
            str(manifest_tsv),
            "--output-root",
            str(tmp_path / "out"),
            "--lock-name",
            "lock",
            "--subset-size",
            "1",
        ]
    )

    assert result.returncode != 0
    assert "duplicate file ids" in result.stderr.lower()


def test_lock_fails_on_case_insensitive_duplicate_manifest_ids(tmp_path: Path) -> None:
    cohort_csv = tmp_path / "cohort.csv"
    manifest_tsv = tmp_path / "manifest.tsv"

    _write_cohort(
        cohort_csv,
        [
            _cohort_row(
                case_id="case-1",
                patient_id="TCGA-01-0001",
                file_suffix="alpha",
                rna_file_id="rna-alpha",
            )
        ],
    )

    rows = _manifest_rows_for_suffixes("alpha")
    rows.append(
        {
            "id": "RNA-ALPHA",
            "filename": "alpha.tsv",
            "md5": "md5-rna-alpha-case-dup",
            "size": "1",
            "state": "live",
        }
    )
    _write_manifest(manifest_tsv, rows)

    result = _run(
        [
            sys.executable,
            str(LOCK_SCRIPT),
            "--cohort-csv",
            str(cohort_csv),
            "--manifest-tsv",
            str(manifest_tsv),
            "--output-root",
            str(tmp_path / "out"),
            "--lock-name",
            "lock",
            "--subset-size",
            "1",
        ]
    )

    assert result.returncode != 0
    assert "duplicate file ids" in result.stderr.lower()


def test_lock_matches_manifest_ids_case_insensitively(tmp_path: Path) -> None:
    cohort_csv = tmp_path / "cohort.csv"
    manifest_tsv = tmp_path / "manifest.tsv"
    output_root = tmp_path / "out"

    _write_cohort(
        cohort_csv,
        [
            _cohort_row(
                case_id="case-1",
                patient_id="TCGA-01-0001",
                file_suffix="alpha",
                rna_file_id="RNA-ALPHA",
            )
        ],
    )
    _write_manifest(manifest_tsv, _manifest_rows_for_suffixes("alpha"))

    result = _run(
        [
            sys.executable,
            str(LOCK_SCRIPT),
            "--cohort-csv",
            str(cohort_csv),
            "--manifest-tsv",
            str(manifest_tsv),
            "--output-root",
            str(output_root),
            "--lock-name",
            "lock",
            "--subset-size",
            "1",
        ]
    )

    assert result.returncode == 0, result.stderr

    provenance = json.loads((output_root / "lock" / "provenance_manifest.json").read_text(encoding="utf-8"))
    rna_assets = [a for a in provenance["assets"] if a["modality"] == "rna"]
    assert len(rna_assets) == 1
    assert rna_assets[0]["gdc_file_id"] == "rna-alpha"


def test_lock_fails_on_filename_mismatch_between_cohort_and_manifest(tmp_path: Path) -> None:
    cohort_csv = tmp_path / "cohort.csv"
    manifest_tsv = tmp_path / "manifest.tsv"

    _write_cohort(
        cohort_csv,
        [
            _cohort_row(
                case_id="case-1",
                patient_id="TCGA-01-0001",
                file_suffix="alpha",
                rna_file_id="rna-alpha",
            )
        ],
    )

    rows = _manifest_rows_for_suffixes("alpha")
    for row in rows:
        if row["id"] == "rna-alpha":
            row["filename"] = "alpha-renamed.tsv"
    _write_manifest(manifest_tsv, rows)

    result = _run(
        [
            sys.executable,
            str(LOCK_SCRIPT),
            "--cohort-csv",
            str(cohort_csv),
            "--manifest-tsv",
            str(manifest_tsv),
            "--output-root",
            str(tmp_path / "out"),
            "--lock-name",
            "lock",
            "--subset-size",
            "1",
        ]
    )

    assert result.returncode != 0
    assert "filename mismatch" in result.stderr.lower()


def test_lock_dry_run_does_not_write_outputs(tmp_path: Path) -> None:
    cohort_csv = tmp_path / "cohort.csv"
    manifest_tsv = tmp_path / "manifest.tsv"
    output_root = tmp_path / "out"
    lock_name = "dryrun-lock"

    _write_cohort(
        cohort_csv,
        [
            _cohort_row(
                case_id="case-1",
                patient_id="TCGA-01-0001",
                file_suffix="alpha",
                rna_file_id="rna-alpha",
            )
        ],
    )
    _write_manifest(manifest_tsv, _manifest_rows_for_suffixes("alpha"))

    result = _run(
        [
            sys.executable,
            str(LOCK_SCRIPT),
            "--cohort-csv",
            str(cohort_csv),
            "--manifest-tsv",
            str(manifest_tsv),
            "--output-root",
            str(output_root),
            "--lock-name",
            lock_name,
            "--subset-size",
            "1",
            "--dry-run",
        ]
    )

    assert result.returncode == 0, result.stderr
    assert "Dry-run enabled: no files were written." in result.stdout
    assert not (output_root / lock_name).exists()


def test_lock_order_is_deterministic_across_input_order(tmp_path: Path) -> None:
    manifest_tsv = tmp_path / "manifest.tsv"
    _write_manifest(manifest_tsv, _manifest_rows_for_suffixes("alpha", "beta", "gamma"))

    rows = [
        _cohort_row(
            case_id="case-alpha",
            patient_id="TCGA-01-0001",
            file_suffix="alpha",
            rna_file_id="rna-alpha",
        ),
        _cohort_row(
            case_id="case-beta",
            patient_id="TCGA-01-0002",
            file_suffix="beta",
            rna_file_id="rna-beta",
        ),
        _cohort_row(
            case_id="case-gamma",
            patient_id="TCGA-01-0003",
            file_suffix="gamma",
            rna_file_id="rna-gamma",
        ),
    ]

    cohort_a = tmp_path / "cohort-a.csv"
    cohort_b = tmp_path / "cohort-b.csv"
    _write_cohort(cohort_a, rows)
    _write_cohort(cohort_b, list(reversed(rows)))

    out_a = tmp_path / "out-a"
    out_b = tmp_path / "out-b"

    run_a = _run(
        [
            sys.executable,
            str(LOCK_SCRIPT),
            "--cohort-csv",
            str(cohort_a),
            "--manifest-tsv",
            str(manifest_tsv),
            "--output-root",
            str(out_a),
            "--lock-name",
            "lock",
            "--subset-size",
            "2",
            "--seed",
            "determinism-seed",
        ]
    )
    run_b = _run(
        [
            sys.executable,
            str(LOCK_SCRIPT),
            "--cohort-csv",
            str(cohort_b),
            "--manifest-tsv",
            str(manifest_tsv),
            "--output-root",
            str(out_b),
            "--lock-name",
            "lock",
            "--subset-size",
            "2",
            "--seed",
            "determinism-seed",
        ]
    )

    assert run_a.returncode == 0, run_a.stderr
    assert run_b.returncode == 0, run_b.stderr

    prov_a = json.loads((out_a / "lock" / "provenance_manifest.json").read_text(encoding="utf-8"))
    prov_b = json.loads((out_b / "lock" / "provenance_manifest.json").read_text(encoding="utf-8"))

    assert prov_a["selection"]["case_ids_in_lock_order"] == prov_b["selection"]["case_ids_in_lock_order"]


def test_validate_dry_run_does_not_create_report_parent(tmp_path: Path) -> None:
    cohort_csv = tmp_path / "cohort.csv"
    report_json = tmp_path / "nested" / "reports" / "report.json"

    _write_cohort(
        cohort_csv,
        [
            _cohort_row(
                case_id="case-1",
                patient_id="TCGA-01-0001",
                file_suffix="alpha",
                rna_file_id="rna-alpha",
            )
        ],
    )

    result = _run(
        [
            sys.executable,
            str(VALIDATE_SCRIPT),
            "--cohort-csv",
            str(cohort_csv),
            "--report-json",
            str(report_json),
            "--dry-run",
        ]
    )

    assert result.returncode == 0, result.stderr
    assert "Dry-run enabled: skipped writing" in result.stdout
    assert not report_json.exists()
    assert not report_json.parent.exists()


def test_validate_errors_when_input_path_is_not_a_file(tmp_path: Path) -> None:
    cohort_dir = tmp_path / "cohort-dir"
    cohort_dir.mkdir()

    result = _run(
        [
            sys.executable,
            str(VALIDATE_SCRIPT),
            "--cohort-csv",
            str(cohort_dir),
        ]
    )

    assert result.returncode != 0
    assert "Cohort CSV must be a file path" in result.stderr
    assert "--cohort-csv" in result.stderr


def test_lock_fails_with_clear_error_when_output_path_is_file(tmp_path: Path) -> None:
    cohort_csv = tmp_path / "cohort.csv"
    manifest_tsv = tmp_path / "manifest.tsv"
    output_root = tmp_path / "out"
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "lock").write_text("blocking file", encoding="utf-8")

    _write_cohort(
        cohort_csv,
        [
            _cohort_row(
                case_id="case-1",
                patient_id="TCGA-01-0001",
                file_suffix="alpha",
                rna_file_id="rna-alpha",
            )
        ],
    )
    _write_manifest(manifest_tsv, _manifest_rows_for_suffixes("alpha"))

    result = _run(
        [
            sys.executable,
            str(LOCK_SCRIPT),
            "--cohort-csv",
            str(cohort_csv),
            "--manifest-tsv",
            str(manifest_tsv),
            "--output-root",
            str(output_root),
            "--lock-name",
            "lock",
            "--subset-size",
            "1",
        ]
    )

    assert result.returncode != 0
    assert "Lock output exists but is not a directory" in result.stderr


def test_lock_outputs_use_lf_newlines(tmp_path: Path) -> None:
    cohort_csv = tmp_path / "cohort.csv"
    manifest_tsv = tmp_path / "manifest.tsv"
    output_root = tmp_path / "out"

    _write_cohort(
        cohort_csv,
        [
            _cohort_row(
                case_id="case-1",
                patient_id="TCGA-01-0001",
                file_suffix="alpha",
                rna_file_id="rna-alpha",
            )
        ],
    )
    _write_manifest(manifest_tsv, _manifest_rows_for_suffixes("alpha"))

    result = _run(
        [
            sys.executable,
            str(LOCK_SCRIPT),
            "--cohort-csv",
            str(cohort_csv),
            "--manifest-tsv",
            str(manifest_tsv),
            "--output-root",
            str(output_root),
            "--lock-name",
            "lock",
            "--subset-size",
            "1",
        ]
    )

    assert result.returncode == 0, result.stderr

    cohort_bytes = (output_root / "lock" / "cohort.csv").read_bytes()
    manifest_bytes = (output_root / "lock" / "manifest.tsv").read_bytes()

    assert b"\r\n" not in cohort_bytes
    assert b"\r\n" not in manifest_bytes


def test_lock_deterministic_tie_breaker_for_duplicate_case_patient(tmp_path: Path) -> None:
    manifest_tsv = tmp_path / "manifest.tsv"
    _write_manifest(manifest_tsv, _manifest_rows_for_suffixes("alpha", "beta"))

    duplicate_case_rows = [
        _cohort_row(
            case_id="case-dupe",
            patient_id="TCGA-01-0001",
            file_suffix="alpha",
            rna_file_id="rna-alpha",
        ),
        _cohort_row(
            case_id="case-dupe",
            patient_id="TCGA-01-0001",
            file_suffix="beta",
            rna_file_id="rna-beta",
        ),
    ]

    cohort_a = tmp_path / "cohort-a.csv"
    cohort_b = tmp_path / "cohort-b.csv"
    _write_cohort(cohort_a, duplicate_case_rows)
    _write_cohort(cohort_b, list(reversed(duplicate_case_rows)))

    out_a = tmp_path / "out-a"
    out_b = tmp_path / "out-b"

    run_a = _run(
        [
            sys.executable,
            str(LOCK_SCRIPT),
            "--cohort-csv",
            str(cohort_a),
            "--manifest-tsv",
            str(manifest_tsv),
            "--output-root",
            str(out_a),
            "--lock-name",
            "lock",
            "--subset-size",
            "1",
            "--seed",
            "determinism-seed",
        ]
    )
    run_b = _run(
        [
            sys.executable,
            str(LOCK_SCRIPT),
            "--cohort-csv",
            str(cohort_b),
            "--manifest-tsv",
            str(manifest_tsv),
            "--output-root",
            str(out_b),
            "--lock-name",
            "lock",
            "--subset-size",
            "1",
            "--seed",
            "determinism-seed",
        ]
    )

    assert run_a.returncode == 0, run_a.stderr
    assert run_b.returncode == 0, run_b.stderr

    prov_a = json.loads((out_a / "lock" / "provenance_manifest.json").read_text(encoding="utf-8"))
    prov_b = json.loads((out_b / "lock" / "provenance_manifest.json").read_text(encoding="utf-8"))
    assert prov_a["cases"][0]["selected_files"] == prov_b["cases"][0]["selected_files"]

    with (out_a / "lock" / "manifest.tsv").open("r", encoding="utf-8", newline="") as f:
        manifest_a_rows = list(csv.DictReader(f, delimiter="	"))
    with (out_b / "lock" / "manifest.tsv").open("r", encoding="utf-8", newline="") as f:
        manifest_b_rows = list(csv.DictReader(f, delimiter="	"))

    assert [row["id"] for row in manifest_a_rows] == [row["id"] for row in manifest_b_rows]


def test_lock_provenance_payload_digest_is_stable_across_runs(tmp_path: Path) -> None:
    cohort_csv = tmp_path / "cohort.csv"
    manifest_tsv = tmp_path / "manifest.tsv"
    _write_cohort(
        cohort_csv,
        [
            _cohort_row(
                case_id="case-1",
                patient_id="TCGA-01-0001",
                file_suffix="alpha",
                rna_file_id="rna-alpha",
            )
        ],
    )
    _write_manifest(manifest_tsv, _manifest_rows_for_suffixes("alpha"))

    out_a = tmp_path / "out-a"
    out_b = tmp_path / "out-b"

    run_a = _run(
        [
            sys.executable,
            str(LOCK_SCRIPT),
            "--cohort-csv",
            str(cohort_csv),
            "--manifest-tsv",
            str(manifest_tsv),
            "--output-root",
            str(out_a),
            "--lock-name",
            "lock",
            "--subset-size",
            "1",
            "--seed",
            "stable-digest-seed",
        ]
    )
    assert run_a.returncode == 0, run_a.stderr

    time.sleep(1.1)

    run_b = _run(
        [
            sys.executable,
            str(LOCK_SCRIPT),
            "--cohort-csv",
            str(cohort_csv),
            "--manifest-tsv",
            str(manifest_tsv),
            "--output-root",
            str(out_b),
            "--lock-name",
            "lock",
            "--subset-size",
            "1",
            "--seed",
            "stable-digest-seed",
        ]
    )
    assert run_b.returncode == 0, run_b.stderr

    checksum_a = json.loads((out_a / "lock" / "checksum_report.json").read_text(encoding="utf-8"))
    checksum_b = json.loads((out_b / "lock" / "checksum_report.json").read_text(encoding="utf-8"))

    assert checksum_a["digests"]["case_id_order_sha256"] == checksum_b["digests"]["case_id_order_sha256"]
    assert checksum_a["digests"]["unique_file_id_set_sha256"] == checksum_b["digests"]["unique_file_id_set_sha256"]
    assert checksum_a["digests"]["provenance_payload_sha256"] == checksum_b["digests"]["provenance_payload_sha256"]
