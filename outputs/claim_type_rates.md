# Typed-claim unsupported rates — reduction of tab:ctypes / tab:ctypes-rule

Reduces the four committed `claim_review.csv` files to the paper's typed-claim unsupported-rate tables. See the module docstring in `scripts/eval/compute_claim_type_rates.py` for the exact taxonomy (closes REPRODUCIBILITY.md caveat #2).

## Findings

- **tab:ctypes (judge label) reproduces in STRUCTURE, not in level.** The qualitative story holds: baseline confabulation is ordered gpt-5.4-mini < gpt-4o-mini < gemini-2.5-flash < gemini-3-flash-preview, Numeric/Modality-tag dominate, and grounding collapses every rate toward zero. But the absolute baseline levels come out systematically BELOW the paper (e.g. Numeric baseline 0.16/0.01/0.64/0.94 here vs 0.42/0.18/0.81/0.96 in the paper), so the exact cells are not reproduced from the released data.
- **tab:ctypes-rule does NOT reproduce, and cannot.** The rule label (`support_label_auto`) emits `unsupported` on only a handful of rows per run (11/21/33/160 out of thousands; table below), so every rule-based typed unsupported rate is ~0.00 — nowhere near the paper's 0.42–0.96. Yet in `paper_8page_icml.tex` the tab:ctypes-rule tabular is **byte-identical** to the tab:ctypes tabular. The appendix table labelled as the rule-based "conservative limit" is a duplicate of the judge table, not a rule-label reduction. This contradicts the paper's own §7 statement that the rule-based `u_b` is "artifactually compressed" — a genuine rule reduction would be near zero, as computed here, not equal to the judge numbers.
- **Some paper cells have no support in the released data.** `Tier` claims are absent for gpt-4o-mini (n=0, standard prompt) and for the grounded `full_multimodal` config across ALL four runs (n=0), so the paper's Tier rows cannot be derived from these files. Grounded `Other` denominators are tiny (6–109 claims), making those cells degenerate/noisy (e.g. 1.00 on 6 claims for gpt-5.4-mini) rather than the paper's smooth 0.02–0.37.


## Table tab:ctypes — agreement-gated JUDGE label (conflict-excluded)

Reproduced from `llm_judge_final`.


### Ungrounded baseline

| Claim type | 4o-m | 5.4-m | 2.5-f | 3-fp | (paper) 4o-m 5.4-m 2.5-f 3-fp |
|---|---|---|---|---|---|
| Numeric | 0.16 | 0.01 | 0.64 | 0.94 | 0.42 0.18 0.81 0.96 |
| Modality-tag | 0.20 | 0.07 | 0.75 | 0.92 | 0.11 0.04 0.58 0.89 |
| Tier |   -   | 0.00 | 0.43 | 0.88 | 0.24 0.07 0.71 0.93 |
| Uncertainty |   -   | 0.00 | 0.20 | 0.39 | 0.01 0.00 0.04 0.07 |
| Literature |   -   |   -   | 0.50 | 0.30 | 0.03 0.02 0.31 0.42 |
| Other | 0.03 | 0.02 | 0.53 | 0.93 | 0.15 0.05 0.48 0.84 |

### Grounded (full_multimodal)

| Claim type | 4o-m | 5.4-m | 2.5-f | 3-fp | (paper) 4o-m 5.4-m 2.5-f 3-fp |
|---|---|---|---|---|---|
| Numeric | 0.00 | 0.01 | 0.05 | 0.19 | 0.00 0.03 0.04 0.11 |
| Modality-tag | 0.00 | 0.01 | 0.06 | 0.18 | 0.00 0.01 0.02 0.08 |
| Tier |   -   |   -   |   -   |   -   | 0.00 0.01 0.01 0.03 |
| Uncertainty | 0.00 | 0.05 | 0.00 | 0.01 | 0.00 0.00 0.00 0.00 |
| Literature |   -   |   -   |   -   | 0.00 | 0.00 0.00 0.01 0.02 |
| Other | 0.00 | 1.00 | 0.77 | 0.00 | 0.02 0.12 0.09 0.37 |

## Table tab:ctypes-rule — rule-based AUTO label (`support_label_auto`)

Reproduced from `support_label_auto`.


### Ungrounded baseline

| Claim type | 4o-m | 5.4-m | 2.5-f | 3-fp | (paper) 4o-m 5.4-m 2.5-f 3-fp |
|---|---|---|---|---|---|
| Numeric | 0.00 | 0.00 | 0.00 | 0.00 | 0.42 0.18 0.81 0.96 |
| Modality-tag | 0.00 | 0.00 | 0.01 | 0.01 | 0.11 0.04 0.58 0.89 |
| Tier |   -   | 0.00 | 0.00 | 0.00 | 0.24 0.07 0.71 0.93 |
| Uncertainty |   -   | 0.00 | 0.00 | 0.00 | 0.01 0.00 0.04 0.07 |
| Literature |   -   |   -   | 1.00 | 1.00 | 0.03 0.02 0.31 0.42 |
| Other | 0.00 | 0.00 | 0.00 | 0.00 | 0.15 0.05 0.48 0.84 |

### Grounded (full_multimodal)

| Claim type | 4o-m | 5.4-m | 2.5-f | 3-fp | (paper) 4o-m 5.4-m 2.5-f 3-fp |
|---|---|---|---|---|---|
| Numeric | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 0.03 0.04 0.11 |
| Modality-tag | 0.00 | 0.00 | 0.00 | 0.04 | 0.00 0.01 0.02 0.08 |
| Tier |   -   |   -   |   -   |   -   | 0.00 0.01 0.01 0.03 |
| Uncertainty | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 0.00 0.00 0.00 |
| Literature | 1.00 |   -   |   -   | 1.00 | 0.00 0.00 0.01 0.02 |
| Other | 0.00 | 0.00 | 0.00 | 0.00 | 0.02 0.12 0.09 0.37 |

## Denominators (per type, `full_multimodal` + `baseline`, standard prompt)

| Run | config | Numeric n | Modality-tag n | Tier n | Uncertainty n | Literature n | Other n |
|---|---|---|---|---|---|---|---|
| 4o-m | baseline | 341 | 589 | 0 | 0 | 0 | 217 |
| 4o-m | full_multimodal | 334 | 488 | 0 | 104 | 1 | 7 |
| 5.4-m | baseline | 204 | 461 | 6 | 18 | 0 | 130 |
| 5.4-m | full_multimodal | 395 | 261 | 0 | 406 | 0 | 6 |
| 2.5-f | baseline | 544 | 691 | 55 | 16 | 4 | 517 |
| 2.5-f | full_multimodal | 604 | 614 | 0 | 313 | 0 | 13 |
| 3-fp | baseline | 1015 | 1061 | 123 | 24 | 10 | 403 |
| 3-fp | full_multimodal | 816 | 941 | 0 | 193 | 37 | 109 |

## Why tab:ctypes-rule cannot match the paper

The rule checker almost never emits `unsupported` (it routes boundary cases to `partial`/`unknown`; paper §7). Below is the total count of rows the rule label calls `unsupported`, over ALL rows in each run:

| Run | rule `unsupported` rows | total rows |
|---|---|---|
| 4o-m | 11 | 2640 |
| 5.4-m | 21 | 2720 |
| 2.5-f | 33 | 4129 |
| 3-fp | 160 | 5415 |
