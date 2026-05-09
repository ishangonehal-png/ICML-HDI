# MVP50 Module (Detachable)

This package contains the reusable MVP50 operator workflows for:

- cohort completeness validation
- deterministic lock generation (`mvp50` subset + provenance/checksum artifacts)

## Why this exists

The implementation is intentionally detached from script wrappers so that:

- core logic stays easy to maintain under `packages/`
- script interfaces stay stable for operators and CI
- future integrations can import the module directly without shelling out

## Public entrypoints

- Unified CLI (recommended):
  - `python3 scripts/mvp50.py validate ...`
  - `python3 scripts/mvp50.py lock ...`
- Direct module CLI file (detached/debug usage):
  - `python3 packages/mvp50/cli.py validate ...`
  - `python3 packages/mvp50/cli.py lock ...`
- Legacy-compatible wrappers (unchanged UX):
  - `python3 scripts/validate_matched_cohort.py ...`
  - `python3 scripts/lock_mvp50_manifest.py ...`

Internally these wrappers delegate to:

- `packages.mvp50.validate`
- `packages.mvp50.lock`
- `packages.mvp50.cli`

## Boundary

This module is limited to reproducibility/operator tooling for data-contract validation and lock artifacts.
It does **not** change research framing, API behavior, or model-scoring semantics.
