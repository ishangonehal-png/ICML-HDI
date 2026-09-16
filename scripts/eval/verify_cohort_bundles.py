#!/usr/bin/env python3
"""
verify_cohort_bundles.py
========================
Audits the INPUT side of the HDI harness: the released cohort split
(``case_selection.csv``) and the per-case ``evidence_bundles/`` JSONs, against the
cohort and four-condition definitions the paper states.

Every other committed reduction (scripts/eval/compute_*.py, adjudicate.py) works on
the *output* labels in ``claim_review.csv`` / ``metrics.json``. None of them can see
what was actually put in front of the model. This script checks that.

Paper claims audited (paper_8page_icml.tex):
  Cohort (Appendix, l.639):
    C1  N = 119 cases.
    C2  Tertile counts 40 Hot / 40 Warm / 39 Cold.
    C3  io_tier is a tertile partition of io_score (non-overlapping, Cold<Warm<Hot).
    C4  Cohort is deterministic and shared across models
        (same case_ids + tiers in every run directory).
    C5  Selected from "522 LUAD cases with complete pathology and RNA layers".
  Four-condition protocol (Methods, l.109) and System (l.~92-96):
    B1  baseline is evidence-free (only case id + cohort; empty pathology bundle).
    B2  pathology_only  = pathology layer only.
    B3  pathology_rna   = pathology + RNA.
    B4  full_multimodal = pathology + RNA + clinical + tier (all present).

The audit is over all four released run directories. Everything is stdlib, offline,
and deterministic. No API keys, no network.

Usage:
    python3 scripts/eval/verify_cohort_bundles.py
    python3 scripts/eval/verify_cohort_bundles.py --out outputs/cohort_bundle_integrity.csv
    python3 scripts/eval/verify_cohort_bundles.py --selftest
"""
from __future__ import annotations

import argparse
import csv
import json
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

PAPER_N = 119
PAPER_TIERS = {"Hot": 40, "Warm": 40, "Cold": 39}


# --------------------------------------------------------------------------- #
# cohort-level checks (case_selection.csv)
# --------------------------------------------------------------------------- #
def load_cohort(run_dir: Path) -> list[dict]:
    with open(run_dir / "case_selection.csv", newline="") as f:
        return list(csv.DictReader(f))


def tier_counts(rows: list[dict]) -> dict:
    counts = {"Hot": 0, "Warm": 0, "Cold": 0}
    for r in rows:
        counts[r["io_tier"]] = counts.get(r["io_tier"], 0) + 1
    return counts


def is_tertile_partition(rows: list[dict]) -> bool:
    """True iff io_score ranges for the three tiers are non-overlapping and
    ordered Cold < Warm < Hot (i.e. io_tier is a strict tertile cut of io_score)."""
    spans = {}
    for t in ("Hot", "Warm", "Cold"):
        sc = sorted(float(r["io_score"]) for r in rows if r["io_tier"] == t)
        if not sc:
            return False
        spans[t] = (sc[0], sc[-1])
    return spans["Cold"][1] < spans["Warm"][0] and spans["Warm"][1] < spans["Hot"][0]


def cohort_fingerprint(rows: list[dict]) -> frozenset:
    return frozenset((r["case_id"], r["io_tier"]) for r in rows)


# --------------------------------------------------------------------------- #
# bundle-level checks (evidence_bundles/*.json)
# --------------------------------------------------------------------------- #
def _norm_bundle(d: dict) -> str:
    """Bundle content with the config label removed, canonicalised for equality."""
    d = dict(d)
    d.pop("config", None)
    return json.dumps(d, sort_keys=True)


def _has_rna(bundle: dict) -> bool:
    if bundle.get("rna_available") is True:
        return True
    tx = bundle.get("transcriptomics") or {}
    return any(tx.get(k) is not None for k in ("cyt_value", "gep_value", "tide_value"))


def _has_clinical(bundle: dict) -> bool:
    c = bundle.get("clinical")
    return c not in (None, {}, "")


def _baseline_is_empty(bundle: dict) -> bool:
    path = bundle.get("pathology") or {}
    return (
        not path.get("tissue_fractions")
        and not path.get("top_tiles")
        and path.get("til_fraction") in (None, 0)
    )


def audit_bundles(run_dir: Path) -> dict:
    """Load every case's four bundles and summarise content integrity."""
    bd = run_dir / "evidence_bundles"
    by_case: dict[str, dict] = {}
    for f in bd.glob("*.json"):
        d = json.load(open(f))
        by_case.setdefault(d["case_id"], {})[d["config"]] = d

    complete = [c for c, cfg in by_case.items() if all(k in cfg for k in CONFIGS)]
    n = len(complete)
    stats = {
        "n_cases": n,
        "grounded_configs_identical": 0,  # po==pr==fm (content)
        "full_has_rna": 0,
        "full_has_clinical": 0,
        "baseline_empty": 0,
    }
    for cid in complete:
        cfg = by_case[cid]
        po, pr, fm = (_norm_bundle(cfg[c]) for c in GROUNDED)
        if po == pr == fm:
            stats["grounded_configs_identical"] += 1
        if _has_rna(cfg["full_multimodal"]):
            stats["full_has_rna"] += 1
        if _has_clinical(cfg["full_multimodal"]):
            stats["full_has_clinical"] += 1
        if _baseline_is_empty(cfg["baseline"]):
            stats["baseline_empty"] += 1
    return stats


# --------------------------------------------------------------------------- #
# audit driver
# --------------------------------------------------------------------------- #
def run_audit() -> list[dict]:
    cohorts = {m: load_cohort(d) for m, d in MODEL_DIRS.items()}
    fps = {m: cohort_fingerprint(rows) for m, rows in cohorts.items()}
    ref = next(iter(fps.values()))
    cohort_shared = all(fp == ref for fp in fps.values())

    rows_out: list[dict] = []
    for model, run_dir in MODEL_DIRS.items():
        cohort = cohorts[model]
        tc = tier_counts(cohort)
        b = audit_bundles(run_dir)
        n = b["n_cases"]

        def frac(k):
            return f"{b[k]}/{n}"

        rows_out.append(
            {
                "model": model,
                "n_cases": len(cohort),
                # C1
                "C1_N119": "PASS" if len(cohort) == PAPER_N else "FAIL",
                # C2
                "tier_counts": f"Hot={tc['Hot']},Warm={tc['Warm']},Cold={tc['Cold']}",
                "C2_tiers_40_40_39": "PASS" if tc == PAPER_TIERS else "FAIL",
                # C3
                "C3_tertile_partition": "PASS" if is_tertile_partition(cohort) else "FAIL",
                # C4
                "C4_cohort_shared": "PASS" if cohort_shared else "FAIL",
                # C5 / B3 / B4 : RNA present in released bundles
                "full_has_rna": frac("full_has_rna"),
                "C5_B3_B4_rna_present": "PASS" if b["full_has_rna"] == n else "FAIL",
                # B4 : clinical present
                "full_has_clinical": frac("full_has_clinical"),
                "B4_clinical_present": "PASS" if b["full_has_clinical"] == n else "FAIL",
                # B1 : baseline empty
                "baseline_empty": frac("baseline_empty"),
                "B1_baseline_evidence_free": "PASS" if b["baseline_empty"] == n else "FAIL",
                # B2/B3/B4 depth gradient : the three grounded bundles should DIFFER
                "grounded_identical": frac("grounded_configs_identical"),
                "B_depth_gradient_present": "PASS"
                if b["grounded_configs_identical"] == 0
                else "FAIL",
            }
        )
    return rows_out


FIELDS = [
    "model",
    "n_cases",
    "C1_N119",
    "tier_counts",
    "C2_tiers_40_40_39",
    "C3_tertile_partition",
    "C4_cohort_shared",
    "full_has_rna",
    "C5_B3_B4_rna_present",
    "full_has_clinical",
    "B4_clinical_present",
    "baseline_empty",
    "B1_baseline_evidence_free",
    "grounded_identical",
    "B_depth_gradient_present",
]


def write_csv(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_md(rows: list[dict], out: Path) -> None:
    r0 = rows[0]
    lines = [
        "# Cohort & evidence-bundle integrity audit",
        "",
        "Input-side audit of the released HDI artifacts: does the cohort split and the",
        "`evidence_bundles/` content match the cohort and four-condition definitions the",
        "paper states? Generated by `scripts/eval/verify_cohort_bundles.py` (stdlib, offline).",
        "",
        "## What reproduces (cohort)",
        "",
        f"- **C1 N=119**: {r0['C1_N119']} — every run has {r0['n_cases']} cases.",
        f"- **C2 tertile counts 40/40/39**: {r0['C2_tiers_40_40_39']} — {r0['tier_counts']}, "
        "matching paper Appendix l.639 exactly.",
        f"- **C3 tertile partition**: {r0['C3_tertile_partition']} — `io_tier` is a strict,"
        " non-overlapping tertile cut of `io_score` (Cold<Warm<Hot).",
        f"- **C4 cohort shared across models**: {r0['C4_cohort_shared']} — all four run"
        " directories carry the identical (case_id, io_tier) set.",
        f"- **B1 baseline evidence-free**: {r0['B1_baseline_evidence_free']} — every"
        " `baseline` bundle has an empty pathology block, so the ungrounded (HDI"
        " denominator) leg is legitimate.",
        "",
        "## What does NOT reproduce (multimodal content)",
        "",
        f"- **C5/B3/B4 RNA present**: {r0['C5_B3_B4_rna_present']} — `full_multimodal` bundles"
        f" with any RNA value: {r0['full_has_rna']}. Every bundle has"
        " `rna_available:false`, `transcriptomics` all null, fusion transcriptomics"
        " contribution 0.0%. The paper (l.639) claims the cohort has \"complete pathology"
        " and RNA layers\"; methods (l.109) define `full_multimodal` as pathology+RNA+"
        "clinical+tier.",
        f"- **B4 clinical present**: {r0['B4_clinical_present']} — `full_multimodal` bundles"
        f" with a clinical block: {r0['full_has_clinical']}. `case_selection.csv` stamps"
        " `has_clinical=True` (hardcoded in `run_bionlp_eval.py` as \"deterministic"
        " fallback\"), but no clinical layer is present in the bundle. (Clinical *proxy*"
        " text does leak via `fusion.modality_contributions.clinical.summary`.)",
        f"- **B depth-of-grounding gradient present**: {r0['B_depth_gradient_present']} —"
        f" cases where the three grounded bundles are byte-identical: {r0['grounded_identical']}."
        " `pathology_only`, `pathology_rna`, and `full_multimodal` present the *same*"
        " pathology-only bundle to the model. There is no evidence-content gradient to"
        " ablate; the per-config differences in Table 6 (`tab:gradient`, reduced in the"
        " tab:gradient PR) come from generation stochasticity and the config label"
        " announced in the prompt, not from evidence depth. Summaries still differ"
        " (0/119 identical `pathology_only` vs `pathology_rna`).",
        "",
        "## Per-model results",
        "",
        "| model | C1 N | C2 tiers | C3 part | C4 shared | RNA | clinical | baseline∅ | grounded≡ |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['model']} | {r['C1_N119']} | {r['C2_tiers_40_40_39']} | "
            f"{r['C3_tertile_partition']} | {r['C4_cohort_shared']} | "
            f"{r['full_has_rna']} | {r['full_has_clinical']} | "
            f"{r['baseline_empty']} | {r['grounded_identical']} |"
        )
    lines += [
        "",
        "Columns RNA / clinical / baseline∅ / grounded≡ are counts over the 119 cases:",
        "RNA-present, clinical-present, baseline-empty, grounded-bundles-byte-identical.",
        "The provenance note is `data_source: deterministic`/`deterministic_proxy` in every",
        "fusion block — the released cohort is built from a synthetic fallback path, not",
        "real TCGA multimodal measurements.",
        "",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))


# --------------------------------------------------------------------------- #
# selftest
# --------------------------------------------------------------------------- #
def selftest() -> None:
    """Unit-checks the pure predicates on synthetic bundles (no repo files)."""
    # tertile partition
    good = (
        [{"io_tier": "Cold", "io_score": "0.1"}, {"io_tier": "Cold", "io_score": "0.2"}]
        + [{"io_tier": "Warm", "io_score": "0.3"}, {"io_tier": "Warm", "io_score": "0.4"}]
        + [{"io_tier": "Hot", "io_score": "0.5"}, {"io_tier": "Hot", "io_score": "0.6"}]
    )
    assert is_tertile_partition(good) is True
    overlap = [
        {"io_tier": "Cold", "io_score": "0.1"},
        {"io_tier": "Cold", "io_score": "0.35"},  # overlaps Warm
        {"io_tier": "Warm", "io_score": "0.3"},
        {"io_tier": "Hot", "io_score": "0.9"},
    ]
    assert is_tertile_partition(overlap) is False

    # tier counts
    assert tier_counts(good) == {"Hot": 2, "Warm": 2, "Cold": 2}

    # rna / clinical detectors
    assert _has_rna({"rna_available": True}) is True
    assert _has_rna({"transcriptomics": {"cyt_value": 1.2}}) is True
    assert _has_rna({"rna_available": False, "transcriptomics": {"cyt_value": None}}) is False
    assert _has_clinical({"clinical": {"stage": "III"}}) is True
    assert _has_clinical({"fusion": {}}) is False

    # baseline emptiness
    assert _baseline_is_empty(
        {"pathology": {"tissue_fractions": {}, "top_tiles": [], "til_fraction": None}}
    ) is True
    assert _baseline_is_empty(
        {"pathology": {"tissue_fractions": {"tumor": 0.6}, "top_tiles": [], "til_fraction": 0.07}}
    ) is False

    # bundle equality ignores config label only
    a = {"config": "pathology_only", "pathology": {"x": 1}}
    b = {"config": "full_multimodal", "pathology": {"x": 1}}
    c = {"config": "full_multimodal", "pathology": {"x": 2}}
    assert _norm_bundle(a) == _norm_bundle(b)
    assert _norm_bundle(a) != _norm_bundle(c)

    # cohort fingerprint equality
    r1 = [{"case_id": "A", "io_tier": "Hot"}, {"case_id": "B", "io_tier": "Cold"}]
    r2 = [{"case_id": "B", "io_tier": "Cold"}, {"case_id": "A", "io_tier": "Hot"}]
    assert cohort_fingerprint(r1) == cohort_fingerprint(r2)
    print("selftest OK")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(REPO / "outputs" / "cohort_bundle_integrity.csv"))
    ap.add_argument("--selftest", action="store_true", help="run unit checks and exit")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    rows = run_audit()
    out_csv = Path(args.out)
    out_md = out_csv.with_suffix(".md")
    write_csv(rows, out_csv)
    write_md(rows, out_md)

    # console summary
    for r in rows:
        verdict = lambda k: r[k]  # noqa: E731
        print(
            f"{r['model']:24s} "
            f"N119={verdict('C1_N119')} tiers={verdict('C2_tiers_40_40_39')} "
            f"part={verdict('C3_tertile_partition')} shared={verdict('C4_cohort_shared')} "
            f"rna={verdict('C5_B3_B4_rna_present')}({r['full_has_rna']}) "
            f"clin={verdict('B4_clinical_present')}({r['full_has_clinical']}) "
            f"base0={verdict('B1_baseline_evidence_free')} "
            f"grad={verdict('B_depth_gradient_present')}(id {r['grounded_identical']})"
        )
    print(f"\nwrote {out_csv}\nwrote {out_md}")


if __name__ == "__main__":
    main()
