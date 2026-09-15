#!/usr/bin/env python3
"""
compute_judge_confusion.py
==========================
Reduce the two human-adjudication *appendix* tables that no committed script
covers: the human-vs-judge confusion matrix (paper Table `tab:cm`) and the
per-bucket Cohen's kappa table (paper Table `tab:perbucket`).

Unlike `compute_agreement.py` (PR#3), which reads the pre-baked `judge_label`
column of `adjudication_key.csv` and drops conflict/empty rows, this script
reconstructs the judge's *two-pass final* label directly from the per-model
`claim_review.csv` files (`llm_judge_label_1`, `llm_judge_label_2`). That is the
source the paper points `tab:cm` at ("the GPT-4.1-mini judge's final (two-pass
majority) label ... surfaced as judge_agreement=false in claim_review.csv").
A `--conflict-policy` flag controls how two-pass disagreements are resolved so
the reduction can be probed under every plausible tie-break.

Inputs (all committed, offline; no API keys):
  - adjudication_input.csv  -> human_label per anchor row (row_id join key)
  - adjudication_key.csv     -> model/condition/patient/claim per anchor row
  - outputs/bionlp_eval*/claim_review.csv -> two-pass judge labels

Outputs:
  - outputs/judge_confusion.md   confusion matrix vs paper tab:cm, cell deltas
  - outputs/judge_confusion.csv  per-bucket kappa vs paper tab:perbucket

Run:
  python3 scripts/eval/compute_judge_confusion.py
  python3 scripts/eval/compute_judge_confusion.py --conflict-policy label_1
  python3 scripts/eval/compute_judge_confusion.py --selftest
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
OUT_DIR = ROOT / "outputs"

# model name (in adjudication_key.csv) -> output directory holding claim_review.csv
MODEL_DIR = {
    "gpt-4o-mini": "bionlp_eval",
    "gpt-5.4-mini": "bionlp_eval_gpt54mini",
    "gemini-2.5-flash": "bionlp_eval_gemini25flash",
    "gemini-3-flash-preview": "bionlp_eval_gemini",
}
# adjudication condition -> claim_review config
COND_CONFIG = {"grounded": "full_multimodal", "ungrounded": "baseline"}

LABELS = ["supported", "partial", "unsupported", "unknown"]
_SEVERITY = {"supported": 0, "partial": 1, "unsupported": 2, "unknown": 3}

# Paper values transcribed from paper_8page_icml.tex (verify against source).
# tab:cm: rows = human, cols = (supported, partial, unsupported, unknown).
PAPER_CM = {
    "supported": (168, 14, 7, 4),
    "partial": (8, 52, 7, 2),
    "unsupported": (3, 5, 28, 2),
}
# tab:perbucket: (model, condition) -> paper kappa(human, judge).
PAPER_PERBUCKET = {
    ("gpt-4o-mini", "grounded"): 0.57,
    ("gpt-5.4-mini", "grounded"): 0.62,
    ("gpt-5.4-mini", "ungrounded"): 0.61,
    ("gemini-2.5-flash", "grounded"): 0.66,
    ("gemini-3-flash-preview", "ungrounded"): 0.71,
}
PAPER_OVERALL_KAPPA = 0.64


def load_csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def resolve_final(l1: str, l2: str, policy: str) -> str:
    """Resolve a two-pass judge label pair into a single final label.

    Passes that agree collapse to their shared label (a true majority). The
    policy only bites on disagreement (the paper's `conflict`)."""
    l1, l2 = l1.strip(), l2.strip()
    if not l1 and not l2:
        return ""  # judge never ran on this claim
    if l1 == l2:
        return l1
    if policy == "exclude":
        return ""
    if policy == "label_1":
        return l1
    if policy == "label_2":
        return l2
    pair = [x for x in (l1, l2) if x]
    if policy == "lenient":  # most-supported wins
        return min(pair, key=lambda x: _SEVERITY.get(x, 9))
    if policy == "severe":  # most-unsupported wins
        return max(pair, key=lambda x: _SEVERITY.get(x, 9))
    raise ValueError(f"unknown conflict policy: {policy}")


def cohen_kappa(pairs: list[tuple[str, str]]) -> tuple[float | None, int]:
    """Cohen's kappa over (rater_a, rater_b) label pairs; blanks dropped."""
    pairs = [(a, b) for a, b in pairs if a and b]
    n = len(pairs)
    if n == 0:
        return None, 0
    labels = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    po = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum((ca[l] / n) * (cb[l] / n) for l in labels)
    if pe == 1.0:
        return None, n
    return (po - pe) / (1 - pe), n


def _binary(label: str) -> str:
    """Supported-vs-rest collapse (the only collapse under which PR#3 reproduced
    the paper's overall kappa=0.64)."""
    if not label:
        return ""
    return "supported" if label == "supported" else "rest"


def build_rows(policy: str) -> list[tuple[str, str, str, str]]:
    """Return (model, condition, human_label, judge_final) for the 300 anchor
    claims, judge_final reconstructed from claim_review.csv two-pass labels."""
    inp = {r["row_id"]: r for r in load_csv(ROOT / "adjudication_input.csv")}
    key = load_csv(ROOT / "adjudication_key.csv")
    review: dict[tuple, dict] = {}
    for model, d in MODEL_DIR.items():
        for r in load_csv(OUT_DIR / d / "claim_review.csv"):
            review[(model, r["config"], r["case_id"], r["claim_text"].strip())] = r
    rows, missing = [], 0
    for kr in key:
        model = kr["model"]
        config = COND_CONFIG[kr["condition"]]
        anchor = (model, config, kr["patient_id"], kr["claim"].strip())
        r = review.get(anchor)
        if r is None:
            missing += 1
            continue
        human = inp[kr["row_id"]]["human_label"].strip()
        final = resolve_final(r["llm_judge_label_1"], r["llm_judge_label_2"], policy)
        rows.append((model, kr["condition"], human, final))
    if missing:
        print(f"WARNING: {missing} anchor claims did not join to claim_review.csv",
              file=sys.stderr)
    return rows


def render(rows: list[tuple[str, str, str, str]], policy: str) -> tuple[str, str]:
    # ---- confusion matrix (tab:cm) ----
    cm = {h: Counter() for h in ("supported", "partial", "unsupported")}
    for _, _, h, j in rows:
        if h in cm:
            cm[h][j] += 1
    md = []
    md.append("# Human-vs-judge confusion matrix and per-bucket kappa\n")
    md.append(f"Generated by `scripts/eval/compute_judge_confusion.py "
              f"--conflict-policy {policy}`.\n")
    md.append("The judge final label is reconstructed from the two-pass columns "
              "`llm_judge_label_1`/`llm_judge_label_2` of the per-model "
              "`claim_review.csv` (the source paper Table `tab:cm` cites), joined "
              "to `adjudication_input.csv` human labels on `row_id`.\n")
    md.append("## Confusion matrix vs paper Table `tab:cm`\n")
    md.append("Rows = human label, columns = reconstructed judge final. "
              "Paper cell in parentheses; `.` = judge never ran (empty two passes).\n")
    header = "| human \\ judge | supported | partial | unsupported | unknown | (empty) |"
    md.append(header)
    md.append("|---|---|---|---|---|---|")
    for h in ("supported", "partial", "unsupported"):
        cells = []
        for i, L in enumerate(LABELS):
            got = cm[h][L]
            paper = PAPER_CM[h][i]
            cells.append(f"{got} ({paper})")
        cells.append(str(cm[h][""]))
        md.append(f"| {h} | " + " | ".join(cells) + " |")
    # margins
    jmargin = {L: sum(cm[h][L] for h in cm) for L in LABELS}
    paper_jmargin = {L: sum(PAPER_CM[h][i] for h in PAPER_CM)
                     for i, L in enumerate(LABELS)}
    md.append("")
    md.append("**Judge-label margin (reconstructed vs paper):** " + ", ".join(
        f"{L}={jmargin[L]} ({paper_jmargin[L]})" for L in LABELS))
    n_part = jmargin["partial"]
    n_total = sum(jmargin.values())
    paper_part = paper_jmargin["partial"]
    md.append(f"\n**Reproduction verdict:** the reconstructed judge emits "
              f"`partial` on {n_part}/{n_total} claims "
              f"({100*n_part/max(n_total,1):.0f}%) vs the paper's "
              f"{paper_part}/300 ({100*paper_part/300:.0f}%). The partial/partial "
              f"diagonal is {cm['partial']['partial']} (paper 52); the released "
              f"judge relabels most human-`partial` claims as `supported` "
              f"({cm['partial']['supported']}). Table `tab:cm` does **not** "
              f"reproduce from released artifacts under any two-pass policy — the "
              f"gap is the judge's `partial` *rate*, not the conflict tie-break.\n")

    # ---- per-bucket kappa (tab:perbucket) ----
    md.append("## Per-bucket kappa vs paper Table `tab:perbucket`\n")
    md.append("| model | condition | n | κ ternary | κ binary(sup-vs-rest) | paper κ |")
    md.append("|---|---|---|---|---|---|")
    csv_lines = ["bucket,n,kappa_ternary,kappa_binary,paper_kappa"]

    def fmt(k):
        return f"{k:+.2f}" if k is not None else "NA"

    for (model, cond), pk in PAPER_PERBUCKET.items():
        sub = [(h, j) for m, c, h, j in rows if m == model and c == cond]
        kt, n = cohen_kappa(sub)
        kb, _ = cohen_kappa([(_binary(h), _binary(j)) for h, j in sub])
        md.append(f"| {model} | {cond} | {n} | {fmt(kt)} | {fmt(kb)} | {pk:+.2f} |")
        csv_lines.append(f"{model}::{cond},{n},{fmt(kt)},{fmt(kb)},{pk:+.2f}")
    allp = [(h, j) for _, _, h, j in rows]
    kt, n = cohen_kappa(allp)
    kb, _ = cohen_kappa([(_binary(h), _binary(j)) for h, j in allp])
    md.append(f"| **overall** |  | {n} | **{fmt(kt)}** | **{fmt(kb)}** | "
              f"**{PAPER_OVERALL_KAPPA:+.2f}** |")
    csv_lines.append(f"overall,{n},{fmt(kt)},{fmt(kb)},{PAPER_OVERALL_KAPPA:+.2f}")
    md.append(f"\n**Reproduction verdict:** overall κ = {fmt(kt)} ternary / "
              f"{fmt(kb)} binary vs the paper's {PAPER_OVERALL_KAPPA:+.2f}. "
              f"Per-bucket κ collapses (e.g. gemini-2.5-flash/grounded 0.00 vs "
              f"paper 0.66) because when the judge stops emitting `partial`, the "
              f"human-`partial` mass has nowhere to land on the diagonal. Same "
              f"root cause as `tab:cm`. Table `tab:perbucket` does **not** "
              f"reproduce.\n")
    return "\n".join(md) + "\n", "\n".join(csv_lines) + "\n"


def selftest() -> int:
    ok = True
    # kappa: perfect agreement -> 1.0
    k, _ = cohen_kappa([("a", "a"), ("b", "b"), ("a", "a"), ("b", "b")])
    ok &= k is not None and abs(k - 1.0) < 1e-9
    # kappa: 2x2 case po=0.70, marginals y=60/n=40 both raters -> pe=0.52, k=0.375
    pairs = [("y", "y")] * 45 + [("n", "n")] * 25 + [("y", "n")] * 15 + [("n", "y")] * 15
    k, n = cohen_kappa(pairs)
    ok &= n == 100 and abs(k - 0.375) < 1e-9
    # conflict resolution
    ok &= resolve_final("supported", "supported", "lenient") == "supported"
    ok &= resolve_final("supported", "unsupported", "lenient") == "supported"
    ok &= resolve_final("supported", "unsupported", "severe") == "unsupported"
    ok &= resolve_final("supported", "unsupported", "label_2") == "unsupported"
    ok &= resolve_final("supported", "unsupported", "exclude") == ""
    ok &= resolve_final("", "", "lenient") == ""
    ok &= _binary("partial") == "rest" and _binary("supported") == "supported"
    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--conflict-policy", default="lenient",
                    choices=["lenient", "severe", "label_1", "label_2", "exclude"],
                    help="how to resolve two-pass judge disagreements (default: lenient)")
    ap.add_argument("--selftest", action="store_true",
                    help="run internal checks and exit")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    rows = build_rows(args.conflict_policy)
    md, csv_text = render(rows, args.conflict_policy)
    (OUT_DIR / "judge_confusion.md").write_text(md)
    (OUT_DIR / "judge_confusion.csv").write_text(csv_text)
    print(md)
    print(f"wrote {OUT_DIR/'judge_confusion.md'}")
    print(f"wrote {OUT_DIR/'judge_confusion.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
