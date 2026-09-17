#!/usr/bin/env python3
"""
compute_claim_type_rates.py
===========================
Reduces the four per-model ``claim_review.csv`` files to the typed-claim
unsupported-rate breakdown reported in the paper as Table~\\ref{tab:ctypes}
(agreement-gated judge label) and Table~\\ref{tab:ctypes-rule} (rule-based
auto label, App.~\\ref{app:claim-types}).

This closes REPRODUCIBILITY.md caveat #2: the paper's six-class typed-claim
taxonomy (numeric / modality-tag / tier / uncertainty / literature / other)
was "maintained out-of-tree". The committed ``claim_review.csv`` has NO
``numeric`` or ``modality`` values in its ``claim_type`` column — that column
is the *modality* tagger's output (pathology/RNA/clinical/fusion/tier/
uncertainty/literature/other). The paper's Numeric and Modality-tag rows are
therefore CROSS-CUTTING tags recovered from the rule-checker's own signal
columns, not partitions of ``claim_type``. The mapping is made explicit and
documented below so the two tables reduce from the committed artifacts.

Operational taxonomy (from committed columns, prompt_type=standard):
  Numeric      : numeric_fidelity_auto in {correct, incorrect}
                 (the rule checker only scores fidelity when the claim carries
                  a numeric value; not_applicable => no numeric)
  Modality-tag : modality_match_auto  in {correct, incorrect}
                 (unknown => no modality attribution to check)
  Tier         : claim_type == 'tier'
  Uncertainty  : claim_type == 'uncertainty'
  Literature   : claim_type == 'literature'
  Other        : claim_type == 'other'
The first two are cross-cutting (a claim can be both Numeric and Modality-tag);
the last four come straight from the modality tagger and are disjoint. Each row
is a rate over the claims carrying that tag, matching the paper's phrasing
("fraction of <type> claims that are unsupported").

Unsupported rate:
  judge : unsupported / (labelled and not conflict and not empty)   [agreement-gated, conflict-excluded]
  rule  : unsupported / (all rows of that type with a support_label_auto)

Run:
  python3 scripts/eval/compute_claim_type_rates.py            # all four runs -> outputs/claim_type_rates.{csv,md}
  python3 scripts/eval/compute_claim_type_rates.py --selftest # stdlib unit check, no data needed
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import OrderedDict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
OUTPUTS = REPO / "outputs"

# run dir -> (paper abbreviation, generator model id)
RUNS = OrderedDict([
    ("bionlp_eval",             ("4o-m",  "gpt-4o-mini")),
    ("bionlp_eval_gpt54mini",   ("5.4-m", "gpt-5.4-mini")),
    ("bionlp_eval_gemini25flash", ("2.5-f", "gemini-2.5-flash")),
    ("bionlp_eval_gemini",      ("3-fp",  "gemini-3-flash-preview")),
])

TYPES = ["Numeric", "Modality-tag", "Tier", "Uncertainty", "Literature", "Other"]
CONFIGS = OrderedDict([("baseline", "Ungrounded baseline"),
                       ("full_multimodal", "Grounded (full_multimodal)")])

# Paper values (paper_8page_icml.tex, tab:ctypes == tab:ctypes-rule, identical in source).
# columns: 4o-m, 5.4-m, 2.5-f, 3-fp
PAPER = {
    ("baseline", "Numeric"):      [0.42, 0.18, 0.81, 0.96],
    ("baseline", "Modality-tag"): [0.11, 0.04, 0.58, 0.89],
    ("baseline", "Tier"):         [0.24, 0.07, 0.71, 0.93],
    ("baseline", "Uncertainty"):  [0.01, 0.00, 0.04, 0.07],
    ("baseline", "Literature"):   [0.03, 0.02, 0.31, 0.42],
    ("baseline", "Other"):        [0.15, 0.05, 0.48, 0.84],
    ("full_multimodal", "Numeric"):      [0.00, 0.03, 0.04, 0.11],
    ("full_multimodal", "Modality-tag"): [0.00, 0.01, 0.02, 0.08],
    ("full_multimodal", "Tier"):         [0.00, 0.01, 0.01, 0.03],
    ("full_multimodal", "Uncertainty"):  [0.00, 0.00, 0.00, 0.00],
    ("full_multimodal", "Literature"):   [0.00, 0.00, 0.01, 0.02],
    ("full_multimodal", "Other"):        [0.02, 0.12, 0.09, 0.37],
}


def _nonempty(v) -> bool:
    return v is not None and str(v).strip() != ""


def claim_types_of(row: dict) -> list[str]:
    """Return the list of paper claim-type tags a row belongs to (cross-cutting)."""
    tags = []
    if str(row.get("numeric_fidelity_auto", "")).strip() in ("correct", "incorrect"):
        tags.append("Numeric")
    if str(row.get("modality_match_auto", "")).strip() in ("correct", "incorrect"):
        tags.append("Modality-tag")
    ct = str(row.get("claim_type", "")).strip()
    if ct == "tier":
        tags.append("Tier")
    elif ct == "uncertainty":
        tags.append("Uncertainty")
    elif ct == "literature":
        tags.append("Literature")
    elif ct == "other":
        tags.append("Other")
    return tags


def rate(rows: list[dict], label_col: str, exclude_conflict: bool):
    """(unsupported_rate, denominator) over rows for a given label column."""
    denom = 0
    unsupp = 0
    for r in rows:
        lbl = str(r.get(label_col, "")).strip()
        if not lbl:
            continue
        if exclude_conflict and lbl == "conflict":
            continue
        denom += 1
        if lbl == "unsupported":
            unsupp += 1
    return (unsupp / denom if denom else None), denom


def reduce_run(path: Path):
    rows = [r for r in csv.DictReader(open(path, newline=""))
            if str(r.get("prompt_type", "")).strip() == "standard"]
    # index rows by (config, type)
    out = {}
    for cfg in CONFIGS:
        cfg_rows = [r for r in rows if str(r.get("config", "")).strip() == cfg]
        for t in TYPES:
            trows = [r for r in cfg_rows if t in claim_types_of(r)]
            j_rate, j_n = rate(trows, "llm_judge_final", exclude_conflict=True)
            r_rate, r_n = rate(trows, "support_label_auto", exclude_conflict=False)
            out[(cfg, t)] = {"n": len(trows), "judge_rate": j_rate, "judge_n": j_n,
                             "rule_rate": r_rate, "rule_n": r_n}
    return out


def fmt(x):
    return "  -  " if x is None else f"{x:.2f}"


def build_report(reductions):
    abbrevs = [RUNS[d][0] for d in RUNS]
    lines = []
    lines.append("# Typed-claim unsupported rates — reduction of tab:ctypes / tab:ctypes-rule\n")
    lines.append("Reduces the four committed `claim_review.csv` files to the paper's "
                 "typed-claim unsupported-rate tables. See the module docstring in "
                 "`scripts/eval/compute_claim_type_rates.py` for the exact taxonomy "
                 "(closes REPRODUCIBILITY.md caveat #2).\n")

    lines.append("## Findings\n")
    lines.append("- **tab:ctypes (judge label) reproduces in STRUCTURE, not in level.** "
                 "The qualitative story holds: baseline confabulation is ordered "
                 "gpt-5.4-mini < gpt-4o-mini < gemini-2.5-flash < gemini-3-flash-preview, "
                 "Numeric/Modality-tag dominate, and grounding collapses every rate toward "
                 "zero. But the absolute baseline levels come out systematically BELOW the "
                 "paper (e.g. Numeric baseline 0.16/0.01/0.64/0.94 here vs 0.42/0.18/0.81/0.96 "
                 "in the paper), so the exact cells are not reproduced from the released data.")
    lines.append("- **tab:ctypes-rule does NOT reproduce, and cannot.** The rule label "
                 "(`support_label_auto`) emits `unsupported` on only a handful of rows per "
                 "run (11/21/33/160 out of thousands; table below), so every rule-based "
                 "typed unsupported rate is ~0.00 — nowhere near the paper's 0.42–0.96. "
                 "Yet in `paper_8page_icml.tex` the tab:ctypes-rule tabular is **byte-identical** "
                 "to the tab:ctypes tabular. The appendix table labelled as the rule-based "
                 "\"conservative limit\" is a duplicate of the judge table, not a rule-label "
                 "reduction. This contradicts the paper's own §7 statement that the rule-based "
                 "`u_b` is \"artifactually compressed\" — a genuine rule reduction would be "
                 "near zero, as computed here, not equal to the judge numbers.")
    lines.append("- **Some paper cells have no support in the released data.** `Tier` claims "
                 "are absent for gpt-4o-mini (n=0, standard prompt) and for the grounded "
                 "`full_multimodal` config across ALL four runs (n=0), so the paper's Tier "
                 "rows cannot be derived from these files. Grounded `Other` denominators are "
                 "tiny (6–109 claims), making those cells degenerate/noisy (e.g. 1.00 on 6 "
                 "claims for gpt-5.4-mini) rather than the paper's smooth 0.02–0.37.\n")

    for label_key, label_name, note in [
        ("judge_rate", "Table tab:ctypes — agreement-gated JUDGE label (conflict-excluded)",
         "Reproduced from `llm_judge_final`."),
        ("rule_rate", "Table tab:ctypes-rule — rule-based AUTO label (`support_label_auto`)",
         "Reproduced from `support_label_auto`."),
    ]:
        lines.append(f"\n## {label_name}\n\n{note}\n")
        for cfg, cfg_name in CONFIGS.items():
            lines.append(f"\n### {cfg_name}\n")
            lines.append("| Claim type | " + " | ".join(abbrevs) + " | (paper) 4o-m 5.4-m 2.5-f 3-fp |")
            lines.append("|---|" + "---|" * len(abbrevs) + "---|")
            for t in TYPES:
                cells = []
                for d in RUNS:
                    cells.append(fmt(reductions[d][(cfg, t)][label_key]))
                paper = " ".join(f"{v:.2f}" for v in PAPER[(cfg, t)])
                lines.append(f"| {t} | " + " | ".join(cells) + f" | {paper} |")

    # Diagnostics: denominators and the rule-vs-judge gap
    lines.append("\n## Denominators (per type, `full_multimodal` + `baseline`, standard prompt)\n")
    lines.append("| Run | config | " + " | ".join(f"{t} n" for t in TYPES) + " |")
    lines.append("|---|---|" + "---|" * len(TYPES))
    for d in RUNS:
        for cfg in CONFIGS:
            ns = " | ".join(str(reductions[d][(cfg, t)]["n"]) for t in TYPES)
            lines.append(f"| {RUNS[d][0]} | {cfg} | {ns} |")

    # Rule-checker unsupported budget: shows tab:ctypes-rule cannot equal the paper.
    lines.append("\n## Why tab:ctypes-rule cannot match the paper\n")
    lines.append("The rule checker almost never emits `unsupported` (it routes boundary "
                 "cases to `partial`/`unknown`; paper §7). Below is the total count of "
                 "rows the rule label calls `unsupported`, over ALL rows in each run:\n")
    lines.append("| Run | rule `unsupported` rows | total rows |")
    lines.append("|---|---|---|")
    for d in RUNS:
        allrows = list(csv.DictReader(open(OUTPUTS / d / "claim_review.csv", newline="")))
        nu = sum(1 for r in allrows if str(r.get("support_label_auto", "")).strip() == "unsupported")
        lines.append(f"| {RUNS[d][0]} | {nu} | {len(allrows)} |")
    return "\n".join(lines) + "\n"


def write_csv(reductions, path: Path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run", "abbrev", "model", "config", "claim_type", "n_claims",
                    "judge_n", "judge_unsupported_rate", "rule_n", "rule_unsupported_rate",
                    "paper_value"])
        for d in RUNS:
            abbrev, model = RUNS[d]
            idx = list(RUNS).index(d)
            for cfg in CONFIGS:
                for t in TYPES:
                    c = reductions[d][(cfg, t)]
                    w.writerow([d, abbrev, model, cfg, t, c["n"], c["judge_n"],
                                "" if c["judge_rate"] is None else f"{c['judge_rate']:.4f}",
                                c["rule_n"],
                                "" if c["rule_rate"] is None else f"{c['rule_rate']:.4f}",
                                f"{PAPER[(cfg, t)][idx]:.2f}"])


def selftest() -> int:
    # synthetic rows exercising the taxonomy + rate math
    rows = [
        # Numeric+Modality, judge unsupported
        {"prompt_type": "standard", "config": "baseline", "claim_type": "pathology",
         "numeric_fidelity_auto": "incorrect", "modality_match_auto": "correct",
         "llm_judge_final": "unsupported", "support_label_auto": "partial"},
        # Numeric only, judge supported
        {"prompt_type": "standard", "config": "baseline", "claim_type": "clinical",
         "numeric_fidelity_auto": "correct", "modality_match_auto": "unknown",
         "llm_judge_final": "supported", "support_label_auto": "supported"},
        # Numeric+Modality, judge conflict (excluded from judge denom)
        {"prompt_type": "standard", "config": "baseline", "claim_type": "RNA",
         "numeric_fidelity_auto": "incorrect", "modality_match_auto": "incorrect",
         "llm_judge_final": "conflict", "support_label_auto": "unsupported"},
        # Tier, no numeric/modality, judge supported
        {"prompt_type": "standard", "config": "baseline", "claim_type": "tier",
         "numeric_fidelity_auto": "not_applicable", "modality_match_auto": "unknown",
         "llm_judge_final": "supported", "support_label_auto": "partial"},
        # wrong prompt_type -> ignored everywhere
        {"prompt_type": "literature", "config": "baseline", "claim_type": "pathology",
         "numeric_fidelity_auto": "incorrect", "modality_match_auto": "correct",
         "llm_judge_final": "unsupported", "support_label_auto": "unsupported"},
    ]
    std = [r for r in rows if r["prompt_type"] == "standard"]
    base = [r for r in std if r["config"] == "baseline"]

    num = [r for r in base if "Numeric" in claim_types_of(r)]
    assert len(num) == 3, f"Numeric tag count {len(num)}"
    jr, jn = rate(num, "llm_judge_final", exclude_conflict=True)
    assert jn == 2 and abs(jr - 0.5) < 1e-9, f"judge numeric {jr},{jn}"  # 1 unsup of 2 non-conflict
    rr, rn = rate(num, "support_label_auto", exclude_conflict=False)
    assert rn == 3 and abs(rr - 1 / 3) < 1e-9, f"rule numeric {rr},{rn}"  # 1 unsup of 3

    mod = [r for r in base if "Modality-tag" in claim_types_of(r)]
    assert len(mod) == 2, f"Modality count {len(mod)}"

    tier = [r for r in base if "Tier" in claim_types_of(r)]
    assert len(tier) == 1, f"Tier count {len(tier)}"
    assert claim_types_of(tier[0]) == ["Tier"], "tier row should carry only Tier tag"

    # empty label excluded from denom
    empt = [{"llm_judge_final": "", "support_label_auto": ""}]
    r0, n0 = rate(empt, "llm_judge_final", exclude_conflict=True)
    assert n0 == 0 and r0 is None
    print("selftest OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true", help="run stdlib unit checks and exit")
    ap.add_argument("--csv-out", default=str(OUTPUTS / "claim_type_rates.csv"))
    ap.add_argument("--md-out", default=str(OUTPUTS / "claim_type_rates.md"))
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    reductions = {}
    for d in RUNS:
        p = OUTPUTS / d / "claim_review.csv"
        if not p.exists():
            print(f"ERROR: {p} not found", file=sys.stderr)
            return 1
        reductions[d] = reduce_run(p)

    write_csv(reductions, Path(args.csv_out))
    Path(args.md_out).write_text(build_report(reductions))
    print(f"wrote {args.csv_out}")
    print(f"wrote {args.md_out}")

    # brief console summary: baseline Numeric row, judge vs paper
    print("\nbaseline Numeric unsupported rate (judge | paper):")
    for d in RUNS:
        c = reductions[d][("baseline", "Numeric")]
        idx = list(RUNS).index(d)
        jr = "  -  " if c["judge_rate"] is None else f"{c['judge_rate']:.2f}"
        print(f"  {RUNS[d][0]:6s} {jr}  |  {PAPER[('baseline','Numeric')][idx]:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
