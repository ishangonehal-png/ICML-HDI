# Numeric-fidelity grounding probe (tab:secondary)

Re-derivation of the Table 5 numeric-fidelity column directly from the
committed `claim_review.csv` + `evidence_bundles/*.json`. The shipped metric
pools ungrounded-baseline claims (empty bundle by construction -> never
matchable) and counts a sentence "correct" when only *some* of its numerics
match. Both contradict the caption ("fraction of claims ... for which the
value matches the bundle within +/-0.01"). Columns:

- **shipped** = pooled standard, lenient (== metrics.json == paper)
- **grounded** = non-baseline configs only, lenient
- **strict** = pooled standard, *all* numerics must match
- **strict_grnd** = non-baseline + all numerics match (caption-faithful)

| Model | #num | #base | paper | shipped | grounded | strict | strict_grnd |
|---|---:|---:|---:|---:|---:|---:|---:|
| gpt-4o-mini | 1327 | 341 | 0.381 | 0.381 | 0.512 | 0.188 | 0.254 |
| gpt-5.4-mini | 1396 | 204 | 0.632 | 0.632 | 0.740 | 0.370 | 0.434 |
| gemini-2.5-flash | 2329 | 544 | 0.578 | 0.578 | 0.754 | 0.367 | 0.479 |
| gemini-3-flash-preview | 3481 | 1015 | 0.455 | 0.455 | 0.642 | 0.193 | 0.273 |

Re-derivation reproduces the paper's four values: **True** (label-level mismatches vs shipped claim_review: **0**).

## What shifts

**Baseline pooling.** The `baseline` bundle is empty, so all baseline numeric
claims are forced to `incorrect`; they are pure denominator ballast whose count
varies ~5x across models:

- gpt-4o-mini: 341 baseline numeric claims forced to failure; shipped 0.381 -> grounded 0.512.
- gpt-5.4-mini: 204 baseline numeric claims forced to failure; shipped 0.632 -> grounded 0.740.
- gemini-2.5-flash: 544 baseline numeric claims forced to failure; shipped 0.578 -> grounded 0.754.
- gemini-3-flash-preview: 1015 baseline numeric claims forced to failure; shipped 0.455 -> grounded 0.642.

**Leniency.** Share of `correct` labels reached via the "Most numerics match"
branch (>=1 fabricated numeric still present):

- gpt-4o-mini: 255/505 (50%) of correct labels have an unmatched numeric.
- gpt-5.4-mini: 365/882 (41%) of correct labels have an unmatched numeric.
- gemini-2.5-flash: 491/1346 (36%) of correct labels have an unmatched numeric.
- gemini-3-flash-preview: 910/1583 (57%) of correct labels have an unmatched numeric.

## Paper trends under each definition

| Within-provider trend | shipped | grounded | strict_grnd |
|---|---:|---:|---:|
| OpenAI 4o-mini -> 5.4-mini | +0.251 | +0.228 | +0.180 |
| Google 2.5-flash -> 3-flash-preview | -0.123 | -0.112 | -0.206 |

The two corrections pull in opposite directions. Dropping the empty-bundle
baseline claims *raises* the rate (grounded > shipped); requiring all numerics
to match *lowers* it (strict < lenient). Leniency dominates: the caption-faithful
rate (strict_grnd, grounded + every numeric matches) is substantially *below*
the printed numbers for all four models (0.254/0.434/0.479/0.273 vs printed
0.381/0.632/0.578/0.455), because ~36-57% of "correct" labels tolerate a
fabricated numeric. The within-provider trends survive in *direction* under
every definition, but the magnitudes move: the Google regression *grows* under
strict_grnd (-0.123 -> -0.206) while the OpenAI gain *shrinks* (+0.251 ->
+0.180), so neither the sign of the story nor its size is definition-invariant.
Caption tolerance is +/-0.01; code uses +/-0.02 (and integer <1).

