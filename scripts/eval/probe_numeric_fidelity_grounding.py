#!/usr/bin/env python3
"""
probe_numeric_fidelity_grounding.py
===================================
Attacks the Table~5 (tab:secondary) *numeric-fidelity* column.

The shipped metric is `metrics.json["numeric_fidelity"]["numeric_fidelity_rate_auto"]`,
computed by `compute_bionlp_metrics.compute_numeric_fidelity()`. Its caption reads:

  "Numeric fidelity: fraction of claims containing numeric values for which the
   value matches the bundle within +/-0.01."

and the Results narrative treats it as grounded copying fidelity ("less faithful
when copying numeric values out of the bundle"). This probe shows the shipped
number is not that quantity, on two independent counts:

  1. POOLING. `compute_numeric_fidelity()` pools every `prompt_type==standard`
     claim regardless of `config`. The `baseline` (ungrounded) config bundle is
     empty by construction (io_score=null, empty tissue_fractions, all
     transcriptomics null, active_score=null), so `check_numeric_fidelity()`
     builds an empty `known_nums` table and labels *every* baseline numeric claim
     `incorrect`. There is no bundle to copy from, yet those claims sit in the
     denominator and the numerator-as-failures. The baseline numeric-claim count
     differs ~5x across models (204..1015), so the pooled rate blends grounded
     copy fidelity with baseline-confabulation *volume*.

  2. LENIENCY. `check_numeric_fidelity()` returns "correct" on the branch
     `matched_any and unmatched_nums` ("Most numerics match; unmatched: ..."), so
     a sentence is counted numerically correct if *any one* of its numbers
     matches the bundle, even with other fabricated numbers present. The caption
     says "the value matches", i.e. all of them.

This script is stdlib-only and reads only committed artifacts
(`outputs/bionlp_eval*/claim_review.csv` + `evidence_bundles/*.json`). It
re-implements `check_numeric_fidelity()` faithfully, verifies the re-derivation
reproduces every shipped label, then recomputes the rate under:

  - shipped       : pooled standard, lenient  (== metrics.json, == paper)
  - grounded      : non-baseline configs, lenient
  - strict        : pooled standard, all-numerics-match
  - strict_grnd   : non-baseline configs, all-numerics-match  (caption-faithful)

Outputs: outputs/numeric_fidelity_grounding.{csv,md}

Usage:
    python3 scripts/eval/probe_numeric_fidelity_grounding.py
    python3 scripts/eval/probe_numeric_fidelity_grounding.py --selftest
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Four released per-model runs and the Table 5 numeric-fidelity values the paper
# prints for them (paper_8page_icml.tex, caption + Section Results).
RUNS = [
    ("gpt-4o-mini", "outputs/bionlp_eval", 0.381),
    ("gpt-5.4-mini", "outputs/bionlp_eval_gpt54mini", 0.632),
    ("gemini-2.5-flash", "outputs/bionlp_eval_gemini25flash", 0.578),
    ("gemini-3-flash-preview", "outputs/bionlp_eval_gemini", 0.455),
]

# Exact regex from build_claim_review.py:71
_NUMBER_PATTERN = re.compile(r"\d+\.?\d*")


def extract_numbers_from_text(text: str) -> set[str]:
    return set(_NUMBER_PATTERN.findall(text))


def collect_known_nums(bundle: dict) -> dict[str, float]:
    """Faithful copy of the bundle->numbers logic in check_numeric_fidelity()."""
    known: dict[str, float] = {}
    io_score = bundle.get("io_score")
    if io_score is not None:
        known["io_score"] = float(io_score)
    path = bundle.get("pathology", {}) or {}
    for k, v in (path.get("tissue_fractions", {}) or {}).items():
        known[f"tissue_{k}"] = float(v)
        known[f"tissue_{k}_pct"] = round(float(v) * 100, 0)
    for tile in path.get("top_tiles", []) or []:
        known["tile_score"] = float(tile.get("score", 0))
    txo = bundle.get("transcriptomics", {}) or {}
    for k in ("cyt_value", "gep_value", "tide_value"):
        v = txo.get(k)
        if v is not None:
            known[k] = float(v)
    fus = bundle.get("fusion", {}) or {}
    act = fus.get("active_score")
    if act is not None:
        known["active_score"] = float(act)
    return known


def check_numeric_fidelity(sentence: str, bundle: dict) -> tuple[str, bool]:
    """Re-implementation of build_claim_review.check_numeric_fidelity.

    Returns (label, partial) where label in {not_applicable, correct, incorrect}
    and `partial` is True iff label=="correct" was reached via the lenient
    "Most numerics match" branch (>=1 unmatched numeric present).
    """
    sentence_nums = extract_numbers_from_text(sentence)
    if not sentence_nums:
        return "not_applicable", False
    known = collect_known_nums(bundle)
    matched_any = False
    unmatched = []
    for sn in sentence_nums:
        sn_float = float(sn)
        found = False
        for val in known.values():
            if abs(sn_float - val) < 0.02 or abs(sn_float - round(val, 0)) < 1:
                found = True
                matched_any = True
                break
        if not found:
            unmatched.append(sn)
    if matched_any and not unmatched:
        return "correct", False
    if matched_any and unmatched:
        return "correct", True
    return "incorrect", False


def _load_bundle(run_dir: Path, case_id: str, config: str) -> dict:
    p = run_dir / "evidence_bundles" / f"{case_id}_{config}.json"
    if not p.exists():
        return {}
    with open(p) as f:
        return json.load(f)


def _rate(num: int, den: int) -> float:
    return (num / den) if den else 0.0


def analyze_run(name: str, run_dir: Path) -> dict:
    """Re-derive numeric fidelity for one model run under four definitions."""
    rows = list(csv.DictReader(open(run_dir / "claim_review.csv")))
    bundle_cache: dict[tuple[str, str], dict] = {}

    def bundle(cid: str, cfg: str) -> dict:
        key = (cid, cfg)
        if key not in bundle_cache:
            bundle_cache[key] = _load_bundle(run_dir, cid, cfg)
        return bundle_cache[key]

    # per-config tallies
    pool_den = pool_lenient = pool_strict = 0          # all standard configs
    grnd_den = grnd_lenient = grnd_strict = 0          # non-baseline configs
    base_den = base_lenient = 0                        # baseline only
    rederive_mismatch = 0

    for r in rows:
        if r.get("prompt_type", "") != "standard":
            continue
        cfg = r.get("config", "")
        label, partial = check_numeric_fidelity(r.get("claim_text", ""), bundle(r["case_id"], cfg))
        if label != r.get("numeric_fidelity_auto", ""):
            rederive_mismatch += 1
        if label == "not_applicable":
            continue
        is_lenient = label == "correct"
        is_strict = label == "correct" and not partial
        pool_den += 1
        pool_lenient += int(is_lenient)
        pool_strict += int(is_strict)
        if cfg == "baseline":
            base_den += 1
            base_lenient += int(is_lenient)
        else:
            grnd_den += 1
            grnd_lenient += int(is_lenient)
            grnd_strict += int(is_strict)

    return {
        "model": name,
        "numeric_claims_std": pool_den,
        "baseline_numeric_claims": base_den,
        "baseline_lenient_correct": base_lenient,
        "shipped_rate": _rate(pool_lenient, pool_den),
        "grounded_rate": _rate(grnd_lenient, grnd_den),
        "strict_rate": _rate(pool_strict, pool_den),
        "strict_grounded_rate": _rate(grnd_strict, grnd_den),
        "lenient_correct": pool_lenient,
        "strict_correct": pool_strict,
        "rederive_mismatch": rederive_mismatch,
    }


def run_probe() -> list[dict]:
    results = []
    for name, rel, paper_val in RUNS:
        run_dir = REPO / rel
        res = analyze_run(name, run_dir)
        res["paper_value"] = paper_val
        res["reproduces_paper"] = abs(res["shipped_rate"] - paper_val) < 0.005
        results.append(res)
    return results


def write_outputs(results: list[dict]) -> None:
    out_dir = REPO / "outputs"
    csv_path = out_dir / "numeric_fidelity_grounding.csv"
    md_path = out_dir / "numeric_fidelity_grounding.md"

    cols = [
        "model", "numeric_claims_std", "baseline_numeric_claims",
        "paper_value", "shipped_rate", "reproduces_paper",
        "grounded_rate", "strict_rate", "strict_grounded_rate",
        "lenient_correct", "strict_correct", "rederive_mismatch",
    ]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in results:
            w.writerow({k: r[k] for k in cols})

    def by(name):
        return next(r for r in results if r["model"] == name)

    o1, o2 = by("gpt-4o-mini"), by("gpt-5.4-mini")
    g1, g2 = by("gemini-2.5-flash"), by("gemini-3-flash-preview")

    def trend(a, b, key):
        return b[key] - a[key]

    lines = []
    lines.append("# Numeric-fidelity grounding probe (tab:secondary)")
    lines.append("")
    lines.append("Re-derivation of the Table 5 numeric-fidelity column directly from the")
    lines.append("committed `claim_review.csv` + `evidence_bundles/*.json`. The shipped metric")
    lines.append("pools ungrounded-baseline claims (empty bundle by construction -> never")
    lines.append("matchable) and counts a sentence \"correct\" when only *some* of its numerics")
    lines.append("match. Both contradict the caption (\"fraction of claims ... for which the")
    lines.append("value matches the bundle within +/-0.01\"). Columns:")
    lines.append("")
    lines.append("- **shipped** = pooled standard, lenient (== metrics.json == paper)")
    lines.append("- **grounded** = non-baseline configs only, lenient")
    lines.append("- **strict** = pooled standard, *all* numerics must match")
    lines.append("- **strict_grnd** = non-baseline + all numerics match (caption-faithful)")
    lines.append("")
    lines.append("| Model | #num | #base | paper | shipped | grounded | strict | strict_grnd |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        lines.append(
            f"| {r['model']} | {r['numeric_claims_std']} | {r['baseline_numeric_claims']} | "
            f"{r['paper_value']:.3f} | {r['shipped_rate']:.3f} | {r['grounded_rate']:.3f} | "
            f"{r['strict_rate']:.3f} | {r['strict_grounded_rate']:.3f} |"
        )
    lines.append("")
    repro = all(r["reproduces_paper"] for r in results)
    mism = sum(r["rederive_mismatch"] for r in results)
    lines.append(f"Re-derivation reproduces the paper's four values: **{repro}** "
                 f"(label-level mismatches vs shipped claim_review: **{mism}**).")
    lines.append("")
    lines.append("## What shifts")
    lines.append("")
    lines.append("**Baseline pooling.** The `baseline` bundle is empty, so all baseline numeric")
    lines.append("claims are forced to `incorrect`; they are pure denominator ballast whose count")
    lines.append("varies ~5x across models:")
    lines.append("")
    for r in results:
        lines.append(f"- {r['model']}: {r['baseline_numeric_claims']} baseline numeric claims "
                     f"forced to failure; shipped {r['shipped_rate']:.3f} -> grounded "
                     f"{r['grounded_rate']:.3f}.")
    lines.append("")
    lines.append("**Leniency.** Share of `correct` labels reached via the \"Most numerics match\"")
    lines.append("branch (>=1 fabricated numeric still present):")
    lines.append("")
    for r in results:
        lenient_only = r["lenient_correct"] - r["strict_correct"]
        frac = _rate(lenient_only, r["lenient_correct"])
        lines.append(f"- {r['model']}: {lenient_only}/{r['lenient_correct']} "
                     f"({frac:.0%}) of correct labels have an unmatched numeric.")
    lines.append("")
    lines.append("## Paper trends under each definition")
    lines.append("")
    lines.append("| Within-provider trend | shipped | grounded | strict_grnd |")
    lines.append("|---|---:|---:|---:|")
    lines.append(
        f"| OpenAI 4o-mini -> 5.4-mini | {trend(o1,o2,'shipped_rate'):+.3f} | "
        f"{trend(o1,o2,'grounded_rate'):+.3f} | {trend(o1,o2,'strict_grounded_rate'):+.3f} |"
    )
    lines.append(
        f"| Google 2.5-flash -> 3-flash-preview | {trend(g1,g2,'shipped_rate'):+.3f} | "
        f"{trend(g1,g2,'grounded_rate'):+.3f} | {trend(g1,g2,'strict_grounded_rate'):+.3f} |"
    )
    lines.append("")
    lines.append("The two corrections pull in opposite directions. Dropping the empty-bundle")
    lines.append("baseline claims *raises* the rate (grounded > shipped); requiring all numerics")
    lines.append("to match *lowers* it (strict < lenient). Leniency dominates: the caption-faithful")
    lines.append("rate (strict_grnd, grounded + every numeric matches) is substantially *below*")
    lines.append("the printed numbers for all four models (0.254/0.434/0.479/0.273 vs printed")
    lines.append("0.381/0.632/0.578/0.455), because ~36-57% of \"correct\" labels tolerate a")
    lines.append("fabricated numeric. The within-provider trends survive in *direction* under")
    lines.append("every definition, but the magnitudes move: the Google regression *grows* under")
    lines.append("strict_grnd (-0.123 -> -0.206) while the OpenAI gain *shrinks* (+0.251 ->")
    lines.append("+0.180), so neither the sign of the story nor its size is definition-invariant.")
    lines.append("Caption tolerance is +/-0.01; code uses +/-0.02 (and integer <1).")
    lines.append("")
    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Wrote {csv_path.relative_to(REPO)}")
    print(f"Wrote {md_path.relative_to(REPO)}")


def selftest() -> int:
    """Unit checks on the re-implemented checker; no repo artifacts required."""
    ok = True

    def expect(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            print(f"  FAIL: {msg}")
        else:
            print(f"  ok: {msg}")

    empty = {"pathology": {}, "transcriptomics": {}, "fusion": {}}
    bundle = {
        "io_score": 0.42,
        "pathology": {"tissue_fractions": {"tumor": 0.60}, "top_tiles": [{"score": 0.88}]},
        "transcriptomics": {"cyt_value": 1.25, "gep_value": None, "tide_value": None},
        "fusion": {"active_score": 0.31},
    }
    # no numerics -> not_applicable
    expect(check_numeric_fidelity("no digits here", bundle) == ("not_applicable", False),
           "sentence with no numerics is not_applicable")
    # empty bundle -> any numeric is incorrect
    expect(check_numeric_fidelity("value is 0.42", empty)[0] == "incorrect",
           "numeric against empty (baseline) bundle is incorrect")
    # exact match -> strict correct
    expect(check_numeric_fidelity("io score 0.42", bundle) == ("correct", False),
           "single matching numeric is strict-correct")
    # one match + one fabricated -> lenient correct (partial True)
    expect(check_numeric_fidelity("io 0.42 and 9.99", bundle) == ("correct", True),
           "one match plus a fabricated numeric is lenient-correct (the gap)")
    # percent form of tissue fraction (60) matches rounded *100
    expect(check_numeric_fidelity("tumor 60 percent", bundle)[0] == "correct",
           "tissue fraction percent form matches")
    # all fabricated -> incorrect
    expect(check_numeric_fidelity("values 7 and 8", bundle)[0] == "incorrect",
           "all-fabricated numerics is incorrect")
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true", help="run unit checks and exit")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    results = run_probe()
    write_outputs(results)
    print()
    for r in results:
        flag = "OK" if r["reproduces_paper"] else "DIFF"
        print(f"[{flag}] {r['model']:22s} paper={r['paper_value']:.3f} "
              f"shipped={r['shipped_rate']:.3f} grounded={r['grounded_rate']:.3f} "
              f"strict_grnd={r['strict_grounded_rate']:.3f} "
              f"(base_num={r['baseline_numeric_claims']}, mismatch={r['rederive_mismatch']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
