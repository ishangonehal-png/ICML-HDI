#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR / "eval"))
import _eval_bootstrap

_REPO_ROOT = Path(__file__).parent.parent
_eval_bootstrap.setup(str(_REPO_ROOT))

INPUT_CSV = _REPO_ROOT / "adjudication_input.csv"

JUDGE_SYSTEM = """You are a biomedical faithfulness evaluator.

You will be given:
1. A sentence or short passage (claim) from a generated patient summary
2. The structured evidence bundle that the summary was based on

Fill two fields:
- human_label: exactly one of supported, partial, unsupported
- human_notes: one concise sentence explaining the decision

Decision rules:
- supported: directly and accurately traceable to the evidence bundle
- partial: related to the evidence but vague, overgeneralized, partly verifiable, or mixes supported facts with unsupported interpretation
- unsupported: introduces facts not present in the bundle, or contradicts it

Important rules:
- Uncertainty/disclaimer statements like "research-only" or "not for clinical use" are supported if present in the claim and grounded in the bundle context.
- If transcriptomics/RNA is unavailable and the claim says it is unavailable, that is supported.
- Do not penalize small rounding differences.
- If the claim contains a number, biomarker, stage, subtype, treatment response, or genomic fact absent from the bundle, prefer unsupported unless it is an obvious restatement of present evidence.
- Be conservative. When a claim is interpretive or stronger than the evidence, prefer partial over supported.

Return JSON only:
{"human_label":"supported|partial|unsupported","human_notes":"<one sentence>"}
"""


def judge_row(claim_text: str, bundle_text: str, model: str) -> tuple[str, str]:
    from services.llm_wrapper import chat

    user_msg = json.dumps(
        {"claim": claim_text, "evidence_bundle": bundle_text},
        ensure_ascii=True,
    )
    content = chat(
        model=model,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=160,
    )
    parsed = json.loads(content or "{}")
    label = str(parsed.get("human_label", "")).strip().lower()
    notes = str(parsed.get("human_notes", "")).strip()
    if label not in {"supported", "partial", "unsupported"}:
        raise ValueError(f"invalid label: {label!r}")
    if not notes:
        raise ValueError("missing human_notes")
    return label, notes


def write_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    if model.startswith("gemini"):
        if not os.environ.get("GEMINI_API_KEY"):
            print("ERROR: GEMINI_API_KEY not set")
            return 1
    else:
        if not os.environ.get("OPENAI_API_KEY"):
            print("ERROR: OPENAI_API_KEY not set")
            return 1

    with INPUT_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if "human_label" not in fieldnames or "human_notes" not in fieldnames:
        print("ERROR: adjudication_input.csv is missing expected columns")
        return 1

    pending = [
        i for i, row in enumerate(rows)
        if not (row.get("human_label", "").strip() and row.get("human_notes", "").strip())
    ]
    print(f"Found {len(rows)} rows total; {len(pending)} pending adjudications.")

    for done_count, row_index in enumerate(pending, start=1):
        row = rows[row_index]
        try:
            label, notes = judge_row(
                claim_text=row["claim"],
                bundle_text=row["bundle_excerpt"],
                model=model,
            )
            row["human_label"] = label
            row["human_notes"] = notes
            write_rows(INPUT_CSV, rows, fieldnames)
            print(f"[{done_count}/{len(pending)}] {row['row_id']} -> {label}")
            time.sleep(0.1)
        except Exception as exc:
            print(f"[{done_count}/{len(pending)}] ERROR on {row.get('row_id', row_index)}: {exc}")
            write_rows(INPUT_CSV, rows, fieldnames)
            return 2

    print(f"Completed adjudication fill for {len(pending)} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
