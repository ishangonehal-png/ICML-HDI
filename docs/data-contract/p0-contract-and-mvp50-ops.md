# P0 Data Contract + MVP50 Locking (Operator Quickstart)

This runbook covers the new P0 reproducibility tooling for **contract validation** and deterministic **mvp50** locking.

Implementation is detached into `packages/mvp50/` with script-level wrappers kept stable for operator continuity.

## 0) Operator entrypoints (detachable module + compatible wrappers)

Preferred unified entrypoint:

```bash
python3 scripts/mvp50.py --help
python3 scripts/mvp50.py validate --help
python3 scripts/mvp50.py lock --help
```

Backward-compatible wrappers remain supported with the same flags/behavior:

```bash
python3 scripts/validate_matched_cohort.py --help
python3 scripts/lock_mvp50_manifest.py --help
```

Wrapper compatibility note: the legacy scripts also tolerate an accidental leading
`validate` / `lock` token (for copy-pasted unified CLI invocations), e.g.
`python3 scripts/validate_matched_cohort.py validate ...`.

All commands below can be run either through `scripts/mvp50.py` subcommands or the legacy wrapper scripts.

## 1) Build/refresh matched cohort + full manifest

```bash
python3 scripts/build_tcga_matched_cohort.py \
  --project TCGA-LUAD \
  --out-csv hansons-context/tcga_downloads/tcga_luad_exact_matched_cohort.csv \
  --out-manifest hansons-context/tcga_downloads/tcga_luad_exact_matched_manifest.tsv
```

## 2) Validate cohort completeness against canonical contract

```bash
python3 scripts/mvp50.py validate \
  --cohort-csv hansons-context/tcga_downloads/tcga_luad_exact_matched_cohort.csv \
  --report-json data/manifests/validation/cohort_completeness_report.json \
  --fail-on-missing
```

Legacy-compatible wrapper (equivalent):

```bash
python3 scripts/validate_matched_cohort.py \
  --cohort-csv hansons-context/tcga_downloads/tcga_luad_exact_matched_cohort.csv \
  --report-json data/manifests/validation/cohort_completeness_report.json \
  --fail-on-missing
```

What this checks:
- required join/selection columns from `packages/schemas/tcga_luad_data_contract_v1.json`
- required modality completeness (`rna`, `he_slide`, `clinical_supplement`, `clinical_xml`, `pathology_report`)
- de-duplicates repeated entries in `--required-modalities` so accidental repeats do not inflate missingness output

## 3) Lock deterministic MVP subset + provenance artifacts

```bash
python3 scripts/mvp50.py lock \
  --cohort-csv hansons-context/tcga_downloads/tcga_luad_exact_matched_cohort.csv \
  --manifest-tsv hansons-context/tcga_downloads/tcga_luad_exact_matched_manifest.tsv \
  --output-root data/manifests \
  --lock-name tcga_luad_mvp50_v1 \
  --subset-size 50 \
  --seed tcga-luad-mvp50-v1
```

Legacy-compatible wrapper (equivalent):

```bash
python3 scripts/lock_mvp50_manifest.py \
  --cohort-csv hansons-context/tcga_downloads/tcga_luad_exact_matched_cohort.csv \
  --manifest-tsv hansons-context/tcga_downloads/tcga_luad_exact_matched_manifest.tsv \
  --output-root data/manifests \
  --lock-name tcga_luad_mvp50_v1 \
  --subset-size 50 \
  --seed tcga-luad-mvp50-v1
```

Locking guardrails:
- rows are selected from modality-complete cohort rows (row-level completeness), including with `--allow-incomplete`
- manifest TSVs with duplicate `id` values fail fast
- cohort/manifest filename mismatches for the same `gdc_file_id` fail fast
- deterministic artifact ordering is stable across input row permutations (including duplicate case/patient tie scenarios)
- artifact text files are written as UTF-8 with final newline and LF line endings (`\n`)
- lock output path validation fails clearly when a file blocks the target directory

Outputs are written to:

```text
data/manifests/tcga_luad_mvp50_v1/
  cohort.csv
  manifest.tsv
  cohort_completeness_report.json
  provenance_manifest.json
  checksum_report.json
```

## 4) Dry-run mode (no files written)

```bash
python3 scripts/mvp50.py lock \
  --cohort-csv <path/to/cohort.csv> \
  --manifest-tsv <path/to/manifest.tsv> \
  --subset-size 50 \
  --dry-run
```

Wrapper equivalent:

```bash
python3 scripts/lock_mvp50_manifest.py \
  --cohort-csv <path/to/cohort.csv> \
  --manifest-tsv <path/to/manifest.tsv> \
  --subset-size 50 \
  --dry-run
```

Use dry-run for quick integrity checks in CI before artifact generation. Dry-run mode does not create output directories or report files.

## 5) CI guardrails for detachable-module compatibility

```bash
python3 scripts/ci/check_data_contract_tooling.py
```

This guardrail verifies that:
- core cohort/download scripts still satisfy locked dataset constants,
- detachable module files under `packages/mvp50/` exist,
- `scripts/mvp50.py` and legacy wrappers are callable and keep expected CLI flags,
- wrappers continue delegating into package entrypoints (no logic drift back into script wrappers).

