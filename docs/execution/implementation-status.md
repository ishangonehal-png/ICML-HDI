# Implementation Status Snapshot

Last updated: 2026-03-06 20:40 PST

This document tracks what is merged on `main`, what is completed on feature branches, what validation has passed, and what remains for P0 delivery.

## 1) Current state summary

- **Platform foundations are merged on `main`**:
  - data contracts + deterministic manifest tooling
  - FastAPI + PostgreSQL scaffold
  - Next.js UI shell (`/upload`, `/analysis/[job_id]`, `/patient/[case_id]`)
- **Maintainability foundations are merged on `main`**:
  - app-level backend/frontend tests
  - DevX tooling (`Makefile`, `.editorconfig`, local Postgres+Redis compose, bootstrap/check scripts)
  - CI architecture coherence guardrails
- **5-lane core bughunt sweep is merged on `main`**:
  - API/runtime hardening
  - frontend/runtime hardening
  - data-script reliability fixes
  - CI reliability hardening
  - docs↔implementation coherence fixes
- **MVP50 detachable module is merged on `main`**:
  - module: `packages/mvp50/`
  - unified CLI: `scripts/mvp50.py`
  - wrapper compatibility preserved: `scripts/validate_matched_cohort.py`, `scripts/lock_mvp50_manifest.py`

## 2) Key merged commits on `main`

### Foundation integration
- `39d5b02` — merge: integrate p0 platform/refactor foundations

### Maintainability integration
- `74231d5` — merge: add maintainability devx tooling
- `9e6db10` — merge: add maintainability app-level test suites
- `5b2e743` — merge: add maintainability architecture coherence guards

### Core bughunt integration
- `5225be9` — merge: bughunt api runtime fixes
- `46ee8fd` — merge: bughunt data tooling reliability fixes
- `82881b8` — merge: bughunt frontend runtime stability fixes
- `15be070` — merge: bughunt ci reliability fixes
- `496055b` — merge: bughunt docs and implementation coherence fixes

### MVP50 module integration
- `854a561` — merge: add detachable mvp50 module with compatible wrappers

## 3) Additional progress completed on feature branches (pending integration)

The following MVP50-focused bughunt branches are complete and validated by subagent reports, but are not merged to `main` yet:

- `feat/mvp50-bughunt-cli` — `b50cba8`
  - CLI/wrapper dispatch hardening, import bootstrap robustness, wrapper argument normalization.
- `feat/mvp50-bughunt-core` — `3c5a2cb`
  - modality normalization aliases, stronger CSV/TSV header/row guards, deterministic tie-break hardening.
- `feat/mvp50-bughunt-io` — `0d00213`
  - dry-run no-write guarantees, safer output path checks, deterministic artifact ordering and serialization consistency.
- `feat/mvp50-bughunt-tests` — `76401a3`
  - stronger cwd-agnostic and deterministic artifact tests.
- `feat/mvp50-bughunt-docs-ci` — `d20d62c`
  - docs/CI guard alignment for detachable MVP50 module invariants.

## 4) Verified validation status (latest local run on current `main`)

All checks below passed on the current branch workspace:

1. `.venv-ci/bin/python -m pytest apps/api/tests -q` → **89 passed**
2. `.venv-ci/bin/python -m pytest tests/ci -q` → **60 passed**
3. `.venv-ci/bin/python -m pytest apps/api/tests/test_pathology.py apps/api/tests/test_transcriptomics.py tests/ci/test_transcriptomics_release_gate.py -q` → **68 passed**
4. `.venv-ci/bin/python scripts/ci/check_data_contract_tooling.py` → **passed**
5. `.venv-ci/bin/python scripts/ci/check_architecture_coherence.py` → **passed**

## 5) P0 progress matrix

| P0 Item | Status | Notes |
|---|---|---|
| P0.1 Data contracts + cohort integrity | 🟡 In progress | Contract + module tooling merged; still need final MVP50 lock against full target cohort artifacts and provenance publish. MVP50 hardening branches pending merge. |
| P0.2 Web UI shell | 🟢 Foundation complete | Shell routes/components and chat rail are merged and tested; pathology panel now hosts the Enso deep-zoom viewer wired to pathology proxy endpoints. |
| P0.3 Pathology endpoints | 🟡 In progress | Typed pathology routes are live with artifact-backed payloads, deterministic recursive short/full ID resolution (non-symlink-first), strict missing-data semantics toggle, and stronger provenance payloads (model/checkpoint/run/embedding + tile coordinates). Heatmap asset serving + ops hardening remain. |
| P0.4 Transcriptomics endpoints | 🟡 In progress | CYT/GEP/TIDE/evidence return deterministic typed responses with artifact/modality-result/counts-backed resolution, explicit availability codes, TIDE precompute semantics, frozen-reference governance for GEP, and coverage-audit release-gate fields. Added `scripts/check_transcriptomics_coverage_gate.py` for threshold enforcement from coverage outputs. |
| P0.5 Clinical endpoints | 🟡 In progress | Clinical routes now return deterministic typed outputs with source-aware availability/provenance semantics (`artifact → modality_result → XML/report parse → case metadata → unavailable`). Production hardening + feature-store materialization remain pending. |
| P0.6 Fusion endpoints | 🟡 In progress | Deterministic fusion score/attribution/similar-cases are implemented with modality availability + contribution/provenance semantics; calibration and retrieval quality hardening remain. |
| P0.7 Agent grounded flow | 🟡 In progress | `/v1/agent/query` now grounds across pathology + transcriptomics + clinical-min + fusion with citations; deeper provenance UX and production hardening remain. |

Legend: 🟢 foundation complete · 🟡 in progress · ⛔ pending implementation

## 6) Known residual risks

- Fusion endpoint group is now deterministic and typed, but still needs cohort calibration and retrieval-quality hardening for production confidence.
- Clinical endpoints are now typed and deterministic, but remain heuristic (research-only), without persisted clinical feature-store materialization.
- Transcriptomics currently depends on artifact/modality-result/counts availability; full production ingestion + durable feature-store materialization remain pending.
- Pathology strict missing-data mode now exists, but production rollout still needs a clear default policy plus downstream UI handling.
- Frontend still falls back to typed mock responses for unimplemented backend modality responses.
- `next@15.2.0` reports an upstream security advisory in npm output; upgrade path should be planned.
- OpenClaw messaging path experienced rare internal payload leak artifacts during timeout/retry windows; outbound sanitization hardening is recommended.

## 7) Immediate next execution order

1. Merge MVP50 bughunt branches (`feat/mvp50-bughunt-*`) and rerun full validation.
2. Run final MVP50 lock + completeness + provenance against real cohort files.
3. Finalize pathology production policy: decide strict-missing default + wire UI/agent handling, then harden heatmap asset serving.
4. Complete transcriptomics operationalization: production TIDE precompute job lifecycle + automated coverage-gate execution in release pipelines.
5. Calibrate P0.6 fusion weights/attribution and similar-case retrieval against locked cohort artifacts.
6. Harden P0.7 grounded agent outputs with richer provenance UX surfacing and stricter production guardrails.

## 8) Pathology status update (2026-03-06)

### Landed since prior snapshot

- Backend:
  - Pathology ID resolution searches recursively across nested artifact/asset layouts with deterministic non-symlink-first tie-breakers preserved.
  - Added strict missing-data semantics (`strict_missing` query + `PATHOLOGY_STRICT_MISSING_DATA` default env).
  - Expanded pathology provenance payloads with resolver strategy, artifact path/hash/timestamp, model/checkpoint/run/embedding fields, and tile coordinates.
- Frontend:
  - Pathology panel uses Enso deep-zoom viewer endpoints (`dzi`, tile, attention-heatmap) in the main panel flow.
- Data audit/validation:
  - Hardened LUAD coverage audit script with deterministic missing/orphan reporting + strict gate flags.
  - Added pathology artifact validation script for schema + manifest alignment checks.

### Validation rerun on latest local branch state

- `.venv-ci/bin/python -m pytest apps/api/tests -q` → **89 passed**
- `.venv-ci/bin/python -m pytest apps/api/tests/test_pathology.py -q` → **54 passed**
- `.venv-ci/bin/python -m pytest tests/ci -q` → **60 passed**
- `.venv-ci/bin/python scripts/ci/check_architecture_coherence.py` → **passed**
- `.venv-ci/bin/python scripts/ci/check_data_contract_tooling.py` → **passed**

### Pathology-specific production gap checklist

1. **Strict availability semantics rollout** *(implemented, policy pending)*
   - `strict_missing` mode is implemented at endpoint + env-default levels.
   - Still need product/default-policy decision and UI/agent behavior alignment.

2. **Inference + artifact generation lifecycle**
   - Integrate analysis/job flow to generate/refresh pathology artifacts automatically.
   - Avoid manual artifact syncing as an operational dependency.

3. **Heatmap asset delivery hardening**
   - Standardize image serving (object-store URL/signing or controlled static proxy).
   - Add stronger error handling, cache policy, and integrity checks.

4. **Coverage gates before release**
   - Enforce manifest coverage thresholds for embeddings/artifacts.
   - Surface explicit missing-slide counts in API and UI.

5. **Operational safeguards**
   - AuthN/AuthZ, quota/rate limiting, audit logs, and monitoring/alerting.

## 9) Transcriptomics status update (2026-03-06)

### Landed since prior snapshot

- Backend:
  - Added TIDE precompute availability semantics (`availability_code` + `precompute` block with source/run metadata).
  - Added frozen-reference governance for GEP (`required/available/valid`, reference id/hash/path) with required-mode enforcement.
  - Expanded `GET /v1/transcriptomics/coverage` with release-gate fields (`tide_precompute_available`, `gep_reference_*`, `release_gate_blockers`) and summary counters.
- Contracts/docs:
  - Updated transcriptomics contract docs with availability codes, governance fields, and release-gate semantics.
  - Added release-gate CLI: `scripts/check_transcriptomics_coverage_gate.py`.
- Tests:
  - Added/updated transcriptomics tests for TIDE precompute semantics, frozen-reference governance, and coverage-field assertions.
  - Added CI tests for transcriptomics release-gate script thresholds + strict mode.

### Validation rerun on latest local branch state

- `.venv-ci/bin/python -m pytest apps/api/tests/test_transcriptomics.py -q` → **10 passed**
- `.venv-ci/bin/python -m pytest tests/ci/test_transcriptomics_release_gate.py -q` → **4 passed**
- `.venv-ci/bin/python -m pytest apps/api/tests -q` → **89 passed**

### Transcriptomics-specific production gap checklist

1. **Frozen normalization governance policy** *(implementation landed, curation pending)*
   - Runtime governance fields + required-mode enforcement are implemented.
   - Still need finalized reference curation/versioning process for production cohorts.

2. **TIDE lifecycle integration**
   - Connect experimental TIDE endpoint to reproducible precompute jobs and provenance capture.

3. **Coverage gating automation** *(script landed, pipeline wiring pending)*
   - `check_transcriptomics_coverage_gate.py` now validates thresholds from coverage JSON.
   - Still need CI/release pipeline integration and baseline threshold ownership.

## 10) Clinical status update (2026-03-06)

### Landed since prior snapshot

- Backend:
  - Replaced clinical research stubs with typed service-backed responses for all existing clinical routes:
    - `GET /v1/clinical/{case_id}/patient-summary`
    - `GET /v1/clinical/{case_id}/eligibility`
    - `GET /v1/clinical/{case_id}/survival-baseline`
  - Added deterministic source resolution order:
    `artifact` → `modality_result` → `clinical_xml` (+ optional report text) → `case_metadata` → explicit `unavailable`.
  - Added explicit availability semantics (`available`, `unavailable_reason`) and source-aware provenance payloads (`source_paths`, `source_records`, extracted fields, parser notes).
  - Added deterministic rule-based clinical eligibility and survival-baseline computation, while honoring precomputed sections when available.
- Contracts/docs:
  - Added dedicated clinical schemas with strict typed response contracts.
  - Documented clinical route semantics and environment knobs in `apps/api/README.md`.
- Tests:
  - Added clinical route/service coverage tests for unavailable states, artifact precedence, modality-result fallback, XML/report parsing, and metadata fallback semantics.

### Validation rerun on latest local branch state

- `python -m pytest apps/api/tests/test_clinical.py -q` → **6 passed**
- `python -m pytest apps/api/tests -q` → **89 passed**

### Clinical-specific production gap checklist

1. **Persisted feature store materialization**
   - Current implementation parses XML/report/metadata on demand; durable tabular feature-store writes are still pending.

2. **Rulebook hardening + governance**
   - Eligibility/survival logic is deterministic but heuristic; formal clinical governance and cohort-calibrated baselines are still needed.

3. **Structured provenance depth**
   - Add richer provenance identifiers (source file hashes, parser run ids, and job linkage) for audit-grade traceability.


## 11) Fusion + agent grounding status update (2026-03-06)

### Landed since prior snapshot

- Backend fusion routes now return typed deterministic outputs:
  - `POST /v1/fusion/{case_id}/score`
  - `GET /v1/fusion/{case_id}/attribution`
  - `GET /v1/fusion/{case_id}/similar-cases`
- Fusion payloads expose modality-level availability, contribution, and provenance semantics:
  - availability fields (`available`, `required_for_requested_mode`, `used_in_score`)
  - contribution fields (`signal`, `weight`, `weighted_contribution`, `contribution_percent`)
  - provenance fields (`data_source` and per-modality references)
- Deterministic scoring progression now follows P0 semantics:
  - provisional = pathology + clinical minimum
  - refined = includes transcriptomics when available
  - typed fallback to provisional when transcriptomics is unavailable
- Agent route (`POST /v1/agent/query`) is now grounded on pathology + transcriptomics + clinical-min + fusion outputs and returns modality summaries + citations.

### Validation rerun on latest local branch state

- `python -m pytest apps/api/tests/test_fusion.py apps/api/tests/test_agent.py -q` → **6 passed**
- `python -m pytest apps/api/tests -q` → **89 passed**
- `python -m pytest tests/ci -q` → **60 passed**

### Remaining fusion/agent hardening gaps

1. **Calibration and retrieval quality**
   - current weights/similarity are deterministic and reliable for demos, but still need cohort calibration.

2. **Clinical endpoint parity linkage**
   - align standalone clinical route outputs more tightly with fusion clinical-min semantics for end-to-end consistency.

3. **UI provenance surfacing**
   - expose modality contribution/provenance blocks directly in the frontend evidence/provenance surfaces.
