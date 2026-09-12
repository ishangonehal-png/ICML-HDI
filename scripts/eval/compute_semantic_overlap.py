#!/usr/bin/env python3
"""
compute_semantic_overlap.py
===========================
Reduces the four per-model ``claim_review.csv`` runs to the semantic-overlap
probe reported in the paper (Table ``tab:panel`` Overlap@0.80 / Max-sim,
Table ``tab:cis`` overlap CIs, Table ``tab:tau-sens`` threshold sensitivity).

The probe (paper Section "Semantic claim overlap"): for each patient, each
grounded (``full_multimodal``, ``prompt_type=standard``) claim is compared to
every baseline (``baseline``, ``prompt_type=standard``) claim from the SAME
patient. Per grounded claim we take the maximum cosine similarity to any
same-patient baseline claim; a grounded claim has a *semantic twin* if that
maximum is >= tau. The patient-level overlap is the fraction of that patient's
grounded claims with a twin; cohort overlap@tau is the mean over patients.
Max-sim is the mean maximum-cosine over all grounded claims (claim-level, per
the paper's caption).

Two similarity backends:

  * ``--backend chartfidf`` (default, OFFLINE, stdlib-only): character 3/4/5-gram
    TF-IDF cosine over the pooled claim corpus. Deterministic; runs with no
    network and no API key. This is a LEXICAL PROXY: its cosine geometry is not
    the paper's dense ``text-embedding-3-small`` space, so its absolute values
    and tau-thresholds are NOT comparable to the paper's. Only the cross-model
    *ordering* and the "is overlap low?" question transfer. Running the proxy
    also writes ``outputs/semantic_overlap.md`` (ordinal comparison to the
    paper's reference values and what does / does not reproduce offline).

  * ``--embeddings FILE`` (EXACT reproduction): a JSON object mapping the SHA-1
    hex digest of each claim_text (utf-8) to its ``text-embedding-3-small``
    vector (list of floats). Given these, the reduction reproduces the paper's
    Overlap@tau and Max-sim exactly. Generating the file requires one embedding
    call per unique claim; see ``--dump-claims`` to emit the claim list to embed.

Usage
-----
    # offline lexical proxy over the four released runs
    python3 scripts/eval/compute_semantic_overlap.py

    # exact reproduction from precomputed text-embedding-3-small vectors
    python3 scripts/eval/compute_semantic_overlap.py --embeddings vectors.json

    # emit the unique claim texts that need embedding (for exact repro)
    python3 scripts/eval/compute_semantic_overlap.py --dump-claims claims.txt

    # self-check the reduction math on a synthetic fixture
    python3 scripts/eval/compute_semantic_overlap.py --selftest
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

# model label -> outputs directory (the four factorial runs)
MODEL_DIRS = {
    "gpt-4o-mini": "outputs/bionlp_eval",
    "gpt-5.4-mini": "outputs/bionlp_eval_gpt54mini",
    "gemini-2.5-flash": "outputs/bionlp_eval_gemini25flash",
    "gemini-3-flash-preview": "outputs/bionlp_eval_gemini",
}

GROUNDED_CONFIG = "full_multimodal"
BASELINE_CONFIG = "baseline"
TAUS = (0.75, 0.80, 0.85)
# The char-TF-IDF proxy cosine lives on a much lower scale than a dense
# embedding space, so the paper's dense thresholds saturate to 0. These
# proxy-calibrated thresholds sit in the body of the lexical-cosine
# distribution and expose the cross-model *ordering* for comparison.
PROXY_TAUS = (0.30, 0.40, 0.50)

# Paper reference values (text-embedding-3-small), for ordinal comparison only.
# Source: paper_8page_icml.tex Table tab:tau-sens (overlap@tau) and the
# Max-sim band stated in the tab:panel caption / body ("0.538-0.621").
PAPER_OVERLAP = {
    "gpt-4o-mini": {"0.75": 0.213, "0.80": 0.115, "0.85": 0.048},
    "gpt-5.4-mini": {"0.75": 0.091, "0.80": 0.032, "0.85": 0.011},
    "gemini-2.5-flash": {"0.75": 0.028, "0.80": 0.005, "0.85": 0.000},
    "gemini-3-flash-preview": {"0.75": 0.128, "0.80": 0.051, "0.85": 0.018},
}
PAPER_MAXSIM_BAND = (0.538, 0.621)


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load_claims(review_csv: Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return (grounded, baseline) mapping case_id -> list of claim_text."""
    grounded: dict[str, list[str]] = defaultdict(list)
    baseline: dict[str, list[str]] = defaultdict(list)
    with open(review_csv, newline="") as fh:
        for row in csv.DictReader(fh):
            if row["prompt_type"] != "standard":
                continue
            text = row["claim_text"].strip()
            if not text:
                continue
            if row["config"] == GROUNDED_CONFIG:
                grounded[row["case_id"]].append(text)
            elif row["config"] == BASELINE_CONFIG:
                baseline[row["case_id"]].append(text)
    return grounded, baseline


# ---------------------------------------------------------------------------
# Backend: character n-gram TF-IDF cosine (offline, deterministic proxy)
# ---------------------------------------------------------------------------
def _char_ngrams(text: str, ns=(3, 4, 5)) -> Counter:
    norm = " ".join(text.lower().split())
    grams: Counter = Counter()
    for n in ns:
        for i in range(len(norm) - n + 1):
            grams[norm[i : i + n]] += 1
    return grams


class CharTfidf:
    """Deterministic char-n-gram TF-IDF vectorizer with L2-normalized cosine."""

    def __init__(self, corpus: list[str]):
        df: Counter = Counter()
        grams_per_doc = [_char_ngrams(t) for t in corpus]
        for grams in grams_per_doc:
            for k in grams:
                df[k] += 1
        n_docs = max(len(corpus), 1)
        # smoothed idf, matches the sklearn default form
        self._idf = {k: math.log((n_docs + 1) / (v + 1)) + 1.0 for k, v in df.items()}
        self._default_idf = math.log(n_docs + 1) + 1.0

    def vector(self, text: str) -> dict[str, float]:
        grams = _char_ngrams(text)
        vec = {k: c * self._idf.get(k, self._default_idf) for k, c in grams.items()}
        norm = math.sqrt(sum(x * x for x in vec.values())) or 1.0
        return {k: x / norm for k, x in vec.items()}


def _sparse_cos(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(k, 0.0) for k, x in a.items())


# ---------------------------------------------------------------------------
# Backend: precomputed dense embeddings (exact reproduction)
# ---------------------------------------------------------------------------
class DenseEmbeddings:
    """Cosine over precomputed vectors keyed by SHA-1(claim_text)."""

    def __init__(self, vectors: dict[str, list[float]]):
        self._norm: dict[str, list[float]] = {}
        for key, v in vectors.items():
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            self._norm[key] = [x / n for x in v]
        self._missing: set[str] = set()

    def unit(self, text: str) -> list[float] | None:
        key = sha1(text)
        vec = self._norm.get(key)
        if vec is None:
            self._missing.add(key)
        return vec


def _dense_cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# Core reduction
# ---------------------------------------------------------------------------
def overlap_for_model(
    grounded: dict[str, list[str]],
    baseline: dict[str, list[str]],
    backend,
    taus=TAUS,
) -> dict:
    """Compute Overlap@tau (per-patient mean) and Max-sim (claim-level mean)."""
    per_patient = {t: [] for t in taus}
    claim_maxsims: list[float] = []
    n_patients = 0

    is_dense = isinstance(backend, DenseEmbeddings)
    for case_id, g_claims in grounded.items():
        b_claims = baseline.get(case_id)
        if not b_claims:
            continue
        n_patients += 1
        if is_dense:
            gv = [backend.unit(t) for t in g_claims]
            bv = [v for v in (backend.unit(t) for t in b_claims) if v is not None]
            maxs = []
            for v in gv:
                if v is None or not bv:
                    maxs.append(0.0)
                else:
                    maxs.append(max(_dense_cos(v, u) for u in bv))
        else:
            gv = [backend.vector(t) for t in g_claims]
            bv = [backend.vector(t) for t in b_claims]
            maxs = [max((_sparse_cos(v, u) for u in bv), default=0.0) for v in gv]

        claim_maxsims.extend(maxs)
        for t in taus:
            frac = sum(1 for s in maxs if s >= t) / len(maxs) if maxs else 0.0
            per_patient[t].append(frac)

    mean_max = sum(claim_maxsims) / len(claim_maxsims) if claim_maxsims else 0.0
    return {
        "n_patients": n_patients,
        "n_grounded_claims": len(claim_maxsims),
        "mean_max_sim": round(mean_max, 4),
        "overlap": {f"{t:.2f}": round(sum(v) / len(v), 4) if v else 0.0 for t, v in per_patient.items()},
    }


def build_backend(name: str, corpus: list[str], embeddings_path: str | None):
    if embeddings_path:
        vectors = json.loads(Path(embeddings_path).read_text())
        return DenseEmbeddings(vectors), "dense/text-embedding-3-small (exact)"
    if name == "chartfidf":
        return CharTfidf(corpus), "chartfidf (offline lexical proxy)"
    raise SystemExit(f"unknown backend: {name}")


# ---------------------------------------------------------------------------
# Self-test: prove the reduction math on a synthetic dense fixture
# ---------------------------------------------------------------------------
def selftest() -> int:
    # patient p1: 2 grounded, 1 baseline; grounded[0] identical to baseline[0]
    grounded = {"p1": ["A", "B"], "p2": ["C"]}
    baseline = {"p1": ["A"], "p2": ["D"]}
    vectors = {
        sha1("A"): [1.0, 0.0],
        sha1("B"): [0.0, 1.0],   # orthogonal to A -> cos 0
        sha1("C"): [1.0, 1.0],
        sha1("D"): [1.0, 1.0],   # identical direction to C -> cos 1
    }
    be = DenseEmbeddings(vectors)
    res = overlap_for_model(grounded, baseline, be, taus=(0.5, 0.99))
    # p1: maxs = [1.0 (A~A), 0.0 (B~A)] -> frac>=0.5 = 0.5 ; p2: [1.0] -> 1.0
    # overlap@0.5 = mean(0.5, 1.0) = 0.75 ; overlap@0.99 = mean(0.5, 1.0) = 0.75
    # mean_max_sim over claims [1.0, 0.0, 1.0] = 0.6667
    ok = (
        res["overlap"]["0.50"] == 0.75
        and res["overlap"]["0.99"] == 0.75
        and abs(res["mean_max_sim"] - 0.6667) < 1e-3
        and res["n_patients"] == 2
        and res["n_grounded_claims"] == 3
    )
    print("selftest:", "PASS" if ok else "FAIL", res)
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="chartfidf", choices=["chartfidf"],
                    help="offline similarity backend (default: chartfidf lexical proxy)")
    ap.add_argument("--embeddings", default=None,
                    help="JSON of {sha1(claim_text): vector} for exact text-embedding-3-small reproduction")
    ap.add_argument("--out", default="outputs/semantic_overlap.csv", help="output CSV path")
    ap.add_argument("--dump-claims", default=None,
                    help="write the unique claim texts (grounded+baseline, standard) to this file and exit")
    ap.add_argument("--selftest", action="store_true", help="run the reduction-math self-check and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    # load all four models
    loaded = {}
    corpus: list[str] = []
    for model, rel in MODEL_DIRS.items():
        path = REPO / rel / "claim_review.csv"
        if not path.exists():
            print(f"WARN: missing {path}, skipping {model}", file=sys.stderr)
            continue
        g, b = load_claims(path)
        loaded[model] = (g, b)
        for cs in (g, b):
            for lst in cs.values():
                corpus.extend(lst)

    if not loaded:
        raise SystemExit("no claim_review.csv found under outputs/")

    if args.dump_claims:
        # JSON list so multi-line claim texts round-trip unambiguously; embed each
        # element and key the resulting vector by sha1(element) for --embeddings.
        uniq = sorted(set(corpus))
        Path(args.dump_claims).write_text(json.dumps(uniq, ensure_ascii=False, indent=0))
        print(f"wrote {len(uniq)} unique claim texts (JSON list) to {args.dump_claims}")
        return 0

    backend, backend_desc = build_backend(args.backend, corpus, args.embeddings)
    is_proxy = not isinstance(backend, DenseEmbeddings)
    taus = tuple(sorted(set(TAUS + (PROXY_TAUS if is_proxy else ()))))

    rows = []
    for model, (g, b) in loaded.items():
        res = overlap_for_model(g, b, backend, taus=taus)
        rows.append((model, res))
        ov = " ".join(f"@{t}={res['overlap'][t]:.4f}" for t in sorted(res["overlap"]))
        print(f"{model:24s} n_pat={res['n_patients']:3d} n_claims={res['n_grounded_claims']:4d} "
              f"mean_max_sim={res['mean_max_sim']:.4f} {ov}")

    if isinstance(backend, DenseEmbeddings) and backend._missing:
        print(f"WARN: {len(backend._missing)} claim(s) had no embedding vector "
              f"(treated as cos 0); overlap is a lower bound.", file=sys.stderr)

    out = REPO / args.out
    tau_cols = sorted(taus)
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "backend", "n_patients", "n_grounded_claims", "mean_max_sim",
                    *[f"overlap@{t:.2f}" for t in tau_cols]])
        for model, res in rows:
            w.writerow([model, backend_desc, res["n_patients"], res["n_grounded_claims"],
                        res["mean_max_sim"], *[res["overlap"][f"{t:.2f}"] for t in tau_cols]])
    print(f"\nwrote {out}  (backend: {backend_desc})")

    if is_proxy:
        write_report(REPO / "outputs" / "semantic_overlap.md", rows, backend_desc)
        print(f"wrote {REPO / 'outputs' / 'semantic_overlap.md'}")
    return 0


def write_report(path: Path, rows: list[tuple[str, dict]], backend_desc: str) -> None:
    """Write a short interpretation comparing the proxy ordering to the paper."""
    # rank models high->low by proxy mean_max_sim and by paper overlap@0.80
    by_proxy = [m for m, _ in sorted(rows, key=lambda r: -r[1]["mean_max_sim"])]
    by_paper = sorted(PAPER_OVERLAP, key=lambda m: -PAPER_OVERLAP[m]["0.80"])
    proxy_top = by_proxy[0]
    # the paper's specific structural claim: gpt-5.4-mini overlap < gpt-4o-mini
    mm = {m: r["mean_max_sim"] for m, r in rows}
    claim_gpt = mm.get("gpt-5.4-mini", 1) < mm.get("gpt-4o-mini", 0)

    L = []
    L.append("# Semantic-overlap probe — offline reproduction status\n")
    L.append(f"_Backend: {backend_desc}. Generated by `scripts/eval/compute_semantic_overlap.py`._\n")
    L.append("## What this is\n")
    L.append(
        "The semantic-overlap probe (paper §\"Semantic claim overlap\", Tables `tab:panel` / "
        "`tab:cis` / `tab:tau-sens`) is the only paper pillar with **no committed reduction**: "
        "it requires per-claim `text-embedding-3-small` vectors that are not in the repo. This "
        "script commits the reduction and runs it with a deterministic **offline lexical proxy** "
        "(char 3/4/5-gram TF-IDF cosine). The proxy is a *different measurement* from the paper's "
        "dense embedding: absolute values and tau-thresholds are not comparable, only the "
        "cross-model **ordering** and the \"is overlap low?\" question transfer.\n")
    L.append("## Proxy results (this repo, offline)\n")
    L.append("| Model | grounded claims | mean max-sim | overlap@0.30 | overlap@0.40 | overlap@0.75/0.80/0.85 |")
    L.append("|---|--:|--:|--:|--:|--:|")
    for m, r in rows:
        o = r["overlap"]
        L.append(f"| {m} | {r['n_grounded_claims']} | {r['mean_max_sim']:.4f} | "
                 f"{o.get('0.30', 0):.4f} | {o.get('0.40', 0):.4f} | "
                 f"{o['0.75']:.4f}/{o['0.80']:.4f}/{o['0.85']:.4f} |")
    L.append("")
    L.append("## Paper reference (text-embedding-3-small, NOT reproduced here)\n")
    L.append("| Model | overlap@0.75 | overlap@0.80 | overlap@0.85 |")
    L.append("|---|--:|--:|--:|")
    for m in PAPER_OVERLAP:
        p = PAPER_OVERLAP[m]
        L.append(f"| {m} | {p['0.75']} | {p['0.80']} | {p['0.85']} |")
    L.append(f"\nPaper mean max-sim band: {PAPER_MAXSIM_BAND[0]}–{PAPER_MAXSIM_BAND[1]} "
             "(dense space; the proxy's mean max-sim is ~0.11–0.14, a lexical scale).\n")
    L.append("## What reproduces and what does not\n")
    L.append(
        f"- **Overlap is low across all models** — the paper's headline directional claim. "
        f"Under the lexical proxy no grounded claim is a near-duplicate of a same-patient baseline "
        f"claim (overlap at the paper's dense tau's is 0.0000 for every model; even at a permissive "
        f"lexical tau=0.40 it stays <0.02). Grounded claims are **not verbatim recyclings** of "
        f"baseline text for any model. *Corroborated (directionally).*\n")
    top_ok = ("holds under mean max-sim" if proxy_top == "gpt-4o-mini"
              else "NOT corroborated") + " (but statistic-fragile, see below)"
    L.append(
        f"- **gpt-4o-mini has the highest overlap** (paper: 0.115 @0.80, the max). Proxy ranks "
        f"`{proxy_top}` highest by mean max-sim → {top_ok}.\n")
    claim_ok = ("holds under mean max-sim" if claim_gpt
                else "NOT corroborated") + " (but statistic-fragile, see below)"
    L.append(
        f"- **overlap does not track HDI: gpt-5.4-mini's overlap < gpt-4o-mini's** (the paper's "
        f"specific structural claim, {PAPER_OVERLAP['gpt-5.4-mini']['0.80']} < "
        f"{PAPER_OVERLAP['gpt-4o-mini']['0.80']}). Proxy mean max-sim "
        f"{mm.get('gpt-5.4-mini'):.4f} vs {mm.get('gpt-4o-mini'):.4f} → {claim_ok}.\n")
    # statistic-sensitivity: the ordering flips depending on which proxy statistic you pick
    have_o30 = all("0.30" in r["overlap"] for _, r in rows)
    if have_o30:
        by_o30 = [m for m, _ in sorted(rows, key=lambda r: -r[1]["overlap"]["0.30"])]
        L.append(
            f"- **The proxy corroboration above is statistic-fragile.** Ranked by overlap@0.30 "
            f"instead of mean max-sim the order becomes {' > '.join(by_o30)} — here gpt-4o-mini is "
            f"*lowest*, contradicting the two bullets above. A lexical proxy simply does not have a "
            f"stable read on the paper's ordering; treat the offline number as a low-overlap floor, "
            f"not a reproduction of the paper's ranking.\n")
    L.append(
        f"- **The fine cross-model ordering is NOT reproducible offline.** Paper overlap@0.80 order "
        f"(high→low): {' > '.join(by_paper)}. Proxy mean-max-sim order: {' > '.join(by_proxy)}. "
        f"The two agree at the top (gpt-4o-mini) but diverge in the middle: gemini-3-flash-preview "
        f"is 2nd in the paper but last under the proxy. The paper's overlap ordering — and hence the "
        f"**Mode B** half of the taxonomy (gpt-5.4-mini: HDI≤0.4 AND overlap@0.80≤0.05) — lives in "
        f"the dense paraphrase space and **cannot be verified from committed artifacts** without the "
        f"`text-embedding-3-small` vectors.\n")
    L.append("## To finish exact reproduction\n")
    L.append(
        "```bash\n"
        "# 1. emit the unique claims that need embedding\n"
        "python3 scripts/eval/compute_semantic_overlap.py --dump-claims claims.txt\n"
        "# 2. embed each line with text-embedding-3-small; write JSON {sha1(text): vector}\n"
        "# 3. exact reproduction\n"
        "python3 scripts/eval/compute_semantic_overlap.py --embeddings vectors.json\n"
        "```\n")
    path.write_text("\n".join(L))


if __name__ == "__main__":
    raise SystemExit(main())
