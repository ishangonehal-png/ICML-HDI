#!/usr/bin/env python3
"""Validate pathology artifact bundle structure + manifest alignment.

Checks:
- Artifact JSON parseability and object shape
- Required sections (`tissue_composition`, `heatmap`, `evidence`)
- Section-level field sanity (fractions/viewport/top_tiles)
- Alignment to manifest slide_id/case_id universe
- Optional cross-check against coverage summary output
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audit_luad_embedding_coverage import (
    DEFAULT_ARTIFACTS_DIR,
    DEFAULT_MANIFEST,
    DEFAULT_OUT_JSON_NAME,
    best_slide_id_from_path,
    canonical_slide_id,
    extract_case_id,
    load_json_if_object,
    load_manifest_slides,
    normalize_tissue_key,
)

DEFAULT_VALIDATION_OUT_JSON_NAME = "pathology_artifact_validation_report.json"


@dataclass(frozen=True)
class ArtifactValidationIssue:
    level: str  # error|warning
    code: str
    path: str
    detail: str


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _validate_tissue_section(
    payload: dict[str, Any],
    *,
    issues: list[ArtifactValidationIssue],
    path: Path,
) -> bool:
    section = payload.get("tissue_composition")
    if not isinstance(section, dict):
        issues.append(
            ArtifactValidationIssue(
                level="error",
                code="missing_tissue_composition",
                path=str(path),
                detail="Missing or invalid 'tissue_composition' object.",
            )
        )
        return False

    fractions = section.get("fractions")
    if not isinstance(fractions, list) or not fractions:
        issues.append(
            ArtifactValidationIssue(
                level="error",
                code="invalid_tissue_fractions",
                path=str(path),
                detail="'tissue_composition.fractions' must be a non-empty list.",
            )
        )
        return False

    seen_tissues: set[str] = set()
    has_fraction_error = False
    for index, entry in enumerate(fractions):
        if not isinstance(entry, dict):
            has_fraction_error = True
            issues.append(
                ArtifactValidationIssue(
                    level="error",
                    code="invalid_tissue_fraction_entry",
                    path=str(path),
                    detail=f"fractions[{index}] is not an object.",
                )
            )
            continue

        tissue_name = normalize_tissue_key(str(entry.get("tissue", "")))
        if not tissue_name:
            has_fraction_error = True
            issues.append(
                ArtifactValidationIssue(
                    level="error",
                    code="invalid_tissue_name",
                    path=str(path),
                    detail=f"fractions[{index}].tissue is missing/unsupported.",
                )
            )
        else:
            seen_tissues.add(tissue_name)

        fraction_value = _coerce_float(entry.get("fraction"))
        if fraction_value is None or not (0.0 <= fraction_value <= 1.0):
            has_fraction_error = True
            issues.append(
                ArtifactValidationIssue(
                    level="error",
                    code="invalid_tissue_fraction_value",
                    path=str(path),
                    detail=f"fractions[{index}].fraction must be in [0, 1].",
                )
            )

    if not seen_tissues:
        has_fraction_error = True

    qc = section.get("qc")
    if not isinstance(qc, dict):
        issues.append(
            ArtifactValidationIssue(
                level="error",
                code="missing_tissue_qc",
                path=str(path),
                detail="Missing/invalid 'tissue_composition.qc' object.",
            )
        )
        return False

    coverage = _coerce_float(qc.get("coverage"))
    if coverage is None or not (0.0 <= coverage <= 1.0):
        issues.append(
            ArtifactValidationIssue(
                level="error",
                code="invalid_tissue_qc_coverage",
                path=str(path),
                detail="'tissue_composition.qc.coverage' must be in [0, 1].",
            )
        )
        return False

    return not has_fraction_error


def _validate_heatmap_section(
    payload: dict[str, Any],
    *,
    issues: list[ArtifactValidationIssue],
    path: Path,
) -> bool:
    section = payload.get("heatmap")
    if not isinstance(section, dict):
        issues.append(
            ArtifactValidationIssue(
                level="error",
                code="missing_heatmap",
                path=str(path),
                detail="Missing or invalid 'heatmap' object.",
            )
        )
        return False

    viewport = section.get("viewport_hint")
    if not isinstance(viewport, dict):
        issues.append(
            ArtifactValidationIssue(
                level="error",
                code="missing_viewport_hint",
                path=str(path),
                detail="Missing or invalid 'heatmap.viewport_hint' object.",
            )
        )
        return False

    bounds: dict[str, float] = {}
    for key in ("x", "y", "width", "height"):
        value = _coerce_float(viewport.get(key))
        if value is None or not (0.0 <= value <= 1.0):
            issues.append(
                ArtifactValidationIssue(
                    level="error",
                    code="invalid_viewport_value",
                    path=str(path),
                    detail=f"'heatmap.viewport_hint.{key}' must be in [0, 1].",
                )
            )
            return False
        bounds[key] = value

    if bounds["width"] <= 0.0 or bounds["height"] <= 0.0:
        issues.append(
            ArtifactValidationIssue(
                level="error",
                code="invalid_viewport_size",
                path=str(path),
                detail="'heatmap.viewport_hint.width/height' must be > 0.",
            )
        )
        return False

    return True


def _validate_evidence_section(
    payload: dict[str, Any],
    *,
    issues: list[ArtifactValidationIssue],
    path: Path,
) -> bool:
    section = payload.get("evidence")
    if not isinstance(section, dict):
        issues.append(
            ArtifactValidationIssue(
                level="error",
                code="missing_evidence",
                path=str(path),
                detail="Missing or invalid 'evidence' object.",
            )
        )
        return False

    top_tiles = section.get("top_tiles")
    if not isinstance(top_tiles, list) or not top_tiles:
        issues.append(
            ArtifactValidationIssue(
                level="error",
                code="invalid_top_tiles",
                path=str(path),
                detail="'evidence.top_tiles' must be a non-empty list.",
            )
        )
        return False

    has_error = False
    for index, tile in enumerate(top_tiles):
        if not isinstance(tile, dict):
            has_error = True
            issues.append(
                ArtifactValidationIssue(
                    level="error",
                    code="invalid_top_tile_entry",
                    path=str(path),
                    detail=f"top_tiles[{index}] is not an object.",
                )
            )
            continue

        tile_id = tile.get("tile_id")
        if not isinstance(tile_id, str) or not tile_id.strip():
            has_error = True
            issues.append(
                ArtifactValidationIssue(
                    level="error",
                    code="invalid_top_tile_id",
                    path=str(path),
                    detail=f"top_tiles[{index}].tile_id must be a non-empty string.",
                )
            )

        score = _coerce_float(tile.get("score"))
        if score is None or not (0.0 <= score <= 1.0):
            has_error = True
            issues.append(
                ArtifactValidationIssue(
                    level="error",
                    code="invalid_top_tile_score",
                    path=str(path),
                    detail=f"top_tiles[{index}].score must be in [0, 1].",
                )
            )

        rationale = tile.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            has_error = True
            issues.append(
                ArtifactValidationIssue(
                    level="error",
                    code="invalid_top_tile_rationale",
                    path=str(path),
                    detail=f"top_tiles[{index}].rationale must be a non-empty string.",
                )
            )

    return not has_error


def _artifact_ids(payload: dict[str, Any], path: Path) -> tuple[str, str]:
    payload_slide = payload.get("slide_id")
    payload_case = payload.get("case_id")

    slide_id = best_slide_id_from_path(path)
    if isinstance(payload_slide, str) and payload_slide.strip():
        normalized_slide = canonical_slide_id(payload_slide)
        if normalized_slide:
            slide_id = normalized_slide

    case_id = extract_case_id(slide_id) or extract_case_id(path.name)
    if isinstance(payload_case, str) and payload_case.strip():
        normalized_case = extract_case_id(payload_case)
        if normalized_case:
            case_id = normalized_case

    return slide_id, case_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate pathology artifact JSON bundle completeness and structure.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"Manifest slides TSV path (default: {DEFAULT_MANIFEST})",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
        help=f"Artifact directory containing pathology JSON files (default: {DEFAULT_ARTIFACTS_DIR})",
    )
    parser.add_argument(
        "--coverage-summary-json",
        type=Path,
        default=None,
        help=(
            "Optional path to luad_embedding_coverage_summary.json for cross-checking. "
            "Defaults to <artifacts-dir>/luad_embedding_coverage_summary.json when present."
        ),
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help=(
            "Optional explicit validation report JSON path. "
            f"Defaults to <artifacts-dir>/{DEFAULT_VALIDATION_OUT_JSON_NAME}"
        ),
    )
    parser.add_argument(
        "--max-issues-preview",
        type=int,
        default=200,
        help="Maximum number of issues to include in report preview (default: 200).",
    )
    parser.add_argument(
        "--fail-on-orphan-artifacts",
        action="store_true",
        help="Exit non-zero if artifact ids do not map to manifest slide_id/case_id.",
    )
    parser.add_argument(
        "--allow-missing-sections",
        action="store_true",
        help="Treat missing core sections as warnings (default behavior is errors).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    manifest_path = args.manifest.expanduser().resolve()
    artifacts_dir = args.artifacts_dir.expanduser().resolve()

    out_json = (
        args.out_json.expanduser().resolve()
        if args.out_json is not None
        else artifacts_dir / DEFAULT_VALIDATION_OUT_JSON_NAME
    )

    coverage_summary_path = (
        args.coverage_summary_json.expanduser().resolve()
        if args.coverage_summary_json is not None
        else artifacts_dir / DEFAULT_OUT_JSON_NAME
    )

    if out_json.exists() and not out_json.is_file():
        raise RuntimeError(f"Validation output path exists but is not a file: {out_json}")

    manifest_slides = load_manifest_slides(manifest_path)
    manifest_slide_ids = {slide.slide_id for slide in manifest_slides}
    manifest_case_ids = {slide.case_id for slide in manifest_slides if slide.case_id}

    if not artifacts_dir.exists():
        raise RuntimeError(f"Artifact directory not found: {artifacts_dir}")
    if not artifacts_dir.is_dir():
        raise RuntimeError(f"Artifact path is not a directory: {artifacts_dir}")

    issues: list[ArtifactValidationIssue] = []
    orphan_artifact_ids: set[str] = set()

    artifacts_total = 0
    artifacts_valid_json = 0
    artifacts_with_all_sections = 0
    artifacts_slide_aligned = 0
    artifacts_case_aligned = 0

    excluded_names = {out_json.name, DEFAULT_OUT_JSON_NAME}

    for artifact_path in sorted(artifacts_dir.rglob("*.json")):
        if artifact_path.name in excluded_names:
            continue

        artifacts_total += 1
        payload = load_json_if_object(artifact_path)
        if payload is None:
            issues.append(
                ArtifactValidationIssue(
                    level="error",
                    code="invalid_json_object",
                    path=str(artifact_path),
                    detail="Artifact file is not valid JSON object.",
                )
            )
            continue

        artifacts_valid_json += 1

        slide_id, case_id = _artifact_ids(payload, artifact_path)

        aligned_by_slide = bool(slide_id and slide_id in manifest_slide_ids)
        aligned_by_case = bool(case_id and case_id in manifest_case_ids)

        if aligned_by_slide:
            artifacts_slide_aligned += 1
        elif aligned_by_case:
            artifacts_case_aligned += 1
        else:
            fallback_id = slide_id or case_id or artifact_path.stem
            orphan_artifact_ids.add(fallback_id)
            issues.append(
                ArtifactValidationIssue(
                    level="warning",
                    code="orphan_artifact_identifier",
                    path=str(artifact_path),
                    detail=(
                        "Artifact id does not map to manifest slide/case universe: "
                        f"slide_id='{slide_id}', case_id='{case_id}'."
                    ),
                )
            )

        tissue_ok = _validate_tissue_section(payload, issues=issues, path=artifact_path)
        heatmap_ok = _validate_heatmap_section(payload, issues=issues, path=artifact_path)
        evidence_ok = _validate_evidence_section(payload, issues=issues, path=artifact_path)

        if args.allow_missing_sections:
            # Downgrade missing-section errors to warnings while preserving malformed-field errors.
            for index, issue in enumerate(issues):
                if issue.path != str(artifact_path):
                    continue
                if issue.code in {
                    "missing_tissue_composition",
                    "missing_heatmap",
                    "missing_evidence",
                } and issue.level == "error":
                    issues[index] = ArtifactValidationIssue(
                        level="warning",
                        code=issue.code,
                        path=issue.path,
                        detail=issue.detail,
                    )

        if tissue_ok and heatmap_ok and evidence_ok:
            artifacts_with_all_sections += 1

    coverage_summary: dict[str, Any] | None = None
    if coverage_summary_path.is_file():
        parsed = load_json_if_object(coverage_summary_path)
        if parsed is not None:
            coverage_summary = parsed
            summary_section = parsed.get("summary")
            if isinstance(summary_section, dict):
                reported_slides_total = summary_section.get("slides_total")
                if reported_slides_total is not None and int(reported_slides_total) != len(manifest_slides):
                    issues.append(
                        ArtifactValidationIssue(
                            level="warning",
                            code="coverage_manifest_size_mismatch",
                            path=str(coverage_summary_path),
                            detail=(
                                "Coverage summary slides_total does not match current manifest "
                                f"size ({reported_slides_total} vs {len(manifest_slides)})."
                            ),
                        )
                    )

    error_count = sum(1 for issue in issues if issue.level == "error")
    warning_count = sum(1 for issue in issues if issue.level == "warning")

    report = {
        "manifest_path": str(manifest_path),
        "artifacts_dir": str(artifacts_dir),
        "coverage_summary_json": str(coverage_summary_path) if coverage_summary_path else None,
        "summary": {
            "manifest_slide_count": len(manifest_slides),
            "manifest_unique_slide_count": len(manifest_slide_ids),
            "manifest_unique_case_count": len(manifest_case_ids),
            "artifacts_total": artifacts_total,
            "artifacts_valid_json": artifacts_valid_json,
            "artifacts_with_all_sections": artifacts_with_all_sections,
            "artifacts_aligned_by_slide": artifacts_slide_aligned,
            "artifacts_aligned_by_case": artifacts_case_aligned,
            "orphan_artifact_count": len(orphan_artifact_ids),
            "orphan_artifact_ids": sorted(orphan_artifact_ids),
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "issues_preview": [
            {
                "level": issue.level,
                "code": issue.code,
                "path": issue.path,
                "detail": issue.detail,
            }
            for issue in issues[: max(0, int(args.max_issues_preview))]
        ],
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("Pathology artifact validation complete")
    print(f"manifest_slide_count={len(manifest_slides)}")
    print(f"artifacts_total={artifacts_total}")
    print(f"artifacts_valid_json={artifacts_valid_json}")
    print(f"artifacts_with_all_sections={artifacts_with_all_sections}")
    print(f"orphan_artifact_count={len(orphan_artifact_ids)}")
    print(f"error_count={error_count}")
    print(f"warning_count={warning_count}")
    print(f"validation_report={out_json}")

    should_fail = error_count > 0
    if args.fail_on_orphan_artifacts and orphan_artifact_ids:
        should_fail = True

    return 1 if should_fail else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
