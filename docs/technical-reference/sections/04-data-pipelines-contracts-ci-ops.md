# Section 04 — Data Pipelines, Contracts, CI Guardrails, and Operational Tooling

## 4.1 Scope, docs-first grounding, and role of this section

This section documents the **data and operations spine** of the repository: how cohort data is built and locked, how modality coverage is audited, how release gates are enforced, and how local/CI workflows keep everything deterministic.

Per the docs-first contract, this section was written after reviewing:

- `docs/README.md`
- `docs/architecture/plan.md`
- `docs/execution/task-backlog.md`
- `docs/execution/implementation-status.md`

It focuses on the implementation boundary spanning:

- `scripts/*.py` and `scripts/*.sh`
- `scripts/ci/*`
- `scripts/dev/*`
- `packages/mvp50/*`
- `packages/schemas/tcga_luad_data_contract_v1.json`
- `.github/workflows/ci.yml`
- `Makefile`
- `infra/dev/docker-compose.yml`
- selected API coverage surfaces (`apps/api/routers/transcriptomics.py`, `apps/api/services/transcriptomics.py`)

Architecturally, this is the operational realization of the plan’s “case-keyed contracts everywhere” and “detachable operator modules with stable wrappers” principles in `docs/architecture/plan.md`.

---

## 4.2 Data contracts and cohort tooling architecture

### 4.2.1 End-to-end pipeline topology

The repository’s contract pipeline is intentionally split into **three layers**:

1. **Acquisition + matching** (build deterministic cohort + manifest from GDC)
2. **Contract validation + deterministic lock** (moduleized in `packages/mvp50/`)
3. **Guardrail enforcement** (tests + CI scripts that assert invariants and CLI compatibility)

```text
GDC API (/cases, /files)
  -> scripts/build_tcga_matched_cohort.py
      -> tcga_luad_exact_matched_cohort.csv
      -> tcga_luad_exact_matched_manifest.tsv
  -> scripts/download_tcga_matched_data.sh
      -> modality-filtered manifest + gdc-client download
  -> scripts/mvp50.py validate|lock (wrappers preserved)
      -> data/manifests/<lock_name>/
         - cohort.csv
         - manifest.tsv
         - cohort_completeness_report.json
         - provenance_manifest.json
         - checksum_report.json
  -> scripts/ci/check_data_contract_tooling.py + tests/ci/*
      -> regression guardrails for constants, delegation, symbols, CLI behavior
```

### 4.2.2 Canonical data contract boundary

The contract authority is `packages/schemas/tcga_luad_data_contract_v1.json`. It encodes:

- **join keys** (`case_id`, `patient_id`, optional `sample_id`, optional `slide_id`, `gdc_file_id`)
- **required cohort columns** (`cohort_required_columns`)
- **modality requirements** with file-ID + filename columns
- **required modalities** (`rna`, `he_slide`, `clinical_supplement`, `clinical_xml`, `pathology_report`)
- **asset-level required fields** for reproducibility artifacts

This means pipeline correctness is not inferred from ad hoc code assumptions; it is anchored to a versioned schema artifact.

### 4.2.3 Acquisition and matching (`scripts/build_tcga_matched_cohort.py`)

`build_tcga_matched_cohort.py` is the deterministic cohort constructor:

- queries GDC `/cases` and `/files`
- applies fixed filters for LUAD and modality-specific file classes
- resolves one “best” file per modality per case
- emits:
  - matched case CSV (`--out-csv`)
  - manifest TSV (`--out-manifest`)

#### Function inventory — cohort builder

| Path | Function | Responsibility |
|---|---|---|
| `scripts/build_tcga_matched_cohort.py` | `_post_json` | POSTs URL-encoded filter payloads to GDC endpoints with network error translation |
| | `_fetch_all` | Paginates deterministic fetch loops over `/cases` and `/files` |
| | `_build_*_filters` helpers | Encodes explicit project/modality constraints (RNA, slide, clinical) |
| | `_best_rna_file` | Applies workflow ranking preference (count-based first) |
| | `_best_slide_file` | Prefers `.svs` and lower DX index ordering |
| | `_best_clinical_supplement_file`, `_best_clinical_xml_file`, `_best_pathology_report_file` | Chooses deterministic clinical artifact representatives |
| | `build_matched_cohort` | Produces case-level rows + deduplicated selected file list |
| | `_write_csv`, `_write_manifest` | Persists contract-ready outputs |
| | `main` | CLI entrypoint and output-path creation |

Key architectural point: “best file” selection is deterministic and codified in named helpers rather than hidden in inline sort expressions.

### 4.2.4 Locked downloader (`scripts/download_tcga_matched_data.sh`)

This script is intentionally opinionated and immutable in scope:

- fixed project: `PROJECT="TCGA-LUAD"`
- expected matched cohort size: `EXPECTED_COHORT_CASES=475`
- expected manifest row counts by modality combinations
- expected extension composition (RNA TSV, H&E SVS, PDF/XML/TXT context)
- deterministic manifest row sort by file ID before download
- destructive reset of target data directory (`rm -rf "$DATA_DIR"`) before fresh `gdc-client download`

This prevents silent drift between demo snapshots and runtime assumptions.

### 4.2.5 Detachable validation/lock module (`packages/mvp50/*`)

The repo deliberately moved operational logic into `packages/mvp50/`, while retaining operator-friendly wrappers:

- unified CLI: `scripts/mvp50.py`
- compatibility wrappers:
  - `scripts/validate_matched_cohort.py`
  - `scripts/lock_mvp50_manifest.py`

Wrappers do only bootstrap/argv normalization/delegation. Core logic stays in:

- `packages/mvp50/cli.py`
- `packages/mvp50/validate.py`
- `packages/mvp50/lock.py`
- `packages/mvp50/data_contract_utils.py`

#### Function inventory — module and wrappers

| Path | Function(s) | Contract role |
|---|---|---|
| `scripts/mvp50.py` | `_bootstrap_repo_root`, `_normalize_argv`, `main` | cwd-agnostic bootstrap + delegation to `packages.mvp50.cli` |
| `scripts/validate_matched_cohort.py` | same pattern | backward-compatible validation CLI surface |
| `scripts/lock_mvp50_manifest.py` | same pattern | backward-compatible lock CLI surface |
| `packages/mvp50/cli.py` | `build_parser`, `main`, `cli_entrypoint` | unified subcommand router (`validate`, `lock`) |
| `packages/mvp50/validate.py` | `add_arguments`, `run`, `cli_entrypoint` | schema-based completeness validation + optional report |
| `packages/mvp50/lock.py` | `add_arguments`, `_read_manifest_map`, `_build_selected_assets`, `run` | deterministic subset lock + provenance/checksum artifact emission |
| `packages/mvp50/data_contract_utils.py` | parsing/hash/ranking helpers | shared deterministic utilities and schema parsing |

### 4.2.6 Manifest lock and validation flow (internal mechanics)

#### Validation stage (`packages/mvp50/validate.py`)

Validation enforces:

1. input file existence and type (`_ensure_input_file`)
2. schema load + modality resolution (`resolve_schema_and_modalities`)
3. required-column presence (`load_and_validate_cohort_rows`)
4. per-case modality completeness (`evaluate_cohort_completeness`)
5. stable, sorted JSON report output (`dumps_json_pretty`)

Notable behavior:

- modality overrides are normalized and de-duplicated (e.g. `RNA,he-slide,RNA` resolves cleanly)
- BOM-prefixed headers are normalized in CSV readers
- optional `--fail-on-missing` provides strict gate mode
- `--dry-run` avoids report writes entirely

#### Lock stage (`packages/mvp50/lock.py`)

Locking adds deterministic subset selection and artifact generation:

1. validates files + subset parameters
2. computes completeness and (unless `--allow-incomplete`) fails early on incomplete cases
3. selects only complete rows
4. ranks rows deterministically (`rank_rows_with_lock_metadata`):
   - lock key = `sha256(seed|case_id|patient_id)`
   - tie-break = stable row fingerprint hash
5. validates manifest map:
   - required columns exist
   - duplicate IDs (case-insensitive) are rejected
6. checks cohort↔manifest filename consistency per selected file ID
7. writes deterministic artifact bundle:
   - `cohort.csv`
   - `manifest.tsv`
   - `provenance_manifest.json`
   - `checksum_report.json`
   - `cohort_completeness_report.json`

The lock output is a reproducibility contract, not only a convenience export.

### 4.2.7 Reproducibility artifacts and their semantics

| Artifact | Path pattern | Purpose |
|---|---|---|
| Locked cohort | `data/manifests/<lock_name>/cohort.csv` | Selected case rows with `lock_rank` and `lock_key_sha256` |
| Locked manifest | `.../manifest.tsv` | Exact file set required for selected cases |
| Completeness report | `.../cohort_completeness_report.json` | Input cohort completeness summary and missing-case preview |
| Provenance manifest | `.../provenance_manifest.json` | Full selection metadata, inputs, algorithm descriptor, case/file mapping |
| Checksum report | `.../checksum_report.json` | digests for case order, file set, provenance payload, and on-disk artifact hashes |

---

### 4.2.8 Operator runbook — build, validate, and lock deterministic MVP subset

#### Runbook A: regenerate full matched cohort and manifest

1. Build cohort + manifest:

```bash
python3 scripts/build_tcga_matched_cohort.py \
  --project TCGA-LUAD \
  --out-csv hansons-context/tcga_downloads/tcga_luad_exact_matched_cohort.csv \
  --out-manifest hansons-context/tcga_downloads/tcga_luad_exact_matched_manifest.tsv
```

2. (Optional) download fixed snapshot by modalities:

```bash
bash scripts/download_tcga_matched_data.sh --rna --he --context
```

3. Confirm downloader guardrails did not trip (cohort count = 475 and expected manifest composition).

#### Runbook B: validate contract completeness and generate lock artifacts

1. Validate contract completeness:

```bash
python3 scripts/mvp50.py validate \
  --cohort-csv hansons-context/tcga_downloads/tcga_luad_exact_matched_cohort.csv \
  --report-json data/manifests/validation/cohort_completeness_report.json \
  --fail-on-missing
```

2. Lock deterministic subset:

```bash
python3 scripts/mvp50.py lock \
  --cohort-csv hansons-context/tcga_downloads/tcga_luad_exact_matched_cohort.csv \
  --manifest-tsv hansons-context/tcga_downloads/tcga_luad_exact_matched_manifest.tsv \
  --output-root data/manifests \
  --lock-name tcga_luad_mvp50_v1 \
  --subset-size 50 \
  --seed tcga-luad-mvp50-v1
```

3. Verify artifact bundle exists and digests are populated:

```bash
ls -lah data/manifests/tcga_luad_mvp50_v1
cat data/manifests/tcga_luad_mvp50_v1/checksum_report.json
```

4. If you only need a non-writing gate check, use `--dry-run` on validate/lock commands.

---

## 4.3 Pathology and transcriptomics coverage + release-gate tooling architecture

Coverage tooling is split by modality domain:

- **Pathology coverage/audit scripts** (manifest ↔ embeddings ↔ artifacts)
- **Transcriptomics coverage endpoint + release-gate checker**

This separation matches implementation status in `docs/execution/implementation-status.md`: each branch can be validated independently, then composed at release time.

### 4.3.1 Pathology coverage audit (`scripts/audit_luad_embedding_coverage.py`)

This script provides deterministic full475 coverage accounting.

Inputs:

- slide manifest (default `tcga_luad_exact_matched_manifest_slides.tsv`)
- embeddings directory (`*.npy`)
- pathology artifacts directory (`*.json`)

Outputs:

- `luad_embedding_coverage_audit.csv`
- `luad_embedding_coverage_summary.json`

It computes per-slide status:

- embedding presence/count
- patch count totals/maxima
- coordinate sidecar presence
- artifact presence
- artifact section completeness (`tissue_composition`, `heatmap`, `evidence`)
- tissue fractions (Tumor/Stroma/Necrosis/Lymphocyte-rich)

And summary-level diagnostics:

- missing embedding IDs
- missing artifact IDs
- orphan embeddings (in embeddings dir but absent from manifest)
- duplicate manifest slide IDs
- patch count read errors
- stable row digest (`rows_digest_sha256`)

#### Function inventory — pathology coverage audit

| Function group | Key functions | Why it matters |
|---|---|---|
| ID normalization | `canonical_slide_id`, `extract_case_id`, `best_slide_id_from_path` | aligns manifest IDs with file-system naming variations |
| Manifest loading | `detect_delimiter`, `load_manifest_slides`, `choose_manifest_slide_source` | robust parsing of TSV/CSV-like slide manifests |
| Embedding scan | `collect_embedding_files`, `read_patch_count_from_npy`, `has_neighbor_coords_file` | presence + quality signals, not just raw file existence |
| Artifact scan | `collect_artifacts`, `extract_tissue_fractions`, `resolve_artifact_for_slide` | deterministic artifact selection and completeness scoring |
| Report generation | `build_audit_rows`, `rows_digest_sha256`, `write_audit_csv`, `write_summary_json` | stable, gate-friendly output surface |
| Gate logic | `_failure_reasons`, `--strict` + fail flags | turns audit output into release blocker semantics |

### 4.3.2 Pathology artifact validator (`scripts/validate_pathology_artifacts.py`)

This validator enforces structure and manifest alignment of artifact bundles.

It checks:

- JSON parseability and object shape
- required sections:
  - `tissue_composition`
  - `heatmap`
  - `evidence`
- section-level value sanity:
  - tissue fractions in `[0,1]`
  - viewport bounds in `[0,1]`
  - evidence tile IDs/scores/rationales
- alignment of artifact IDs to manifest slide/case universe
- optional cross-check against coverage summary JSON

The output report (`pathology_artifact_validation_report.json`) separates summary counters from issue previews, which helps both humans and automation.

### 4.3.3 Transcriptomics coverage and release gate

Transcriptomics uses a two-step architecture:

1. **coverage payload generation** in API runtime:
   - router: `apps/api/routers/transcriptomics.py` (`GET /v1/transcriptomics/coverage`)
   - service: `apps/api/services/transcriptomics.py` (`get_transcriptomics_coverage_report`)
2. **policy gate evaluation** in script form:
   - `scripts/check_transcriptomics_coverage_gate.py`

Coverage generation includes per-case fields such as:

- `has_rna_input`
- `cyt_available`, `gep_available`, `tide_available`, `evidence_available`
- `tide_precompute_available`
- `gep_reference_required`, `gep_reference_valid`, `gep_reference_id`
- `release_gate_blockers`
- aggregate summary counters (`cases_missing_mvp_coverage`, `cases_missing_tide_precompute`, `cases_missing_gep_reference`, etc.)

Case discovery for coverage is intentionally broad and deterministic (`_resolve_coverage_case_ids`):

- explicit query case IDs (if provided)
- optional coverage cohort CSV (`TRANSCRIPTOMICS_COVERAGE_COHORT_CSV`)
- DB case IDs
- artifact directory discovery (`TRANSCRIPTOMICS_ARTIFACT_DIR`)
- counts directory discovery (`TRANSCRIPTOMICS_COUNTS_DIR`)

Then the gate script applies thresholds and optional strict policy.

#### Function inventory — transcriptomics release gate script

| Function | Responsibility |
|---|---|
| `parse_args` | defines threshold and strict-mode policy inputs |
| `_load_json` | robust file read + JSON validation |
| `_resolve_coverage_payload` | enforces expected payload shape (`summary`, `cases`) |
| `_require_int` | type-safe summary metric extraction |
| `_count_release_blocker_cases` | counts blocker-bearing cases |
| `_evaluate_failures` | evaluates threshold violations and strict defaults |
| `main` | emits summary + pass/fail exit code |

### 4.3.4 Operator runbook — modality release-gate checks

#### Runbook C: pathology coverage gate (strict)

```bash
python3 scripts/audit_luad_embedding_coverage.py \
  --manifest /path/to/tcga_luad_exact_matched_manifest_slides.tsv \
  --embeddings-dir /path/to/embeddings \
  --artifacts-dir /path/to/pathology_artifacts \
  --expected-slide-count 475 \
  --strict

python3 scripts/validate_pathology_artifacts.py \
  --manifest /path/to/tcga_luad_exact_matched_manifest_slides.tsv \
  --artifacts-dir /path/to/pathology_artifacts \
  --fail-on-orphan-artifacts
```

Interpretation:

- first command blocks on missing embeddings/artifacts/incomplete artifacts/orphans (strict mode)
- second command blocks malformed/orphaned artifact JSON payloads

#### Runbook D: transcriptomics release gate from API coverage snapshot

1. Fetch coverage JSON:

```bash
curl -sS "http://127.0.0.1:8000/v1/transcriptomics/coverage" > /tmp/transcriptomics_coverage.json
```

2. Evaluate strict gate:

```bash
python3 scripts/check_transcriptomics_coverage_gate.py \
  --coverage-json /tmp/transcriptomics_coverage.json \
  --strict
```

3. Evaluate custom tolerances (example):

```bash
python3 scripts/check_transcriptomics_coverage_gate.py \
  --coverage-json /tmp/transcriptomics_coverage.json \
  --expected-cases-total 475 \
  --max-missing-mvp-coverage 0 \
  --max-missing-tide-precompute 5 \
  --max-missing-gep-reference 0 \
  --fail-on-release-blockers
```

---

## 4.4 CI workflows and guardrail checks (what, where, why)

### 4.4.1 Workflow architecture (`.github/workflows/ci.yml`)

CI is arranged into explicit jobs with reliability controls.

| Job | Trigger condition | Primary checks | Why |
|---|---|---|---|
| `detect-layout` | always | discovers presence of `apps/api` and `apps/web` | avoids running app-specific jobs when directories are absent |
| `repo-guardrails` | always (independent of layout) | `pytest tests/ci -q`, `scripts/ci/check_architecture_coherence.py`, `scripts/ci/check_data_contract_tooling.py` | protects docs-first policy, contract tooling, and repo safety invariants |
| `backend-checks` | only if `apps/api` exists | dependency install + `scripts/ci/run_backend_smoke.py` | validates Python compile/import and backend tests without forcing nonexistent app paths |
| `frontend-checks` | only if `apps/web` exists | `bash scripts/ci/run_frontend_checks.sh` | validates deterministic npm install + test/type/build |

Reliability controls encoded in CI:

- per-job `timeout-minutes`
- dependency caching (`pip` / `npm`)
- step summary status based on actual step outcomes
- concurrency cancellation (`cancel-in-progress: true`) to avoid stale pipelines

### 4.4.2 Repo guardrails surface

The always-on guardrails combine pytest policies and script checks.

#### Guardrail matrix

| Enforcement artifact | Path | Enforces |
|---|---|---|
| Repo structure tests | `tests/ci/test_repo_guardrails.py` | required docs/scripts/module files exist; deprecated root docs absent; Makefile includes architecture checks |
| Markdown link integrity | `tests/ci/test_markdown_links.py` | local markdown links resolve across repo |
| Architecture coherence tests | `tests/ci/test_architecture_coherence.py` + `scripts/ci/check_architecture_coherence.py` | docs index coherence + plan/UI/API route-group alignment + route-tree consistency |
| Data-contract tooling tests | `tests/ci/test_data_contract_tooling.py` + `scripts/ci/check_data_contract_tooling.py` | script/module existence, syntax, CLI help, constants, wrapper delegation, symbol contracts |
| MVP50 detachability tests | `tests/ci/test_mvp50_module_detachability.py` | wrapper cwd-agnostic behavior, delegation semantics, argv normalization, exit-code coercion |
| Data-contract edge cases | `tests/ci/test_data_contract_edge_cases.py` | duplicate IDs, BOM headers, dry-run no-write, deterministic tie-breaks, stable digests |
| Pathology tooling tests | `tests/ci/test_pathology_data_scripts.py` | coverage/audit outputs, strict failures, artifact validator behavior |
| Transcriptomics gate tests | `tests/ci/test_transcriptomics_release_gate.py` | threshold and strict-mode semantics of coverage gate script |
| CI reliability tests | `tests/ci/test_ci_workflow_reliability.py` | workflow has timeouts, caching, independent guardrails, runtime step outcome summaries |

### 4.4.3 Data-contract CI script (`scripts/ci/check_data_contract_tooling.py`)

This script adds script-level guardrails beyond test assertions:

- compiles and executes `--help` for build/download/MVP50 entrypoints
- checks locked literals in `scripts/download_tcga_matched_data.sh`
- verifies wrapper delegation snippets (ensuring logic doesn’t drift back into wrappers)
- verifies required public symbols in `packages/mvp50/*.py`

In effect, it treats the operator CLI surface as a stable API contract.

### 4.4.4 Architecture coherence script (`scripts/ci/check_architecture_coherence.py`)

This script enforces docs↔implementation consistency:

- required docs exist and are listed in `docs/README.md`
- API route groups align between:
  - `docs/architecture/plan.md`
  - `docs/architecture/ui-architecture.md`
  - backend router prefixes (`apps/api/routers/*.py`)
- required plan endpoints exist in backend routers
- UI core routes in `ui-architecture.md` exist in `apps/web/app` route tree (if web app exists)

This is crucial because docs-first is not a style preference; it is an enforced architecture policy.

### 4.4.5 Operator runbook — reproduce CI locally

#### Runbook E: local CI-equivalent execution and triage order

From repo root:

```bash
python3 -m pip install -r requirements-ci.txt
make test-ci
make backend-smoke
make frontend-smoke
```

or one-command chain:

```bash
make ci
```

If failure occurs, triage in this order:

1. `python3 scripts/ci/check_architecture_coherence.py`
2. `python3 scripts/ci/check_data_contract_tooling.py`
3. `python3 -m pytest tests/ci -q`
4. backend/frontend smoke scripts depending on app presence

This sequence mirrors CI job intent and reduces false debugging branches.

---

## 4.5 DevX/tooling and local infra workflow

### 4.5.1 Makefile as the operator front door

The root `Makefile` is the canonical local workflow interface.

#### Target inventory

| Target | Implementation | Purpose |
|---|---|---|
| `make ci` | chains `format-check lint-shell test-ci backend-smoke frontend-smoke` | local CI parity |
| `make test-ci` | pytest guardrails + architecture + data-contract checks | docs/contracts/CI policy validation |
| `make backend-smoke` | `python scripts/ci/run_backend_smoke.py` | compile/import/backend pytest checks |
| `make frontend-smoke` | `bash scripts/ci/run_frontend_checks.sh` | deterministic npm install/test/type/build |
| `make lint-shell` | `bash -n` + optional `shellcheck` over `scripts/*.sh` | shell syntax/lint hygiene |
| `make format-check` | optional frontend format and optional `ruff format --check` | formatting consistency when configured |
| `make dev-bootstrap` | `bash scripts/dev/bootstrap.sh` | non-destructive setup helper |
| `make dev-check` | `bash scripts/dev/check.sh` | readiness and optional CI run |
| `make infra-up/down/logs` | docker compose over `infra/dev/docker-compose.yml` | local postgres+redis lifecycle |

### 4.5.2 Non-destructive setup helpers (`scripts/dev/*`)

`scripts/dev/bootstrap.sh`:

- checks required commands (`python3`, `make`, `git`)
- reports optional tooling (`docker`, `npm`)
- creates `apps/api/.env` from `.env.example` only if missing
- validates compose config when Docker exists
- optional `--start-infra` to bring up services

`scripts/dev/check.sh`:

- verifies required commands (`bash`, `python3`, `make`, `git`)
- runs `bash -n` over shell scripts
- validates env vars (`DATABASE_URL`, `REDIS_URL`) with optional non-failing mode
- validates compose config and shows compose status if Docker exists
- optional `--run-ci` to run CI-equivalent checks after readiness validation

This gives a deterministic onboarding and daily “is my machine healthy?” path.

### 4.5.3 Local infrastructure contract (`infra/dev/docker-compose.yml`)

Local infra is intentionally minimal:

- PostgreSQL (`postgres:16-alpine`)
- Redis (`redis:7-alpine`)

Both include health checks and persistent named volumes.

| Service | Port default | Key env/command | Healthcheck |
|---|---|---|---|
| `postgres` | `5432` | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` from `DEV_*` vars | `pg_isready` |
| `redis` | `6379` | `redis-server --appendonly yes` | `redis-cli ping` |

No app containers are included; app processes run directly on the host/venv, which keeps iteration loops fast and debugging transparent.

### 4.5.4 Formatting and newline determinism

Operational determinism is supported by `.editorconfig`:

- UTF-8
- LF line endings
- final newline insertion
- explicit indentation rules (including tab indent for `Makefile`)

This aligns with tests in `tests/ci/test_data_contract_edge_cases.py` that assert no CRLF in lock outputs.

### 4.5.5 Operator runbook — local bootstrap and daily workflow

#### Runbook F: first-time setup and validation

```bash
make dev-bootstrap

# set env vars in current shell
export DATABASE_URL='postgresql+psycopg://yc_aixbio:change_me_local_only@localhost:5432/yc_aixbio'
export REDIS_URL='redis://localhost:6379/0'

make infra-up
make dev-check
make ci
```

#### Runbook G: after pulling new changes

```bash
git pull --ff-only
make dev-check --no-print-directory
make test-ci
```

(If backend/frontend changed materially, run full `make ci`.)

---

## 4.6 Operational concerns: reproducibility, determinism, and failure handling

### 4.6.1 Reproducibility controls by layer

| Layer | Reproducibility control | Path(s) |
|---|---|---|
| Dataset definition | hard-coded LUAD constants and expected row counts | `scripts/download_tcga_matched_data.sh` |
| Contract schema | versioned modality + column requirements | `packages/schemas/tcga_luad_data_contract_v1.json` |
| Selection determinism | SHA256 seed + row fingerprint tie-break ranking | `packages/mvp50/data_contract_utils.py`, `packages/mvp50/lock.py` |
| Artifact determinism | sorted assets, stable JSON formatting, LF newlines | `packages/mvp50/lock.py`, `packages/mvp50/data_contract_utils.py`, `.editorconfig` |
| Coverage determinism | normalized identifiers + deterministic scoring + rows digest | `scripts/audit_luad_embedding_coverage.py` |
| Gate determinism | explicit threshold flags + strict mode defaults | `scripts/check_transcriptomics_coverage_gate.py` |
| CI determinism | pinned workflow jobs, timeouts, caching, stable local parity commands | `.github/workflows/ci.yml`, `Makefile` |

### 4.6.2 Determinism/failure hotspots and mitigation

| Hotspot | Failure mode | Mitigation present |
|---|---|---|
| GDC upstream drift | changed cohort/manifest cardinality | expected counts and composition checks in downloader |
| malformed CSV/TSV headers | silent parser mismatch | normalized headers + required-column checks |
| duplicate manifest IDs | ambiguous file mapping | explicit duplicate-ID failure (case-insensitive) |
| cohort↔manifest mismatch | wrong file attached to case | filename consistency checks in lock builder |
| row-order dependence | non-reproducible lock subset | hash-based ranking + stable tie-break |
| accidental writes in dry checks | CI side effects | dry-run no-write behavior tested and enforced |
| artifact naming variance | missed pathology coverage | canonical ID normalization + candidate scoring |
| incomplete modality outputs | hidden release risk | strict gate modes and release blocker counters |
| docs/code drift | stale contracts/route docs | architecture coherence checks and required docs index |

### 4.6.3 Failure handling strategy patterns

The repo consistently uses a few operational patterns:

1. **Fail fast with explicit diagnostics**
   - Runtime errors include file path and flag context (e.g., `--cohort-csv`, `--manifest-tsv`).
2. **Typed unavailable states where API-level soft failure is preferable**
   - transcriptomics/clinical/pathology services surface availability codes instead of crashing endpoints for every missing artifact condition.
3. **Strict-mode switches for release-time hard blocking**
   - pathology and transcriptomics gate scripts can convert partial data to hard failures.
4. **Dry-run pathways for preflight in CI and local checks**
   - validate/lock can execute full logic without writing outputs.

### 4.6.4 Operator runbook — release candidate quality gate

#### Runbook H: pre-release deterministic gate sequence

1. Data-contract baseline:

```bash
python3 scripts/ci/check_data_contract_tooling.py
```

2. Build + validate + lock (or verify existing lock with dry-run validation as needed).

3. Pathology strict coverage gate:

```bash
python3 scripts/audit_luad_embedding_coverage.py --strict --expected-slide-count 475
python3 scripts/validate_pathology_artifacts.py --fail-on-orphan-artifacts
```

4. Transcriptomics strict gate from coverage payload:

```bash
python3 scripts/check_transcriptomics_coverage_gate.py \
  --coverage-json /tmp/transcriptomics_coverage.json \
  --strict
```

5. Repository/architecture guardrails and app smoke:

```bash
make ci
```

Only publish/merge when all five layers pass.

---

## 4.7 Practical takeaways for maintainers

1. **Treat `packages/schemas/tcga_luad_data_contract_v1.json` as the non-negotiable source of truth.**
2. **Treat `packages/mvp50/*` as core logic and `scripts/*` wrappers as stable UX contracts.**
3. **Treat pathology/transcriptomics coverage scripts as release infrastructure, not optional analytics.**
4. **Treat `repo-guardrails` CI job as always-on policy enforcement, not just a unit test bucket.**
5. **Use `Makefile` and `scripts/dev/*` as the only supported local workflow surface for repeatability.**

In short, this repository’s operational design is intentionally conservative: deterministic selection, explicit contracts, hard gates for drift, and layered fallback semantics for research-time development. That is exactly what enables rapid iteration without sacrificing auditability.