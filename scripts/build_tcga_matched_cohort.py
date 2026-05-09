#!/usr/bin/env python3
"""Build a TCGA cohort matched at the patient level across:
- clinical reports (pathology report, clinical supplement txt, and clinical supplement xml),
- RNA profiles, and
- H&E slides.

This script queries the GDC API and creates:
1) A cohort CSV where each row is one matched patient/case.
2) A GDC manifest TSV for the selected RNA + H&E + clinical files per patient.

Usage examples:
  python3 scripts/build_tcga_matched_cohort.py --project TCGA-LUAD
  python3 scripts/build_tcga_matched_cohort.py --project TCGA-LUAD --patient TCGA-05-4244
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


GDC_API_BASE = "https://api.gdc.cancer.gov"


def _post_json(endpoint: str, payload: Dict[str, str]) -> Dict:
    url = f"{GDC_API_BASE}{endpoint}"
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GDC API error {exc.code} for {endpoint}: {body[:500]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach GDC API ({endpoint}). Check network connectivity."
        ) from exc


def _fetch_all(
    endpoint: str,
    filters: Dict,
    fields: Optional[Iterable[str]] = None,
    expand: Optional[str] = None,
    page_size: int = 2000,
) -> List[Dict]:
    hits: List[Dict] = []
    offset = 0
    fields_arg = ",".join(fields) if fields else None

    while True:
        payload: Dict[str, str] = {
            "filters": json.dumps(filters),
            "format": "JSON",
            "size": str(page_size),
            "from": str(offset),
        }
        if fields_arg:
            payload["fields"] = fields_arg
        if expand:
            payload["expand"] = expand

        data = _post_json(endpoint, payload)
        page_hits = data.get("data", {}).get("hits", [])
        total = data.get("data", {}).get("pagination", {}).get("total", 0)

        hits.extend(page_hits)
        offset += len(page_hits)
        if not page_hits or offset >= total:
            break

    return hits


def _build_case_filters(project: str) -> Dict:
    return {
        "op": "in",
        "content": {"field": "project.project_id", "value": [project]},
    }


def _build_rna_file_filters(project: str) -> Dict:
    return {
        "op": "and",
        "content": [
            {"op": "in", "content": {"field": "cases.project.project_id", "value": [project]}},
            {"op": "in", "content": {"field": "data_category", "value": ["Transcriptome Profiling"]}},
            {"op": "in", "content": {"field": "data_type", "value": ["Gene Expression Quantification"]}},
            {"op": "in", "content": {"field": "experimental_strategy", "value": ["RNA-Seq"]}},
            {"op": "in", "content": {"field": "access", "value": ["open"]}},
        ],
    }


def _build_slide_file_filters(project: str) -> Dict:
    return {
        "op": "and",
        "content": [
            {"op": "in", "content": {"field": "cases.project.project_id", "value": [project]}},
            {"op": "in", "content": {"field": "data_type", "value": ["Slide Image"]}},
            {"op": "in", "content": {"field": "experimental_strategy", "value": ["Diagnostic Slide"]}},
            {"op": "in", "content": {"field": "access", "value": ["open"]}},
        ],
    }


def _build_clinical_file_filters(project: str) -> Dict:
    return {
        "op": "and",
        "content": [
            {"op": "in", "content": {"field": "cases.project.project_id", "value": [project]}},
            {"op": "in", "content": {"field": "data_category", "value": ["Clinical"]}},
            {"op": "in", "content": {"field": "access", "value": ["open"]}},
        ],
    }


def _first_or_empty(items: List[Dict]) -> Dict:
    return items[0] if items else {}


def _age_days_to_years(age_days: Optional[object]) -> str:
    if age_days is None:
        return ""
    try:
        age = float(age_days) / 365.25
        return f"{age:.1f}"
    except (ValueError, TypeError):
        return ""


def _best_rna_file(files: List[Dict]) -> Dict:
    # Prefer count-based quantifications first, then normalized variants.
    workflow_rank = {
        "STAR - Counts": 0,
        "HTSeq - Counts": 1,
        "STAR - FPKM": 2,
        "STAR - FPKM-UQ": 3,
        "HTSeq - FPKM": 4,
        "HTSeq - FPKM-UQ": 5,
    }

    def score(f: Dict) -> Tuple[int, str]:
        workflow = (f.get("analysis") or {}).get("workflow_type") or ""
        return (workflow_rank.get(workflow, 99), f.get("file_name", ""))

    return sorted(files, key=score)[0]


def _best_slide_file(files: List[Dict]) -> Dict:
    svs_files = [f for f in files if str(f.get("file_name", "")).lower().endswith(".svs")]
    candidates = svs_files if svs_files else files

    def score(f: Dict) -> Tuple[int, str]:
        name = str(f.get("file_name", ""))
        match = re.search(r"-DX(\d+)", name, re.IGNORECASE)
        if match:
            return (int(match.group(1)), name)
        return (99, name)

    return sorted(candidates, key=score)[0]


def _is_pathology_report_file(file: Dict) -> bool:
    return (file.get("data_type") or "") == "Pathology Report"


def _is_clinical_xml_file(file: Dict) -> bool:
    filename = str(file.get("file_name") or "").lower()
    return (file.get("data_type") or "") == "Clinical Supplement" and filename.endswith(".xml")


def _is_clinical_supplement_file(file: Dict) -> bool:
    return (file.get("data_type") or "") == "Clinical Supplement" and not _is_clinical_xml_file(file)


def _best_clinical_supplement_file(files: List[Dict]) -> Dict:
    # Prefer patient-level supplement files first, then stable lexical order.
    def score(f: Dict) -> Tuple[int, str]:
        name = str(f.get("file_name", "")).lower()
        if "clinical_patient" in name:
            rank = 0
        elif "clinical_drug" in name:
            rank = 1
        elif "clinical_follow" in name:
            rank = 2
        elif "clinical_radiation" in name:
            rank = 3
        elif "clinical_omf" in name:
            rank = 4
        else:
            rank = 5
        return (rank, name)

    return sorted(files, key=score)[0]


def _best_pathology_report_file(files: List[Dict]) -> Dict:
    return sorted(files, key=lambda f: (f.get("file_name", "")))[0]


def _best_clinical_xml_file(files: List[Dict]) -> Dict:
    return sorted(files, key=lambda f: (f.get("file_name", "")))[0]


def _index_files_by_case(files: List[Dict]) -> Dict[str, List[Dict]]:
    by_case: Dict[str, List[Dict]] = {}
    for f in files:
        for c in f.get("cases", []):
            case_id = c.get("case_id")
            if not case_id:
                continue
            by_case.setdefault(case_id, []).append(f)
    return by_case


def _extract_clinical(case: Dict) -> Dict[str, str]:
    demographic = case.get("demographic") or {}
    diagnosis = _first_or_empty(case.get("diagnoses") or [])
    exposure = _first_or_empty(case.get("exposures") or [])

    age_days = diagnosis.get("age_at_diagnosis")
    return {
        "project_id": ((case.get("project") or {}).get("project_id") or ""),
        "case_id": case.get("case_id", ""),
        "patient_id": case.get("submitter_id", ""),
        "gender": demographic.get("gender", ""),
        "race": demographic.get("race", ""),
        "ethnicity": demographic.get("ethnicity", ""),
        "vital_status": demographic.get("vital_status", ""),
        "age_at_diagnosis_days": "" if age_days is None else str(age_days),
        "age_at_diagnosis_years": _age_days_to_years(age_days),
        "primary_diagnosis": diagnosis.get("primary_diagnosis", ""),
        "tumor_stage": diagnosis.get("tumor_stage", ""),
        "smoking_status": exposure.get("tobacco_smoking_status", ""),
    }


def _write_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_manifest(path: Path, file_rows: List[Dict]) -> None:
    fieldnames = ["id", "filename", "md5", "size", "state"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in file_rows:
            writer.writerow(
                {
                    "id": row.get("file_id", ""),
                    "filename": row.get("file_name", ""),
                    "md5": row.get("md5sum", ""),
                    "size": row.get("file_size", ""),
                    "state": row.get("state", ""),
                }
            )


def _filter_rows_for_patient(rows: List[Dict[str, str]], patient: str) -> List[Dict[str, str]]:
    patient_lower = patient.lower()
    return [
        row
        for row in rows
        if row.get("patient_id", "").lower() == patient_lower
        or row.get("case_id", "").lower() == patient_lower
    ]


def build_matched_cohort(project: str, patient: Optional[str]) -> Tuple[List[Dict[str, str]], List[Dict]]:
    cases = _fetch_all(
        endpoint="/cases",
        filters=_build_case_filters(project),
        expand="project,demographic,diagnoses,exposures",
    )
    clinical_metadata_by_case = {case["case_id"]: _extract_clinical(case) for case in cases if case.get("case_id")}

    file_fields = [
        "file_id",
        "file_name",
        "md5sum",
        "file_size",
        "state",
        "analysis.workflow_type",
        "cases.case_id",
        "cases.submitter_id",
    ]

    rna_files = _fetch_all(
        endpoint="/files",
        filters=_build_rna_file_filters(project),
        fields=file_fields,
    )
    slide_files = _fetch_all(
        endpoint="/files",
        filters=_build_slide_file_filters(project),
        fields=file_fields,
    )
    clinical_files = _fetch_all(
        endpoint="/files",
        filters=_build_clinical_file_filters(project),
        fields=file_fields + ["data_type"],
    )

    rna_by_case = _index_files_by_case(rna_files)
    slide_by_case = _index_files_by_case(slide_files)
    clinical_by_case = _index_files_by_case(clinical_files)

    def _has_required_clinical(files_for_case: List[Dict]) -> bool:
        has_pathology = any(_is_pathology_report_file(f) for f in files_for_case)
        has_supplement = any(_is_clinical_supplement_file(f) for f in files_for_case)
        has_xml = any(_is_clinical_xml_file(f) for f in files_for_case)
        return has_pathology and has_supplement and has_xml

    matched_case_ids = sorted(
        set(clinical_by_case) & set(rna_by_case) & set(slide_by_case)
    )
    matched_case_ids = [
        case_id
        for case_id in matched_case_ids
        if _has_required_clinical(clinical_by_case.get(case_id, []))
    ]
    rows: List[Dict[str, str]] = []
    selected_files: List[Dict] = []

    for case_id in matched_case_ids:
        clinical = clinical_metadata_by_case[case_id]
        rna_for_case = rna_by_case[case_id]
        slides_for_case = slide_by_case[case_id]
        clinical_for_case = clinical_by_case[case_id]
        chosen_rna = _best_rna_file(rna_for_case)
        chosen_slide = _best_slide_file(slides_for_case)
        chosen_clinical_supplement = _best_clinical_supplement_file(
            [f for f in clinical_for_case if _is_clinical_supplement_file(f)]
        )
        chosen_clinical_xml = _best_clinical_xml_file(
            [f for f in clinical_for_case if _is_clinical_xml_file(f)]
        )
        chosen_pathology = _best_pathology_report_file(
            [f for f in clinical_for_case if _is_pathology_report_file(f)]
        )

        row = {
            **clinical,
            "n_rna_files": str(len(rna_for_case)),
            "selected_rna_file_id": chosen_rna.get("file_id", ""),
            "selected_rna_file_name": chosen_rna.get("file_name", ""),
            "selected_rna_workflow": (chosen_rna.get("analysis") or {}).get("workflow_type", ""),
            "n_slide_files": str(len(slides_for_case)),
            "selected_slide_file_id": chosen_slide.get("file_id", ""),
            "selected_slide_file_name": chosen_slide.get("file_name", ""),
            "selected_clinical_supplement_file_id": chosen_clinical_supplement.get("file_id", ""),
            "selected_clinical_supplement_file_name": chosen_clinical_supplement.get("file_name", ""),
            "selected_clinical_xml_file_id": chosen_clinical_xml.get("file_id", ""),
            "selected_clinical_xml_file_name": chosen_clinical_xml.get("file_name", ""),
            "selected_pathology_report_file_id": chosen_pathology.get("file_id", ""),
            "selected_pathology_report_file_name": chosen_pathology.get("file_name", ""),
        }
        rows.append(row)
        selected_files.extend(
            [
                chosen_rna,
                chosen_slide,
                chosen_clinical_supplement,
                chosen_clinical_xml,
                chosen_pathology,
            ]
        )

    if patient:
        rows = _filter_rows_for_patient(rows, patient)
        if not rows:
            raise RuntimeError(
                f"Patient '{patient}' not found with matched clinical + RNA + H&E data in {project}."
            )
        keep_ids = {
            file_id
            for row in rows
            for file_id in [
                row["selected_rna_file_id"],
                row["selected_slide_file_id"],
                row["selected_clinical_supplement_file_id"],
                row["selected_clinical_xml_file_id"],
                row["selected_pathology_report_file_id"],
            ]
            if file_id
        }
        selected_files = [f for f in selected_files if f.get("file_id") in keep_ids]

    # Deduplicate selected files by file_id.
    by_id: Dict[str, Dict] = {}
    for f in selected_files:
        file_id = f.get("file_id")
        if file_id:
            by_id[file_id] = f

    return rows, list(by_id.values())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build matched TCGA cohort with clinical reports (pathology + clinical supplement + "
            "clinical XML), transcriptome, and H&E slides."
        )
    )
    parser.add_argument("--project", default="TCGA-LUAD", help="GDC project id (default: TCGA-LUAD)")
    parser.add_argument(
        "--patient",
        default=None,
        help="Optional patient/case identifier (e.g., TCGA-05-4244 or case UUID) to filter to one matched patient.",
    )
    parser.add_argument(
        "--out-csv",
        default="outputs/tcga_matched_cohort.csv",
        help="Output CSV path for matched cohort rows.",
    )
    parser.add_argument(
        "--out-manifest",
        default="outputs/tcga_matched_manifest.tsv",
        help="Output GDC manifest TSV path for selected files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_csv = Path(args.out_csv).resolve()
    out_manifest = Path(args.out_manifest).resolve()
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_manifest.parent.mkdir(parents=True, exist_ok=True)

    rows, selected_files = build_matched_cohort(project=args.project, patient=args.patient)
    _write_csv(out_csv, rows)
    _write_manifest(out_manifest, selected_files)

    print(f"Project: {args.project}")
    print(f"Matched patients: {len(rows)}")
    if rows:
        print(
            "Example patient:",
            rows[0].get("patient_id", ""),
            f"(case {rows[0].get('case_id', '')})",
        )
    print(f"Cohort CSV: {out_csv}")
    print(f"Manifest TSV: {out_manifest}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
