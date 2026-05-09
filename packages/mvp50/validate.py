#!/usr/bin/env python3
"""Validate TCGA matched cohort completeness against the canonical data contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .constants import DEFAULT_COHORT, DEFAULT_SCHEMA
from .data_contract_utils import (
    build_completeness_report,
    dumps_json_pretty,
    evaluate_cohort_completeness,
    load_and_validate_cohort_rows,
    resolve_schema_and_modalities,
)


def add_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--cohort-csv",
        type=Path,
        default=DEFAULT_COHORT,
        help=f"Matched cohort CSV path (default: {DEFAULT_COHORT})",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help=f"Contract schema JSON (default: {DEFAULT_SCHEMA})",
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
        "--report-json",
        type=Path,
        default=None,
        help="Optional path to write validation report JSON.",
    )
    parser.add_argument(
        "--max-missing-preview",
        type=int,
        default=10,
        help="Max number of incomplete-case examples to print to stdout (default: 10).",
    )
    parser.add_argument(
        "--fail-on-missing",
        action="store_true",
        help="Exit with code 1 when incomplete cases are found.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run checks and print results without writing report files.",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate that each case in a matched TCGA cohort has all required modalities "
            "defined by the canonical data contract."
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


def _ensure_parent_directory(path: Path, *, label: str) -> None:
    parent = path.parent
    if parent.exists() and not parent.is_dir():
        raise RuntimeError(f"Cannot write {label}; parent exists but is not a directory: {parent}")
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - environment/permission dependent
        raise RuntimeError(
            f"Failed to create parent directory for {label} '{path}': {exc}"
        ) from exc


def run(args: argparse.Namespace) -> int:
    _ensure_input_file(args.cohort_csv, flag="--cohort-csv", label="Cohort CSV")
    _ensure_input_file(args.schema, flag="--schema", label="Schema JSON")

    schema, modality_requirements, required_modalities = resolve_schema_and_modalities(
        args.schema,
        args.required_modalities,
    )

    _fieldnames, rows = load_and_validate_cohort_rows(args.cohort_csv, schema)

    completeness = evaluate_cohort_completeness(
        rows=rows,
        required_modalities=required_modalities,
        modality_requirements=modality_requirements,
    )

    report = build_completeness_report(
        schema=schema,
        cohort_csv=args.cohort_csv,
        required_modalities=required_modalities,
        completeness=completeness,
    )

    print(f"Contract: {report['contract_name']} v{report['contract_version']}")
    print(f"Cohort CSV: {report['cohort_csv']}")
    print(f"Total cases: {report['summary']['total_cases']}")
    print(f"Complete cases: {report['summary']['complete_cases']}")
    print(f"Incomplete cases: {report['summary']['incomplete_cases']}")

    preview_limit = max(0, args.max_missing_preview)
    if report["missing_cases"] and preview_limit:
        print(f"Incomplete case preview (max {preview_limit}):")
        for item in report["missing_cases"][:preview_limit]:
            case_id = item.get("case_id") or ""
            patient_id = item.get("patient_id") or ""
            missing = ", ".join(item.get("missing_modalities") or [])
            print(f"  - case_id={case_id} patient_id={patient_id} missing=[{missing}]")

    if args.report_json and not args.dry_run:
        _ensure_parent_directory(args.report_json, label="report JSON")
        try:
            args.report_json.write_text(dumps_json_pretty(report), encoding="utf-8")
        except OSError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(f"Failed writing report JSON {args.report_json}: {exc}") from exc
        print(f"Report JSON: {args.report_json.resolve()}")
    elif args.report_json and args.dry_run:
        print(f"Dry-run enabled: skipped writing {args.report_json}")

    if args.fail_on_missing and report["summary"]["incomplete_cases"] > 0:
        return 1
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
