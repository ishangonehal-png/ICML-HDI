#!/usr/bin/env python3
"""Download TCGA-LUAD clinical XMLs and pathology report PDFs from the GDC API.

Organizes downloads by case_id into a structured output directory:

  <output_dir>/
    xmls/                          # one XML per case: {case_id}.xml
    reports/                       # one PDF per case: {case_id}.pdf
    download_manifest.json         # case_id → {xml_path, report_path, gdc_ids, md5s}

Idempotent: skips files that are already present and pass md5 verification.
Does not require gdc-client; uses the GDC REST API directly.

Usage:
  python3 scripts/download_clinical_data.py \\
    --cohort-csv data/manifests/tcga_luad_mvp50_v1/cohort.csv \\
    --output-dir data/clinical

  # Download only for MVP50 cases (filter by case IDs in a second CSV):
  python3 scripts/download_clinical_data.py \\
    --cohort-csv data/manifests/tcga_luad_mvp50_v1/cohort.csv \\
    --output-dir data/clinical --fail-on-missing
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple


GDC_API_BASE = "https://api.gdc.cancer.gov"
_RETRY_DELAYS = (2, 5, 15)


# ---------------------------------------------------------------------------
# GDC API helpers (reuse patterns from build_tcga_matched_cohort.py)
# ---------------------------------------------------------------------------

def _post_json(endpoint: str, payload: Dict[str, str]) -> Dict:
    url = f"{GDC_API_BASE}{endpoint}"
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GDC API error {exc.code} for {endpoint}: {body[:500]}"
            ) from exc
        except urllib.error.URLError as exc:
            if delay is None:
                raise RuntimeError(
                    f"GDC API unreachable after {attempt} attempts: {exc}"
                ) from exc
            print(f"  [warn] network error (attempt {attempt}), retrying in {delay}s: {exc}")
            time.sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover


def _fetch_all(
    endpoint: str,
    filters: Dict,
    fields: List[str],
    page_size: int = 2000,
) -> List[Dict]:
    hits: List[Dict] = []
    offset = 0
    while True:
        payload: Dict[str, str] = {
            "filters": json.dumps(filters),
            "fields": ",".join(fields),
            "format": "JSON",
            "size": str(page_size),
            "from": str(offset),
        }
        data = _post_json(endpoint, payload)
        page_hits = data.get("data", {}).get("hits", [])
        total = data.get("data", {}).get("pagination", {}).get("total", 0)
        hits.extend(page_hits)
        offset += len(page_hits)
        if not page_hits or offset >= total:
            break
    return hits


# ---------------------------------------------------------------------------
# GDC file queries
# ---------------------------------------------------------------------------

def _clinical_file_filters(project: str) -> Dict:
    return {
        "op": "and",
        "content": [
            {"op": "in", "content": {"field": "cases.project.project_id", "value": [project]}},
            {"op": "in", "content": {"field": "data_category", "value": ["Clinical"]}},
            {"op": "in", "content": {"field": "access", "value": ["open"]}},
        ],
    }


def _pathology_report_filters(project: str) -> Dict:
    return {
        "op": "and",
        "content": [
            {"op": "in", "content": {"field": "cases.project.project_id", "value": [project]}},
            {"op": "in", "content": {"field": "data_type", "value": ["Pathology Report"]}},
            {"op": "in", "content": {"field": "access", "value": ["open"]}},
        ],
    }


_FILE_FIELDS = [
    "file_id",
    "file_name",
    "data_type",
    "data_format",
    "md5sum",
    "file_size",
    "cases.case_id",
    "cases.submitter_id",
]


def _index_by_case(files: List[Dict]) -> Dict[str, List[Dict]]:
    by_case: Dict[str, List[Dict]] = {}
    for f in files:
        for c in f.get("cases", []):
            case_id = c.get("case_id") or c.get("submitter_id")
            if case_id:
                by_case.setdefault(case_id, []).append(f)
    return by_case


def _best_clinical_xml(files: List[Dict]) -> Optional[Dict]:
    candidates = [
        f for f in files
        if (f.get("data_type") or "") == "Clinical Supplement"
        and str(f.get("file_name", "")).lower().endswith(".xml")
    ]
    if not candidates:
        return None
    # Prefer patient-level files
    def _rank(f: Dict) -> Tuple[int, str]:
        name = str(f.get("file_name", "")).lower()
        return (0 if "clinical_patient" in name else 1, name)
    return sorted(candidates, key=_rank)[0]


def _best_pathology_report(files: List[Dict]) -> Optional[Dict]:
    candidates = [
        f for f in files
        if (f.get("data_type") or "") == "Pathology Report"
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda f: f.get("file_name", ""))[0]


# ---------------------------------------------------------------------------
# File download
# ---------------------------------------------------------------------------

def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_file(file_id: str, dest: Path, expected_md5: Optional[str]) -> bool:
    """Download a single GDC file. Returns True if downloaded, False if skipped."""
    if dest.exists() and expected_md5:
        if _md5(dest) == expected_md5:
            return False  # already present and valid

    url = f"{GDC_API_BASE}/data/{file_id}"
    for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "tcga-luad-ehr-downloader/1.0")
            with urllib.request.urlopen(req, timeout=300) as resp:
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(".tmp")
                with tmp.open("wb") as fh:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        fh.write(chunk)
                tmp.rename(dest)
            if expected_md5 and _md5(dest) != expected_md5:
                dest.unlink(missing_ok=True)
                raise RuntimeError(f"md5 mismatch for {file_id}")
            return True
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} downloading {file_id}") from exc
        except (urllib.error.URLError, OSError) as exc:
            if delay is None:
                raise RuntimeError(
                    f"Download failed after {attempt} attempts: {file_id}: {exc}"
                ) from exc
            print(f"  [warn] download error (attempt {attempt}), retrying in {delay}s")
            time.sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _load_case_ids(cohort_csv: Path) -> List[str]:
    case_ids: List[str] = []
    with cohort_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = (row.get("case_id") or "").strip()
            if cid:
                case_ids.append(cid)
    return case_ids


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download TCGA-LUAD clinical XMLs and pathology report PDFs."
    )
    parser.add_argument(
        "--cohort-csv",
        required=True,
        type=Path,
        help="Cohort CSV with case_id column (from build_tcga_matched_cohort.py or mvp50 lock).",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Root output directory. Subdirs xmls/ and reports/ will be created.",
    )
    parser.add_argument(
        "--project",
        default="TCGA-LUAD",
        help="GDC project ID (default: TCGA-LUAD).",
    )
    parser.add_argument(
        "--fail-on-missing",
        action="store_true",
        help="Exit non-zero if any case is missing a clinical XML or pathology report.",
    )
    args = parser.parse_args(argv)

    cohort_csv: Path = args.cohort_csv
    output_dir: Path = args.output_dir
    project: str = args.project

    if not cohort_csv.exists():
        print(f"ERROR: cohort CSV not found: {cohort_csv}", file=sys.stderr)
        return 1

    case_ids = _load_case_ids(cohort_csv)
    if not case_ids:
        print("ERROR: cohort CSV contains no case_id entries.", file=sys.stderr)
        return 1

    case_id_set = set(case_ids)
    print(f"Loaded {len(case_ids)} cases from {cohort_csv}")

    xml_dir = output_dir / "xmls"
    report_dir = output_dir / "reports"
    xml_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    # Query GDC for all clinical + pathology report files
    print(f"\nQuerying GDC for clinical supplement files ({project})...")
    clinical_files = _fetch_all(
        "/files",
        filters=_clinical_file_filters(project),
        fields=_FILE_FIELDS,
    )
    print(f"  Found {len(clinical_files)} clinical files.")

    print(f"Querying GDC for pathology report files ({project})...")
    report_files = _fetch_all(
        "/files",
        filters=_pathology_report_filters(project),
        fields=_FILE_FIELDS,
    )
    print(f"  Found {len(report_files)} pathology report files.")

    clinical_by_case = _index_by_case(clinical_files)
    report_by_case = _index_by_case(report_files)

    manifest: Dict[str, Dict] = {}
    missing_xml: List[str] = []
    missing_report: List[str] = []
    n_xml_downloaded = 0
    n_xml_skipped = 0
    n_report_downloaded = 0
    n_report_skipped = 0

    print(f"\nDownloading files for {len(case_ids)} cases...\n")

    for i, case_id in enumerate(case_ids, start=1):
        prefix = f"[{i:>3}/{len(case_ids)}] {case_id}"
        entry: Dict = {"case_id": case_id, "xml": None, "report": None}

        # --- Clinical XML ---
        xml_file = _best_clinical_xml(clinical_by_case.get(case_id, []))
        if xml_file is None:
            print(f"{prefix}  XML: NOT FOUND in GDC")
            missing_xml.append(case_id)
        else:
            dest = xml_dir / f"{case_id}.xml"
            try:
                downloaded = _download_file(
                    xml_file["file_id"], dest, xml_file.get("md5sum")
                )
                if downloaded:
                    print(f"{prefix}  XML: downloaded ({xml_file['file_name']})")
                    n_xml_downloaded += 1
                else:
                    print(f"{prefix}  XML: already present, md5 ok")
                    n_xml_skipped += 1
                entry["xml"] = {
                    "path": str(dest),
                    "gdc_file_id": xml_file["file_id"],
                    "file_name": xml_file.get("file_name"),
                    "md5": xml_file.get("md5sum"),
                }
            except RuntimeError as exc:
                print(f"{prefix}  XML: DOWNLOAD ERROR — {exc}")
                missing_xml.append(case_id)

        # --- Pathology Report PDF ---
        rpt_file = _best_pathology_report(report_by_case.get(case_id, []))
        if rpt_file is None:
            print(f"{prefix}  PDF: NOT FOUND in GDC")
            missing_report.append(case_id)
        else:
            dest = report_dir / f"{case_id}.pdf"
            try:
                downloaded = _download_file(
                    rpt_file["file_id"], dest, rpt_file.get("md5sum")
                )
                if downloaded:
                    print(f"{prefix}  PDF: downloaded ({rpt_file['file_name']})")
                    n_report_downloaded += 1
                else:
                    print(f"{prefix}  PDF: already present, md5 ok")
                    n_report_skipped += 1
                entry["report"] = {
                    "path": str(dest),
                    "gdc_file_id": rpt_file["file_id"],
                    "file_name": rpt_file.get("file_name"),
                    "md5": rpt_file.get("md5sum"),
                }
            except RuntimeError as exc:
                print(f"{prefix}  PDF: DOWNLOAD ERROR — {exc}")
                missing_report.append(case_id)

        manifest[case_id] = entry

    # Write manifest
    manifest_path = output_dir / "download_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Summary
    print(f"\n{'='*60}")
    print(f"Download complete.")
    print(f"  Clinical XMLs:      {n_xml_downloaded} downloaded, {n_xml_skipped} skipped")
    print(f"  Pathology reports:  {n_report_downloaded} downloaded, {n_report_skipped} skipped")
    print(f"  Manifest written:   {manifest_path}")

    if missing_xml:
        print(f"\n  Missing clinical XMLs ({len(missing_xml)}):")
        for cid in missing_xml:
            print(f"    {cid}")

    if missing_report:
        print(f"\n  Missing pathology reports ({len(missing_report)}):")
        for cid in missing_report:
            print(f"    {cid}")

    if args.fail_on_missing and (missing_xml or missing_report):
        print("\nERROR: --fail-on-missing: some files could not be downloaded.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
