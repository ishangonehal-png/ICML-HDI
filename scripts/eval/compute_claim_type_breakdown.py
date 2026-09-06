#!/usr/bin/env python3
"""
compute_claim_type_breakdown.py
===============================
Reduce the four per-model ``claim_review.csv`` files to the per-claim-type
unsupported-rate breakdown reported as Table 7 (``tab:ctypes``, agreement-gated
judge label) and its rule-based companion (Appendix C) in the HDI paper.

Writes ``outputs/claim_type_unsupported_rates.csv`` and prints a cell-by-cell
comparison against the values printed in the paper.

Why this script exists
----------------------
REPRODUCIBILITY.md previously stated that the mapping from the paper's six-class
typed-claim taxonomy (``numeric / modality-tag / tier / uncertainty / literature /
other``) to the modality-split ``claim_type`` column in ``claim_review.csv``
(``pathology / RNA / clinical / fusion / tier / uncertainty / literature / other``)
was "maintained out-of-tree" and "not yet committed." This script commits a
best-effort, fully documented mapping so the table is at least re-derivable, and it
quantifies how far the released artifacts fall from the paper's printed Table 7 (see
the comparison block at the end of the run — the two do not match; see
REPRODUCIBILITY.md caveat 2 for the reason).

Reduction rules (match the Table 7 caption)
-------------------------------------------
- Standard-prompt claims only (``prompt_type == "standard"``).
- Judge basis: ``llm_judge_final``, agreement-gated, ``conflict``/blank rows excluded
  (the harness's ``baseline_comparison`` reduction).
- Rule basis: ``support_label_auto`` (the conservative rule-based checker; no rows
  excluded, matching Appendix C).
- Unsupported rate = ``unsupported`` / (claims of that type on that basis).

Best-effort paper-taxonomy mapping (documented; NOT a clean partition)
----------------------------------------------------------------------
- ``numeric``      -> ``numeric_fidelity_auto != "not_applicable"`` (the CSV has no
                      ``numeric`` claim_type; this recovers claims carrying a numeric
                      assertion from the numeric-extractor's per-claim signal). This
                      overlaps ``modality-tag`` / ``other`` by construction.
- ``modality-tag`` -> ``claim_type in {pathology, RNA, clinical, fusion}``
- ``tier``         -> ``claim_type == "tier"``
- ``uncertainty``  -> ``claim_type == "uncertainty"``
- ``literature``   -> ``claim_type == "literature"``
- ``other``        -> ``claim_type == "other"``
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_OUT_ROOT = _REPO_ROOT / "outputs"

# Canonical run directories -> paper column abbreviations (matches Table 7 header).
RUNS: dict[str, str] = {
    "4o-m": "bionlp_eval",
    "5.4-m": "bionlp_eval_gpt54mini",
    "2.5-f": "bionlp_eval_gemini25flash",
    "3-fp": "bionlp_eval_gemini",
}

# Paper claim-type order, as printed in Table 7.
PAPER_TYPES = ["Numeric", "Modality-tag", "Tier", "Uncertainty", "Literature", "Other"]

_MODALITY_TAGS = {"pathology", "RNA", "clinical", "fusion"}


def _type_predicates() -> dict:
    """Map each paper claim type to a predicate over a claim_review.csv row."""
    return {
        "Numeric": lambda r: r.get("numeric_fidelity_auto", "") != "not_applicable",
        "Modality-tag": lambda r: r.get("claim_type", "") in _MODALITY_TAGS,
        "Tier": lambda r: r.get("claim_type", "") == "tier",
        "Uncertainty": lambda r: r.get("claim_type", "") == "uncertainty",
        "Literature": lambda r: r.get("claim_type", "") == "literature",
        "Other": lambda r: r.get("claim_type", "") == "other",
    }


# Paper Table 7 (agreement-gated judge label) as printed in paper_8page_icml.tex,
# for the reproducibility comparison. None marks a cell the paper does not print.
PAPER_TABLE7_JUDGE = {
    "baseline": {
        "Numeric": {"4o-m": 0.42, "5.4-m": 0.18, "2.5-f": 0.81, "3-fp": 0.96},
        "Modality-tag": {"4o-m": 0.11, "5.4-m": 0.04, "2.5-f": 0.58, "3-fp": 0.89},
        "Tier": {"4o-m": 0.24, "5.4-m": 0.07, "2.5-f": 0.71, "3-fp": 0.93},
        "Uncertainty": {"4o-m": 0.01, "5.4-m": 0.00, "2.5-f": 0.04, "3-fp": 0.07},
        "Literature": {"4o-m": 0.03, "5.4-m": 0.02, "2.5-f": 0.31, "3-fp": 0.42},
        "Other": {"4o-m": 0.15, "5.4-m": 0.05, "2.5-f": 0.48, "3-fp": 0.84},
    },
    "full_multimodal": {
        "Numeric": {"4o-m": 0.00, "5.4-m": 0.03, "2.5-f": 0.04, "3-fp": 0.11},
        "Modality-tag": {"4o-m": 0.00, "5.4-m": 0.01, "2.5-f": 0.02, "3-fp": 0.08},
        "Tier": {"4o-m": 0.00, "5.4-m": 0.01, "2.5-f": 0.01, "3-fp": 0.03},
        "Uncertainty": {"4o-m": 0.00, "5.4-m": 0.00, "2.5-f": 0.00, "3-fp": 0.00},
        "Literature": {"4o-m": 0.00, "5.4-m": 0.00, "2.5-f": 0.01, "3-fp": 0.02},
        "Other": {"4o-m": 0.02, "5.4-m": 0.12, "2.5-f": 0.09, "3-fp": 0.37},
    },
}

CONDITIONS = ["baseline", "full_multimodal"]


def load_claims(run_dir: Path) -> list[dict]:
    path = run_dir / "claim_review.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing {path}")
    with open(path, newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("prompt_type", "") == "standard"]


def unsupported_rate(claims, predicate, condition, label_col, excluded):
    """(rate, n) of unsupported claims of a type on a label basis, or (None, 0)."""
    sel = [
        r for r in claims
        if r.get("config", "") == condition
        and r.get(label_col, "") not in excluded
        and predicate(r)
    ]
    n = len(sel)
    if n == 0:
        return None, 0
    ct = Counter(r[label_col] for r in sel)
    return round(ct.get("unsupported", 0) / n, 4), n


def compute() -> list[dict]:
    """Return one artifact row per (basis, condition, claim_type, model)."""
    preds = _type_predicates()
    bases = {
        "judge": ("llm_judge_final", ("", "conflict")),
        "rule": ("support_label_auto", ()),
    }
    claims_by_model = {m: load_claims(_OUT_ROOT / d) for m, d in RUNS.items()}

    rows: list[dict] = []
    for basis, (label_col, excluded) in bases.items():
        for condition in CONDITIONS:
            for ptype in PAPER_TYPES:
                for model in RUNS:
                    rate, n = unsupported_rate(
                        claims_by_model[model], preds[ptype], condition, label_col, excluded
                    )
                    rows.append({
                        "label_basis": basis,
                        "condition": condition,
                        "claim_type": ptype,
                        "model": model,
                        "n_claims": n,
                        "unsupported_rate": "" if rate is None else f"{rate:.4f}",
                    })
    return rows


def write_csv(rows: list[dict], out_path: Path) -> None:
    fields = ["label_basis", "condition", "claim_type", "model", "n_claims", "unsupported_rate"]
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def compare_to_paper(rows: list[dict]) -> dict:
    """Cell-by-cell deviation of the committed judge reduction vs paper Table 7."""
    computed = {
        (r["condition"], r["claim_type"], r["model"]): r["unsupported_rate"]
        for r in rows if r["label_basis"] == "judge"
    }
    deviations, unpopulatable = [], []
    for condition in CONDITIONS:
        for ptype in PAPER_TYPES:
            for model in RUNS:
                paper = PAPER_TABLE7_JUDGE[condition][ptype][model]
                got = computed.get((condition, ptype, model), "")
                if got == "":
                    unpopulatable.append((condition, ptype, model, paper))
                else:
                    deviations.append(abs(float(got) - paper))
    total_cells = len(CONDITIONS) * len(PAPER_TYPES) * len(RUNS)
    mad = round(sum(deviations) / len(deviations), 4) if deviations else None
    max_dev = round(max(deviations), 4) if deviations else None
    return {
        "total_cells": total_cells,
        "populated_cells": len(deviations),
        "unpopulatable_cells": unpopulatable,
        "mean_abs_deviation": mad,
        "max_abs_deviation": max_dev,
    }


def _fmt(rate: str) -> str:
    return "  -- " if rate == "" else f"{float(rate):.2f}"


def print_report(rows: list[dict], cmp: dict) -> None:
    for basis in ("judge", "rule"):
        title = "AGREEMENT-GATED JUDGE LABEL (Table 7)" if basis == "judge" \
            else "RULE-BASED AUTO LABEL (Appendix C companion)"
        print(f"\n=== {title} ===")
        for condition in CONDITIONS:
            print(f"\n  {condition}")
            print("  " + "claim_type".ljust(13) + "".join(m.rjust(8) for m in RUNS))
            for ptype in PAPER_TYPES:
                cells = {
                    r["model"]: r["unsupported_rate"] for r in rows
                    if r["label_basis"] == basis and r["condition"] == condition
                    and r["claim_type"] == ptype
                }
                print("  " + ptype.ljust(13) + "".join(_fmt(cells[m]).rjust(8) for m in RUNS))

    print("\n=== REPRODUCIBILITY CHECK vs paper Table 7 (judge basis) ===")
    print(f"  cells total:            {cmp['total_cells']}")
    print(f"  cells the CSV can fill: {cmp['populated_cells']}")
    print(f"  cells CSV CANNOT fill:  {len(cmp['unpopulatable_cells'])} "
          f"(paper prints a value; released claim_type has 0 such claims)")
    for cond, ptype, model, paper in cmp["unpopulatable_cells"]:
        print(f"      {cond:>15} / {ptype:<12} / {model:<5}  paper={paper:.2f}  CSV: n=0")
    print(f"  mean |committed - paper| on fillable cells: {cmp['mean_abs_deviation']}")
    print(f"  max  |committed - paper| on fillable cells: {cmp['max_abs_deviation']}")
    verdict = (
        "NOT REPRODUCIBLE from released artifacts: the committed reduction preserves the\n"
        "  qualitative structure (numeric/modality-tag dominate ungrounded confabulation;\n"
        "  grounded residual concentrates in 'other') but does not recover Table 7's exact\n"
        "  values, and several printed cells have no corresponding claims in claim_review.csv."
    )
    print(f"\n  VERDICT: {verdict}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-csv",
        default=str(_OUT_ROOT / "claim_type_unsupported_rates.csv"),
        help="artifact path (default: outputs/claim_type_unsupported_rates.csv)",
    )
    args = parser.parse_args()

    rows = compute()
    out_path = Path(args.out_csv)
    write_csv(rows, out_path)
    cmp = compare_to_paper(rows)
    print_report(rows, cmp)
    print(f"\nWrote {out_path.relative_to(_REPO_ROOT)} ({len(rows)} rows).")


if __name__ == "__main__":
    main()
