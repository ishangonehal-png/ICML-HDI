#!/usr/bin/env python3
"""Shared utilities for TCGA-LUAD data contract validation and manifest locking."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


_SAMPLE_ID_RE = re.compile(r"(TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}-[0-9]{2}[A-Z])", re.IGNORECASE)
_SLIDE_ID_RE = re.compile(
    r"(TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}-[0-9]{2}[A-Z]-[0-9]{2}-[A-Z0-9]{2,4})",
    re.IGNORECASE,
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_column_name(name: str) -> str:
    return (name or "").lstrip("\ufeff").strip()


def _normalize_modality_token(modality: str) -> str:
    return (modality or "").strip().lower().replace("-", "_")


def load_contract_schema(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    if not isinstance(schema, dict):
        raise ValueError(f"Schema at {path} must be a JSON object")
    return schema


def parse_required_modalities(modalities_arg: Optional[str], schema: Dict) -> List[str]:
    known = list((schema.get("modality_requirements") or {}).keys())

    normalized_known_to_canonical: Dict[str, str] = {}
    ambiguous_keys: Dict[str, set[str]] = {}
    for modality in known:
        normalized = _normalize_modality_token(modality)
        existing = normalized_known_to_canonical.get(normalized)
        if existing and existing != modality:
            ambiguous_keys.setdefault(normalized, {existing}).add(modality)
            continue
        normalized_known_to_canonical[normalized] = modality

    if ambiguous_keys:
        details = ", ".join(
            f"{key}: {sorted(list(values))}" for key, values in sorted(ambiguous_keys.items())
        )
        raise ValueError(
            "Schema modality keys are ambiguous after normalization "
            f"(case/hyphen-insensitive comparison): {details}"
        )

    if modalities_arg:
        raw_requested = [x.strip() for x in modalities_arg.split(",") if x.strip()]
    else:
        raw_requested = [str(x).strip() for x in (schema.get("required_modalities") or []) if str(x).strip()]

    # De-duplicate while preserving order so accidental repeated CLI values
    # do not double-count missingness or duplicate manifest assets.
    requested: List[str] = []
    seen = set()
    unknown: List[str] = []
    unknown_seen = set()

    for raw_modality in raw_requested:
        canonical = normalized_known_to_canonical.get(_normalize_modality_token(raw_modality))
        if canonical is None:
            if raw_modality not in unknown_seen:
                unknown_seen.add(raw_modality)
                unknown.append(raw_modality)
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        requested.append(canonical)

    if unknown:
        raise ValueError(
            f"Unknown modalities: {unknown}. Known modalities: {known}"
        )
    if not requested:
        raise ValueError("No required modalities were provided/resolved.")
    return requested


def resolve_schema_and_modalities(schema_path: Path, modalities_arg: Optional[str]) -> Tuple[Dict, Dict[str, Dict], List[str]]:
    schema = load_contract_schema(schema_path)
    modality_requirements = schema.get("modality_requirements") or {}
    required_modalities = parse_required_modalities(modalities_arg, schema)
    return schema, modality_requirements, required_modalities


def read_delimited_rows(path: Path, delimiter: str = ",") -> Tuple[List[str], List[Dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        raw_fieldnames = list(reader.fieldnames or [])

        if not raw_fieldnames:
            return [], []

        fieldnames = [_normalize_column_name(name) for name in raw_fieldnames]

        duplicate_columns = [name for name, count in Counter(fieldnames).items() if name and count > 1]
        if duplicate_columns:
            raise ValueError(
                f"Duplicate columns in delimited file ({path}) after normalization: {sorted(duplicate_columns)}"
            )

        rows: List[Dict[str, str]] = []
        for row_idx, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                extra_values = [v for v in (raw_row.get(None) or []) if (v or "").strip()]
                if extra_values:
                    raise ValueError(
                        f"Row {row_idx} in {path} has extra values beyond header columns: {extra_values}"
                    )

            normalized_row: Dict[str, str] = {}
            for raw_name, normalized_name in zip(raw_fieldnames, fieldnames):
                value = raw_row.get(raw_name, "")
                normalized_row[normalized_name] = "" if value is None else str(value)
            rows.append(normalized_row)

    return fieldnames, rows


def ensure_required_columns(
    available_columns: Sequence[str], required_columns: Iterable[str], label: str
) -> None:
    available = set(available_columns)
    missing = [c for c in required_columns if c not in available]
    if missing:
        raise ValueError(f"Missing required columns in {label}: {missing}")


def load_and_validate_cohort_rows(cohort_csv: Path, schema: Dict) -> Tuple[List[str], List[Dict[str, str]]]:
    fieldnames, rows = read_delimited_rows(cohort_csv, delimiter=",")
    ensure_required_columns(
        available_columns=fieldnames,
        required_columns=schema.get("cohort_required_columns") or [],
        label=f"cohort CSV ({cohort_csv})",
    )
    return fieldnames, rows


def evaluate_cohort_completeness(
    rows: List[Dict[str, str]],
    required_modalities: Sequence[str],
    modality_requirements: Dict[str, Dict],
) -> Dict:
    missing_cases: List[Dict[str, object]] = []
    complete_case_count = 0

    for row in rows:
        case_id = (row.get("case_id") or "").strip()
        patient_id = (row.get("patient_id") or "").strip()
        missing_modalities: List[str] = []

        for modality in required_modalities:
            req = modality_requirements[modality]
            col = str(req.get("file_id_column") or "")
            value = (row.get(col) or "").strip()
            if not value:
                missing_modalities.append(modality)

        if missing_modalities:
            missing_cases.append(
                {
                    "case_id": case_id,
                    "patient_id": patient_id,
                    "missing_modalities": missing_modalities,
                }
            )
        else:
            complete_case_count += 1

    missing_cases.sort(
        key=lambda item: (
            str(item.get("case_id") or ""),
            str(item.get("patient_id") or ""),
            ",".join(str(x) for x in (item.get("missing_modalities") or [])),
        )
    )

    return {
        "total_cases": len(rows),
        "complete_cases": complete_case_count,
        "incomplete_cases": len(missing_cases),
        "missing_cases": missing_cases,
        "required_modalities": list(required_modalities),
    }


def build_completeness_report(
    *,
    schema: Dict,
    cohort_csv: Path,
    required_modalities: Sequence[str],
    completeness: Dict,
) -> Dict[str, Any]:
    return {
        "validated_at_utc": utcnow_iso(),
        "contract_name": schema.get("contract_name"),
        "contract_version": schema.get("contract_version"),
        "cohort_csv": str(cohort_csv.resolve()),
        "required_modalities": list(required_modalities),
        "summary": {
            "total_cases": completeness["total_cases"],
            "complete_cases": completeness["complete_cases"],
            "incomplete_cases": completeness["incomplete_cases"],
        },
        "missing_cases": completeness["missing_cases"],
    }


def _stable_row_fingerprint(row: Dict[str, str]) -> str:
    normalized = {
        str(k): "" if v is None else str(v).strip()
        for k, v in sorted(row.items(), key=lambda item: str(item[0]))
    }
    return sha256_json(normalized)


def rank_rows_with_lock_metadata(rows: List[Dict[str, str]], seed: str) -> List[Dict[str, str]]:
    ranked: List[Tuple[str, str, str, str, Dict[str, str]]] = []
    for row in rows:
        case_id = (row.get("case_id") or "").strip()
        patient_id = (row.get("patient_id") or "").strip()
        lock_key = sha256_text(f"{seed}|{case_id}|{patient_id}")
        row_fingerprint = _stable_row_fingerprint(row)
        ranked.append((lock_key, case_id, patient_id, row_fingerprint, row))

    ranked.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

    out: List[Dict[str, str]] = []
    for idx, (lock_key, _case_id, _patient_id, _row_fingerprint, row) in enumerate(ranked, start=1):
        row_copy = dict(row)
        row_copy["lock_rank"] = str(idx)
        row_copy["lock_key_sha256"] = lock_key
        out.append(row_copy)
    return out


def deterministic_subset(
    rows: List[Dict[str, str]],
    subset_size: int,
    seed: str,
) -> List[Dict[str, str]]:
    if subset_size <= 0:
        raise ValueError("subset_size must be > 0")

    ranked_rows = rank_rows_with_lock_metadata(rows, seed=seed)
    return ranked_rows[:subset_size]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(obj: object) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return sha256_text(payload)


def dumps_json_pretty(obj: object) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_int(value: object) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def extract_tcga_ids(filename: str, patient_id: str = "") -> Tuple[str, str]:
    """Return (sample_id, slide_id) parsed from filename; values may be empty."""
    sample_match = _SAMPLE_ID_RE.search(filename or "")
    slide_match = _SLIDE_ID_RE.search(filename or "")

    sample_id = (sample_match.group(1).upper() if sample_match else "")
    slide_id = (slide_match.group(1).upper() if slide_match else "")

    if not sample_id and patient_id:
        # Keep patient-level fallback explicit when file naming omits sample granularity.
        sample_id = patient_id.strip().upper()

    return sample_id, slide_id


def infer_source_path(file_id: str, filename: str) -> str:
    file_id = file_id.strip()
    filename = filename.strip()
    return f"files/{file_id}/{filename}" if file_id and filename else ""
