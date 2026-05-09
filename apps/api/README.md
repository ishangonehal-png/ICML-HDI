# YC AIxBio FastAPI Backend (P0 Scaffold)

Research-only backend scaffold for the YC AIxBio hackathon.

> This API returns **proxy research outputs** and is **not** intended for clinical decision-making.

## Included in this scaffold

- FastAPI app bootstrap (`main.py`)
- Router modules:
  - `uploads`
  - `analysis`
  - `pathology`
  - `transcriptomics`
  - `clinical`
  - `fusion`
  - `agent`
- Shared router services (`services/`) for case bootstrap + modality-specific typed response shaping
- Health endpoint: `GET /health`
- SQLAlchemy + PostgreSQL session layer
- Core DB models:
  - `cases`
  - `files`
  - `upload_sessions`
  - `analysis_jobs`
  - `job_events`
  - `modality_results`
- Alembic migration scaffold under `infra/db/migrations`

## Quick start (local)

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `DATABASE_URL` to your local Postgres instance if needed.
For cross-machine/browser setups, also set `CORS_ALLOW_ORIGINS` as a comma-separated list
(for example `http://localhost:3000,http://127.0.0.1:3000`).
Queue/worker behavior is env-driven via:
- `REDIS_URL`
- `ANALYSIS_QUEUE_KEY`
- `ANALYSIS_QUEUE_PROCESSING_KEY`
- `ANALYSIS_QUEUE_DEDUPE_TTL_SECONDS`
- `ANALYSIS_WORKER_POLL_TIMEOUT_SECONDS`
- `ANALYSIS_WORKER_REQUEUE_INFLIGHT_ON_START`

### Run migrations

From repo root:

```bash
source apps/api/.venv/bin/activate
alembic -c infra/db/migrations/alembic.ini upgrade head
```

### Start API

From repo root:

```bash
source apps/api/.venv/bin/activate
uvicorn main:app --app-dir apps/api --reload
```

### Start analysis worker

Run the dedicated queue consumer in a separate process:

```bash
source apps/api/.venv/bin/activate
python apps/api/worker.py
```

Docs:
- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

### Run backend tests

```bash
source apps/api/.venv/bin/activate
pip install -r apps/api/requirements-test.txt
python -m pytest apps/api/tests -q
```

Tests use an in-memory sqlite fixture, so local Postgres is not required.

## Minimal persisted endpoints

- `POST /v1/uploads/init`
- `POST /v1/analysis/jobs`
- `GET /v1/analysis/jobs/{job_id}`
- `GET /v1/analysis/jobs/{job_id}/artifacts`

For non-cached analysis jobs, `/v1/analysis/jobs` now writes a queued job record and enqueues the job to Redis for worker processing. The worker transitions jobs through `queued -> running -> completed/failed` and persists modality-level `job_events` + `modality_results`.

`/v1/pathology` is implemented with deterministic typed outputs and optional artifact-backed loading, and `/v1/agent/query` is grounded to multimodal outputs in a research-only posture, only reaching out to PubMed for literature-focused questions.
`/v1/transcriptomics` now returns typed, deterministic availability-aware responses (artifact/modality-result/counts-backed when present).
`/v1/clinical` now returns deterministic typed outputs with source-aware availability/provenance semantics; `/v1/fusion` remains scaffolded.

## Pathology endpoint behavior (detailed)

Pathology routes exposed by this API:
- `GET /v1/pathology/slides/{slide_id}/tissue-composition`
- `GET /v1/pathology/slides/{slide_id}/heatmap`
- `POST /v1/pathology/slides/{slide_id}/evidence`

### 1) Artifact-backed first, SegLung source second, deterministic fallback third (with strict mode)

Pathology section resolution now follows this precedence:
1. sectioned artifact JSON from `PATHOLOGY_ARTIFACT_DIR`
2. SegLungTCGA segmentation artifact from `PATHOLOGY_SEGLUNG_DIR`
3. deterministic research-only fallback response

Strict missing-data mode preserves artifact-only behavior. When strict mode is enabled, the API returns `404` if a schema-valid artifact section is absent (it will not silently use SegLung or deterministic fallback).

Strict missing-data mode is available per request and by default-env:
- query param: `strict_missing=true` on `/tissue-composition`, `/heatmap`, `/evidence`
- env default: `PATHOLOGY_STRICT_MISSING_DATA=true`

When strict mode is enabled, the endpoint returns `404` with explicit missing-data detail instead of deterministic fallback.

Supported section keys inside each artifact:
- `tissue_composition`
- `heatmap`
- `evidence`

If a section is malformed or missing and strict mode is disabled, that section is skipped and the resolver continues to SegLung then deterministic fallback.

### 2) Robust ID resolution (no symlink dependency)

Pathology artifact lookup uses resolver logic in `apps/api/services/pathology_id_resolution.py`.

Resolver behavior:
- Derives case IDs from slide IDs (`TCGA-XX-YYYY-DX1` → `TCGA-XX-YYYY`)
- Expands candidate identifiers (full slide ID, short slide ID, full/short case IDs)
- Resolves files by exact/prefix/contains matching in **root + recursive subdirectories**
- Prefers real files over symlink aliases when multiple candidates exist
- Uses deterministic tie-breaking (identifier priority → symlink rank → path depth → lexical path)
- Supports modality-specific suffix sets:
  - artifacts: `.json`
  - heatmaps: `.png/.jpg/.jpeg/.webp`
  - WSI assets: `.svs/.tif/.tiff/.ndpi/.scn/.mrxs`

This allows short-ID requests (for example `TCGA-05-4244-DX1`) to resolve correctly even when only full manifest-native IDs exist in nested storage layouts.

### 3) Response semantics

- `tissue-composition`: returns fractions + QC block
- `heatmap`: returns `heatmap_uri` + `viewport_hint` for viewer positioning
- `evidence`: returns top evidence tiles (`tile_id`, `score`, `rationale`, `bbox`, `tile_coordinates`)

Each pathology response includes:
- metadata (`method`, `version`, `timestamp`, `proxy_estimate=true`)
- provenance (`data_source` = `artifact | seglung | deterministic_fallback`, resolver strategy, source path/hash/timestamp, model/checkpoint/run/embedding identifiers when available, and `tile_encoder_model_id` for path-B policy visibility)

All outputs remain explicitly research-only.

### 4) Frontend linkage

`apps/web/components/panels/pathology-panel.tsx` hosts the Enso deep-zoom viewer (`apps/web/components/panels/enso-pathology-viewer.tsx`).

The frontend now checks `/v1/pathology/slides/{slide_id}/viewer-config` for:
- `deepzoom_available` + `deepzoom_unavailable_reason`
- fallback image URLs (`fallback_preview_url`, `fallback_heatmap_url`)

When deep-zoom is unavailable (for example slide missing in Enso embeddings/proxy), the UI switches to static preview/heatmap mode instead of hard failing.

### 5) Pathology runtime env knobs

- `TCGA_FULL475_ROOT` — optional root folder for default pathology/transcriptomics data subpaths.
- `PATHOLOGY_ARTIFACT_DIR` — sectioned pathology JSON artifacts.
- `PATHOLOGY_SEGLUNG_DIR` — optional SegLungTCGA segmentation artifacts (used before deterministic fallback when strict mode is off).
- `PATHOLOGY_TILE_ENCODER_MODEL` — path-B encoder model id surfaced in provenance (`google/path-foundation` default).
- `PATHOLOGY_HEATMAP_DIR` — optional standalone heatmap image directory.
- `PATHOLOGY_WSI_DIR` — optional standalone WSI image directory.
- `ENSO_EMBEDDINGS_DIR` — embedding root used for robust Enso slide-id resolution + viewer deep-zoom availability contract.
- `ENSO_API_BASE_URL` — upstream Enso API base URL for DZI/tile/heatmap proxy routes.

`ENSO_EMBEDDINGS_DIR` takes precedence over `TCGA_FULL475_ROOT` when both are set.

## Transcriptomics endpoint behavior (MVP)

Transcriptomics routes exposed by this API:
- `GET /v1/transcriptomics/{case_id}/cyt`
- `GET /v1/transcriptomics/{case_id}/gep`
- `GET /v1/transcriptomics/{case_id}/tide` *(requires `experimental=true` query param)*
- `POST /v1/transcriptomics/{case_id}/evidence`
- `GET /v1/transcriptomics/{case_id}/deg-volcano`
- `GET /v1/transcriptomics/coverage`

### Response contract

`/cyt`, `/gep`, and `/tide` now return typed payloads with explicit availability + governance semantics:
- `value`: float when available, `null` when unavailable
- `available`: boolean
- `availability_code`: typed status (`available`, `missing_input`, `precompute_missing`, `frozen_reference_unavailable`, etc.)
- `data_source`: one of `artifact | modality_result | counts_tsv | unavailable`
- `unavailable_reason`: nullable reason string for missing/non-computable cases
- `precompute` (TIDE): required/available/source semantics plus optional run metadata
- `gep_reference` (GEP governance): required/available/valid + reference id/hash/path
- `meta`: method/version/timestamp/proxy metadata

`/evidence` returns:
- `top_genes` (normalized counts)
- `notes`
- `qc` block (`has_rna_input`, panel coverage, missing genes)
- same availability/data-source semantics as metric endpoints
- `gep_reference` governance block

`/deg-volcano` returns structured interactive data (JSON, no rendered image):
- `points[]` with `gene_symbol`, `x` (log2FC proxy), `y` (-log10 p proxy), `p_value_proxy`, `direction`, significance flags, and optional reference z-score
- `plot` config with axis labels, thresholds, proxy semantics, and point counts
- `available` / `availability_code` / `unavailable_reason` + `data_source`
- explicit proxy note that p-values are approximate research-only estimates

`/coverage` returns an audit/report payload with per-case transcriptomics presence + missingness for MVP + release-gate semantics:
- case-level `has_rna_input`, `cyt_available`, `gep_available`, `tide_available`, `tide_precompute_available`, `evidence_available`
- case-level `gep_reference_required`, `gep_reference_valid`, `release_gate_blockers`
- `missing_components` list (`rna_input`, `cyt`, `gep`, `evidence`, `tide_experimental`, optional `gep_reference`)
- aggregate summary counts (`cases_with_full_mvp_coverage`, `cases_missing_tide_precompute`, `cases_missing_gep_reference`, etc.)

### Data-source resolution order

For each case, transcriptomics services resolve in deterministic order:
1. precomputed artifact JSON (`TRANSCRIPTOMICS_ARTIFACT_DIR`)
2. persisted `modality_results` payload (`modality="transcriptomics"`)
3. STAR-count delimited file parse from `TRANSCRIPTOMICS_COUNTS_DIR` (expects `gene_name` + `tpm_unstranded` when available)
4. explicit unavailable typed response

### Environment knobs

- `TRANSCRIPTOMICS_ARTIFACT_DIR` — directory of precomputed per-case transcriptomics JSON artifacts.
- `TRANSCRIPTOMICS_COUNTS_DIR` — directory of RNA STAR-count TSV/CSV/TXT files for on-demand CYT/GEP/evidence derivation.
- `TRANSCRIPTOMICS_COVERAGE_COHORT_CSV` — optional cohort CSV/TSV used to seed `GET /transcriptomics/coverage` case list.
- `TRANSCRIPTOMICS_GEP_REFERENCE_STATS_JSON` — optional frozen reference stats (`mean`/`std`) for GEP z-score normalization.
- `TRANSCRIPTOMICS_GEP_REFERENCE_REQUIRED` — when `true`, GEP from counts requires a valid frozen-reference payload.
- `TRANSCRIPTOMICS_GEP_REFERENCE_ID` — optional explicit governance reference identifier surfaced in API responses.

### Transcriptomics coverage release-gate script

Validate release thresholds from coverage JSON output:

```bash
python3 scripts/check_transcriptomics_coverage_gate.py \
  --coverage-json path/to/transcriptomics_coverage.json \
  --strict
```

Useful flags:
- `--expected-cases-total <N>`
- `--max-missing-mvp-coverage <N>`
- `--max-missing-tide-precompute <N>`
- `--max-missing-gep-reference <N>`
- `--fail-on-release-blockers`

## Clinical endpoint behavior (MVP)

Clinical routes exposed by this API:
- `GET /v1/clinical/{case_id}/patient-summary`
- `GET /v1/clinical/{case_id}/eligibility`
- `GET /v1/clinical/{case_id}/survival-baseline`

### Response contract

All clinical route responses now include:
- `available`: boolean
- `data_source`: one of `artifact | modality_result | clinical_xml | case_metadata | unavailable`
- `unavailable_reason`: nullable reason string when route-level fields are insufficient
- `provenance`: source paths/records + extracted field list + parser notes
- `meta`: method/version/timestamp/proxy metadata

Route payload specifics:
- `/patient-summary`: `stage`, `smoking_status`, `age_at_diagnosis`, `diagnosis`, `sex`, `vital_status`, `report_highlights`
- `/eligibility`: rule-based or precomputed `eligible_trials`, `eligibility_label`, criterion-level rationale
- `/survival-baseline`: rule-based or precomputed `risk_group`, `baseline_months`, `confidence_interval`, prognostic factors

### Data-source resolution order

For each case, clinical services resolve in deterministic order:
1. precomputed clinical artifact JSON (`CLINICAL_ARTIFACT_DIR`)
2. persisted `modality_results` payload (`modality="clinical"`)
3. parsed TCGA clinical XML + optional report text highlights (`CLINICAL_XML_DIR`, `CLINICAL_REPORTS_DIR`)
4. persisted `cases` / `files` metadata fallback
5. explicit typed unavailable response

### Environment knobs

- `CLINICAL_ARTIFACT_DIR` — directory of precomputed per-case clinical JSON artifacts.
- `CLINICAL_XML_DIR` — directory containing TCGA clinical XML files.
- `CLINICAL_REPORTS_DIR` — optional directory of per-case report text files (`.txt/.md/.text`) used for highlights + ECOG/stage hints.

## Pathology: production-readiness gaps (current)

Even with artifact-backed + strict-mode pathology endpoints, this is still a research prototype. Main missing pieces before production-like readiness:

1. **Inference + artifact generation lifecycle**
   - Current API consumes precomputed artifacts; it does not yet run Enso inference or artifact refresh jobs in-service.

2. **Heatmap asset serving hardening**
   - Needs a fully standardized image serving strategy (signed/object-store URLs or controlled static proxy) with stronger availability/error semantics.

3. **Coverage completeness gate**
   - Not all slides have embeddings/artifacts yet. Release gate should require complete manifest coverage (or explicit, user-visible missingness semantics).

4. **Operational hardening**
   - AuthN/AuthZ, quotas/rate limiting, audit logging, monitoring/alerting, and stricter config separation are still pending.

## LUAD embedding coverage audit (manifest ↔ embeddings ↔ artifacts)

From repo root, run:

```bash
python3 scripts/audit_luad_embedding_coverage.py
```

By default, the audit resolves paths in this order:

1. explicit CLI flags (`--manifest`, `--embeddings-dir`, `--artifacts-dir`)
2. env overrides (`LUAD_AUDIT_MANIFEST`, `LUAD_AUDIT_EMBEDDINGS_DIR`, `LUAD_AUDIT_ARTIFACTS_DIR`)
3. compatibility env aliases (`ENSO_EMBEDDINGS_DIR`, `PATHOLOGY_ARTIFACT_DIR`)
4. `TCGA_FULL475_ROOT`-derived defaults
5. repo-relative fallbacks:
   - `hansons-context/tcga_downloads/tcga_luad_exact_matched_manifest_slides.tsv`
   - `data/luad/embeddings/level0`
   - `data/pathology_artifacts/full475`

Stable outputs:
- `luad_embedding_coverage_audit.csv`
- `luad_embedding_coverage_summary.json`

Coverage report now includes deterministic missing-id/orphan-id lists, artifact section completeness, and a `rows_digest_sha256` checksum.

Useful gate flags:
- `--expected-slide-count 475`
- `--strict`
- `--fail-on-missing-embeddings`
- `--fail-on-missing-artifacts`
- `--fail-on-incomplete-artifacts`
- `--fail-on-orphan-embeddings`

Example full475 gate run:

```bash
python3 scripts/audit_luad_embedding_coverage.py \
  --expected-slide-count 475 \
  --strict
```

## Pathology artifact bundle validation

Run structure + manifest-alignment validation for artifact JSON files:

```bash
python3 scripts/validate_pathology_artifacts.py
```

Default validation report output:
- `pathology_artifact_validation_report.json`

Useful options:
- `--fail-on-orphan-artifacts`
- `--allow-missing-sections`
- `--coverage-summary-json <path>`
