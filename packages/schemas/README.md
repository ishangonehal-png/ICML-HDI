# Schema Package

Canonical schema definitions used by cohort validation and deterministic manifest locking.

## Files

- `tcga_luad_data_contract_v1.json` — P0 contract for join keys, required modalities, and core metadata fields.

This contract is consumed by:
- `scripts/validate_matched_cohort.py`
- `scripts/lock_mvp50_manifest.py`
