#!/usr/bin/env python3
"""
run_baseline.py
===============
Generates ungrounded GPT-4o-mini baseline summaries for the same 20 selected cases.
The LLM receives ONLY: the case ID, cohort (TCGA-LUAD), and the standard prompt.
No evidence bundle, no fusion score, no clinical data, no pathology values.

Appends baseline rows to summaries.csv (config="baseline") and saves
evidence bundles as <case_id>_baseline.json (empty bundle).

Usage:
  OPENAI_API_KEY=sk-... python3 scripts/eval/run_baseline.py
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR))
import _eval_bootstrap
_REPO_ROOT = Path(__file__).parent.parent.parent
_eval_bootstrap.setup(str(_REPO_ROOT))

OUT_DIR = Path(os.environ.get("BIONLP_OUT_DIR", str(_REPO_ROOT / "outputs" / "bionlp_eval")))
SUMMARIES_CSV  = OUT_DIR / "summaries.csv"
CASE_SEL_CSV   = OUT_DIR / "case_selection.csv"
BUNDLES_DIR    = OUT_DIR / "evidence_bundles"

STANDARD_PROMPT = (
    "Summarize this patient's immunotherapy readiness using only the available structured evidence. "
    "State the IO immune tier, key pathology evidence, RNA evidence if available, clinical context "
    "if relevant, and any uncertainty or limitations. Keep the response concise and factual."
)

BASELINE_SYSTEM = (
    "You are a biomedical assistant helping summarize patient cases. "
    "Answer based on general medical knowledge. This is research-only."
)


def count_sentences(text: str) -> int:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return len([s for s in parts if s.strip()])


def generate_baseline(case_id: str) -> str:
    user_msg = (
        f"Case ID: {case_id}\nCohort: TCGA-LUAD (lung adenocarcinoma)\n\n{STANDARD_PROMPT}"
    )
    from services.llm_wrapper import chat
    return chat(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": BASELINE_SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.2,
    )


def main() -> None:
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    if model.startswith("gemini"):
        if not os.environ.get("GEMINI_API_KEY"):
            print("ERROR: GEMINI_API_KEY not set"); sys.exit(1)
    else:
        if not os.environ.get("OPENAI_API_KEY"):
            print("ERROR: OPENAI_API_KEY not set"); sys.exit(1)

    # Load selected cases
    with open(CASE_SEL_CSV, newline="") as f:
        selected = list(csv.DictReader(f))
    print(f"Generating baseline summaries for {len(selected)} cases...")

    # Load existing summaries to append
    with open(SUMMARIES_CSV, newline="") as f:
        existing = list(csv.DictReader(f))
    fields = list(existing[0].keys())

    new_rows = []
    for i, case in enumerate(selected):
        case_id = case["case_id"]
        tier    = case["io_tier"]
        print(f"  [{i+1}/{len(selected)}] {case_id} ({tier})...", end="", flush=True)

        summary = generate_baseline(case_id)
        n_sent  = count_sentences(summary)

        row = {
            "case_id":            case_id,
            "config":             "baseline",
            "prompt_type":        "standard",
            "summary_text":       summary,
            "io_tier_expected":   tier,
            "literature_requested": False,
            "literature_used":    False,
            "num_sentences":      n_sent,
            "num_chars":          len(summary),
        }
        new_rows.append(row)

        # Save empty evidence bundle so downstream scripts don't break
        bundle = {
            "case_id": case_id,
            "config": "baseline",
            "prompt_type": "standard",
            "io_score": None,
            "io_tier": tier,
            "note": "Ungrounded baseline — no evidence bundle provided to LLM",
            "pathology": {"tissue_fractions": {}, "top_tiles": [], "til_fraction": None},
            "transcriptomics": {"cyt_value": None, "cyt_available": False,
                                "gep_value": None, "gep_available": False,
                                "tide_value": None, "tide_available": False},
            "fusion": {"mode_used": "none", "active_score": None, "modality_contributions": {}},
            "literature_retrieval_invoked": False,
            "literature_citations": [],
        }
        with open(BUNDLES_DIR / f"{case_id}_baseline.json", "w") as f:
            json.dump(bundle, f, indent=2)

        print(f" done ({n_sent} sentences)")
        time.sleep(0.2)

    # Append to summaries.csv
    all_rows = existing + new_rows
    with open(SUMMARIES_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nAppended {len(new_rows)} baseline rows to {SUMMARIES_CSV}")
    print("Baseline evidence bundles saved to", BUNDLES_DIR)


if __name__ == "__main__":
    main()
