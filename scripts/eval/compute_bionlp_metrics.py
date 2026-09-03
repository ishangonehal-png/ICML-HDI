#!/usr/bin/env python3
"""
compute_bionlp_metrics.py
=========================
Reads claim_review.csv, summaries.csv, and retrieval_discipline.csv and computes
all BioNLP evaluation metrics, writing metrics.json.

Metrics computed:
  - Core faithfulness (supported/partial/unsupported/unknown rates)
  - Numeric fidelity rate
  - Modality attribution accuracy
  - Completeness rubric per config (tier/pathology/RNA/clinical/uncertainty mention rates)
  - Retrieval discipline (standard vs literature prompt)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

OUT_DIR = Path(__file__).parent.parent.parent / "outputs" / "bionlp_eval"

_TIER_RE = re.compile(r"\b(hot|warm|cold)\b", re.IGNORECASE)
_PATH_RE = re.compile(r"\b(pathology|tumor|stroma|necrosis|lymphocyte|til|tile|wsi|slide)\b", re.IGNORECASE)
_RNA_RE = re.compile(r"\b(rna|transcriptomics?|cyt|gep|tide|gene|expression)\b", re.IGNORECASE)
_CLIN_RE = re.compile(r"\b(stage|age|smoking|smoker|clinical|survival|months?|risk)\b", re.IGNORECASE)
_UNCERT_RE = re.compile(
    r"\b(uncertain|limit|caveat|proxy|research.only|not for clinical|approximat|unavailable|missing)\b",
    re.IGNORECASE,
)
_LIT_RE = re.compile(
    r"\b(literature|pubmed|paper|study|studies|trial|citation|published)\b", re.IGNORECASE
)


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  WARNING: {path} not found — skipping")
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def str_to_bool(v: str) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def safe_div(n: int, d: int, default: float = 0.0) -> float:
    return round(n / d, 4) if d > 0 else default


def compute_faithfulness(claims: list[dict]) -> dict:
    """Core faithfulness metrics across standard-prompt summaries."""
    std_claims = [c for c in claims if c.get("prompt_type", "") == "standard"]
    total = len(std_claims)
    if total == 0:
        return {"error": "no standard-prompt claims"}

    counts = Counter(c["support_label_auto"] for c in std_claims)
    return {
        "total_claims": total,
        "supported_count": counts.get("supported", 0),
        "partial_count": counts.get("partial", 0),
        "unsupported_count": counts.get("unsupported", 0),
        "unknown_count": counts.get("unknown", 0),
        "supported_rate_auto": safe_div(counts.get("supported", 0), total),
        "partial_rate_auto": safe_div(counts.get("partial", 0), total),
        "unsupported_rate_auto": safe_div(counts.get("unsupported", 0), total),
        "unknown_rate_auto": safe_div(counts.get("unknown", 0), total),
    }


def compute_numeric_fidelity(claims: list[dict]) -> dict:
    """Numeric fidelity rate across sentences with numeric values."""
    std_claims = [c for c in claims if c.get("prompt_type", "") == "standard"]
    with_numerics = [c for c in std_claims if c.get("numeric_fidelity_auto", "") != "not_applicable"]
    correct = [c for c in with_numerics if c.get("numeric_fidelity_auto", "") == "correct"]
    return {
        "sentences_with_numerics": len(with_numerics),
        "numerically_correct": len(correct),
        "numeric_fidelity_rate_auto": safe_div(len(correct), len(with_numerics)),
    }


def compute_modality_attribution(claims: list[dict]) -> dict:
    """Modality attribution accuracy among sentences with identifiable modality."""
    std_claims = [c for c in claims if c.get("prompt_type", "") == "standard"]
    identifiable = [c for c in std_claims if c.get("modality_match_auto", "") != "unknown"]
    correct = [c for c in identifiable if c.get("modality_match_auto", "") == "correct"]
    return {
        "claims_with_identifiable_modality": len(identifiable),
        "modality_correct": len(correct),
        "modality_attribution_accuracy_auto": safe_div(len(correct), len(identifiable)),
    }


def compute_avg_claims_per_summary(summaries: list[dict], claims: list[dict]) -> dict:
    """Average sentences/claims per summary."""
    std_summaries = [r for r in summaries if r.get("prompt_type", "") == "standard"]
    if not std_summaries:
        return {"avg_sentences_per_summary": 0}
    total_sent = sum(int(r.get("num_sentences", 0)) for r in std_summaries)
    return {
        "total_standard_summaries": len(std_summaries),
        "total_standard_claims": len([c for c in claims if c.get("prompt_type", "") == "standard"]),
        "avg_sentences_per_summary": round(total_sent / len(std_summaries), 2),
    }


def completeness_for_text(text: str, config: str, rna_in_bundle: bool) -> dict:
    """Compute binary completeness signals for a single summary."""
    mentions_tier = bool(_TIER_RE.search(text))
    mentions_pathology = bool(_PATH_RE.search(text))
    mentions_rna = bool(_RNA_RE.search(text))
    mentions_clinical = bool(_CLIN_RE.search(text))
    mentions_uncertainty = bool(_UNCERT_RE.search(text))

    score = sum([
        mentions_tier,
        mentions_pathology,
        (mentions_rna if rna_in_bundle or config != "pathology_only" else True),  # don't penalize if RNA not in config
        mentions_clinical if config != "pathology_only" else True,
        mentions_uncertainty,
    ])

    return {
        "mentions_tier": mentions_tier,
        "mentions_pathology": mentions_pathology,
        "mentions_rna": mentions_rna,
        "mentions_clinical": mentions_clinical,
        "mentions_uncertainty": mentions_uncertainty,
        "completeness_score": score / 5,
    }


def compute_completeness_by_config(summaries: list[dict], bundles_dir: Path) -> dict:
    """Completeness rubric per config."""
    import json as _json
    std_rows = [r for r in summaries if r.get("prompt_type", "") == "standard"]
    by_config: dict[str, list] = defaultdict(list)
    for row in std_rows:
        by_config[row["config"]].append(row)

    results = {}
    for config, rows in by_config.items():
        tier_mentions = []
        path_mentions = []
        rna_mentions = []
        clin_mentions = []
        uncert_mentions = []
        completeness_scores = []

        for row in rows:
            # Load bundle to know if RNA was in this config
            bundle_path = bundles_dir / f"{row['case_id']}_{config}.json"
            rna_in_bundle = False
            if bundle_path.exists():
                with open(bundle_path) as f:
                    b = _json.load(f)
                rna_in_bundle = b.get("transcriptomics", {}).get("cyt_available", False)

            comp = completeness_for_text(row["summary_text"], config, rna_in_bundle)
            tier_mentions.append(comp["mentions_tier"])
            path_mentions.append(comp["mentions_pathology"])
            rna_mentions.append(comp["mentions_rna"])
            clin_mentions.append(comp["mentions_clinical"])
            uncert_mentions.append(comp["mentions_uncertainty"])
            completeness_scores.append(comp["completeness_score"])

        n = len(rows)
        results[config] = {
            "n_summaries": n,
            "tier_mention_rate": safe_div(sum(tier_mentions), n),
            "pathology_mention_rate": safe_div(sum(path_mentions), n),
            "rna_mention_rate": safe_div(sum(rna_mentions), n),
            "clinical_mention_rate": safe_div(sum(clin_mentions), n),
            "uncertainty_mention_rate": safe_div(sum(uncert_mentions), n),
            "mean_completeness_score": round(sum(completeness_scores) / n, 4) if n > 0 else 0,
        }
    return results


def compute_retrieval_discipline(retrieval_rows: list[dict], summaries: list[dict]) -> dict:
    """Retrieval discipline metrics."""
    if not retrieval_rows:
        return {"error": "no retrieval rows found"}

    lit_used_when_requested = [r for r in retrieval_rows if str_to_bool(r.get("literature_used_literature_prompt", "false"))]
    lit_used_without_request = [r for r in retrieval_rows if str_to_bool(r.get("literature_used_standard", "false"))]

    # Also check all standard summaries for unintended literature use
    std_summaries = [r for r in summaries if r.get("prompt_type") == "standard"]
    std_lit_used = [r for r in std_summaries if str_to_bool(r.get("literature_used", "false"))]

    retrieval_used_when_requested_rate = safe_div(
        len(lit_used_when_requested), len(retrieval_rows)
    )
    retrieval_used_without_request_rate = safe_div(
        len(lit_used_without_request), len(retrieval_rows)
    )

    # Count summaries where literature content is detectable in standard summaries
    std_with_lit_language = [
        r for r in std_summaries
        if _LIT_RE.search(r.get("summary_text", ""))
    ]

    # Provenance note: derive from the generation-time `notes` column recorded in
    # retrieval_discipline.csv, NOT from the ambient environment. The reduction is a
    # pure function of committed inputs, so re-running it (e.g. a reviewer verifying the
    # headline numbers) must not depend on whether OPENAI_API_KEY happens to be exported.
    csv_notes = sorted({r.get("notes", "").strip() for r in retrieval_rows if r.get("notes", "").strip()})
    if csv_notes:
        note = " | ".join(csv_notes)
    else:
        note = "No per-case retrieval provenance recorded in retrieval_discipline.csv."

    return {
        "retrieval_test_cases": len(retrieval_rows),
        "lit_used_when_requested_count": len(lit_used_when_requested),
        "lit_used_without_request_count": len(lit_used_without_request),
        "retrieval_used_when_requested_rate": retrieval_used_when_requested_rate,
        "retrieval_used_without_request_rate": retrieval_used_without_request_rate,
        "total_standard_summaries": len(std_summaries),
        "standard_summaries_with_lit_language": len(std_with_lit_language),
        "standard_summaries_with_lit_used_flag": len(std_lit_used),
        "note": note,
    }


def compute_judge_faithfulness(claims: list[dict]) -> dict:
    """Judge-based faithfulness using llm_judge_final labels (standard-prompt, grounded only)."""
    grounded = [c for c in claims
                if c.get("prompt_type") == "standard" and c.get("config") != "baseline"
                and c.get("llm_judge_final", "") != ""]
    if not grounded:
        return {"error": "no judge labels found"}
    total = len(grounded)
    counts = Counter(c["llm_judge_final"] for c in grounded)
    agree = [c for c in grounded if str(c.get("llm_judge_agreement", "")) == "True"]
    return {
        "total_claims_judged": total,
        "supported_count": counts.get("supported", 0),
        "partial_count":   counts.get("partial", 0),
        "unsupported_count": counts.get("unsupported", 0),
        "conflict_count":  counts.get("conflict", 0),
        "supported_rate_judge":    safe_div(counts.get("supported", 0), total),
        "partial_rate_judge":      safe_div(counts.get("partial", 0), total),
        "unsupported_rate_judge":  safe_div(counts.get("unsupported", 0), total),
        "judge_agreement_rate":    safe_div(len(agree), total),
        "note": "LLM-as-judge (GPT-4o-mini, T=0, two passes). Human annotation planned.",
    }


def compute_baseline_vs_grounded(claims: list[dict]) -> dict:
    """Compare grounded full_multimodal vs ungrounded baseline using judge labels."""
    grounded = [c for c in claims
                if c.get("config") == "full_multimodal"
                and c.get("prompt_type") == "standard"
                and c.get("llm_judge_final", "") not in ("", "conflict")]
    baseline = [c for c in claims
                if c.get("config") == "baseline"
                and c.get("prompt_type") == "standard"
                and c.get("llm_judge_final", "") not in ("", "conflict")]

    def rates(rows):
        total = len(rows)
        if total == 0:
            return {}
        ct = Counter(r["llm_judge_final"] for r in rows)
        return {
            "n": total,
            "supported_rate": safe_div(ct.get("supported", 0), total),
            "partial_rate":   safe_div(ct.get("partial", 0), total),
            "unsupported_rate": safe_div(ct.get("unsupported", 0), total),
        }

    g = rates(grounded)
    b = rates(baseline)
    return {
        "grounded_full_multimodal": g,
        "ungrounded_baseline": b,
        "delta_supported": round(g.get("supported_rate", 0) - b.get("supported_rate", 0), 4),
        "delta_unsupported": round(b.get("unsupported_rate", 0) - g.get("unsupported_rate", 0), 4),
        "interpretation": (
            "Positive delta_supported means grounded system is more faithful. "
            "Positive delta_unsupported means baseline introduces more unsupported claims."
        ),
    }


def main(out_dir: Path = OUT_DIR) -> None:
    claims_path = out_dir / "claim_review.csv"
    summaries_path = out_dir / "summaries.csv"
    retrieval_path = out_dir / "retrieval_discipline.csv"
    bundles_dir = out_dir / "evidence_bundles"

    claims = load_csv(claims_path)
    summaries = load_csv(summaries_path)
    retrieval_rows = load_csv(retrieval_path)

    print(f"Loaded: {len(claims)} claims, {len(summaries)} summaries, {len(retrieval_rows)} retrieval rows")

    metrics = {}

    print("Computing faithfulness metrics...")
    metrics["faithfulness"] = compute_faithfulness(claims)

    print("Computing numeric fidelity...")
    metrics["numeric_fidelity"] = compute_numeric_fidelity(claims)

    print("Computing modality attribution...")
    metrics["modality_attribution"] = compute_modality_attribution(claims)

    print("Computing average claims/summary...")
    metrics["summary_stats"] = compute_avg_claims_per_summary(summaries, claims)

    print("Computing completeness by config...")
    metrics["completeness_by_config"] = compute_completeness_by_config(summaries, bundles_dir)

    print("Computing retrieval discipline...")
    metrics["retrieval_discipline"] = compute_retrieval_discipline(retrieval_rows, summaries)

    print("Computing LLM-judge faithfulness...")
    metrics["judge_faithfulness"] = compute_judge_faithfulness(claims)

    print("Computing grounded vs baseline comparison...")
    metrics["baseline_comparison"] = compute_baseline_vs_grounded(claims)

    # Combined headline metrics
    metrics["headline"] = {
        "supported_rate": metrics["faithfulness"].get("supported_rate_auto", 0),
        "partial_rate": metrics["faithfulness"].get("partial_rate_auto", 0),
        "unsupported_rate": metrics["faithfulness"].get("unsupported_rate_auto", 0),
        "numeric_fidelity_rate": metrics["numeric_fidelity"].get("numeric_fidelity_rate_auto", 0),
        "modality_attribution_accuracy": metrics["modality_attribution"].get("modality_attribution_accuracy_auto", 0),
        "avg_sentences_per_summary": metrics["summary_stats"].get("avg_sentences_per_summary", 0),
        "full_multimodal_completeness": metrics["completeness_by_config"].get("full_multimodal", {}).get("mean_completeness_score", 0),
        "pathology_only_completeness": metrics["completeness_by_config"].get("pathology_only", {}).get("mean_completeness_score", 0),
        "retrieval_discipline_rate_when_requested": metrics["retrieval_discipline"].get("retrieval_used_when_requested_rate", 0),
        "retrieval_false_positive_rate": metrics["retrieval_discipline"].get("retrieval_used_without_request_rate", 0),
        "judge_supported_rate": metrics["judge_faithfulness"].get("supported_rate_judge", 0),
        "judge_unsupported_rate": metrics["judge_faithfulness"].get("unsupported_rate_judge", 0),
        "judge_agreement_rate": metrics["judge_faithfulness"].get("judge_agreement_rate", 0),
        "grounded_vs_baseline_delta_supported": metrics["baseline_comparison"].get("delta_supported", 0),
        "grounded_vs_baseline_delta_unsupported": metrics["baseline_comparison"].get("delta_unsupported", 0),
    }

    metrics_path = out_dir / "metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\nSaved: {metrics_path}")

    # Print headline
    h = metrics["headline"]
    print("\n=== HEADLINE METRICS ===")
    print(f"  Supported rate:           {h['supported_rate']:.1%}")
    print(f"  Partial rate:             {h['partial_rate']:.1%}")
    print(f"  Unsupported rate:         {h['unsupported_rate']:.1%}")
    print(f"  Numeric fidelity rate:    {h['numeric_fidelity_rate']:.1%}")
    print(f"  Modality attr. accuracy:  {h['modality_attribution_accuracy']:.1%}")
    print(f"  Avg sentences/summary:    {h['avg_sentences_per_summary']:.1f}")
    print(f"  Full-MM completeness:     {h['full_multimodal_completeness']:.1%}")
    print(f"  Retrieval (requested):    {h['retrieval_discipline_rate_when_requested']:.1%}")
    print(f"  Retrieval (unrequested):  {h['retrieval_false_positive_rate']:.1%}")
    print(f"\n--- LLM-Judge (GPT-4o-mini, T=0, two passes) ---")
    j = metrics["judge_faithfulness"]
    print(f"  Judge supported rate:     {j.get('supported_rate_judge',0):.1%}")
    print(f"  Judge partial rate:       {j.get('partial_rate_judge',0):.1%}")
    print(f"  Judge unsupported rate:   {j.get('unsupported_rate_judge',0):.1%}")
    print(f"  Judge agreement rate:     {j.get('judge_agreement_rate',0):.1%}")
    print(f"\n--- Grounded vs Ungrounded Baseline ---")
    bc = metrics["baseline_comparison"]
    g  = bc.get("grounded_full_multimodal", {})
    b  = bc.get("ungrounded_baseline", {})
    print(f"  Grounded supported:       {g.get('supported_rate',0):.1%}")
    print(f"  Baseline supported:       {b.get('supported_rate',0):.1%}")
    print(f"  Δ supported (grounded - baseline): {bc.get('delta_supported',0):+.1%}")
    print(f"  Grounded unsupported:     {g.get('unsupported_rate',0):.1%}")
    print(f"  Baseline unsupported:     {b.get('unsupported_rate',0):.1%}")
    print(f"  Δ unsupported (baseline - grounded): {bc.get('delta_unsupported',0):+.1%}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()
    main(out_dir=Path(args.out_dir))
