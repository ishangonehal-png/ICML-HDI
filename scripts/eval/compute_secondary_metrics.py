#!/usr/bin/env python3
"""
compute_secondary_metrics.py
============================
Reduces the released per-model artifacts to the six columns of Table 5
(``tab:secondary``) and checks each cell against the value printed in the paper.

The paper prints, per model: Avg sent. / Numeric fid. / Mod. attr. /
Ret. on-req. / Ret. FP / Compl. No committed script produced this table
(REPRODUCIBILITY.md attributes it to a ``secondary_metrics`` block in
``metrics.json`` that does not exist); the six columns actually derive from five
separate reductions in ``compute_bionlp_metrics.py``. This script recomputes all
six directly from the committed ``summaries.csv`` / ``claim_review.csv`` /
``retrieval_discipline.csv`` / ``evidence_bundles/`` and reports which cells
reproduce the printed table and which do not.

Deterministic, offline, stdlib only. Reuses the rule-checker regexes from
``compute_bionlp_metrics.py`` so the completeness rubric is identical.

Outputs ``outputs/secondary_metrics.csv``: one row per (model, metric) with the
computed value, the paper value, and whether it reproduces (|Δ|<=tol).

Usage:
    python3 scripts/eval/compute_secondary_metrics.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from compute_bionlp_metrics import (  # noqa: E402  (sibling reuse)
    completeness_for_text,
    safe_div,
    str_to_bool,
)

REPO = Path(__file__).parent.parent.parent
OUT_DIR = REPO / "outputs"

# Model -> output directory. Order matches the printed table.
MODELS = [
    ("gpt-4o-mini", "bionlp_eval"),
    ("gpt-5.4-mini", "bionlp_eval_gpt54mini"),
    ("gemini-2.5-flash", "bionlp_eval_gemini25flash"),
    ("gemini-3-flash-preview", "bionlp_eval_gemini"),
]

# Table 5 / tab:secondary as printed in paper_8page_icml.tex (identical in
# paper_4page_icml.tex). Keys are the metric slugs used below.
PAPER = {
    "gpt-4o-mini":            {"avg_sent": 5.4,  "numeric_fid": 0.381, "mod_attr": 0.976, "ret_onreq": 1.0, "ret_fp": 0.0, "completeness": 0.89},
    "gpt-5.4-mini":           {"avg_sent": 5.5,  "numeric_fid": 0.632, "mod_attr": 0.982, "ret_onreq": 1.0, "ret_fp": 0.0, "completeness": 0.92},
    "gemini-2.5-flash":       {"avg_sent": 8.5,  "numeric_fid": 0.578, "mod_attr": 0.878, "ret_onreq": 1.0, "ret_fp": 0.0, "completeness": 0.80},
    "gemini-3-flash-preview": {"avg_sent": 11.1, "numeric_fid": 0.455, "mod_attr": 0.876, "ret_onreq": 1.0, "ret_fp": 0.0, "completeness": 0.79},
}

# Reproduction tolerances. Avg sentences is printed to 1 decimal; rates to 3.
TOL = {"avg_sent": 0.05, "numeric_fid": 0.001, "mod_attr": 0.001,
       "ret_onreq": 0.001, "ret_fp": 0.001, "completeness": 0.005}


def load_csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def reduce_avg_sent(summaries: list[dict]) -> float:
    std = [r for r in summaries if r.get("prompt_type") == "standard"]
    total = sum(int(r.get("num_sentences", 0)) for r in std)
    return round(safe_div(total, len(std)), 2)


def reduce_numeric_fidelity(claims: list[dict]) -> float:
    std = [c for c in claims if c.get("prompt_type") == "standard"]
    with_num = [c for c in std if c.get("numeric_fidelity_auto", "") != "not_applicable"]
    correct = [c for c in with_num if c.get("numeric_fidelity_auto", "") == "correct"]
    return round(safe_div(len(correct), len(with_num)), 4)


def reduce_modality_attribution(claims: list[dict]) -> float:
    """Standard-prompt reduction, matching compute_bionlp_metrics."""
    std = [c for c in claims if c.get("prompt_type") == "standard"]
    ident = [c for c in std if c.get("modality_match_auto", "") != "unknown"]
    correct = [c for c in ident if c.get("modality_match_auto", "") == "correct"]
    return round(safe_div(len(correct), len(ident)), 4)


def reduce_modality_attribution_by_config(claims: list[dict]) -> dict:
    """Per-config modality attribution, for diagnosing cells that do not
    reproduce under the headline reduction."""
    std = [c for c in claims if c.get("prompt_type") == "standard"]
    out = {}
    for cfg in sorted({c["config"] for c in std}):
        rows = [c for c in std if c["config"] == cfg]
        ident = [c for c in rows if c.get("modality_match_auto", "") != "unknown"]
        correct = [c for c in ident if c.get("modality_match_auto", "") == "correct"]
        out[cfg] = round(safe_div(len(correct), len(ident)), 4)
    return out


def reduce_retrieval(retrieval_rows: list[dict]) -> tuple[float, float]:
    n = len(retrieval_rows)
    on_req = sum(str_to_bool(r.get("literature_used_literature_prompt", "false")) for r in retrieval_rows)
    fp = sum(str_to_bool(r.get("literature_used_standard", "false")) for r in retrieval_rows)
    return round(safe_div(on_req, n), 4), round(safe_div(fp, n), 4)


def reduce_completeness(summaries: list[dict], bundles_dir: Path) -> dict:
    """Recompute the full_multimodal completeness rubric from raw summaries +
    bundles. Returns both the 5-signal reduction the code uses (tier + path +
    rna + clin + uncert, /5) and the 4-signal reduction the caption states
    (path + rna + clin + uncert, /4, excluding the never-mentioned tier signal).
    """
    rows = [r for r in summaries
            if r.get("prompt_type") == "standard" and r.get("config") == "full_multimodal"]
    five, four = [], []
    for row in rows:
        bundle_path = bundles_dir / f"{row['case_id']}_full_multimodal.json"
        rna_in_bundle = False
        if bundle_path.exists():
            with open(bundle_path) as f:
                b = json.load(f)
            rna_in_bundle = b.get("transcriptomics", {}).get("cyt_available", False)
        comp = completeness_for_text(row["summary_text"], "full_multimodal", rna_in_bundle)
        # 5-signal score/5 is exactly comp["completeness_score"].
        five.append(comp["completeness_score"])
        four.append((comp["mentions_pathology"] + comp["mentions_rna"]
                     + comp["mentions_clinical"] + comp["mentions_uncertainty"]) / 4)
    n = len(rows)
    return {
        "n": n,
        "completeness_5signal": round(safe_div(sum(five), n), 4),
        "completeness_4signal_caption": round(safe_div(sum(four), n), 4),
    }


def main() -> int:
    rows_out = []
    diag = {}
    for model, subdir in MODELS:
        d = OUT_DIR / subdir
        summaries = load_csv(d / "summaries.csv")
        claims = load_csv(d / "claim_review.csv")
        retrieval = load_csv(d / "retrieval_discipline.csv")

        avg_sent = reduce_avg_sent(summaries)
        numeric_fid = reduce_numeric_fidelity(claims)
        mod_attr = reduce_modality_attribution(claims)
        ret_onreq, ret_fp = reduce_retrieval(retrieval)
        comp = reduce_completeness(summaries, d / "evidence_bundles")

        computed = {
            "avg_sent": avg_sent,
            "numeric_fid": numeric_fid,
            "mod_attr": mod_attr,
            "ret_onreq": ret_onreq,
            "ret_fp": ret_fp,
            # The code reduction (5-signal) is what metrics.json stores and what
            # the printed Gemini cells match; we compare against it and surface
            # the caption's 4-signal value in the note.
            "completeness": comp["completeness_5signal"],
        }
        diag[model] = {
            "modality_by_config": reduce_modality_attribution_by_config(claims),
            "completeness_4signal_caption": comp["completeness_4signal_caption"],
            "completeness_n": comp["n"],
        }

        for metric in ["avg_sent", "numeric_fid", "mod_attr", "ret_onreq", "ret_fp", "completeness"]:
            paper = PAPER[model][metric]
            cval = computed[metric]
            reproduces = abs(cval - paper) <= TOL[metric]
            note = ""
            if metric == "completeness":
                note = f"caption 4-signal reduction = {comp['completeness_4signal_caption']}"
            if metric == "mod_attr" and not reproduces:
                bc = diag[model]["modality_by_config"]
                note = "no config slice reproduces: " + ", ".join(f"{k}={v}" for k, v in bc.items())
            rows_out.append({
                "model": model,
                "metric": metric,
                "computed": cval,
                "paper": paper,
                "abs_delta": round(abs(cval - paper), 4),
                "reproduces": reproduces,
                "note": note,
            })

    out_csv = OUT_DIR / "secondary_metrics.csv"
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["model", "metric", "computed", "paper",
                                          "abs_delta", "reproduces", "note"])
        w.writeheader()
        w.writerows(rows_out)

    # Console summary
    metrics = ["avg_sent", "numeric_fid", "mod_attr", "ret_onreq", "ret_fp", "completeness"]
    print(f"Table 5 / tab:secondary reduction  (wrote {out_csv.relative_to(REPO)})\n")
    header = f"{'model':24}" + "".join(f"{m:>14}" for m in metrics)
    print(header)
    for model, _ in MODELS:
        cells = []
        for m in metrics:
            r = next(x for x in rows_out if x["model"] == model and x["metric"] == m)
            mark = "" if r["reproduces"] else "*"
            cells.append(f"{r['computed']}{mark}")
        print(f"{model:24}" + "".join(f"{c:>14}" for c in cells))
    print("\n(* = does not reproduce the printed paper value)\n")

    n_fail = sum(1 for r in rows_out if not r["reproduces"])
    print(f"{len(rows_out) - n_fail}/{len(rows_out)} cells reproduce; {n_fail} do not:")
    for r in rows_out:
        if not r["reproduces"]:
            print(f"  {r['model']:24} {r['metric']:14} computed={r['computed']} paper={r['paper']}  ({r['note']})")

    print("\nCompleteness rubric note: the code averages 5 signals (tier included,"
          " but tier is never mentioned so its rate is 0), while the caption states"
          " a 4-signal mean (path/rna/clin/uncert). The printed Gemini cells match"
          " the 5-signal reduction; under the caption's 4-signal definition:")
    for model, _ in MODELS:
        print(f"  {model:24} 4-signal={diag[model]['completeness_4signal_caption']} "
              f"paper={PAPER[model]['completeness']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
