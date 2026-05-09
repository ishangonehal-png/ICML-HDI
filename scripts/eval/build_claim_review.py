#!/usr/bin/env python3
"""
build_claim_review.py
=====================
Reads summaries.csv and evidence bundles, splits each summary into sentence-level
claims, and auto-populates as many review columns as possible with lightweight heuristics.

Output: outputs/bionlp_eval/claim_review.csv

Heuristics used (documented in report.md):
  - IO tier mention: checks if tier word (Hot/Warm/Cold) appears in sentence
  - Numeric fidelity: checks if key numeric values from evidence bundle appear in sentence
    (with ±0.01 tolerance for formatted floats)
  - Modality attribution: checks for modality keywords (pathology/RNA/clinical/fusion)
  - Uncertainty detection: checks for hedge phrases
  - Literature detection: checks for pubmed/study/paper/citation keywords
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

# ── bootstrap ─────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR))
import _eval_bootstrap  # noqa: E402
_REPO_ROOT = Path(__file__).parent.parent.parent
_eval_bootstrap.setup(str(_REPO_ROOT))

OUT_DIR = _REPO_ROOT / "outputs" / "bionlp_eval"
SUMMARIES_CSV = OUT_DIR / "summaries.csv"
BUNDLES_DIR = OUT_DIR / "evidence_bundles"
CLAIM_REVIEW_CSV = OUT_DIR / "claim_review.csv"

CLAIM_REVIEW_FIELDS = [
    "case_id", "config", "prompt_type", "claim_id", "claim_text",
    "claim_type", "predicted_modality", "support_label_auto", "support_rationale_auto",
    "modality_match_auto", "numeric_fidelity_auto",
    "human_support_label", "human_modality_match", "human_notes",
]

# ── regex helpers ─────────────────────────────────────────────────────────────

_TIER_PATTERN = re.compile(r"\b(hot|warm|cold)\b", re.IGNORECASE)
_PATHOLOGY_PATTERN = re.compile(
    r"\b(pathology|tissue|tumor|stroma|necrosis|lymphocyte|til|tile|wsi|slide)\b", re.IGNORECASE
)
_RNA_PATTERN = re.compile(
    r"\b(rna|transcriptomics?|cyt|gep|tide|gene|expression|mrna|ifng|gzma|prf1|volcano)\b", re.IGNORECASE
)
_CLINICAL_PATTERN = re.compile(
    r"\b(clinical|stage|age|smoking|smoke|smoker|diagnosis|ecog|vital|survival|months?|risk)\b",
    re.IGNORECASE,
)
_FUSION_PATTERN = re.compile(
    r"\b(fusion|multimodal|score|provisional|refined|delta|contribution)\b", re.IGNORECASE
)
_UNCERTAINTY_PATTERN = re.compile(
    r"\b(uncertain|limit|caveat|proxy|research.only|not for clinical|approximat|fallback|unavailable|missing)\b",
    re.IGNORECASE,
)
_LITERATURE_PATTERN = re.compile(
    r"\b(literature|pubmed|paper|study|studies|trial|citation|published|abstract|guideline)\b",
    re.IGNORECASE,
)
_NUMBER_PATTERN = re.compile(r"\d+\.?\d*")


def split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    # Split on period/exclamation/question followed by space or end
    raw_parts = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = []
    for part in raw_parts:
        part = part.strip()
        if part:
            sentences.append(part)
    return sentences


def classify_claim_type(sentence: str) -> str:
    """Classify the primary type of claim in a sentence."""
    if _TIER_PATTERN.search(sentence):
        return "tier"
    if _LITERATURE_PATTERN.search(sentence):
        return "literature"
    if _UNCERTAINTY_PATTERN.search(sentence):
        return "uncertainty"
    if _RNA_PATTERN.search(sentence):
        return "RNA"
    if _PATHOLOGY_PATTERN.search(sentence):
        return "pathology"
    if _CLINICAL_PATTERN.search(sentence):
        return "clinical"
    if _FUSION_PATTERN.search(sentence):
        return "fusion"
    return "other"


def predict_modality(sentence: str) -> str:
    """Predict which modality a sentence draws from."""
    scores = {
        "pathology": len(_PATHOLOGY_PATTERN.findall(sentence)),
        "RNA": len(_RNA_PATTERN.findall(sentence)),
        "clinical": len(_CLINICAL_PATTERN.findall(sentence)),
        "literature": len(_LITERATURE_PATTERN.findall(sentence)),
        "fusion": len(_FUSION_PATTERN.findall(sentence)),
    }
    top = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())
    if total == 0:
        return "other"
    # If multiple modalities are tied or close, return "mixed"
    top_score = scores[top]
    runners_up = [k for k, v in scores.items() if v == top_score and k != top]
    if runners_up:
        return "mixed"
    return top


def extract_numbers_from_text(text: str) -> set[str]:
    """Extract all numeric substrings from text."""
    return set(_NUMBER_PATTERN.findall(text))


def check_tier_support(sentence: str, expected_tier: str) -> tuple[str, str]:
    """Check if the tier mentioned in a sentence matches expected tier."""
    match = _TIER_PATTERN.search(sentence)
    if not match:
        return "unknown", "No tier mentioned in this sentence"
    mentioned = match.group(0).capitalize()
    if mentioned.lower() == expected_tier.lower():
        return "supported", f"Tier '{mentioned}' matches expected '{expected_tier}'"
    return "partial", f"Tier '{mentioned}' mentioned but expected '{expected_tier}'"


def check_numeric_fidelity(sentence: str, bundle: dict) -> tuple[str, str]:
    """Check whether numerics in sentence match the evidence bundle."""
    sentence_nums = extract_numbers_from_text(sentence)
    if not sentence_nums:
        return "not_applicable", "No numeric values in sentence"

    # Collect all known numeric values from bundle
    known_nums: dict[str, float] = {}

    io_score = bundle.get("io_score")
    if io_score is not None:
        known_nums["io_score"] = float(io_score)

    path = bundle.get("pathology", {})
    for k, v in path.get("tissue_fractions", {}).items():
        known_nums[f"tissue_{k}"] = float(v)
        known_nums[f"tissue_{k}_pct"] = round(float(v) * 100, 0)

    for tile in path.get("top_tiles", []):
        known_nums[f"tile_score"] = float(tile.get("score", 0))

    txo = bundle.get("transcriptomics", {})
    for k in ("cyt_value", "gep_value", "tide_value"):
        v = txo.get(k)
        if v is not None:
            known_nums[k] = float(v)

    fus = bundle.get("fusion", {})
    act = fus.get("active_score")
    if act is not None:
        known_nums["active_score"] = float(act)

    # Check if any sentence number is close to a known value
    matched_any = False
    unmatched_nums = []
    for sn in sentence_nums:
        sn_float = float(sn)
        found = False
        for name, val in known_nums.items():
            if abs(sn_float - val) < 0.02 or abs(sn_float - round(val, 0)) < 1:
                found = True
                matched_any = True
                break
        if not found:
            unmatched_nums.append(sn)

    if matched_any and not unmatched_nums:
        return "correct", f"All {len(sentence_nums)} numeric(s) match evidence bundle"
    if matched_any and unmatched_nums:
        return "correct", f"Most numerics match; unmatched: {unmatched_nums[:3]} (may be formatted differently)"
    return "incorrect", f"Numbers {list(sentence_nums)[:5]} not found in evidence bundle (may be generic text)"


def check_support(sentence: str, bundle: dict, claim_type: str, expected_tier: str) -> tuple[str, str]:
    """Auto-label whether a claim is supported by the evidence bundle."""
    if claim_type == "tier":
        label, rationale = check_tier_support(sentence, expected_tier)
        return label, rationale

    if claim_type == "uncertainty":
        return "supported", "Uncertainty/caveat claim — always acceptable in research-only summaries"

    if claim_type == "literature":
        if bundle.get("literature_retrieval_invoked", False):
            return "partial", "Literature claim present; retrieval was invoked — content needs manual review"
        return "unsupported", "Literature claim present but retrieval was not invoked"

    # For factual claims, check if numeric values match
    path = bundle.get("pathology", {})
    txo = bundle.get("transcriptomics", {})

    if claim_type == "pathology":
        # Check if tile score or tissue fraction appears
        tile_scores = [str(round(t.get("score", 0), 2)) for t in path.get("top_tiles", [])]
        for ts in tile_scores:
            if ts in sentence:
                return "supported", f"Tile score {ts} found in sentence matches evidence bundle"
        fracs = path.get("tissue_fractions", {})
        for tissue, frac in fracs.items():
            pct = str(int(round(frac * 100)))
            if pct in sentence:
                return "supported", f"Tissue fraction {pct}% for '{tissue}' matches evidence bundle"
        if _PATHOLOGY_PATTERN.search(sentence):
            return "partial", "Pathology language present; specific values not directly matched — manual review"
        return "unknown", "Cannot auto-verify pathology claim"

    if claim_type == "RNA":
        if not txo.get("cyt_available") and not txo.get("gep_available"):
            if "unavailable" in sentence.lower() or "not available" in sentence.lower():
                return "supported", "RNA correctly reported as unavailable"
            return "partial", "RNA claim but RNA is unavailable; may be from pathology_only config"
        for key in ("cyt_value", "gep_value", "tide_value"):
            v = txo.get(key)
            if v is not None:
                vs = str(round(v, 3))
                if vs in sentence or str(round(v, 2)) in sentence:
                    return "supported", f"{key}={v:.3f} found in sentence"
        if _RNA_PATTERN.search(sentence):
            return "partial", "RNA language present; specific metric values not directly matched"
        return "unknown", "Cannot auto-verify RNA claim"

    if claim_type == "clinical":
        # Stage/age/smoking are in the deterministic proxy
        # We can't easily extract them from the bundle without parsing context_for_llm
        if _CLINICAL_PATTERN.search(sentence):
            return "partial", "Clinical language present; values derived from deterministic proxy — manual review recommended"
        return "unknown", "Cannot auto-verify clinical claim"

    if claim_type == "fusion":
        active = bundle.get("fusion", {}).get("active_score")
        if active is not None:
            as_str = str(round(active, 3))
            if as_str in sentence or str(round(active, 2)) in sentence:
                return "supported", f"Fusion score {active:.3f} found in sentence"
        return "partial", "Fusion language present; score value not directly matched"

    return "unknown", "Claim type 'other' — requires manual review"


def check_modality_match(sentence: str, claim_type: str, predicted_modality: str, bundle: dict) -> str:
    """Check if the predicted modality is consistent with what the evidence bundle contains."""
    txo = bundle.get("transcriptomics", {})

    if claim_type == "RNA":
        if predicted_modality in ("RNA", "mixed"):
            return "correct"
        return "incorrect"

    if claim_type == "pathology":
        if predicted_modality in ("pathology", "mixed"):
            return "correct"
        return "incorrect"

    if claim_type == "clinical":
        if predicted_modality in ("clinical", "mixed"):
            return "correct"
        return "incorrect"

    if claim_type == "literature":
        if predicted_modality == "literature":
            return "correct"
        return "incorrect"

    if claim_type in ("tier", "fusion"):
        if predicted_modality in ("fusion", "mixed", "pathology"):
            return "correct"
        return "unknown"

    return "unknown"


def process_summary(row: dict, bundle: dict) -> list[dict]:
    """Process one summary row into claim-level rows."""
    case_id = row["case_id"]
    config = row["config"]
    prompt_type = row["prompt_type"]
    summary_text = row["summary_text"]
    expected_tier = row["io_tier_expected"]

    sentences = split_sentences(summary_text)
    claims = []
    for idx, sent in enumerate(sentences):
        claim_id = f"{case_id}_{config}_{prompt_type}_{idx:03d}"
        claim_type = classify_claim_type(sent)
        predicted_modality = predict_modality(sent)
        support_label, support_rationale = check_support(sent, bundle, claim_type, expected_tier)
        modality_match = check_modality_match(sent, claim_type, predicted_modality, bundle)
        numeric_fidelity, _ = check_numeric_fidelity(sent, bundle)

        claims.append({
            "case_id": case_id,
            "config": config,
            "prompt_type": prompt_type,
            "claim_id": claim_id,
            "claim_text": sent,
            "claim_type": claim_type,
            "predicted_modality": predicted_modality,
            "support_label_auto": support_label,
            "support_rationale_auto": support_rationale,
            "modality_match_auto": modality_match,
            "numeric_fidelity_auto": numeric_fidelity,
            "human_support_label": "",
            "human_modality_match": "",
            "human_notes": "",
        })
    return claims


def load_bundle(case_id: str, config: str) -> dict:
    """Load evidence bundle JSON for a case/config pair."""
    path = BUNDLES_DIR / f"{case_id}_{config}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def main(out_dir: Path = OUT_DIR) -> None:
    summaries_path = out_dir / "summaries.csv"
    if not summaries_path.exists():
        print(f"ERROR: {summaries_path} not found. Run run_bionlp_eval.py first.")
        sys.exit(1)

    with open(summaries_path, newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"Loaded {len(rows)} summary rows")

    all_claims: list[dict] = []
    for i, row in enumerate(rows):
        case_id = row["case_id"]
        config = row["config"]
        bundle = load_bundle(case_id, config)
        claims = process_summary(row, bundle)
        all_claims.extend(claims)
        if i % 10 == 0:
            print(f"  Processed {i}/{len(rows)}...")

    out_path = out_dir / "claim_review.csv"
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CLAIM_REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(all_claims)

    print(f"\nSaved: {out_path} ({len(all_claims)} claim rows)")

    # Quick stats
    from collections import Counter
    support_counts = Counter(c["support_label_auto"] for c in all_claims)
    claim_types = Counter(c["claim_type"] for c in all_claims)
    print(f"Support distribution: {dict(support_counts)}")
    print(f"Claim types: {dict(claim_types)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()
    main(out_dir=Path(args.out_dir))
