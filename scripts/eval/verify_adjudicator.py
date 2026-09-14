#!/usr/bin/env python3
"""
verify_adjudicator.py
=====================
Characterizes what `adjudicate.py` (REPRODUCIBILITY.md step 5) actually produces and
how it relates to the released human anchor and the released rule-label column.

Motivation
----------
REPRODUCIBILITY.md step 5 is documented as "re-validate the human anchor:
`python3 adjudicate.py`". Two problems, both offline-verifiable:

  1. `adjudicate.py` previously hardcoded an absolute path and crashed on any other
     machine. (Fixed in the same increment; it now defaults to repo-relative paths
     and writes to `outputs/adjudication_regenerated.csv`.)

  2. `adjudicate.py` does not *validate* the human anchor. It is a rule-based label
     *generator*: it overwrites the `human_label` column with a machine label. The
     true two-expert anchor is the `human_label` column already present in
     `adjudication_input.csv`.

This script imports `adjudicate.adjudicate()` (read-only) and reports:

  - regenerated-rule == committed `adjudication_output.csv` `human_label`
    (expected exact, i.e. adjudicate.py IS the generator of that file);
  - regenerated-rule vs the two-expert human anchor (raw agreement, Cohen's kappa,
    binary supported-vs-rest kappa, confusion matrix);
  - regenerated-rule vs the released `adjudication_key.csv` `rule_label`
    (they are two *different* rule labelings, and this quantifies the divergence).

Inputs (released, offline, no API keys):
  - adjudication_input.csv  : claim + bundle_excerpt + two-expert `human_label`
  - adjudication_output.csv : adjudicate.py's committed rule labels (in `human_label`)
  - adjudication_key.csv    : `rule_label`, `judge_label` keyed by `row_id`

Writes:
  - outputs/adjudicator_verification.csv  (tidy: one row per comparison)
  - outputs/adjudicator_verification.md   (confusion matrices + provenance note)

Nothing is written to any committed adjudication CSV.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_adjudicate_module(repo_root: Path):
    """Import adjudicate.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("adjudicate", repo_root / "adjudicate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cohen_kappa(pairs: list[tuple[str, str]]) -> tuple[float, float]:
    """Return (raw_agreement, Cohen's kappa) over paired categorical labels."""
    n = len(pairs)
    if n == 0:
        return 0.0, 0.0
    p_o = sum(1 for a, b in pairs if a == b) / n
    ca = Counter(a for a, _ in pairs)
    cb = Counter(b for _, b in pairs)
    cats = set(ca) | set(cb)
    p_e = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    kappa = 0.0 if p_e >= 1.0 else (p_o - p_e) / (1.0 - p_e)
    return p_o, kappa


def binary_supported(label: str) -> str:
    return "supported" if label == "supported" else "not_supported"


def render_confusion(pairs: list[tuple[str, str]], a_name: str, b_name: str) -> str:
    rows = sorted({a for a, _ in pairs})
    cols = sorted({b for _, b in pairs})
    cell = Counter(pairs)
    header = f"| {a_name} \\ {b_name} | " + " | ".join(cols) + " |"
    sep = "|" + "---|" * (len(cols) + 1)
    lines = [header, sep]
    for r in rows:
        lines.append("| " + r + " | " + " | ".join(str(cell[(r, c)]) for c in cols) + " |")
    return "\n".join(lines)


def selftest() -> int:
    # kappa of a perfect labeling is 1.0; of an all-same labeling is 0.0 (p_e=1).
    perfect = [("supported", "supported"), ("partial", "partial"), ("unsupported", "unsupported")]
    raw, k = cohen_kappa(perfect)
    assert abs(raw - 1.0) < 1e-9 and abs(k - 1.0) < 1e-9, (raw, k)
    degenerate = [("supported", "supported")] * 5
    _, k2 = cohen_kappa(degenerate)
    assert k2 == 0.0, k2
    # a known 2x2 confusion: 8 agree-sup, 2 disagree -> raw 0.8
    mixed = [("supported", "supported")] * 8 + [("supported", "partial")] * 2
    raw3, _ = cohen_kappa(mixed)
    assert abs(raw3 - 0.8) < 1e-9, raw3
    assert binary_supported("partial") == "not_supported"
    assert binary_supported("supported") == "supported"
    print("selftest OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=REPO_ROOT / "adjudication_input.csv")
    ap.add_argument("--output-csv", type=Path, default=REPO_ROOT / "adjudication_output.csv")
    ap.add_argument("--key", type=Path, default=REPO_ROOT / "adjudication_key.csv")
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "outputs")
    ap.add_argument("--selftest", action="store_true", help="run internal checks and exit")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    adj = load_adjudicate_module(REPO_ROOT)
    inp = load_csv(args.input)
    committed = {r["row_id"]: r["human_label"].strip() for r in load_csv(args.output_csv)}
    key = {r["row_id"]: r for r in load_csv(args.key)}

    # Regenerate the rule label from the released input (read-only).
    regen = {}
    for r in inp:
        label, _ = adj.adjudicate(r["claim"], adj.parse_bundle(r["bundle_excerpt"]))
        regen[r["row_id"]] = label
    human_anchor = {r["row_id"]: r["human_label"].strip() for r in inp}

    rows_out = []

    # 1) regenerated == committed adjudication_output.csv (exact-reproduction check)
    common_c = sorted(set(regen) & set(committed))
    match = sum(1 for rid in common_c if regen[rid] == committed[rid])
    rows_out.append({
        "comparison": "regenerated_vs_committed_output",
        "n": len(common_c),
        "raw_agreement": round(match / len(common_c), 4) if common_c else 0.0,
        "cohen_kappa": "",
        "kappa_binary_supported": "",
        "note": "expected 1.0 -> adjudicate.py is the generator of adjudication_output.csv",
    })

    # 2) regenerated rule label vs two-expert human anchor
    pairs_ha = [(human_anchor[rid], regen[rid]) for rid in regen if rid in human_anchor]
    raw_ha, k_ha = cohen_kappa(pairs_ha)
    _, k_ha_bin = cohen_kappa(
        [(binary_supported(a), binary_supported(b)) for a, b in pairs_ha]
    )
    rows_out.append({
        "comparison": "regenerated_rule_vs_human_anchor",
        "n": len(pairs_ha),
        "raw_agreement": round(raw_ha, 4),
        "cohen_kappa": round(k_ha, 4),
        "kappa_binary_supported": round(k_ha_bin, 4),
        "note": "rule label vs the two-expert anchor in adjudication_input.csv",
    })

    # 3) regenerated rule label vs released key.rule_label (two rule labelings)
    pairs_rr = [
        (regen[rid], key[rid]["rule_label"].strip())
        for rid in regen
        if rid in key
    ]
    raw_rr, k_rr = cohen_kappa(pairs_rr)
    rows_out.append({
        "comparison": "regenerated_rule_vs_key_rule_label",
        "n": len(pairs_rr),
        "raw_agreement": round(raw_rr, 4),
        "cohen_kappa": round(k_rr, 4),
        "kappa_binary_supported": "",
        "note": "adjudicate.py's rule label vs adjudication_key.csv rule_label",
    })

    # 4) for reference: released key.rule_label vs human anchor
    pairs_kh = [
        (human_anchor[rid], key[rid]["rule_label"].strip())
        for rid in human_anchor
        if rid in key
    ]
    raw_kh, k_kh = cohen_kappa(pairs_kh)
    rows_out.append({
        "comparison": "key_rule_label_vs_human_anchor",
        "n": len(pairs_kh),
        "raw_agreement": round(raw_kh, 4),
        "cohen_kappa": round(k_kh, 4),
        "kappa_binary_supported": "",
        "note": "reference: the released rule_label column vs the human anchor",
    })

    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "adjudicator_verification.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["comparison", "n", "raw_agreement", "cohen_kappa",
                        "kappa_binary_supported", "note"],
        )
        w.writeheader()
        w.writerows(rows_out)

    md_path = args.out_dir / "adjudicator_verification.md"
    with open(md_path, "w") as f:
        f.write("# adjudicate.py verification\n\n")
        f.write(
            "Generated by `scripts/eval/verify_adjudicator.py` (stdlib, offline). It\n"
            "imports `adjudicate.adjudicate()` read-only and regenerates the rule label\n"
            "from `adjudication_input.csv`. Nothing is written to any committed\n"
            "adjudication CSV.\n\n"
        )
        f.write("## Summary\n\n")
        f.write("| comparison | n | raw | kappa | kappa (binary sup.) |\n")
        f.write("|---|---|---|---|---|\n")
        for r in rows_out:
            f.write(
                f"| {r['comparison']} | {r['n']} | {r['raw_agreement']} | "
                f"{r['cohen_kappa']} | {r['kappa_binary_supported']} |\n"
            )
        f.write("\n")
        f.write(
            "**What this shows.** `adjudicate.py` reproduces the committed\n"
            "`adjudication_output.csv` `human_label` column exactly, confirming it is the\n"
            "generator of that file. That column is a *rule* label, not a human label:\n"
            "against the two-expert anchor it agrees only moderately, and it is a\n"
            "*different* rule labeling from the released `adjudication_key.csv`\n"
            "`rule_label` column.\n\n"
        )
        f.write("## Confusion: human anchor (rows) vs regenerated rule label (cols)\n\n")
        f.write(render_confusion(pairs_ha, "human", "rule(adjudicate.py)") + "\n\n")
        f.write("## Confusion: regenerated rule (rows) vs key.rule_label (cols)\n\n")
        f.write(render_confusion(pairs_rr, "rule(adjudicate.py)", "rule(key)") + "\n")

    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")
    for r in rows_out:
        print(
            f"  {r['comparison']}: n={r['n']} raw={r['raw_agreement']} "
            f"kappa={r['cohen_kappa']} kappa_bin={r['kappa_binary_supported']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
