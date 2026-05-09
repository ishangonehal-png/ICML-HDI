#!/usr/bin/env python3
"""
llm_judge.py
============
Runs GPT-4o-mini as a faithfulness judge on every standard-prompt claim in
claim_review.csv. Two passes at temperature 0.0 give a reliability estimate
analogous to inter-annotator agreement.

Adds columns to claim_review.csv:
  llm_judge_label_1, llm_judge_rationale_1
  llm_judge_label_2, llm_judge_rationale_2
  llm_judge_agreement   (True/False)
  llm_judge_final       (label_1 if agreement, else "conflict")

Usage:
  OPENAI_API_KEY=sk-... python3 scripts/eval/llm_judge.py
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR))
import _eval_bootstrap
_REPO_ROOT = Path(__file__).parent.parent.parent
_eval_bootstrap.setup(str(_REPO_ROOT))

OUT_DIR = Path(os.environ.get("BIONLP_OUT_DIR", str(_REPO_ROOT / "outputs" / "bionlp_eval")))
CLAIM_CSV = OUT_DIR / "claim_review.csv"
BUNDLES_DIR = OUT_DIR / "evidence_bundles"

JUDGE_SYSTEM = """You are a biomedical faithfulness evaluator.

You will be given:
1. A sentence (claim) from a generated patient summary
2. The structured evidence bundle that the summary was based on

Label the claim as exactly one of:
  supported   – the claim is directly and accurately traceable to the evidence bundle
  partial     – the claim relates to the evidence but is vague, imprecise, or only partly verifiable
  unsupported – the claim introduces facts not present in the bundle, or contradicts it

Return JSON only:
{"label": "supported"|"partial"|"unsupported", "rationale": "<one sentence>"}

Rules:
- Uncertainty/disclaimer sentences ("research-only", "not for clinical use") are always supported.
- If RNA is reported as unavailable and the bundle confirms it unavailable, that is supported.
- Do not penalise rounding (e.g. 0.630 vs 0.63).
- If a number in the claim is absent from the bundle, mark unsupported unless it is a clearly derived value.
"""


def load_bundle(case_id: str, config: str) -> dict:
    path = BUNDLES_DIR / f"{case_id}_{config}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def bundle_summary(bundle: dict) -> str:
    """Compact text representation of evidence bundle for judge prompt."""
    parts = []
    parts.append(f"IO score: {bundle.get('io_score','?')} (tier: {bundle.get('io_tier','?')})")
    path = bundle.get("pathology", {})
    fracs = ", ".join(f"{k}={v}" for k, v in path.get("tissue_fractions", {}).items())
    tiles = "; ".join(f"tile {t['tile_id']} score={t['score']} ({t['rationale']})"
                      for t in path.get("top_tiles", []))
    parts.append(f"Pathology: {fracs}; {tiles}")
    txo = bundle.get("transcriptomics", {})
    parts.append(f"CYT={txo.get('cyt_value','N/A')} available={txo.get('cyt_available',False)}, "
                 f"GEP={txo.get('gep_value','N/A')} available={txo.get('gep_available',False)}, "
                 f"TIDE={txo.get('tide_value','N/A')} available={txo.get('tide_available',False)}")
    fus = bundle.get("fusion", {})
    parts.append(f"Fusion active score: {fus.get('active_score','?')}, mode: {fus.get('mode_used','?')}")
    contribs = fus.get("modality_contributions", {})
    for mod, info in contribs.items():
        parts.append(f"  {mod}: contribution={info.get('contribution_percent','?')}%, "
                     f"source={info.get('data_source','?')}")
    return "\n".join(parts)


def judge_claim(claim_text: str, bundle_text: str, pass_num: int) -> tuple[str, str]:
    user_msg = json.dumps({"claim": claim_text, "evidence_bundle": bundle_text})
    from services.llm_wrapper import chat
    try:
        content = chat(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        parsed = json.loads(content or "{}")
        label = parsed.get("label", "unknown").strip().lower()
        if label not in ("supported", "partial", "unsupported"):
            label = "unknown"
        rationale = parsed.get("rationale", "").strip()
        return label, rationale
    except Exception as e:
        return "unknown", f"judge error: {e}"


def main() -> None:
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    if model.startswith("gemini"):
        if not os.environ.get("GEMINI_API_KEY"):
            print("ERROR: GEMINI_API_KEY not set"); sys.exit(1)
    else:
        if not os.environ.get("OPENAI_API_KEY"):
            print("ERROR: OPENAI_API_KEY not set"); sys.exit(1)

    with open(CLAIM_CSV, newline="") as f:
        rows = list(csv.DictReader(f))

    # Only judge standard-prompt claims (literature claims need different logic)
    std_rows = [r for r in rows if r.get("prompt_type") == "standard"]
    other_rows = [r for r in rows if r.get("prompt_type") != "standard"]
    print(f"Judging {len(std_rows)} standard-prompt claims (2 passes each)...")

    # Cache bundles to avoid repeated disk reads
    bundle_cache: dict[str, dict] = {}

    results: list[dict] = []
    for i, row in enumerate(std_rows):
        key = f"{row['case_id']}_{row['config']}"
        if key not in bundle_cache:
            bundle_cache[key] = load_bundle(row["case_id"], row["config"])
        bundle = bundle_cache[key]
        btext = bundle_summary(bundle)

        label1, rat1 = judge_claim(row["claim_text"], btext, 1)
        time.sleep(0.1)
        label2, rat2 = judge_claim(row["claim_text"], btext, 2)
        time.sleep(0.1)

        agree = label1 == label2
        final = label1 if agree else "conflict"

        row["llm_judge_label_1"] = label1
        row["llm_judge_rationale_1"] = rat1
        row["llm_judge_label_2"] = label2
        row["llm_judge_rationale_2"] = rat2
        row["llm_judge_agreement"] = agree
        row["llm_judge_final"] = final
        results.append(row)

        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(std_rows)} done...")

    # Add empty judge columns to non-standard rows
    for row in other_rows:
        row["llm_judge_label_1"] = ""
        row["llm_judge_rationale_1"] = ""
        row["llm_judge_label_2"] = ""
        row["llm_judge_rationale_2"] = ""
        row["llm_judge_agreement"] = ""
        row["llm_judge_final"] = ""
        results.append(row)

    # Write back
    all_fields = list(rows[0].keys()) + [
        "llm_judge_label_1", "llm_judge_rationale_1",
        "llm_judge_label_2", "llm_judge_rationale_2",
        "llm_judge_agreement", "llm_judge_final",
    ]
    # Deduplicate field names (in case already present from a prior run)
    seen = set(); fields = []
    for f in all_fields:
        if f not in seen:
            fields.append(f); seen.add(f)

    with open(CLAIM_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    # Stats
    from collections import Counter
    judge_labels = [r["llm_judge_final"] for r in results if r.get("prompt_type") == "standard"]
    agreement_flags = [r["llm_judge_agreement"] for r in results if r.get("prompt_type") == "standard"]
    agree_count = sum(1 for a in agreement_flags if str(a) == "True")
    print(f"\nJudge label distribution: {dict(Counter(judge_labels))}")
    print(f"Agreement rate (pass1 == pass2): {agree_count}/{len(std_rows)} = {agree_count/len(std_rows):.1%}")
    print(f"Saved: {CLAIM_CSV}")


if __name__ == "__main__":
    main()
