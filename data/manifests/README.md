# Manifest Output Conventions

This directory stores **small reproducibility artifacts only** (no raw TCGA files).

## Layout

Each deterministic lock writes to:

```text
data/manifests/<lock_name>/
  cohort.csv
  manifest.tsv
  cohort_completeness_report.json
  provenance_manifest.json
  checksum_report.json
```

Default lock name from tooling:

- `tcga_luad_mvp50_v1`

## Artifact meanings

- `cohort.csv` — locked case rows with `lock_rank` and `lock_key_sha256`
- `manifest.tsv` — deduplicated GDC manifest for selected files
- `cohort_completeness_report.json` — required modality completeness audit
- `provenance_manifest.json` — deterministic selection metadata + per-asset provenance
- `checksum_report.json` — reproducibility digests and expected GDC MD5 checksums

## Guardrail

Do not commit downloaded raw payloads here. Raw files belong under local runtime storage (for example `hansons-context/tcga_downloads/files/`), not source control.
