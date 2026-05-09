# Transcriptomics MVP Feasibility (Deep Research Digest)

Last updated: 2026-03-05
Source conversation: https://chatgpt.com/c/69a7d2b6-6b20-8324-86fc-594b8ff5f439 (same thread as pathology deep research)

## Scope audited
- `/v1/transcriptomics/{case_id}/cyt`
- `/v1/transcriptomics/{case_id}/gep`
- `/v1/transcriptomics/{case_id}/tide`
- `/v1/transcriptomics/{case_id}/evidence`

> Note: Routes updated to include `{case_id}` — see [`../architecture/plan.md`](../architecture/plan.md) § 4 for canonical API surface.

Context: TCGA-LUAD, STAR-count augmented TSV, 50-case MVP scalable to ~475 matched cases.

## Feasibility verdict

| Endpoint | Status | Notes |
|---|---|---|
| CYT | Green | Trivial from `tpm_unstranded` for GZMA/PRF1 |
| 18-gene GEP (RNA proxy) | Green | Ship explicit RNA-seq proxy formulation (documented) |
| TIDE | Yellow | Use local TIDEpy only; original web server is retired |
| Evidence endpoint | Green | Packaging layer over computed scores + QC + provenance |

## Recommended implementation standard

1. Parse STAR-count augmented TSV columns from GDC.
2. Use `tpm_unstranded` as base expression unit.
3. Transform with `log2(TPM + 1)`.
4. Strip Ensembl version suffix for stable joins (e.g., `ENSG... .17 -> ENSG...`).
5. Use a **frozen reference cohort** for z-score normalization so scores do not drift when scaling from 50 to 475.

## Endpoint notes

### CYT
Formula:
`CYT = log2(sqrt((TPM_GZMA + eps) * (TPM_PRF1 + eps)))`

### GEP proxy
Use explicit RNA-seq proxy (document and version):
- 18-gene set,
- cohort z-score standardization,
- signed weighting (CD276 treated separately if using signed mean variant).

### TIDE
- Local implementation via TIDEpy (experimental).
- Must return limitations in payload:
  - research-only,
  - normalization-reference dependent,
  - not validated as direct response prediction in treatment-naive TCGA cohort.

### Evidence endpoint
Return compact, auditable payload:
- summary scores,
- key genes panel,
- QC + missing genes,
- provenance (workflow type, gencode version, code commit).

## Runtime expectations (CPU)
- 50 cases: minutes
- 475 cases: tens of minutes
- Main bottleneck is ingestion/parsing/download, not scoring compute.

## Policy for demo truthfulness
- Transcriptomic scores are proxy biomarkers/signatures.
- Not a clinical assay and not a treatment recommendation engine.
- Show uncertainty/QC/provenance in all responses.
