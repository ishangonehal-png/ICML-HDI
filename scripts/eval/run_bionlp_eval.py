#!/usr/bin/env python3
"""
run_bionlp_eval.py
==================
BioNLP evaluation: case selection, evidence bundle capture, summary generation (3 ablation configs),
and retrieval-discipline test.

Outputs (written to outputs/bionlp_eval/):
  case_selection.csv
  summaries.csv
  evidence_bundles/<case_id>_<config>.json
  retrieval_discipline.csv   (10-case subset)

Usage:
  python scripts/eval/run_bionlp_eval.py [--repo-root <path>] [--out-dir <path>]

The script calls the existing API services directly (db=None → deterministic fallbacks).
If OPENAI_API_KEY is set, the real LLM path is used; otherwise the structured fallback answer
(_build_repo_fallback_answer) is used and documented in the report.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import warnings
from copy import deepcopy
from pathlib import Path
from typing import Any

# ── bootstrap (must come before any API imports) ──────────────────────────────
_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR))
import _eval_bootstrap  # noqa: E402

_REPO_ROOT = Path(__file__).parent.parent.parent
_eval_bootstrap.setup(str(_REPO_ROOT))

warnings.filterwarnings("ignore", category=UserWarning)

# ── API service imports ───────────────────────────────────────────────────────
from services.agent_context import build_agent_context  # noqa: E402
from services.io_score import get_io_immune_score  # noqa: E402
from services.llm_agent import _need_pubmed, run_llm_agent  # noqa: E402
from services.transcriptomics import (  # noqa: E402
    get_cyt_signature,
    get_gep_signature,
    get_tide_signature,
)
from services.pathology import get_tissue_composition  # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────────
CONFIGS = ["pathology_only", "pathology_rna", "full_multimodal"]

# Standard prompt: deliberately avoids "literature"/"paper"/"study" keywords
# so _need_pubmed() returns False.
STANDARD_PROMPT = (
    "Summarize this patient's immunotherapy readiness using only the available structured evidence. "
    "State the IO immune tier, key pathology evidence, RNA evidence if available, clinical context "
    "if relevant, and any uncertainty or limitations. Keep the response concise and factual."
)

# Literature prompt: contains "literature" → triggers _need_pubmed()
LITERATURE_PROMPT = (
    "Summarize this patient's immunotherapy readiness using the available structured evidence, "
    "and add brief relevant literature context if available. Clearly distinguish patient-specific "
    "evidence from literature-derived context. Keep the response concise and factual."
)

TARGET_N = 119
TARGET_HOT = 40
TARGET_WARM = 40
TARGET_COLD = 39
RETRIEVAL_N = 10  # cases used for retrieval discipline test

DATA_CSV = _REPO_ROOT / "data" / "luad" / "fused_pathology_rna_embeddings_with_metadata.csv"
OUT_DIR = _REPO_ROOT / "outputs" / "bionlp_eval"
BUNDLES_DIR = OUT_DIR / "evidence_bundles"


# ── helpers ───────────────────────────────────────────────────────────────────

def load_case_ids() -> list[str]:
    ids: list[str] = []
    with open(DATA_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            tcga_id = row.get("tcga_id", "").strip()
            if tcga_id:
                ids.append(tcga_id)
    return ids


def compute_io_tier(case_id: str) -> dict[str, Any]:
    """
    Compute IO tier and component values for a case (deterministic fallbacks).

    NOTE: Without real artifact files, CYT/GEP/TIDE are all unavailable so the
    pure IO biomarker score collapses to TIL-fraction only (~0.07 for all cases → all Cold).
    We therefore use the FUSION SCORE (which incorporates pathology + clinical signals) as
    the primary tier indicator. Tiers are assigned by the same thresholds but applied to the
    fusion score. This is documented in report.md.
    """
    from services.fusion import get_fusion_score as _get_fusion_score
    slide_id = f"{case_id}-DX1"
    tissue = get_tissue_composition(slide_id, strict_missing=False)
    til_frac = next(
        (f.fraction for f in tissue.fractions if "lymphocyte" in f.tissue.lower()), None
    )
    cyt = get_cyt_signature(case_id, db=None)
    gep = get_gep_signature(case_id, db=None)
    tide = get_tide_signature(case_id, db=None)

    io = get_io_immune_score(
        case_id,
        til_fraction=til_frac,
        cyt_value=cyt.value if cyt.available else None,
        gep_value=gep.value if gep.available else None,
        tide_value=tide.value if tide.available else None,
    )

    # Use fusion score for tier since IO score collapses to all-Cold without artifacts
    fs = _get_fusion_score(case_id, include_rna=True, db=None)
    active_score = fs.refined_score if fs.mode_used == "refined" else fs.provisional_score

    return {
        "case_id": case_id,
        "io_score": active_score,  # fusion score used as primary tier signal
        "io_score_biomarker_only": io.score,  # pure biomarker score (all-Cold in fallback)
        "io_tier": io.tier,  # will be overridden after population-level tertile assignment
        "til_fraction": til_frac,
        "cyt_value": cyt.value,
        "cyt_available": cyt.available,
        "gep_value": gep.value,
        "gep_available": gep.available,
        "tide_value": tide.value,
        "tide_available": tide.available,
        "rna_available": io.rna_available,
        "provisional_score": io.provisional_score,
        "refined_score": io.refined_score,
    }


def assign_tiers_by_tertile(scored: list[dict]) -> list[dict]:
    """
    Since deterministic fallback produces no Cold cases via the biomarker-only IO score,
    assign tiers by score tertile across the cohort so the evaluation spans all 3 groups.
    Top third → Hot, middle → Warm, bottom → Cold.
    """
    sorted_scores = sorted(scored, key=lambda c: c["io_score"])
    n = len(sorted_scores)
    low_cut = sorted_scores[n // 3]["io_score"]
    high_cut = sorted_scores[2 * n // 3]["io_score"]
    for c in scored:
        if c["io_score"] >= high_cut:
            c["io_tier"] = "Hot"
        elif c["io_score"] >= low_cut:
            c["io_tier"] = "Warm"
        else:
            c["io_tier"] = "Cold"
    return scored


def select_cases(scored: list[dict]) -> list[dict]:
    """Select TARGET_N cases balanced across IO tiers."""
    hot = [c for c in scored if c["io_tier"] == "Hot"]
    warm = [c for c in scored if c["io_tier"] == "Warm"]
    cold = [c for c in scored if c["io_tier"] == "Cold"]

    # Sort each tier by io_score to prefer cases with fuller data (higher score spread)
    hot.sort(key=lambda c: c["io_score"], reverse=True)
    warm.sort(key=lambda c: abs(c["io_score"] - 0.525))  # pick mid-Warm
    cold.sort(key=lambda c: c["io_score"])  # pick least cold to avoid edge cases

    selected = hot[:TARGET_HOT] + warm[:TARGET_WARM] + cold[:TARGET_COLD]

    # If any tier is short, fill from the others
    remaining_pool = [c for c in scored if c not in selected]
    remaining_pool.sort(key=lambda c: c["io_score"])
    while len(selected) < TARGET_N and remaining_pool:
        selected.append(remaining_pool.pop(0))

    return selected[:TARGET_N]


def build_case_context_full(case_id: str) -> tuple[Any, dict]:
    """Build the full evidence bundle (all modalities)."""
    ctx, raw = build_agent_context(case_id, db=None, include_raw=True)
    return ctx, raw


def mask_raw_for_config(raw: dict, config: str) -> dict:
    """
    Ablation masking: return a modified copy of raw case_context with certain
    modalities zeroed-out.

    pathology_only  → CYT/GEP/TIDE unavailable, clinical minimal
    pathology_rna   → clinical minimal (CYT/GEP/TIDE kept)
    full_multimodal → unchanged
    """
    if config == "full_multimodal":
        return raw

    import copy
    masked = copy.deepcopy(raw)

    if config == "pathology_only":
        # Zero out transcriptomics
        _zero_metric(masked, "cyt")
        _zero_metric(masked, "gep")
        _zero_metric(masked, "tide")
        # Also zero transcriptomic_evidence top_genes
        if hasattr(masked.get("transcriptomic_evidence"), "top_genes"):
            try:
                object.__setattr__(masked["transcriptomic_evidence"], "top_genes", [])
            except Exception:
                pass

    # For pathology_rna, keep CYT/GEP/TIDE but mark clinical as minimal
    # (clinical is already minimal / deterministic in fallback mode)
    # No additional masking needed for pathology_rna since clinical uses
    # deterministic proxy regardless.

    return masked


def _zero_metric(raw: dict, key: str) -> None:
    """Replace a TranscriptomicsMetricResponse in raw with an unavailable version."""
    from schemas.transcriptomics import TranscriptomicsMetricResponse
    from schemas.pathology import MethodMetadata
    from datetime import datetime, timezone

    # Get the original to copy required fields
    original = raw.get(key)
    case_id = getattr(original, "case_id", "unknown") if original else "unknown"

    raw[key] = TranscriptomicsMetricResponse(
        case_id=case_id,
        value=None,
        available=False,
        data_source="unavailable",
        availability_code="missing_input",
        unavailable_reason=f"Masked for ablation: {key} excluded in this config (eval-only)",
        meta=MethodMetadata(
            method=f"eval-mask-{key}",
            version="eval-v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
            proxy_estimate=True,
        ),
    )


def build_evidence_bundle(
    case_id: str, config: str, raw: dict, io_info: dict, prompt_type: str,
    literature_used: bool, citations: list
) -> dict:
    """Assemble the evidence bundle JSON for a case/config combination."""
    tissue = raw.get("tissue")
    evidence = raw.get("evidence")
    cyt = raw.get("cyt")
    gep = raw.get("gep")
    tide = raw.get("tide")
    fusion_score = raw.get("fusion_score")
    fusion_attribution = raw.get("fusion_attribution")

    tissue_fractions = {}
    if tissue and tissue.fractions:
        for frac in tissue.fractions:
            tissue_fractions[frac.tissue.lower().replace(" ", "_").replace("-", "_")] = round(frac.fraction, 4)

    top_tiles = []
    if evidence and evidence.top_tiles:
        for tile in evidence.top_tiles:
            top_tiles.append({
                "tile_id": tile.tile_id,
                "score": round(tile.score, 4),
                "rationale": tile.rationale,
            })

    modality_contribs = {}
    if fusion_attribution and fusion_attribution.modalities:
        for m in fusion_attribution.modalities:
            modality_contribs[m.modality] = {
                "contribution_percent": round(m.contribution_percent, 2),
                "available": m.available,
                "data_source": m.data_source,
                "summary": m.summary,
            }

    lit_citations = []
    for c in citations:
        lit_citations.append({
            "panel": c.panel,
            "field": c.field,
            "source": c.source,
            "value": c.value,
        })

    bundle = {
        "case_id": case_id,
        "config": config,
        "prompt_type": prompt_type,
        "io_score": round(io_info["io_score"], 4),
        "io_tier": io_info["io_tier"],
        "provisional_score": round(io_info["provisional_score"], 4),
        "refined_score": round(io_info["refined_score"], 4) if io_info["refined_score"] is not None else None,
        "rna_available": io_info["rna_available"],
        "pathology": {
            "tissue_fractions": tissue_fractions,
            "top_tiles": top_tiles,
            "til_fraction": round(io_info["til_fraction"], 4) if io_info["til_fraction"] is not None else None,
        },
        "transcriptomics": {
            "cyt_value": round(cyt.value, 4) if (cyt and cyt.available and cyt.value is not None) else None,
            "cyt_available": cyt.available if cyt else False,
            "gep_value": round(gep.value, 4) if (gep and gep.available and gep.value is not None) else None,
            "gep_available": gep.available if gep else False,
            "tide_value": round(tide.value, 4) if (tide and tide.available and tide.value is not None) else None,
            "tide_available": tide.available if tide else False,
        },
        "fusion": {
            "mode_used": fusion_score.mode_used if fusion_score else "unknown",
            "active_score": round(
                (fusion_score.refined_score if fusion_score.mode_used == "refined" else fusion_score.provisional_score), 4
            ) if fusion_score else None,
            "modality_contributions": modality_contribs,
        },
        "literature_retrieval_invoked": literature_used,
        "literature_citations": lit_citations,
    }

    # Try to extract clinical fields from the context string
    return bundle


def generate_summary(case_id: str, config: str, prompt: str, prompt_type: str, raw: dict, ctx: Any) -> tuple[str, list, bool]:
    """Generate a summary for a case/config/prompt combination."""
    masked_raw = mask_raw_for_config(raw, config)
    literature_requested = _need_pubmed(prompt)
    answer, citations = run_llm_agent(
        case_id=case_id,
        question=prompt,
        case_context=masked_raw,
        context_for_llm=ctx.context_for_llm,
    )
    literature_used = len(citations) > 0
    return answer, citations, literature_used


def count_sentences(text: str) -> int:
    """Count sentences in text."""
    # Split on sentence-ending punctuation followed by space or end
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return len([s for s in sentences if s.strip()])


def main(out_dir: Path = OUT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    bundles_dir = out_dir / "evidence_bundles"
    bundles_dir.mkdir(exist_ok=True)

    print("Loading cases from CSV...")
    case_ids = load_case_ids()
    print(f"  Found {len(case_ids)} cases")

    print("Computing IO tiers for all cases...")
    scored = []
    for i, case_id in enumerate(case_ids):
        if i % 20 == 0:
            print(f"  {i}/{len(case_ids)}...")
        scored.append(compute_io_tier(case_id))

    # Assign tiers by tertile since deterministic fallback gives all-Cold for biomarker-only score
    scored = assign_tiers_by_tertile(scored)

    tier_counts = {"Hot": 0, "Warm": 0, "Cold": 0}
    for c in scored:
        tier_counts[c["io_tier"]] = tier_counts.get(c["io_tier"], 0) + 1
    print(f"  Tier distribution (full cohort, tertile-assigned): {tier_counts}")

    print("Selecting 20 cases...")
    selected = select_cases(scored)
    tier_sel = {"Hot": 0, "Warm": 0, "Cold": 0}
    for c in selected:
        tier_sel[c["io_tier"]] = tier_sel.get(c["io_tier"], 0) + 1
    print(f"  Selected tier distribution: {tier_sel}")

    # Write case_selection.csv
    case_sel_path = out_dir / "case_selection.csv"
    with open(case_sel_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "case_id", "io_tier", "io_score", "has_pathology",
            "has_rna", "has_clinical", "selection_reason"
        ])
        writer.writeheader()
        for c in selected:
            tier_group = c["io_tier"]
            targets = {"Hot": TARGET_HOT, "Warm": TARGET_WARM, "Cold": TARGET_COLD}
            writer.writerow({
                "case_id": c["case_id"],
                "io_tier": c["io_tier"],
                "io_score": round(c["io_score"], 4),
                "has_pathology": True,  # all cases have pathology (deterministic fallback)
                "has_rna": c["rna_available"],
                "has_clinical": True,  # all cases have clinical (deterministic fallback)
                "selection_reason": (
                    f"Tier-balanced selection: {tier_group} tier "
                    f"(target {targets.get(tier_group, '?')}); "
                    f"deterministic fallback data; score={c['io_score']:.3f}"
                ),
            })
    print(f"  Saved: {case_sel_path}")

    # Build full evidence bundles and generate summaries
    print("\nGenerating summaries (3 configs × standard prompt, plus literature prompt for first 10 cases)...")
    summaries_rows: list[dict] = []
    retrieval_rows: list[dict] = []

    retrieval_cases = [c["case_id"] for c in selected[:RETRIEVAL_N]]

    for i, case_info in enumerate(selected):
        case_id = case_info["case_id"]
        print(f"\n  [{i+1}/{TARGET_N}] {case_id} (IO {case_info['io_tier']}, score={case_info['io_score']:.3f})")

        # Build full context once
        ctx, raw = build_case_context_full(case_id)

        # --- 3 ablation configs with standard prompt ---
        for config in CONFIGS:
            print(f"    config={config}...", end="", flush=True)
            answer, citations, lit_used = generate_summary(
                case_id, config, STANDARD_PROMPT, "standard", raw, ctx
            )
            lit_requested = _need_pubmed(STANDARD_PROMPT)
            n_sent = count_sentences(answer)

            summaries_rows.append({
                "case_id": case_id,
                "config": config,
                "prompt_type": "standard",
                "summary_text": answer,
                "io_tier_expected": case_info["io_tier"],
                "literature_requested": lit_requested,
                "literature_used": lit_used,
                "num_sentences": n_sent,
                "num_chars": len(answer),
            })

            # Save evidence bundle
            masked_raw = mask_raw_for_config(raw, config)
            bundle = build_evidence_bundle(
                case_id, config, masked_raw, case_info, "standard", lit_used, citations
            )
            bundle_path = bundles_dir / f"{case_id}_{config}.json"
            with open(bundle_path, "w") as f:
                json.dump(bundle, f, indent=2, default=str)
            print(f" done ({n_sent} sentences)")

        # --- Literature prompt (for retrieval discipline cases) ---
        if case_id in retrieval_cases:
            print(f"    config=full_multimodal, prompt=literature...", end="", flush=True)
            lit_answer, lit_citations, lit_used = generate_summary(
                case_id, "full_multimodal", LITERATURE_PROMPT, "literature", raw, ctx
            )
            lit_requested = _need_pubmed(LITERATURE_PROMPT)

            summaries_rows.append({
                "case_id": case_id,
                "config": "full_multimodal",
                "prompt_type": "literature",
                "summary_text": lit_answer,
                "io_tier_expected": case_info["io_tier"],
                "literature_requested": lit_requested,
                "literature_used": lit_used,
                "num_sentences": count_sentences(lit_answer),
                "num_chars": len(lit_answer),
            })

            # Retrieval discipline row
            std_row = next(
                (r for r in summaries_rows
                 if r["case_id"] == case_id and r["config"] == "full_multimodal" and r["prompt_type"] == "standard"),
                {}
            )
            retrieval_rows.append({
                "case_id": case_id,
                "summary_standard": std_row.get("summary_text", ""),
                "summary_literature": lit_answer,
                "literature_used_standard": std_row.get("literature_used", False),
                "literature_used_literature_prompt": lit_used,
                "notes": (
                    "OpenAI key not set — retrieval path not reached; "
                    "_need_pubmed() would trigger but LLM fallback returned structured summary. "
                    if not os.environ.get("OPENAI_API_KEY")
                    else "OpenAI-generated summary with/without PubMed RAG."
                ),
            })
            print(f" done")

    # Write summaries.csv
    summaries_path = out_dir / "summaries.csv"
    with open(summaries_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "case_id", "config", "prompt_type", "summary_text",
            "io_tier_expected", "literature_requested", "literature_used",
            "num_sentences", "num_chars",
        ])
        writer.writeheader()
        writer.writerows(summaries_rows)
    print(f"\nSaved: {summaries_path} ({len(summaries_rows)} rows)")

    # Write retrieval_discipline.csv
    retrieval_path = out_dir / "retrieval_discipline.csv"
    with open(retrieval_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "case_id", "summary_standard", "summary_literature",
            "literature_used_standard", "literature_used_literature_prompt", "notes"
        ])
        writer.writeheader()
        writer.writerows(retrieval_rows)
    print(f"Saved: {retrieval_path} ({len(retrieval_rows)} rows)")

    print("\nrun_bionlp_eval.py complete.")
    print(f"  Evidence bundles: {bundles_dir}")
    print(f"  Summaries: {summaries_path}")
    print(f"  Case selection: {case_sel_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(_REPO_ROOT))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()
    main(out_dir=Path(args.out_dir))
