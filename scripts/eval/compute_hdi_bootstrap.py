#!/usr/bin/env python3
"""
Patient-paired nonparametric bootstrap for the Hallucination Dependence Index.

Regenerates the two statistical tables of the 8-page paper directly from the
committed per-model ``claim_review.csv`` files, with no network access and no
heavy dependencies (stdlib only, so the resample sequence is fully pinned):

  * Table ``tab:cis``  — per-model HDI 95% CI
  * Table ``tab:pairs`` — pairwise ΔHDI 95% CI + Holm-corrected p-values

HDI for a model is ``(u_b - u_g) / u_b`` where ``u_b`` / ``u_g`` are the
unsupported-claim rates in the ungrounded ``baseline`` / grounded
``full_multimodal`` conditions, over the ``llm_judge_final`` column with
``prompt_type == "standard"`` and ``conflict``/empty rows excluded — identical
to ``compute_bionlp_metrics.compute_baseline_vs_grounded``.

The bootstrap resamples the shared 119 patients with replacement (B=2000,
seed 42) and recomputes every model's HDI end-to-end on each resample. All four
models are scored on the *same* patient-resample sequence, so per-resample
ΔHDI between two models is paired and the pairwise tests are legitimate paired
tests.

Determinism note: the paper's original snippet used numpy/scipy and did not pin
which RNG produced the seed-42 sequence, so the exact CI *bounds* are not
byte-reproducible from the paper alone. This script pins the sequence to
``random.Random(42)`` and documents it; the reproducible claim we test is the
paper's *qualitative* bootstrap conclusions (non-overlapping per-model CIs, the
four-way ordering, and six-pair Holm significance), plus the point estimates.

Usage:
    python3 scripts/eval/compute_hdi_bootstrap.py \
        [--b 2000] [--seed 42] [--out-dir outputs]
"""
from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# (display name, output directory) in the paper's factorial order.
MODELS: list[tuple[str, str]] = [
    ("gpt-4o-mini", "outputs/bionlp_eval"),
    ("gpt-5.4-mini", "outputs/bionlp_eval_gpt54mini"),
    ("gemini-2.5-flash", "outputs/bionlp_eval_gemini25flash"),
    ("gemini-3-flash-preview", "outputs/bionlp_eval_gemini"),
]

GROUNDED = "full_multimodal"
BASELINE = "baseline"


def load_claims(csv_path: Path) -> list[dict]:
    with csv_path.open(newline="") as f:
        return list(csv.DictReader(f))


def _judged(rows: list[dict], config: str) -> list[dict]:
    """Rows entering the reduction for one condition (matches compute_bionlp_metrics)."""
    return [
        r
        for r in rows
        if r.get("config") == config
        and r.get("prompt_type") == "standard"
        and r.get("llm_judge_final", "") not in ("", "conflict")
    ]


def index_by_case(rows: list[dict], config: str) -> dict[str, list[bool]]:
    """case_id -> list of is_unsupported flags for that case in `config`."""
    by_case: dict[str, list[bool]] = defaultdict(list)
    for r in _judged(rows, config):
        by_case[r["case_id"]].append(r["llm_judge_final"] == "unsupported")
    return dict(by_case)


def unsupported_rate(cases: list[str], by_case: dict[str, list[bool]]) -> tuple[int, int]:
    """Return (n_unsupported, n_claims) pooled over the (possibly repeated) cases."""
    unsup = tot = 0
    for c in cases:
        flags = by_case.get(c, ())
        unsup += sum(flags)
        tot += len(flags)
    return unsup, tot


def hdi_for(cases: list[str], g_by_case, b_by_case) -> float | None:
    """HDI over a (resampled) list of cases; None if u_b is undefined/zero."""
    g_unsup, g_tot = unsupported_rate(cases, g_by_case)
    b_unsup, b_tot = unsupported_rate(cases, b_by_case)
    if b_tot == 0 or b_unsup == 0:
        # u_b == 0 -> HDI undefined (no ungrounded hallucination to suppress).
        return None
    u_b = b_unsup / b_tot
    u_g = g_unsup / g_tot if g_tot else 0.0
    return (u_b - u_g) / u_b


def percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0,1]. Matches numpy's default."""
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def two_sided_p(deltas: list[float], b: int) -> float:
    """Percentile two-sided p on the paired ΔHDI resample distribution."""
    n = len(deltas)
    if n == 0:
        return float("nan")
    le = sum(1 for d in deltas if d <= 0) / n
    ge = sum(1 for d in deltas if d >= 0) / n
    return max(2 * min(le, ge), 1.0 / b)


def holm(pairs: list[tuple[str, float]]) -> dict[str, float]:
    """Holm-Bonferroni step-down over the raw p-values, keyed by pair name."""
    order = sorted(pairs, key=lambda kv: kv[1])
    m = len(order)
    adjusted: dict[str, float] = {}
    running = 0.0
    for i, (name, p) in enumerate(order):
        val = min(1.0, (m - i) * p)
        running = max(running, val)  # enforce monotonic non-decreasing
        adjusted[name] = running
    return adjusted


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--b", type=int, default=2000, help="bootstrap resamples")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", default="outputs", help="dir for the two CSVs")
    args = ap.parse_args()

    # ── load and index each model ────────────────────────────────────────────
    g_idx: dict[str, dict] = {}
    b_idx: dict[str, dict] = {}
    point: dict[str, float] = {}
    case_sets: list[set] = []
    for name, rel in MODELS:
        rows = load_claims(REPO_ROOT / rel / "claim_review.csv")
        g_idx[name] = index_by_case(rows, GROUNDED)
        b_idx[name] = index_by_case(rows, BASELINE)
        case_sets.append(
            {
                r["case_id"]
                for r in rows
                if r.get("prompt_type") == "standard"
            }
        )
        h = hdi_for(sorted(case_sets[-1]), g_idx[name], b_idx[name])
        point[name] = h

    # The paired bootstrap requires one shared patient universe.
    shared = set.intersection(*case_sets)
    union = set.union(*case_sets)
    if shared != union:
        raise SystemExit(
            f"models do not share an identical case set "
            f"(shared={len(shared)}, union={len(union)}); paired resample undefined"
        )
    cases = sorted(shared)
    n = len(cases)

    # ── bootstrap: one shared resample sequence across all models ────────────
    rng = random.Random(args.seed)
    names = [m[0] for m in MODELS]
    hdi_samples: dict[str, list[float]] = {nm: [] for nm in names}
    delta_samples: dict[tuple[str, str], list[float]] = {
        (a, b): [] for i, a in enumerate(names) for b in names[i + 1 :]
    }
    dropped: dict[str, int] = {nm: 0 for nm in names}

    for _ in range(args.b):
        resample = [cases[rng.randrange(n)] for _ in range(n)]
        cur: dict[str, float | None] = {}
        for nm in names:
            h = hdi_for(resample, g_idx[nm], b_idx[nm])
            cur[nm] = h
            if h is None:
                dropped[nm] += 1
            else:
                hdi_samples[nm].append(h)
        for (a, b) in delta_samples:
            if cur[a] is not None and cur[b] is not None:
                delta_samples[(a, b)].append(cur[a] - cur[b])

    out_dir = REPO_ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── per-model HDI CI (tab:cis) ───────────────────────────────────────────
    ci_path = out_dir / "hdi_bootstrap_ci.csv"
    with ci_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "hdi_point", "hdi_ci_lo", "hdi_ci_hi", "n_effective", "n_dropped_ub0"])
        model_ci: dict[str, tuple[float, float]] = {}
        for nm in names:
            vals = sorted(hdi_samples[nm])
            lo = percentile(vals, 0.025)
            hi = percentile(vals, 0.975)
            model_ci[nm] = (lo, hi)
            w.writerow([nm, f"{point[nm]:.4f}", f"{lo:.4f}", f"{hi:.4f}", len(vals), dropped[nm]])

    # ── pairwise ΔHDI (tab:pairs) ────────────────────────────────────────────
    raw_p: list[tuple[str, float]] = []
    pair_rows: list[dict] = []
    for (a, b), deltas in delta_samples.items():
        dv = sorted(deltas)
        lo = percentile(dv, 0.025)
        hi = percentile(dv, 0.975)
        p = two_sided_p(deltas, args.b)
        key = f"{a} vs {b}"
        raw_p.append((key, p))
        pair_rows.append(
            {"pair": key, "delta_ci_lo": lo, "delta_ci_hi": hi, "p_raw": p, "n_paired": len(dv)}
        )
    holm_p = holm(raw_p)

    pairs_path = out_dir / "hdi_bootstrap_pairs.csv"
    with pairs_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pair", "delta_hdi_ci_lo", "delta_hdi_ci_hi", "p_raw", "p_holm", "n_paired"])
        for row in pair_rows:
            w.writerow(
                [
                    row["pair"],
                    f"{row['delta_ci_lo']:.4f}",
                    f"{row['delta_ci_hi']:.4f}",
                    f"{row['p_raw']:.4g}",
                    f"{holm_p[row['pair']]:.4g}",
                    row["n_paired"],
                ]
            )

    # ── reproduction verdict (printed; no fabricated numbers) ────────────────
    print(f"Patient-paired HDI bootstrap  B={args.b}  seed={args.seed}  n_cases={n}")
    print(f"  RNG: random.Random({args.seed}) (stdlib, pinned)\n")
    print("Per-model HDI 95% CI (tab:cis):")
    for nm in names:
        lo, hi = model_ci[nm]
        print(f"  {nm:24s} point={point[nm]:.3f}  CI=[{lo:+.3f}, {hi:+.3f}]  "
              f"(dropped {dropped[nm]} resamples with u_b=0)")

    # CI ordering / non-overlap check (the paper's core statistical claim)
    ordered = sorted(names, key=lambda nm: point[nm])  # ascending HDI
    lowest = ordered[0]
    lo_low, hi_low = model_ci[lowest]
    others_lower_bounds = [model_ci[nm][0] for nm in names if nm != lowest]
    non_overlap = all(hi_low < lb for lb in others_lower_bounds)
    print(f"\n  lowest-HDI model = {lowest}; its CI upper bound {hi_low:.3f} "
          f"{'<' if non_overlap else '>= at least one of'} "
          f"the other models' CI lower bounds {[round(x,3) for x in others_lower_bounds]}")
    print(f"  -> per-model CIs non-overlapping (Mode A/B split): {non_overlap}")

    print("\nPairwise ΔHDI (tab:pairs):")
    all_sig = True
    for row in pair_rows:
        ph = holm_p[row["pair"]]
        sig = ph <= 0.05
        all_sig = all_sig and sig
        print(f"  {row['pair']:44s} ΔCI=[{row['delta_ci_lo']:+.3f}, {row['delta_ci_hi']:+.3f}]  "
              f"p_raw={row['p_raw']:.4g}  p_holm={ph:.4g}  {'sig' if sig else 'NS'}")
    print(f"\n  -> all six pairs separate at Holm p<=0.05: {all_sig}")
    print(f"\nWrote {ci_path.relative_to(REPO_ROOT)} and {pairs_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
