#!/usr/bin/env python3
"""
compute_agreement.py
====================
Reduces the released human-adjudication artifacts to the inter-rater agreement
numbers the paper reports in Table `tab:agreement` (Section 4, "Human validation").

Inputs (released, offline, no API keys):
  - adjudication_input.csv : 300-claim stratified sample with the two-expert
                             consensus `human_label` (supported/partial/unsupported)
  - adjudication_key.csv   : same 300 claims keyed by `row_id`, carrying the
                             rule-based `rule_label`, the agreement-gated LLM
                             `judge_label`, `judge_agreement`, `claim_type`,
                             `model`, `condition`

For each rater pair (human vs judge, human vs rule, rule vs judge) it computes:
  - n, raw agreement, Cohen's kappa on the native label set
  - Cohen's kappa under a binary "supported vs. not-supported" collapse
  - a percentile bootstrap 95% CI on the native kappa (fixed seed, pure stdlib)
  - the confusion matrix

It also reports per-bucket (model x condition) human-vs-judge kappa, mirroring the
appendix table, and prints an explicit comparison against the paper's printed values.

Judge handling: claims whose two judge passes disagree are recorded as `conflict`
(and a few carry an empty judge label); these are excluded from any pair that
involves the judge, matching the harness's agreement-gated `baseline_comparison`
reduction. The exact excluded count is reported.

Writes:
  - outputs/agreement_analysis.csv       (tidy: one row per pair/subset)
  - outputs/agreement_confusion.md       (confusion matrices + provenance note)

This script exists because REPRODUCIBILITY.md previously attributed these kappa
numbers to `adjudicate.py`, which is a rule-based *label generator* (it hardcodes an
absolute path and computes no agreement statistic). Nothing else in the repo computed
Table `tab:agreement`.
"""
from __future__ import annotations

import argparse
import csv
import random
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Judge labels that mean "no gated decision" and are dropped from judge pairs.
JUDGE_GATED_OUT = {"", "conflict"}

# Paper's printed Table tab:agreement values, for the reproduction check.
PAPER_TARGETS = {
    "human_vs_judge": {"raw": 0.72, "kappa": 0.64},
    "rule_vs_human": {"kappa": 0.43},
    "rule_vs_judge": {"raw": 0.54, "kappa": 0.42},
}


def load_csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def safe_div(n: int, d: int, default: float = 0.0) -> float:
    return round(n / d, 4) if d > 0 else default


def cohen_kappa(pairs: list[tuple[str, str]]) -> tuple[float, float]:
    """Return (raw_agreement, Cohen's kappa) over paired categorical labels."""
    n = len(pairs)
    if n == 0:
        return 0.0, 0.0
    p_o = sum(1 for a, b in pairs if a == b) / n
    ca = Counter(a for a, b in pairs)
    cb = Counter(b for a, b in pairs)
    cats = set(ca) | set(cb)
    p_e = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    kappa = 0.0 if p_e >= 1.0 else (p_o - p_e) / (1.0 - p_e)
    return p_o, kappa


def bootstrap_kappa_ci(
    pairs: list[tuple[str, str]], resamples: int, seed: int
) -> tuple[float, float]:
    """Percentile 95% CI on Cohen's kappa via claim-level resampling (deterministic)."""
    n = len(pairs)
    if n == 0:
        return 0.0, 0.0
    rng = random.Random(seed)
    stats = []
    for _ in range(resamples):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        _, k = cohen_kappa(sample)
        stats.append(k)
    stats.sort()
    lo = stats[int(0.025 * resamples)]
    hi = stats[int(0.975 * resamples) - 1]
    return round(lo, 4), round(hi, 4)


def binary_supported(label: str) -> str:
    """Collapse to 'supported' vs 'not_supported' (the binary basis the paper's
    human-vs-judge kappa appears to use)."""
    return "supported" if label == "supported" else "not_supported"


def confusion_matrix(pairs: list[tuple[str, str]]) -> tuple[list[str], list[str], dict]:
    rows = sorted({a for a, _ in pairs})
    cols = sorted({b for _, b in pairs})
    cell = Counter(pairs)
    return rows, cols, cell


def build_pairs(joined, a_key, b_key, drop_judge_key=None):
    """Extract (label_a, label_b) pairs, dropping rows where a judge column is gated out."""
    pairs = []
    for r in joined:
        a = r[a_key]
        b = r[b_key]
        if drop_judge_key is not None and r[drop_judge_key] in JUDGE_GATED_OUT:
            continue
        pairs.append((a, b))
    return pairs


def analyze_pair(name, pairs, resamples, seed):
    raw, kappa = cohen_kappa(pairs)
    bpairs = [(binary_supported(a), binary_supported(b)) for a, b in pairs]
    _, kappa_bin = cohen_kappa(bpairs)
    lo, hi = bootstrap_kappa_ci(pairs, resamples, seed)
    return {
        "pair": name,
        "n": len(pairs),
        "raw_agreement": round(raw, 4),
        "cohen_kappa": round(kappa, 4),
        "kappa_ci_low": lo,
        "kappa_ci_high": hi,
        "kappa_binary_supported": round(kappa_bin, 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=REPO_ROOT / "adjudication_input.csv")
    ap.add_argument("--key", type=Path, default=REPO_ROOT / "adjudication_key.csv")
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "outputs")
    ap.add_argument("--bootstrap", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    inp = {r["row_id"]: r for r in load_csv(args.input)}
    key = {r["row_id"]: r for r in load_csv(args.key)}
    common = sorted(set(inp) & set(key))
    only_in = (len(set(inp) - set(key)), len(set(key) - set(inp)))
    if only_in != (0, 0):
        print(f"  WARNING: unmatched row_ids input-only={only_in[0]} key-only={only_in[1]}")

    joined = []
    for rid in common:
        joined.append(
            {
                "row_id": rid,
                "model": key[rid]["model"],
                "condition": key[rid]["condition"],
                "claim_type": key[rid]["claim_type"],
                "human_label": inp[rid]["human_label"],
                "rule_label": key[rid]["rule_label"],
                "judge_label": key[rid]["judge_label"],
                "judge_agreement": key[rid]["judge_agreement"],
            }
        )

    n_total = len(joined)
    n_gated = sum(1 for r in joined if r["judge_label"] in JUDGE_GATED_OUT)
    print(f"Joined claims: {n_total}  (judge gated-out: {n_gated}, kept for judge pairs: {n_total - n_gated})")

    # --- Pairwise agreement ---
    results = []
    results.append(
        analyze_pair(
            "human_vs_judge",
            build_pairs(joined, "human_label", "judge_label", drop_judge_key="judge_label"),
            args.bootstrap,
            args.seed,
        )
    )
    results.append(
        analyze_pair(
            "rule_vs_human",
            build_pairs(joined, "rule_label", "human_label"),
            args.bootstrap,
            args.seed,
        )
    )
    results.append(
        analyze_pair(
            "rule_vs_judge",
            build_pairs(joined, "rule_label", "judge_label", drop_judge_key="judge_label"),
            args.bootstrap,
            args.seed,
        )
    )

    # --- Per-bucket human-vs-judge kappa (model x condition) ---
    buckets = defaultdict(list)
    for r in joined:
        if r["judge_label"] in JUDGE_GATED_OUT:
            continue
        buckets[(r["model"], r["condition"])].append((r["human_label"], r["judge_label"]))
    bucket_rows = []
    for (model, cond), pairs in sorted(buckets.items()):
        raw, kappa = cohen_kappa(pairs)
        bucket_rows.append(
            {
                "pair": f"human_vs_judge::{model}::{cond}",
                "n": len(pairs),
                "raw_agreement": round(raw, 4),
                "cohen_kappa": round(kappa, 4),
                "kappa_ci_low": "",
                "kappa_ci_high": "",
                "kappa_binary_supported": "",
            }
        )

    # --- Write tidy CSV ---
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = args.out_dir / "agreement_analysis.csv"
    fields = [
        "pair",
        "n",
        "raw_agreement",
        "cohen_kappa",
        "kappa_ci_low",
        "kappa_ci_high",
        "kappa_binary_supported",
    ]
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
        w.writerows(bucket_rows)

    # --- Write confusion matrices ---
    out_md = args.out_dir / "agreement_confusion.md"
    lines = [
        "# Inter-rater confusion matrices",
        "",
        "Generated by `scripts/eval/compute_agreement.py` from `adjudication_input.csv`",
        "(`human_label`) joined on `row_id` to `adjudication_key.csv` (`rule_label`,",
        f"`judge_label`). {n_total} claims; {n_gated} judge-gated-out (conflict/empty) are",
        "excluded from any pair involving the judge. Rows = first rater, columns = second.",
        "",
    ]
    cm_specs = [
        ("human_vs_judge", build_pairs(joined, "human_label", "judge_label", "judge_label")),
        ("rule_vs_human", build_pairs(joined, "rule_label", "human_label")),
        ("rule_vs_judge", build_pairs(joined, "rule_label", "judge_label", "judge_label")),
    ]
    for name, pairs in cm_specs:
        rows, cols, cell = confusion_matrix(pairs)
        lines.append(f"## {name} (n={len(pairs)})")
        lines.append("")
        lines.append("| rater_a \\ rater_b | " + " | ".join(cols) + " |")
        lines.append("|" + "---|" * (len(cols) + 1))
        for rr in rows:
            row = [str(cell.get((rr, cc), 0)) for cc in cols]
            lines.append(f"| {rr} | " + " | ".join(row) + " |")
        lines.append("")
    out_md.write_text("\n".join(lines))

    # --- Console summary + paper reproduction check ---
    print("\nPairwise agreement (native label set):")
    for r in results:
        print(
            f"  {r['pair']:<16} n={r['n']:<3} raw={r['raw_agreement']:.3f} "
            f"kappa={r['cohen_kappa']:.3f} 95%CI[{r['kappa_ci_low']:.3f},{r['kappa_ci_high']:.3f}] "
            f"kappa_binary_supported={r['kappa_binary_supported']:.3f}"
        )

    print("\nReproduction check vs paper Table tab:agreement:")
    by_pair = {r["pair"]: r for r in results}
    for pair, tgt in PAPER_TARGETS.items():
        r = by_pair[pair]
        msgs = []
        if "raw" in tgt:
            ok = abs(r["raw_agreement"] - tgt["raw"]) <= 0.02
            msgs.append(f"raw {r['raw_agreement']:.3f} vs paper {tgt['raw']:.2f} {'OK' if ok else 'MISMATCH'}")
        if "kappa" in tgt:
            ok_native = abs(r["cohen_kappa"] - tgt["kappa"]) <= 0.02
            ok_bin = abs(r["kappa_binary_supported"] - tgt["kappa"]) <= 0.02
            tag = "OK" if ok_native else (f"OK@binary({r['kappa_binary_supported']:.3f})" if ok_bin else "MISMATCH")
            msgs.append(f"kappa {r['cohen_kappa']:.3f} vs paper {tgt['kappa']:.2f} {tag}")
        print(f"  {pair:<16} " + "; ".join(msgs))

    print("\nPer-bucket human-vs-judge kappa:")
    for b in bucket_rows:
        print(f"  {b['pair']:<48} n={b['n']:<3} raw={b['raw_agreement']:.3f} kappa={b['cohen_kappa']:.3f}")

    print(f"\nWrote {out_csv.relative_to(REPO_ROOT)}")
    print(f"Wrote {out_md.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
