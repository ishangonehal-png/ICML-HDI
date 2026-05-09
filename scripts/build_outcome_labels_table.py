#!/usr/bin/env python3
"""Build a per-case outcome labels table for LUAD (survival, event, binary outcomes).

Reads cohort CSV and clinical XML (or a directory of XMLs keyed by case_id), extracts
vital_status, days_to_death, days_to_last_follow_up, and writes a table suitable for
joining with embeddings and training survival models.

Usage:
  python scripts/build_outcome_labels_table.py \\
    --cohort-csv hansons-context/tcga_downloads/tcga_luad_exact_matched_cohort.csv \\
    --clinical-xml-dir /path/to/clinical/xml \\
    --out labels/survival_labels.csv

See docs/architecture/luad-outcome-labels-for-training.md for label definitions.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# Tag names used in TCGA clinical XML (aligned with apps/api/services/clinical.py).
TAG_VITAL_STATUS = "vital_status"
TAG_DAYS_TO_DEATH = "days_to_death"
TAG_DAYS_TO_LAST_FOLLOWUP = ("days_to_last_followup", "days_to_last_follow_up")

HORIZONS_DAYS = (365, 730, 1825)  # 1yr, 2yr, 5yr


def _first_int(*values: Any) -> int | None:
    for v in values:
        if v is None:
            continue
        if isinstance(v, int):
            return v
        s = str(v).strip()
        if not s:
            continue
        try:
            return int(float(s))
        except (ValueError, TypeError):
            continue
    return None


def _normalize_vital_status(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s or s in ("na", "n/a", "unknown", "not reported"):
        return None
    if s in ("dead", "deceased"):
        return "Dead"
    if s in ("alive", "living"):
        return "Alive"
    return value.strip() if isinstance(value, str) else s


def _extract_tag_text(root: ET.Element) -> dict[str, str]:
    """Build a flat tag -> text map from XML (nested tags; last wins)."""
    out: dict[str, str] = {}

    def walk(el: ET.Element) -> None:
        tag = (el.tag or "").split("}")[-1].strip()
        if tag:
            text = (el.text or "").strip()
            if text:
                out[tag] = text
        for child in el:
            walk(child)
        tail = (el.tail or "").strip()
        if tail and tag:
            out[tag] = tail

    walk(root)
    return out


def parse_clinical_xml(path: Path) -> dict[str, Any] | None:
    """Parse a single TCGA-style clinical XML; return dict with vital_status, days_to_death, days_to_last_follow_up."""
    if not path.is_file():
        return None
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except (ET.ParseError, OSError):
        return None
    tag_values = _extract_tag_text(root)

    vital_status = _normalize_vital_status(
        tag_values.get(TAG_VITAL_STATUS)
    )
    days_to_death = _first_int(tag_values.get(TAG_DAYS_TO_DEATH))
    days_to_follow = _first_int(
        tag_values.get(k) for k in TAG_DAYS_TO_LAST_FOLLOWUP
    )

    return {
        "vital_status": vital_status,
        "days_to_death": days_to_death,
        "days_to_last_follow_up": days_to_follow,
    }


def resolve_xml_for_case(clinical_xml_dir: Path, case_id: str, patient_id: str) -> Path | None:
    """Find best-matching XML file for a case under clinical_xml_dir."""
    if not clinical_xml_dir.is_dir():
        return None
    # Try exact and prefix matches (simplified; full logic in pathology_id_resolution).
    candidates = [
        clinical_xml_dir / f"{case_id}.xml",
        clinical_xml_dir / f"{patient_id}.xml",
    ]
    for p in candidates:
        if p.is_file():
            return p
    for p in sorted(clinical_xml_dir.rglob("*.xml")):
        if case_id in p.name or (patient_id and patient_id in p.name):
            return p
    return None


def compute_outcome_row(
    case_id: str,
    patient_id: str,
    parsed: dict[str, Any],
) -> dict[str, Any]:
    """Compute survival_time_days, event, and optional binary outcomes."""
    vital = parsed.get("vital_status") or ""
    is_dead = vital.lower() in ("dead", "deceased")
    days_death = parsed.get("days_to_death")
    days_follow = parsed.get("days_to_last_follow_up")

    if is_dead and days_death is not None:
        survival_time_days = days_death
        event = 1
    elif days_follow is not None:
        survival_time_days = days_follow
        event = 1 if is_dead else 0
    else:
        survival_time_days = None
        event = None

    row = {
        "case_id": case_id,
        "patient_id": patient_id,
        "vital_status": vital or "",
        "days_to_death": "" if days_death is None else str(days_death),
        "days_to_last_follow_up": "" if days_follow is None else str(days_follow),
        "survival_time_days": "" if survival_time_days is None else str(survival_time_days),
        "event": "" if event is None else str(event),
    }

    for horizon_days in HORIZONS_DAYS:
        key = f"survived_{horizon_days // 365}yr"
        if survival_time_days is None or event is None:
            row[key] = ""
        elif event == 0:
            # Censored before horizon: unknown
            row[key] = "" if survival_time_days < horizon_days else "1"
        else:
            # Dead: 1 if survived at least horizon_days, else 0
            row[key] = "1" if survival_time_days >= horizon_days else "0"

    return row


def load_cohort_rows(cohort_csv: Path) -> list[dict[str, str]]:
    """Load cohort CSV; expect case_id and optionally patient_id."""
    if not cohort_csv.is_file():
        return []
    with cohort_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build outcome labels table (survival, event, 1/2/5yr) from cohort + clinical XML."
    )
    parser.add_argument(
        "--cohort-csv",
        type=Path,
        default=REPO_ROOT / "hansons-context/tcga_downloads/tcga_luad_exact_matched_cohort.csv",
        help="Cohort CSV with case_id (and optionally patient_id).",
    )
    parser.add_argument(
        "--clinical-xml-dir",
        type=Path,
        default=None,
        help="Directory of clinical XML files (default: CLINICAL_XML_DIR env).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "data/manifests/outcome_labels.csv",
        help="Output CSV path.",
    )
    parser.add_argument(
        "--missing-report",
        type=Path,
        default=None,
        help="Optional path to write case_ids missing XML.",
    )
    args = parser.parse_args()

    clinical_xml_dir = args.clinical_xml_dir
    if clinical_xml_dir is None:
        raw = os.getenv("CLINICAL_XML_DIR", "").strip()
        clinical_xml_dir = Path(raw).expanduser() if raw else REPO_ROOT / "hansons-context/tcga_downloads/clinical/xml"

    cohort_rows = load_cohort_rows(args.cohort_csv)
    if not cohort_rows:
        print("No cohort rows found; ensure --cohort-csv exists and has case_id.", file=sys.stderr)
        return 1

    out_rows: list[dict[str, Any]] = []
    missing: list[str] = []

    for row in cohort_rows:
        case_id = (row.get("case_id") or "").strip()
        patient_id = (row.get("patient_id") or case_id).strip()
        if not case_id:
            continue

        xml_path = resolve_xml_for_case(clinical_xml_dir, case_id, patient_id)
        if xml_path is None:
            missing.append(case_id)
            parsed = {}
        else:
            parsed = parse_clinical_xml(xml_path) or {}

        out_rows.append(
            compute_outcome_row(case_id, patient_id, parsed)
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case_id", "patient_id", "vital_status",
        "days_to_death", "days_to_last_follow_up",
        "survival_time_days", "event",
        "survived_1yr", "survived_2yr", "survived_5yr",
    ]
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(out_rows)

    n_with_time = sum(1 for r in out_rows if r.get("survival_time_days"))
    print(f"Wrote {len(out_rows)} rows to {args.out}")
    print(f"  With survival time: {n_with_time}")
    if missing:
        print(f"  Missing XML: {len(missing)} cases", file=sys.stderr)
        if args.missing_report:
            args.missing_report.parent.mkdir(parents=True, exist_ok=True)
            args.missing_report.write_text("\n".join(missing), encoding="utf-8")
            print(f"  Missing case_ids written to {args.missing_report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
