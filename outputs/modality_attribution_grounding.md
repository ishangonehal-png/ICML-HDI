# Modality-attribution probe: tag self-agreement vs. evidence presence

Re-derivation of the `Mod. attr.` column of Table 5 (`tab:secondary`). The shipped metric (`build_claim_review.check_modality_match`) never reads the evidence bundle — it checks whether two regex taggers over the same sentence agree — so it cannot be the caption's "fraction of modality-tagged claims whose tag matches the evidence modality." This probe re-derives the column against actual bundle presence.

RNA is absent from **0 of 476** released bundles (`transcriptomics.cyt_available == gep_available == False` everywhere), and the ungrounded `baseline` config ships an empty bundle by construction. Every RNA-tagged or baseline-config "correct" credit is therefore an attribution to a modality the evidence does not contain.

## Per-model recomputation

| Model | n | Paper | Shipped | metrics.json | RNA-corrected | Bundle-aware | Bundle-aware (grounded only) |
|---|--:|--:|--:|---|--:|--:|--:|
| gpt-4o-mini | 2020 | 0.976 | 0.790 | match | 0.509 | 0.454 | 0.511 |
| gpt-5.4-mini | 1233 | 0.982 | 0.982 | match | 0.675 | 0.567 | 0.738 |
| gemini-2.5-flash | 2518 | 0.878 | 0.878 | match | 0.706 | 0.650 | 0.782 |
| gemini-3-flash-preview | 3896 | 0.876 | 0.876 | match | 0.682 | 0.592 | 0.679 |

## Ranking inversion

- **Shipped / paper:** `gpt-5.4-mini(0.982) > gemini-2.5-flash(0.878) > gemini-3-flash-preview(0.876) > gpt-4o-mini(0.790)`
- **Bundle-aware:** `gemini-2.5-flash(0.650) > gemini-3-flash-preview(0.592) > gpt-5.4-mini(0.567) > gpt-4o-mini(0.454)`

The paper narrates this column as "OpenAI 0.976–0.982, Google 0.876–0.878 ... longer Google summaries dilute correct modality tagging." Under the evidence-grounded definition the ordering reverses: the two OpenAI models fall **below** both Google models, so the anti-correlation-with-sentence-count story does not survive honoring the caption.

## Where the revoked credits come from (bundle-aware)

| Model | revoked total | by claim_type | by config |
|---|--:|---|---|
| gpt-4o-mini | 680 | RNA=567, literature=1, pathology=112 | baseline=370, full_multimodal=109, pathology_only=106, pathology_rna=95 |
| gpt-5.4-mini | 512 | RNA=379, fusion=1, pathology=132 | baseline=330, full_multimodal=69, pathology_only=56, pathology_rna=57 |
| gemini-2.5-flash | 573 | RNA=433, fusion=4, literature=5, pathology=131 | baseline=423, full_multimodal=52, pathology_only=46, pathology_rna=52 |
| gemini-3-flash-preview | 1108 | RNA=758, fusion=2, literature=125, pathology=223 | baseline=625, full_multimodal=163, pathology_only=155, pathology_rna=165 |

## What this does and does not establish

- **Establishes:** the published `Mod. attr.` column measures tagger-vs-tagger self-agreement, not evidence attribution; under the caption's own definition the numbers drop by 0.14–0.42 and the cross-provider ranking inverts.
- **Conservative:** clinical/tier/other claims keep their shipped label (bundle presence is not determinable from the JSON), so `bundle_aware` *under*-states the correction.
- **Does not establish** the "true" attribution accuracy a human would assign; it establishes that the metric as defined contradicts the metric as captioned, and quantifies the gap using the repo's own bundle fields.

