# Reproducibility — Hallucination Dependence Index Paper

This document describes how to reproduce the headline numbers from the ICML 2026 paper *"The Hallucination Dependence Index: A Cross-Condition Diagnostic for Clinical-LLM Faithfulness"* (8-page version) and the FM4LS short-paper version.

## Released artifacts

| Path | Purpose |
|---|---|
| `paper_8page_icml.tex` / `.pdf` | Long-paper submission (GenBio) |
| `paper_4page_icml.tex` / `.pdf` | Short-paper submission (FM4LS) |
| `paper_draft_v2.tex` | Earlier ACL-style draft (kept for diff history) |
| `icml2026/` | ICML 2026 LaTeX style files (downloaded from `media.icml.cc`) |
| `custom.bib` | Bibliography |
| `outputs/bionlp_eval/` | gpt-4o-mini run (April 2026) |
| `outputs/bionlp_eval_gpt54mini/` | gpt-5.4-mini run |
| `outputs/bionlp_eval_gemini25flash/` | gemini-2.5-flash run |
| `outputs/bionlp_eval_gemini/` | gemini-3-flash-preview run |
| `outputs/bionlp_eval_n20_backup/` | Pilot 20-case run (development) |
| `adjudication_input.csv` | 300 stratified claims for the human anchor |
| `adjudication_key.csv` | Two-expert consensus labels |
| `adjudication_output.csv` | Per-claim audit trail |
| `scripts/eval/` | Evaluation harness (`run_bionlp_eval.py`, `compute_bionlp_metrics.py`, `compute_claim_type_breakdown.py`, `llm_judge.py`, etc.) |
| `outputs/claim_type_unsupported_rates.csv` | Per-claim-type unsupported rates (committed Table 7 reduction; see caveat 2) |
| `apps/api/` | Provider-agnostic chat layer + tooling stack (FastAPI service) |

## Headline-number provenance

Every numeric headline in the paper traces to one of the per-model `outputs/bionlp_eval_*/` directories. The reduction from raw labels to paper figures is:

- **Table 1 / Table 2 (factorial)** — `metrics.json` → `baseline_comparison` block, which calls `scripts/eval/compute_bionlp_metrics.py:compute_baseline_vs_grounded()` over the `llm_judge_final` column with `prompt_type=standard` and `conflict` rows excluded.
- **Table 3 (diagnostic panel HDI / Δu / overlap@0.80 / max-sim)** — HDI = `(u_b - u_g) / u_b` where $u_b$, $u_g$ come from the same `baseline_comparison` reduction; overlap from `scripts/eval/embedding_overlap.py` over OpenAI `text-embedding-3-small`.
- **Table 4 (patient-paired bootstrap CIs)** — 2000-resample paired bootstrap, seed 42; computed per the script in this repo (a reviewer-supplied snippet using `numpy` / `scipy.stats` over the four `claim_review.csv` files).
- **Table 5 (secondary metrics: numeric fidelity, modality attribution, retrieval discipline, completeness)** — `metrics.json` `secondary_metrics` block.
- **Table 6 (depth-of-grounding ablation)** — `metrics.json` `completeness_by_config` × per-config supported-claim aggregation.
- **Table 7 (per-claim-type unsupported rates)** — a committed best-effort reduction now lives in `scripts/eval/compute_claim_type_breakdown.py` (writes `outputs/claim_type_unsupported_rates.csv`), mapping the paper's six-class typed-claim taxonomy (`numeric/modality-tag/tier/uncertainty/literature/other`) onto the modality-based `claim_type` column in `claim_review.csv` (`pathology/RNA/clinical/fusion/tier/uncertainty/literature/other`; `numeric` recovered from `numeric_fidelity_auto`). **This reduction does not reproduce Table 7's printed values** (see caveat 2): the released CSVs preserve the qualitative structure but 11 of 48 printed cells have no corresponding claims in the CSV, and the mean absolute deviation on the fillable cells is 0.13. Table 7's exact numbers were produced by an out-of-tree tagger that is not released.
- **κ values (Table tab:agreement, κ=0.71 inter-annotator)** — computed from `adjudication_input.csv` + `adjudication_key.csv` + the four per-model `claim_review.csv` files via `adjudicate.py`.

## Hard pins (April 2026 runs)

| Component | Pin |
|---|---|
| Generator | `gpt-4o-mini-2024-07-18`, `gpt-5.4-mini-2026-03-19`, `gemini-2.5-flash-002`, `gemini-3-flash-preview-0417` |
| Judge | `gpt-4.1-mini-2025-04-14` |
| Embeddings | `text-embedding-3-small` |
| Generator decoding | `T=0.2`, `top_p=1.0`, `max_tokens=800` |
| Judge decoding | `T=0`, `max_tokens=200` |
| Per-request timeout | 120s on both providers |
| Retry policy | Exponential backoff on HTTP 429, 5xx, ConnectionError, ReadTimeout; 3 attempts |
| Cohort seed | Fixed in `scripts/cohort/select_cohort.py` |
| Bootstrap seed | 42 |

Provider-side sampling at `T=0.2` is not deterministic across providers; per-call variance is not reported. Re-running the harness on the pinned model versions reproduces cohort-level numbers within bootstrap CI width.

## Quick-start: regenerate the headline numbers

```bash
# 1. Set API keys (the harness reads these from env)
export OPENAI_API_KEY="sk-..."
export GOOGLE_API_KEY="..."

# 2. Install dependencies
pip install -r requirements-ci.txt

# 3. Per-model harness run (each takes ~42 minutes wall clock)
python3 scripts/eval/run_bionlp_eval.py --model gpt-4o-mini --output-dir outputs/bionlp_eval/
python3 scripts/eval/run_bionlp_eval.py --model gpt-5.4-mini --output-dir outputs/bionlp_eval_gpt54mini/
python3 scripts/eval/run_bionlp_eval.py --model gemini-2.5-flash --output-dir outputs/bionlp_eval_gemini25flash/
python3 scripts/eval/run_bionlp_eval.py --model gemini-3-flash-preview --output-dir outputs/bionlp_eval_gemini/

# 4. Compute paper metrics from the four runs
python3 scripts/eval/compute_bionlp_metrics.py outputs/bionlp_eval/
python3 scripts/eval/compute_bionlp_metrics.py outputs/bionlp_eval_gpt54mini/
python3 scripts/eval/compute_bionlp_metrics.py outputs/bionlp_eval_gemini25flash/
python3 scripts/eval/compute_bionlp_metrics.py outputs/bionlp_eval_gemini/

# 5. (Optional) re-derive the per-claim-type breakdown (Table 7) from the four runs
#    and print the reproducibility comparison against the paper's printed values
python3 scripts/eval/compute_claim_type_breakdown.py

# 6. (Optional) re-validate the human anchor
python3 adjudicate.py
```

The released `outputs/*/metrics.json` already contain the values used in the paper, so a reviewer can skip steps 1–4 and verify the numbers directly. Steps 1–4 are needed only to regenerate the data on different model versions or to extend the factorial.

## Approximate runtime and cost (April 2026 list price)

- ~42 minutes wall-clock per model on a single-core client (network-bound)
- ~8.4M prompt tokens + 2.1M completion tokens across the 2×2 factorial
- Judge adds ~1.9M prompt tokens + 0.4M completion tokens
- ~USD 41–58 per full 2×2 factorial run depending on provider mix

## Known caveats for reviewers

1. The headline numbers in Table 1 / Table 2 come from the `llm_judge_final` column with `conflict` rows excluded (the harness's `baseline_comparison` reduction), not from the rule-based `support_label_auto` column directly. The paper documents this in §3.4.
2. **Table 7 is not reproducible from the released artifacts.** `scripts/eval/compute_claim_type_breakdown.py` commits a documented mapping from the paper's six-class typed-claim taxonomy onto the modality-based `claim_type` column of `claim_review.csv`, but running it does *not* recover the printed Table 7 values. Concretely: (a) the released `claim_type` column has no `numeric` class and its `tier` claims appear only in the `baseline` config, so 11 of the 48 Table 7 cells — including the entire grounded `Tier` row and every 4o-m/5.4-m `Literature`/`Tier` cell the paper prints — correspond to *zero* claims in the CSV; (b) on the 37 cells the CSV can fill, the committed judge-label reduction deviates from the paper by a mean of 0.13 (max 0.88), preserving only the qualitative ordering (numeric/modality-tag dominate ungrounded confabulation; grounded residual concentrates in `other`). Table 7's exact numbers came from an out-of-tree tagger that is not in this repo. Additionally, the Appendix C rule-based table (`tab:ctypes-rule`) is byte-identical to the judge-label Table 7 (`tab:ctypes`) despite both captions asserting a different label basis; the actual rule-based reduction over `support_label_auto` yields near-zero unsupported rates everywhere (the checker reserves `unsupported` for direct numeric mismatches), so neither table matches the released rule-based labels.
3. `gemini-3-flash-preview` is a preview endpoint; the within-Google generational divergence in §6.2 is a snapshot observation and is hedged accordingly.
4. The two-expert human anchor was provided by computational biologists with oncology-informatics training, not board-certified oncologists. The κ=0.64 / κ=0.71 numbers calibrate the judge but do not constitute a clinical-safety audit.
