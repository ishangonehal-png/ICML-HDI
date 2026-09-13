#!/usr/bin/env python3
"""
compute_hdi_robustness.py
=========================
Recomputes the Hallucination Dependence Index (HDI, Eq. 1) for all four models
under the three checker regimes the paper claims are interchangeable, and tests the
paper's checker-invariance claim directly.

HDI = (u_b - u_g) / u_b, where u_b, u_g are the unsupported-claim rates in the
ungrounded baseline and grounded full_multimodal conditions (prompt_type=standard).
The headline number (tab:panel) uses the LLM judge label. The paper additionally
asserts, three times, that this ranking is robust to the checker used:

  - line 187:  "restricting Table 3 to the subset of claims where the rule-based
               checker and the LLM judge concur preserves the same four-way ordering
               and keeps gpt-5.4-mini below all three other models."
  - line 228:  "we recompute HDI under both labels and under the agreement-gated
               subset for the robustness analysis."
  - line 329:  "recomputing HDI on the pure rule-based label ... preserves the
               Mode A / Mode B separation, even though the rule-based-only u_b is
               artificially compressed by checker conservatism."

No committed script computed HDI under anything but the judge label, so these three
robustness claims rested on out-of-tree analysis. This script closes that gap.

Three checker regimes (all offline, over the committed claim_review.csv files):
  judge : llm_judge_final, excluding "" / "conflict" (the headline reduction,
          identical to compute_bionlp_metrics.compute_baseline_vs_grounded)
  auto  : support_label_auto (the pure rule-based checker; no conflict gating)
  gated : the subset where support_label_auto == llm_judge_final (both checkers
          concur, judge non-conflict); rate taken on the concurring label

For each model x regime it reports u_b, u_g, HDI, the per-condition claim counts,
the four-way ranking, and the Mode-A classification (HDI >= 0.7). Mode B additionally
requires overlap@0.80 <= 0.05, whose overlap leg is not reproducible from committed
artifacts (see REPRODUCIBILITY.md Table 3 caveat), so we flag Mode-B *candidates*
(HDI <= 0.4) rather than assert Mode B.

Inputs (released, offline, no API keys): the four outputs/bionlp_eval*/claim_review.csv
Writes:
  - outputs/hdi_robustness.csv  (tidy: one row per model x regime)
  - outputs/hdi_robustness.md   (ranking table + claim-by-claim verdict)
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# model -> run directory, in the paper's factorial order
RUNS = {
    "gpt-4o-mini": "outputs/bionlp_eval",
    "gpt-5.4-mini": "outputs/bionlp_eval_gpt54mini",
    "gemini-2.5-flash": "outputs/bionlp_eval_gemini25flash",
    "gemini-3-flash-preview": "outputs/bionlp_eval_gemini",
}

# Paper's printed tab:panel HDI values (judge label), for the reproduction check.
PAPER_HDI_JUDGE = {
    "gpt-4o-mini": 0.984,
    "gemini-2.5-flash": 0.919,
    "gemini-3-flash-preview": 0.847,
    "gpt-5.4-mini": 0.336,
}

MODE_A_MIN = 0.70   # HDI >= 0.70  -> Mode A (overt confabulation, suppressed)
MODE_B_MAX = 0.40   # HDI <= 0.40  -> Mode B candidate (needs overlap@0.80 <= 0.05)

JUDGE_GATED_OUT = {"", "conflict"}


def load_claims(run_dir: Path) -> list[dict]:
    with open(run_dir / "claim_review.csv", newline="") as f:
        return list(csv.DictReader(f))


def unsupported_rate(rows: list[dict], label_col: str) -> tuple[float | None, int]:
    """Fraction of rows whose label is 'unsupported'. None if the subset is empty."""
    n = len(rows)
    if n == 0:
        return None, 0
    u = sum(1 for r in rows if r[label_col] == "unsupported")
    return u / n, n


def hdi(u_b: float | None, u_g: float | None) -> float | None:
    """HDI = (u_b - u_g)/u_b. Undefined when u_b is 0 or missing (paper's edge case)."""
    if u_b is None or u_g is None or u_b == 0:
        return None
    return (u_b - u_g) / u_b


def regime_rows(std_rows: list[dict], regime: str, config: str) -> tuple[list[dict], str]:
    """Return (rows, label_column) for one config under one checker regime."""
    cfg = [r for r in std_rows if r["config"] == config]
    if regime == "judge":
        return [r for r in cfg if r["llm_judge_final"] not in JUDGE_GATED_OUT], "llm_judge_final"
    if regime == "auto":
        return cfg, "support_label_auto"
    if regime == "gated":
        gated = [
            r for r in cfg
            if r["llm_judge_final"] not in JUDGE_GATED_OUT
            and r["support_label_auto"] == r["llm_judge_final"]
        ]
        return gated, "llm_judge_final"  # labels concur on this subset
    raise ValueError(regime)


def compute(runs: dict[str, str]) -> dict:
    """model -> regime -> {u_b, u_g, hdi, n_b, n_g}."""
    out: dict[str, dict] = {}
    for model, rel in runs.items():
        claims = load_claims(REPO_ROOT / rel)
        std = [c for c in claims if c.get("prompt_type") == "standard"]
        out[model] = {}
        for regime in ("judge", "auto", "gated"):
            b_rows, b_col = regime_rows(std, regime, "baseline")
            g_rows, g_col = regime_rows(std, regime, "full_multimodal")
            u_b, n_b = unsupported_rate(b_rows, b_col)
            u_g, n_g = unsupported_rate(g_rows, g_col)
            out[model][regime] = {
                "u_b": u_b, "u_g": u_g, "hdi": hdi(u_b, u_g), "n_b": n_b, "n_g": n_g,
            }
    return out


def ranking(results: dict, regime: str) -> list[str]:
    """Models ordered by HDI descending; undefined HDI sorts last."""
    def key(m):
        h = results[m][regime]["hdi"]
        return -h if h is not None else float("inf")
    return sorted(results, key=key)


def mode_label(h: float | None) -> str:
    if h is None:
        return "undefined"
    if h >= MODE_A_MIN:
        return "A"
    if h <= MODE_B_MAX:
        return "B?"
    return "mid"


def fmt(x: float | None, nd: int = 4) -> str:
    return "NA" if x is None else f"{x:.{nd}f}"


def write_csv(results: dict, path: Path) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "regime", "u_b", "u_g", "hdi", "mode", "n_baseline", "n_grounded"])
        for model in results:
            for regime in ("judge", "auto", "gated"):
                r = results[model][regime]
                w.writerow([
                    model, regime, fmt(r["u_b"]), fmt(r["u_g"]), fmt(r["hdi"], 3),
                    mode_label(r["hdi"]), r["n_b"], r["n_g"],
                ])


def write_md(results: dict, path: Path) -> None:
    judge_rank = ranking(results, "judge")
    lines = [
        "# HDI robustness to checker choice",
        "",
        "Generated by `scripts/eval/compute_hdi_robustness.py` from the four committed",
        "`outputs/bionlp_eval*/claim_review.csv` files (offline, no API keys).",
        "HDI = (u_b - u_g)/u_b on the unsupported-claim rate; u_b = ungrounded baseline,",
        "u_g = grounded full_multimodal, prompt_type=standard. Undefined when u_b = 0.",
        "",
        "Regimes: **judge** = `llm_judge_final` (headline, conflict-excluded);",
        "**auto** = pure rule-based `support_label_auto`; **gated** = subset where",
        "`support_label_auto` == `llm_judge_final`.",
        "",
    ]
    for regime in ("judge", "auto", "gated"):
        lines += [
            f"## Regime: {regime}",
            "",
            "| Model | u_b | u_g | HDI | Mode | n_base | n_grnd |",
            "|---|---|---|---|---|---|---|",
        ]
        for m in ranking(results, regime):
            r = results[m][regime]
            lines.append(
                f"| {m} | {fmt(r['u_b'])} | {fmt(r['u_g'])} | {fmt(r['hdi'], 3)} | "
                f"{mode_label(r['hdi'])} | {r['n_b']} | {r['n_g']} |"
            )
        lines += ["", f"Ranking (HDI desc): {' > '.join(ranking(results, regime))}", ""]

    # Verdict against the paper's checker-invariance claims.
    lines += ["## Verdict on the paper's checker-invariance claims", ""]
    for regime in ("auto", "gated"):
        rank = ranking(results, regime)
        undef = [m for m in results if results[m][regime]["hdi"] is None]
        order_ok = rank == judge_rank
        neg = [m for m in results if (results[m][regime]["hdi"] or 0) < 0]
        lines.append(
            f"- **{regime}**: four-way ordering "
            f"{'MATCHES' if order_ok else 'does NOT match'} the judge ranking "
            f"({' > '.join(rank)}); HDI undefined (u_b=0) for {len(undef)}/4 models"
            f"{': ' + ', '.join(undef) if undef else ''}"
            f"{'; negative HDI (grounding worsens): ' + ', '.join(neg) if neg else ''}."
        )
    # gpt-5.4-mini specific claim (line 187)
    g54 = "gpt-5.4-mini"
    lines += [
        "",
        f"- Paper (line 187) claims the agreement gate keeps {g54} below all three "
        f"other models. Gated HDI for {g54} = {fmt(results[g54]['gated']['hdi'], 3)} "
        f"(n_baseline={results[g54]['gated']['n_b']}) — "
        f"{'unrankable (undefined)' if results[g54]['gated']['hdi'] is None else 'defined'}.",
    ]
    path.write_text("\n".join(lines) + "\n")


def selftest() -> None:
    assert hdi(0.16, 0.0025) is not None and abs(hdi(0.16, 0.0025) - 0.984375) < 1e-6
    assert hdi(0.0, 0.03) is None, "u_b=0 must give undefined HDI"
    assert hdi(0.0064, 0.0298) < 0, "u_g>u_b must give negative HDI"
    rows = [{"c": "unsupported"}, {"c": "supported"}, {"c": "partial"}, {"c": "unsupported"}]
    r, n = unsupported_rate(rows, "c")
    assert n == 4 and abs(r - 0.5) < 1e-9
    assert unsupported_rate([], "c") == (None, 0)
    assert mode_label(0.85) == "A" and mode_label(0.336) == "B?" and mode_label(None) == "undefined"
    print("selftest OK")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "outputs")
    ap.add_argument("--selftest", action="store_true", help="run unit checks and exit")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return

    results = compute(RUNS)

    # Reproduction check against the printed judge-label HDI.
    print("Judge-label HDI reproduction check (paper tab:panel):")
    for m in RUNS:
        got = results[m]["judge"]["hdi"]
        want = PAPER_HDI_JUDGE[m]
        flag = "OK" if got is not None and abs(got - want) <= 0.01 else "MISMATCH"
        print(f"  {m:24s} computed={fmt(got, 3)} paper={want:.3f}  [{flag}]")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(results, args.out_dir / "hdi_robustness.csv")
    write_md(results, args.out_dir / "hdi_robustness.md")
    print(f"\nWrote {args.out_dir / 'hdi_robustness.csv'}")
    print(f"Wrote {args.out_dir / 'hdi_robustness.md'}")

    print("\nRanking by regime:")
    for regime in ("judge", "auto", "gated"):
        print(f"  {regime:6s}: {' > '.join(ranking(results, regime))}")


if __name__ == "__main__":
    main()
