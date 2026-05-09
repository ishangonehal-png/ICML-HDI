#!/usr/bin/env python3
"""Release-gate transcriptomics MVP readiness from coverage JSON outputs.

Input is the JSON payload returned by:
  GET /v1/transcriptomics/coverage

The script evaluates deterministic gate checks and exits non-zero when one or
more checks fail.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate transcriptomics release gates from coverage output JSON.",
    )
    parser.add_argument(
        "--coverage-json",
        type=Path,
        required=True,
        help="Path to transcriptomics coverage JSON payload.",
    )
    parser.add_argument(
        "--expected-cases-total",
        type=int,
        default=None,
        help="Optional expected cases_total count.",
    )
    parser.add_argument(
        "--max-missing-mvp-coverage",
        type=int,
        default=None,
        help="Fail when cases_missing_mvp_coverage exceeds this threshold.",
    )
    parser.add_argument(
        "--max-missing-tide-precompute",
        type=int,
        default=None,
        help="Fail when cases_missing_tide_precompute exceeds this threshold.",
    )
    parser.add_argument(
        "--max-missing-gep-reference",
        type=int,
        default=None,
        help="Fail when cases_missing_gep_reference exceeds this threshold.",
    )
    parser.add_argument(
        "--fail-on-release-blockers",
        action="store_true",
        help="Fail when any case has release_gate_blockers entries.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Enable strict mode: default all max-* thresholds to zero and "
            "fail on release blockers."
        ),
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Failed to read coverage JSON: {path} ({exc})") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON payload at {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Coverage payload must be a JSON object.")

    return payload


def _resolve_coverage_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary = payload.get("summary")
    cases = payload.get("cases")

    if not isinstance(summary, dict):
        raise RuntimeError("Coverage JSON is missing object field: summary")
    if not isinstance(cases, list):
        raise RuntimeError("Coverage JSON is missing list field: cases")

    normalized_cases: list[dict[str, Any]] = [case for case in cases if isinstance(case, dict)]
    return summary, normalized_cases


def _require_int(summary: dict[str, Any], key: str) -> int:
    value = summary.get(key)
    if not isinstance(value, int):
        raise RuntimeError(f"Coverage summary field '{key}' must be an integer.")
    return value


def _count_release_blocker_cases(cases: list[dict[str, Any]]) -> int:
    count = 0
    for case in cases:
        blockers = case.get("release_gate_blockers")
        if isinstance(blockers, list) and blockers:
            count += 1
    return count


def _evaluate_failures(
    *,
    summary: dict[str, Any],
    cases: list[dict[str, Any]],
    args: argparse.Namespace,
) -> list[str]:
    failures: list[str] = []

    strict = bool(args.strict)

    max_missing_mvp = args.max_missing_mvp_coverage
    max_missing_tide = args.max_missing_tide_precompute
    max_missing_gep_ref = args.max_missing_gep_reference
    fail_on_release_blockers = bool(args.fail_on_release_blockers)

    if strict:
        if max_missing_mvp is None:
            max_missing_mvp = 0
        if max_missing_tide is None:
            max_missing_tide = 0
        if max_missing_gep_ref is None:
            max_missing_gep_ref = 0
        fail_on_release_blockers = True

    cases_total = _require_int(summary, "cases_total")
    missing_mvp = _require_int(summary, "cases_missing_mvp_coverage")
    missing_tide = _require_int(summary, "cases_missing_tide_precompute")
    missing_gep_ref = _require_int(summary, "cases_missing_gep_reference")

    if args.expected_cases_total is not None and cases_total != int(args.expected_cases_total):
        failures.append(
            f"cases_total={cases_total} does not match expected_cases_total={args.expected_cases_total}"
        )

    if max_missing_mvp is not None and missing_mvp > max_missing_mvp:
        failures.append(
            f"cases_missing_mvp_coverage={missing_mvp} exceeds max_missing_mvp_coverage={max_missing_mvp}"
        )

    if max_missing_tide is not None and missing_tide > max_missing_tide:
        failures.append(
            "cases_missing_tide_precompute="
            f"{missing_tide} exceeds max_missing_tide_precompute={max_missing_tide}"
        )

    if max_missing_gep_ref is not None and missing_gep_ref > max_missing_gep_ref:
        failures.append(
            "cases_missing_gep_reference="
            f"{missing_gep_ref} exceeds max_missing_gep_reference={max_missing_gep_ref}"
        )

    blocker_cases = _count_release_blocker_cases(cases)
    if fail_on_release_blockers and blocker_cases > 0:
        failures.append(f"release_gate_blockers present in {blocker_cases} case(s)")

    return failures


def main() -> int:
    args = parse_args()

    payload = _load_json(args.coverage_json)
    summary, cases = _resolve_coverage_payload(payload)

    print("Transcriptomics coverage gate summary")
    print(f"cases_total={summary.get('cases_total')}")
    print(f"cases_missing_mvp_coverage={summary.get('cases_missing_mvp_coverage')}")
    print(f"cases_missing_tide_precompute={summary.get('cases_missing_tide_precompute')}")
    print(f"cases_missing_gep_reference={summary.get('cases_missing_gep_reference')}")

    failures = _evaluate_failures(summary=summary, cases=cases, args=args)
    if failures:
        print("FAIL: transcriptomics release gate checks failed", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("PASS: transcriptomics release gate checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
