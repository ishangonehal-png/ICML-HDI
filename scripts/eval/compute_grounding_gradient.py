#!/usr/bin/env python3
"""
compute_grounding_gradient.py
=============================
Reduces the depth-of-grounding ablation reported in the paper as Table 6
(``tab:gradient`` in paper_8page_icml.tex, ``tab:gradient`` / ``tab:gradient-app``
in paper_4page_icml.tex): supported rate by generation condition
(pathology_only <= pathology_rna <= full_multimodal, collapsing on baseline),
for each of the four generator models.

Unlike the other paper tables, ``tab:gradient`` had no committed reduction. Its
caption states the cells are the *auto*-supported rate and asserts they are
"monotone in evidence depth for every model." This script computes the ablation
directly from the released ``claim_review.csv`` under BOTH documented reductions
(rule-based ``support_label_auto`` and the fixed judge's ``llm_judge_final``,
conflict/empty excluded), plus the judge unsupported rate and HDI per grounded
condition, and checks the paper's two claims (the reduction and the
monotonicity) cell by cell.

Everything here is stdlib, offline, and deterministic given the released CSVs.
No API keys, no embeddings.

Usage:
    python3 scripts/eval/compute_grounding_gradient.py
    python3 scripts/eval/compute_grounding_gradient.py --out outputs/grounding_gradient.csv
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

REPO = Path(__file__).parent.parent.parent

# model -> released run directory
MODEL_DIRS = {
    "gpt-4o-mini": REPO / "outputs" / "bionlp_eval",
    "gpt-5.4-mini": REPO / "outputs" / "bionlp_eval_gpt54mini",
    "gemini-2.5-flash": REPO / "outputs" / "bionlp_eval_gemini25flash",
    "gemini-3-flash-preview": REPO / "outputs" / "bionlp_eval_gemini",
}

GROUNDED = ["pathology_only", "pathology_rna", "full_multimodal"]
CONFIGS = GROUNDED + ["baseline"]

# Paper tab:gradient (8-page l.238-241; identical in 4-page tab:gradient-app).
# Columns: pathology_only, pathology_rna, full_multimodal, baseline.
PAPER = {
    "gpt-4o-mini": [0.80, 0.80, 0.84, 0.01],
    "gpt-5.4-mini": [0.85, 0.87, 0.88, 0.04],
    "gemini-2.5-flash": [0.89, 0.91, 0.93, 0.05],
    "gemini-3-flash-preview": [0.76, 0.79, 0.82, 0.05],
}


def load_standard_claims(run_dir: Path) -> list[dict]:
    path = run_dir / "claim_review.csv"
    with open(path, newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("prompt_type") == "standard"]


def rate_auto_supported(rows: list[dict]) -> tuple[float, int]:
    """Rule-based auto-supported rate (denominator = all standard claims)."""
    n = len(rows)
    if n == 0:
        return float("nan"), 0
    sup = sum(1 for r in rows if r["support_label_auto"] == "supported")
    return sup / n, n


def rate_judge(rows: list[dict], label: str) -> tuple[float, int]:
    """Judge rate for ``label`` with conflict/empty rows excluded (matches the
    baseline_comparison reduction in compute_bionlp_metrics.py)."""
    judged = [r for r in rows if r["llm_judge_final"] not in ("", "conflict")]
    n = len(judged)
    if n == 0:
        return float("nan"), 0
    return sum(1 for r in judged if r["llm_judge_final"] == label) / n, n


def is_monotone(vals: list[float]) -> bool:
    return all(vals[i] <= vals[i + 1] + 1e-9 for i in range(len(vals) - 1))


def main(out_path: Path) -> None:
    rows_out = []
    hdi_by_config: dict[str, dict[str, float]] = {c: {} for c in GROUNDED}

    print("Depth-of-grounding ablation (paper Table 6 / tab:gradient)\n")
    header = f"{'model':24s} {'config':16s} {'n':>5s} {'auto_sup':>9s} {'judge_sup':>10s} {'judge_uns':>10s} {'HDI':>8s} {'paper':>6s}"
    print(header)
    print("-" * len(header))

    for model, run_dir in MODEL_DIRS.items():
        claims = load_standard_claims(run_dir)
        by_cfg = {c: [r for r in claims if r["config"] == c] for c in CONFIGS}

        u_base, _ = rate_judge(by_cfg["baseline"], "unsupported")

        for i, cfg in enumerate(CONFIGS):
            rows = by_cfg[cfg]
            auto_sup, n_auto = rate_auto_supported(rows)
            judge_sup, n_judge = rate_judge(rows, "supported")
            judge_uns, _ = rate_judge(rows, "unsupported")
            hdi = (u_base - judge_uns) / u_base if u_base and cfg != "baseline" else float("nan")
            if cfg in GROUNDED:
                hdi_by_config[cfg][model] = hdi
            paper = PAPER[model][i]
            rows_out.append({
                "model": model,
                "config": cfg,
                "n_claims": n_auto,
                "n_judged": n_judge,
                "supported_rate_auto": round(auto_sup, 4),
                "supported_rate_judge": round(judge_sup, 4),
                "unsupported_rate_judge": round(judge_uns, 4),
                "hdi_judge_vs_baseline": ("" if cfg == "baseline" else round(hdi, 4)),
                "paper_tab_gradient": paper,
            })
            hdi_s = "  --  " if cfg == "baseline" else f"{hdi:8.3f}"
            print(f"{model:24s} {cfg:16s} {n_auto:5d} {auto_sup:9.4f} {judge_sup:10.4f} {judge_uns:10.4f} {hdi_s} {paper:6.2f}")

    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)
    print(f"\nWrote {out_path.relative_to(REPO)}")

    # --- Claim checks ------------------------------------------------------
    print("\n=== Does the paper's stated reduction reproduce? (|cell - paper| <= 0.01) ===")
    for reduction in ("supported_rate_auto", "supported_rate_judge"):
        grounded_hits = 0
        base_hits = 0
        for r in rows_out:
            got = r[reduction]
            hit = abs(got - r["paper_tab_gradient"]) <= 0.01
            if r["config"] == "baseline":
                base_hits += hit
            else:
                grounded_hits += hit
        tag = "auto (what the caption claims)" if reduction.endswith("auto") else "judge (excl. conflict)"
        print(f"  {tag:34s}: grounded cells {grounded_hits}/12, baseline cells {base_hits}/4 match")

    print("\n=== Monotonicity: path <= path_rna <= full? ===")
    for reduction in ("supported_rate_auto", "supported_rate_judge"):
        mono = 0
        for model in MODEL_DIRS:
            vals = [r[reduction] for c in GROUNDED for r in rows_out if r["model"] == model and r["config"] == c]
            mono += is_monotone(vals)
        tag = "auto" if reduction.endswith("auto") else "judge"
        print(f"  {tag:6s}: monotone for {mono}/4 models")

    print("\n=== HDI ranking invariance across grounded conditions (app:conditions) ===")
    rankings = {cfg: sorted(hdi_by_config[cfg], key=lambda m: -hdi_by_config[cfg][m]) for cfg in GROUNDED}
    for cfg in GROUNDED:
        print(f"  {cfg:16s}: {' > '.join(rankings[cfg])}")
    invariant = len({tuple(rankings[c]) for c in GROUNDED}) == 1
    print(f"  ranking identical across all three grounded conditions: {invariant}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "outputs" / "grounding_gradient.csv"))
    args = ap.parse_args()
    main(Path(args.out))
