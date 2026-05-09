#!/usr/bin/env python3
"""Deterministically lock an MVP subset and emit provenance + checksum artifacts."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from .constants import DEFAULT_COHORT, DEFAULT_MANIFEST, DEFAULT_OUTPUT_ROOT, DEFAULT_SCHEMA
from .data_contract_utils import (
    build_completeness_report,
    dumps_json_pretty,
    ensure_required_columns,
    evaluate_cohort_completeness,
    extract_tcga_ids,
    infer_source_path,
    load_and_validate_cohort_rows,
    rank_rows_with_lock_metadata,
    read_delimited_rows,
    resolve_schema_and_modalities,
    safe_int,
    sha256_file,
    sha256_json,
    sha256_text,
    utcnow_iso,
)


def _normalize_file_id(file_id: str) -> str:
    return (file_id or "").strip().lower()


def _stable_provenance_payload_for_digest(provenance: Dict[str, Any]) -> Dict[str, Any]:
    # Exclude run timestamps so digest remains stable across repeat runs
    # on identical inputs and deterministic selection settings.
    stable = dict(provenance)
    stable.pop("generated_at_utc", None)
    return stable


def add_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--cohort-csv",
        type=Path,
        default=DEFAULT_COHORT,
        help=f"Matched cohort CSV path (default: {DEFAULT_COHORT})",
    )
    parser.add_argument(
        "--manifest-tsv",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"Full manifest TSV path (default: {DEFAULT_MANIFEST})",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help=f"Contract schema JSON path (default: {DEFAULT_SCHEMA})",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=f"Output root for lock artifacts (default: {DEFAULT_OUTPUT_ROOT})",
    )
    parser.add_argument(
        "--lock-name",
        default="tcga_luad_mvp50_v1",
        help="Output folder name under output-root (default: tcga_luad_mvp50_v1).",
    )
    parser.add_argument(
        "--subset-size",
        type=int,
        default=50,
        help="Number of complete cases to lock deterministically (default: 50).",
    )
    parser.add_argument(
        "--seed",
        default="tcga-luad-mvp50-v1",
        help="Deterministic seed string used in lock ordering (default: tcga-luad-mvp50-v1).",
    )
    parser.add_argument(
        "--required-modalities",
        default=None,
        help=(
            "Optional comma-separated modality override. "
            "Defaults to schema.required_modalities."
        ),
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Allow incomplete rows in input cohort, but subset is still selected from complete rows only.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run selection and validation without writing output files.",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Lock a deterministic MVP subset (default 50 cases) from a matched TCGA cohort "
            "and generate reproducibility artifacts."
        )
    )
    return add_arguments(parser)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def _ensure_input_file(path: Path, *, flag: str, label: str) -> None:
    if not path.exists():
        raise RuntimeError(f"{label} not found: {path} (from {flag})")
    if not path.is_file():
        raise RuntimeError(f"{label} must be a file path: {path} (from {flag})")


def _ensure_directory(path: Path, *, label: str) -> None:
    if path.exists() and not path.is_dir():
        raise RuntimeError(f"{label} exists but is not a directory: {path}")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - platform/permission dependent
        raise RuntimeError(f"Failed to create {label} directory '{path}': {exc}") from exc


def _read_manifest_map(path: Path) -> Tuple[List[Dict[str, str]], Dict[str, Dict[str, str]]]:
    fieldnames, rows = read_delimited_rows(path, delimiter="\t")
    ensure_required_columns(
        available_columns=fieldnames,
        required_columns=["id", "filename", "md5", "size", "state"],
        label=f"manifest TSV ({path})",
    )

    by_normalized_id: Dict[str, Dict[str, str]] = {}
    duplicate_ids: Dict[str, set[str]] = {}

    for row in rows:
        file_id_raw = (row.get("id") or "").strip()
        if not file_id_raw:
            continue

        normalized_file_id = _normalize_file_id(file_id_raw)
        existing = by_normalized_id.get(normalized_file_id)
        if existing is not None:
            duplicate_ids.setdefault(normalized_file_id, {(existing.get("id") or "").strip()}).add(file_id_raw)
            continue

        row_copy = dict(row)
        row_copy["id"] = file_id_raw
        row_copy["filename"] = (row_copy.get("filename") or "").strip()
        row_copy["md5"] = (row_copy.get("md5") or "").strip()
        row_copy["size"] = (row_copy.get("size") or "").strip()
        row_copy["state"] = (row_copy.get("state") or "").strip()
        by_normalized_id[normalized_file_id] = row_copy

    if duplicate_ids:
        preview_items = [
            f"{normalized_id} -> {sorted(list(raw_values))}"
            for normalized_id, raw_values in sorted(duplicate_ids.items())
        ]
        preview = "; ".join(preview_items[:10])
        raise RuntimeError(
            "Manifest TSV contains duplicate file ids. "
            f"Found {len(duplicate_ids)} duplicate id(s). Examples: {preview}"
        )

    return rows, by_normalized_id


def _write_delimited(path: Path, rows: List[Dict[str, object]], fieldnames: Sequence[str], delimiter: str) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(fieldnames),
            delimiter=delimiter,
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _row_is_complete_for_modalities(
    row: Dict[str, str],
    required_modalities: Sequence[str],
    modality_requirements: Dict[str, Dict],
) -> bool:
    for modality in required_modalities:
        req = modality_requirements[modality]
        col = str(req.get("file_id_column") or "")
        value = (row.get(col) or "").strip()
        if not value:
            return False
    return True


def _build_selected_assets(
    selected_rows: List[Dict[str, str]],
    required_modalities: Sequence[str],
    modality_requirements: Dict[str, Dict],
    manifest_by_id: Dict[str, Dict[str, str]],
    contract_version: str,
) -> List[Dict[str, object]]:
    assets: List[Dict[str, object]] = []
    for row in selected_rows:
        case_id = (row.get("case_id") or "").strip()
        patient_id = (row.get("patient_id") or "").strip()
        project_id = (row.get("project_id") or "").strip()
        lock_rank = int(row.get("lock_rank") or 0)
        lock_key = (row.get("lock_key_sha256") or "").strip()

        for modality in required_modalities:
            req = modality_requirements[modality]
            file_id_col = str(req.get("file_id_column") or "")
            filename_col = str(req.get("filename_column") or "")
            cohort_file_id = (row.get(file_id_col) or "").strip()
            if not cohort_file_id:
                continue

            manifest_row = manifest_by_id.get(_normalize_file_id(cohort_file_id))
            if manifest_row is None:
                raise RuntimeError(
                    f"Required file id {cohort_file_id} for case {case_id} not found in manifest TSV"
                )

            cohort_filename = (row.get(filename_col) or "").strip()
            manifest_filename = (manifest_row.get("filename") or "").strip()
            if cohort_filename and manifest_filename and cohort_filename != manifest_filename:
                raise RuntimeError(
                    "Filename mismatch between cohort CSV and manifest TSV for "
                    f"file id {cohort_file_id} (case {case_id}): "
                    f"cohort='{cohort_filename}' manifest='{manifest_filename}'"
                )
            filename = cohort_filename or manifest_filename
            if not filename:
                raise RuntimeError(
                    f"Missing filename for file id {cohort_file_id} (case {case_id})"
                )

            canonical_file_id = (manifest_row.get("id") or cohort_file_id).strip()
            sample_id, slide_id = extract_tcga_ids(filename=filename, patient_id=patient_id)
            if modality != "he_slide":
                # Non-slide modalities usually do not carry a slide barcode.
                slide_id = ""

            assets.append(
                {
                    "contract_version": contract_version,
                    "case_id": case_id,
                    "patient_id": patient_id,
                    "sample_id": sample_id,
                    "slide_id": slide_id,
                    "gdc_file_id": canonical_file_id,
                    "modality": modality,
                    "filename": filename,
                    "source_path": infer_source_path(canonical_file_id, filename),
                    "checksum": (manifest_row.get("md5") or "").strip(),
                    "size_bytes": safe_int(manifest_row.get("size")),
                    "state": (manifest_row.get("state") or "").strip(),
                    "project_id": project_id,
                    "lock_rank": lock_rank,
                    "lock_key_sha256": lock_key,
                }
            )

    assets.sort(
        key=lambda x: (
            int(x.get("lock_rank") or 0),
            str(x.get("case_id") or ""),
            str(x.get("modality") or ""),
            str(x.get("gdc_file_id") or ""),
        )
    )
    return assets


def run(args: argparse.Namespace) -> int:
    if args.subset_size <= 0:
        raise RuntimeError("--subset-size must be > 0")
    if not str(args.lock_name).strip():
        raise RuntimeError("--lock-name must be non-empty")

    _ensure_input_file(args.cohort_csv, flag="--cohort-csv", label="Cohort CSV")
    _ensure_input_file(args.manifest_tsv, flag="--manifest-tsv", label="Manifest TSV")
    _ensure_input_file(args.schema, flag="--schema", label="Schema JSON")

    schema, modality_requirements, required_modalities = resolve_schema_and_modalities(
        args.schema,
        args.required_modalities,
    )

    cohort_fieldnames, cohort_rows = load_and_validate_cohort_rows(args.cohort_csv, schema)

    completeness = evaluate_cohort_completeness(
        rows=cohort_rows,
        required_modalities=required_modalities,
        modality_requirements=modality_requirements,
    )

    if completeness["incomplete_cases"] > 0 and not args.allow_incomplete:
        raise RuntimeError(
            f"Found {completeness['incomplete_cases']} incomplete cases. "
            "Re-run with --allow-incomplete to continue selecting from complete rows only."
        )

    eligible_rows = [
        row
        for row in cohort_rows
        if _row_is_complete_for_modalities(
            row=row,
            required_modalities=required_modalities,
            modality_requirements=modality_requirements,
        )
    ]

    if len(eligible_rows) < args.subset_size:
        raise RuntimeError(
            f"Only {len(eligible_rows)} complete cases available, need {args.subset_size}."
        )

    ranked_rows = rank_rows_with_lock_metadata(eligible_rows, seed=args.seed)
    selected_rows = ranked_rows[: args.subset_size]

    _manifest_rows, manifest_by_id = _read_manifest_map(args.manifest_tsv)

    selected_file_ids_normalized = set()
    for row in selected_rows:
        for modality in required_modalities:
            req = modality_requirements[modality]
            file_id_col = str(req.get("file_id_column") or "")
            file_id = (row.get(file_id_col) or "").strip()
            if file_id:
                selected_file_ids_normalized.add(_normalize_file_id(file_id))

    missing_file_ids = sorted(fid for fid in selected_file_ids_normalized if fid not in manifest_by_id)
    if missing_file_ids:
        preview = ", ".join(missing_file_ids[:10])
        raise RuntimeError(
            f"{len(missing_file_ids)} selected file ids are missing from manifest TSV. "
            f"Examples: {preview}"
        )

    selected_manifest_rows = [manifest_by_id[fid] for fid in sorted(selected_file_ids_normalized)]
    assets = _build_selected_assets(
        selected_rows=selected_rows,
        required_modalities=required_modalities,
        modality_requirements=modality_requirements,
        manifest_by_id=manifest_by_id,
        contract_version=str(schema.get("contract_version") or ""),
    )

    lock_dir = args.output_root / args.lock_name
    cohort_out = lock_dir / "cohort.csv"
    manifest_out = lock_dir / "manifest.tsv"
    provenance_out = lock_dir / "provenance_manifest.json"
    checksum_out = lock_dir / "checksum_report.json"
    completeness_out = lock_dir / "cohort_completeness_report.json"

    case_ids_in_order = [str(row.get("case_id") or "") for row in selected_rows]
    file_ids_sorted = [str(row.get("id") or "") for row in selected_manifest_rows]

    selected_case_records = []
    for row in selected_rows:
        selected_case_records.append(
            {
                "case_id": (row.get("case_id") or "").strip(),
                "patient_id": (row.get("patient_id") or "").strip(),
                "project_id": (row.get("project_id") or "").strip(),
                "lock_rank": int(row.get("lock_rank") or 0),
                "lock_key_sha256": (row.get("lock_key_sha256") or "").strip(),
                "selected_files": {
                    modality: (row.get(str(modality_requirements[modality].get("file_id_column") or "")) or "").strip()
                    for modality in required_modalities
                },
            }
        )

    selected_case_records.sort(
        key=lambda item: (
            int(item.get("lock_rank") or 0),
            str(item.get("case_id") or ""),
            str(item.get("patient_id") or ""),
        )
    )

    provenance = {
        "generated_at_utc": utcnow_iso(),
        "manifest_id": args.lock_name,
        "contract_name": schema.get("contract_name"),
        "contract_version": schema.get("contract_version"),
        "project_id": schema.get("project_id"),
        "inputs": {
            "cohort_csv": str(args.cohort_csv.resolve()),
            "manifest_tsv": str(args.manifest_tsv.resolve()),
            "schema": str(args.schema.resolve()),
        },
        "selection": {
            "subset_size": args.subset_size,
            "seed": args.seed,
            "algorithm": (
                "sha256(seed|case_id|patient_id), then sha256(normalized_row_json) "
                "for stable tie-break; sorted by lock_key/case_id/patient_id/fingerprint"
            ),
            "required_modalities": list(required_modalities),
            "case_ids_in_lock_order": case_ids_in_order,
        },
        "summary": {
            "input_total_cases": completeness["total_cases"],
            "input_complete_cases": completeness["complete_cases"],
            "selected_cases": len(selected_rows),
            "selected_unique_files": len(selected_manifest_rows),
            "asset_records": len(assets),
        },
        "cases": selected_case_records,
        "assets": assets,
    }

    checksum_report = {
        "generated_at_utc": utcnow_iso(),
        "manifest_id": args.lock_name,
        "summary": {
            "selected_cases": len(selected_rows),
            "selected_unique_files": len(selected_manifest_rows),
            "required_modalities": list(required_modalities),
        },
        "digests": {
            "case_id_order_sha256": sha256_text("\n".join(case_ids_in_order)),
            "unique_file_id_set_sha256": sha256_text("\n".join(file_ids_sorted)),
            "provenance_payload_sha256": sha256_json(_stable_provenance_payload_for_digest(provenance)),
        },
        "expected_file_checksums": [
            {
                "gdc_file_id": row.get("id", ""),
                "filename": row.get("filename", ""),
                "checksum_md5": row.get("md5", ""),
                "size_bytes": safe_int(row.get("size")),
            }
            for row in selected_manifest_rows
        ],
    }

    completeness_report = build_completeness_report(
        schema=schema,
        cohort_csv=args.cohort_csv,
        required_modalities=required_modalities,
        completeness=completeness,
    )

    print(f"Lock name: {args.lock_name}")
    print(f"Subset size requested: {args.subset_size}")
    print(f"Selected complete cases: {len(selected_rows)}")
    print(f"Selected unique files: {len(selected_manifest_rows)}")
    print(f"Output directory: {lock_dir.resolve()}")

    if args.dry_run:
        print("Dry-run enabled: no files were written.")
        print(f"Would write: {cohort_out}")
        print(f"Would write: {manifest_out}")
        print(f"Would write: {provenance_out}")
        print(f"Would write: {checksum_out}")
        print(f"Would write: {completeness_out}")
        return 0

    _ensure_directory(lock_dir, label="Lock output")

    cohort_output_fieldnames = list(cohort_fieldnames)
    for extra in ["lock_rank", "lock_key_sha256"]:
        if extra not in cohort_output_fieldnames:
            cohort_output_fieldnames.append(extra)

    try:
        _write_delimited(cohort_out, selected_rows, cohort_output_fieldnames, delimiter=",")
        _write_delimited(
            manifest_out,
            selected_manifest_rows,
            fieldnames=["id", "filename", "md5", "size", "state"],
            delimiter="\t",
        )
        provenance_out.write_text(dumps_json_pretty(provenance), encoding="utf-8")

        checksum_report["digests"].update(
            {
                "cohort_csv_sha256": sha256_file(cohort_out),
                "manifest_tsv_sha256": sha256_file(manifest_out),
                "provenance_manifest_sha256": sha256_file(provenance_out),
            }
        )
        checksum_out.write_text(dumps_json_pretty(checksum_report), encoding="utf-8")
        completeness_out.write_text(dumps_json_pretty(completeness_report), encoding="utf-8")
    except OSError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(f"Failed writing lock artifacts in {lock_dir}: {exc}") from exc

    print(f"Wrote: {cohort_out}")
    print(f"Wrote: {manifest_out}")
    print(f"Wrote: {provenance_out}")
    print(f"Wrote: {checksum_out}")
    print(f"Wrote: {completeness_out}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


def cli_entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        return main(argv)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli_entrypoint())
