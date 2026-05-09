"""Extract structured fields from TCGA-LUAD pathology report PDFs using Claude.

Usage
-----
    python scripts/extract_path_report_fields.py \\
        --reports-dir  data/clinical/reports \\
        --output-dir   data/clinical/path_report_fields \\
        --model        claude-sonnet-4-6 \\
        --concurrency  4

Inputs
------
- PDF files in ``--reports-dir``, named ``{case_id}.pdf`` or
  ``{case_id}_pathology_report.pdf`` (any suffix the download script uses).

Outputs
-------
- One JSON file per case in ``--output-dir/{case_id}.json`` with the schema::

    {
      "grade": "moderately differentiated" | null,
      "margins": "negative" | "positive" | "close (<1mm)" | null,
      "lymph_nodes_positive": 2 | null,
      "lymph_nodes_total": 18 | null,
      "lvi": "present" | "absent" | "not reported" | null,
      "tumor_size_cm": 3.2 | null,
      "histologic_pattern": "acinar predominant" | null,
      "ihc_pdl1_tps": "< 1%" | null,
      "til_comment": "<verbatim quote>" | null,
      "raw_highlights": ["sentence1", "sentence2", ...]
    }

- ``--output-dir/extraction_manifest.json`` summarising per-case status.

Environment
-----------
ANTHROPIC_API_KEY must be set.

Dependencies
------------
    pip install anthropic pymupdf  # pymupdf provides fitz for PDF text extraction
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------

def _extract_pdf_text(pdf_path: Path) -> str | None:
    """Return plain text from a PDF using PyMuPDF (fitz)."""
    try:
        import fitz  # type: ignore[import-untyped]
    except ImportError:
        log.error("pymupdf not installed. Run: pip install pymupdf")
        return None

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        log.warning("Could not open %s: %s", pdf_path, exc)
        return None

    pages: list[str] = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()

    text = "\n".join(pages).strip()
    return text if text else None


# ---------------------------------------------------------------------------
# Claude extraction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a clinical NLP assistant specializing in surgical pathology reports for \
lung adenocarcinoma (LUAD). Extract structured fields from the report below and \
return ONLY valid JSON — no prose, no markdown fences. Use null for any field \
not explicitly stated in the report. Do NOT infer or hallucinate values.

Return this exact JSON schema:
{
  "grade": string | null,          // e.g. "well differentiated", "moderately differentiated", "poorly differentiated"
  "margins": string | null,        // "negative", "positive", or "close (<1mm)"
  "lymph_nodes_positive": integer | null,  // number of positive lymph nodes
  "lymph_nodes_total": integer | null,     // total lymph nodes examined
  "lvi": string | null,            // "present", "absent", or "not reported"
  "tumor_size_cm": number | null,  // largest tumor dimension in cm
  "histologic_pattern": string | null,    // e.g. "acinar predominant", "lepidic predominant"
  "ihc_pdl1_tps": string | null,   // PD-L1 TPS if IHC reported, e.g. "< 1%", ">= 50%"
  "til_comment": string | null,    // verbatim quote from pathologist if TILs mentioned
  "raw_highlights": [string]       // 3-5 most clinically relevant sentences verbatim
}
"""

_MAX_TEXT_CHARS = 12_000  # stay well within token budget


def _call_claude(text: str, model: str, client: object) -> dict | None:
    """Call Claude and parse the JSON response. Returns None on failure."""
    truncated = text[:_MAX_TEXT_CHARS]
    if len(text) > _MAX_TEXT_CHARS:
        truncated += "\n\n[Report truncated for length]"

    try:
        response = client.messages.create(  # type: ignore[union-attr]
            model=model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": truncated}],
        )
    except Exception as exc:
        log.warning("Claude API call failed: %s", exc)
        return None

    raw = response.content[0].text.strip() if response.content else ""

    # Strip accidental markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("JSON parse error from Claude: %s\nRaw: %.200s", exc, raw)
        return None


# ---------------------------------------------------------------------------
# Per-case processing
# ---------------------------------------------------------------------------

def _process_case(
    case_id: str,
    pdf_path: Path,
    output_dir: Path,
    model: str,
    client: object,
    overwrite: bool,
) -> dict:
    out_path = output_dir / f"{case_id}.json"

    if out_path.is_file() and not overwrite:
        log.info("SKIP %s (cache hit)", case_id)
        return {"case_id": case_id, "status": "skipped"}

    text = _extract_pdf_text(pdf_path)
    if not text:
        log.warning("No text extracted from %s", pdf_path)
        return {"case_id": case_id, "status": "no_text", "pdf": str(pdf_path)}

    fields = _call_claude(text, model=model, client=client)
    if fields is None:
        return {"case_id": case_id, "status": "extraction_failed", "pdf": str(pdf_path)}

    # Validate / coerce types before writing
    fields = _coerce_fields(fields)
    fields["_source_pdf"] = str(pdf_path)
    fields["_case_id"] = case_id

    out_path.write_text(json.dumps(fields, indent=2), encoding="utf-8")
    log.info("OK   %s → %s", case_id, out_path.name)
    return {"case_id": case_id, "status": "ok", "pdf": str(pdf_path)}


def _coerce_fields(raw: dict) -> dict:
    """Light coercion to ensure types match expected schema."""
    out: dict = {}
    out["grade"] = _str_or_none(raw.get("grade"))
    out["margins"] = _str_or_none(raw.get("margins"))
    out["lymph_nodes_positive"] = _int_or_none(raw.get("lymph_nodes_positive"))
    out["lymph_nodes_total"] = _int_or_none(raw.get("lymph_nodes_total"))
    out["lvi"] = _str_or_none(raw.get("lvi"))
    out["tumor_size_cm"] = _float_or_none(raw.get("tumor_size_cm"))
    out["histologic_pattern"] = _str_or_none(raw.get("histologic_pattern"))
    out["ihc_pdl1_tps"] = _str_or_none(raw.get("ihc_pdl1_tps"))
    out["til_comment"] = _str_or_none(raw.get("til_comment"))
    highlights = raw.get("raw_highlights") or []
    if isinstance(highlights, list):
        out["raw_highlights"] = [str(h) for h in highlights[:5]]
    else:
        out["raw_highlights"] = []
    return out


def _str_or_none(v: object) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.lower() not in {"null", "none", "n/a", "na"} else None


def _int_or_none(v: object) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float_or_none(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Case discovery
# ---------------------------------------------------------------------------

_PDF_SUFFIXES = {".pdf", ".PDF"}
_CASE_ID_PATTERN = re.compile(r"(TCGA-[A-Z0-9]+-[A-Z0-9]+)", re.IGNORECASE)


def _discover_cases(reports_dir: Path) -> dict[str, Path]:
    """Return {case_id: pdf_path} for all PDFs found in reports_dir."""
    cases: dict[str, Path] = {}
    for path in sorted(reports_dir.iterdir()):
        if path.suffix not in _PDF_SUFFIXES:
            continue
        match = _CASE_ID_PATTERN.search(path.stem)
        if match:
            case_id = match.group(1).upper()
            cases[case_id] = path
    return cases


def _filter_to_cohort(cases: dict[str, Path], cohort_csv: Path | None) -> dict[str, Path]:
    if cohort_csv is None:
        return cases

    import csv

    cohort_ids: set[str] = set()
    with cohort_csv.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            cid = (row.get("case_id") or "").strip().upper()
            if cid:
                cohort_ids.add(cid)

    filtered = {cid: p for cid, p in cases.items() if cid in cohort_ids}
    log.info("Cohort filter: %d/%d cases retained", len(filtered), len(cases))
    return filtered


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Extract structured fields from TCGA-LUAD pathology report PDFs via Claude.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--reports-dir", required=True, type=Path, help="Directory containing pathology PDF files")
    p.add_argument("--output-dir", required=True, type=Path, help="Directory to write per-case JSON files")
    p.add_argument("--cohort-csv", type=Path, default=None, help="Optional cohort CSV to restrict processing")
    p.add_argument("--model", default="claude-sonnet-4-6", help="Claude model ID")
    p.add_argument("--concurrency", type=int, default=4, help="Max parallel API calls")
    p.add_argument("--overwrite", action="store_true", help="Re-extract even if JSON cache exists")
    p.add_argument("--dry-run", action="store_true", help="Discover cases but do not call Claude")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key and not args.dry_run:
        log.error("ANTHROPIC_API_KEY environment variable not set")
        return 1

    reports_dir: Path = args.reports_dir
    output_dir: Path = args.output_dir

    if not reports_dir.is_dir():
        log.error("--reports-dir does not exist: %s", reports_dir)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    cases = _discover_cases(reports_dir)
    if not cases:
        log.error("No PDF files found in %s", reports_dir)
        return 1

    cases = _filter_to_cohort(cases, args.cohort_csv)
    log.info("Processing %d cases with model %s", len(cases), args.model)

    if args.dry_run:
        for cid, p in cases.items():
            print(f"{cid}\t{p}")
        return 0

    import anthropic  # type: ignore[import-untyped]

    client = anthropic.Anthropic(api_key=api_key)

    results: list[dict] = []
    t0 = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(
                _process_case,
                case_id=cid,
                pdf_path=pdf_path,
                output_dir=output_dir,
                model=args.model,
                client=client,
                overwrite=args.overwrite,
            ): cid
            for cid, pdf_path in cases.items()
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    elapsed = time.monotonic() - t0

    status_counts: dict[str, int] = {}
    for r in results:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

    manifest_path = output_dir / "extraction_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "model": args.model,
                "total_cases": len(cases),
                "elapsed_seconds": round(elapsed, 1),
                "status_counts": status_counts,
                "cases": sorted(results, key=lambda r: r["case_id"]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    log.info(
        "Done in %.1fs — ok=%d skipped=%d failed=%d no_text=%d",
        elapsed,
        status_counts.get("ok", 0),
        status_counts.get("skipped", 0),
        status_counts.get("extraction_failed", 0),
        status_counts.get("no_text", 0),
    )
    log.info("Manifest: %s", manifest_path)

    failed = status_counts.get("extraction_failed", 0) + status_counts.get("no_text", 0)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
