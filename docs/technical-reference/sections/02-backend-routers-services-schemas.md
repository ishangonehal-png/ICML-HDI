# Section 02 — Backend Routers, Services, and Schemas

## 2.1 Scope, docs-first inputs, and architecture role

This section documents the **implemented backend reference surface** for:

- `apps/api/main.py`
- `apps/api/routers/*`
- `apps/api/services/*`
- `apps/api/schemas/*`
- `apps/api/db/{base.py,session.py}` and `apps/api/models/core.py`
- `infra/db/migrations/*`

It is written after reviewing the required docs-first inputs:

- `docs/README.md`
- `docs/architecture/plan.md`
- `docs/execution/task-backlog.md`
- `docs/execution/implementation-status.md`

Architecturally, this backend implements the plan’s **specialist-branches + fusion + agent** flow (`pathology`, `transcriptomics`, `clinical` → `fusion` → `agent`) while preserving the global research-only guardrail.

---

## 2.2 Backend module map (path-referenced)

| Path | Responsibility | Primary dependencies |
|---|---|---|
| `apps/api/main.py` | FastAPI app construction, CORS, research headers, startup DB init, router registration | `core.config`, `db.session`, `routers.register_routers` |
| `apps/api/routers/*.py` | HTTP surface and request/response binding | `schemas/*`, `services/*`, `dependencies/db.py` |
| `apps/api/services/pathology.py` | Pathology section resolver with strict-missing + deterministic fallback | `schemas/pathology.py`, `services/pathology_id_resolution.py` |
| `apps/api/services/pathology_assets.py` | Heatmap/WSI file loading and Enso proxy passthrough | local asset directories, `httpx`, `services/pathology_id_resolution.py` |
| `apps/api/services/transcriptomics.py` | CYT/GEP/TIDE/evidence resolution, availability codes, governance + coverage report | DB models (`Case`, `File`, `ModalityResult`), artifact/counts files |
| `apps/api/services/clinical.py` | Clinical source resolution and deterministic eligibility/survival derivation | DB models, XML/report parsing, artifact payloads |
| `apps/api/services/fusion.py` | Provisional/refined multimodal score, attribution, similar-case retrieval | pathology + transcriptomics services, DB clinical payloads |
| `apps/api/services/pathology_id_resolution.py` | Deterministic recursive ID/file resolution strategy | `pathlib`, `glob`, regex normalization |
| `apps/api/schemas/*.py` | Typed API contracts (Pydantic), strict validators, availability/provenance shape | Pydantic v2 |
| `apps/api/models/core.py` | SQLAlchemy ORM entities (`cases`, `files`, jobs/results lifecycle tables) | `db.base.Base` |
| `apps/api/db/session.py` | Engine/session factory + optional auto-create | `core.config`, SQLAlchemy |
| `infra/db/migrations/env.py` | Alembic runtime integration with backend metadata | `core.config.settings`, `db.base.Base`, `models.core` |
| `infra/db/migrations/versions/0001_initial_core.py` | Canonical initial Postgres schema migration | Alembic `op`, SQLAlchemy |

### Runtime dependency diagram (text)

```text
HTTP Client
  -> FastAPI app (apps/api/main.py)
    -> Router handler (apps/api/routers/*.py)
      -> Service layer (apps/api/services/*.py)
        -> [A] Postgres (apps/api/models/core.py via SQLAlchemy session)
        -> [B] Filesystem artifacts (JSON/XML/report/counts/WSI/heatmap)
        -> [C] Enso API proxy (pathology deep zoom/tiles/heatmaps)
      -> Typed response models (apps/api/schemas/*.py)
```

---

## 2.3 Application bootstrap and API boundary (`apps/api/main.py`)

`apps/api/main.py` centralizes backend runtime policy:

1. **Startup lifecycle**
   - `lifespan()` calls `init_db()` from `apps/api/db/session.py`.
   - `init_db()` conditionally runs `Base.metadata.create_all(...)` when `AUTO_CREATE_TABLES=true` (development convenience path).

2. **Global API metadata and posture**
   - App title uses `settings.app_name`.
   - Description explicitly states research-only proxy behavior.

3. **CORS**
   - Allows localhost frontend origins (`3000`) for local Next.js integration.

4. **Research headers middleware**
   - Every HTTP response gets:
     - `X-Research-Use-Only: true`
     - `X-Clinical-Use: not-intended`

5. **Router registration model**
   - `register_routers(app, api_prefix=settings.api_v1_prefix)` in `apps/api/routers/__init__.py`.
   - `health` is mounted without `/v1`; all others are mounted under `/v1`.

This split keeps health checks globally reachable and version-scopes product endpoints.

---

## 2.4 Route inventory + endpoint handler abstraction

> All routes below are implemented in `apps/api/routers/*`. Paths are shown as served (with `/v1` where applicable).

### Core and orchestration routes

| Method + path | Handler | Request schema | Response schema/type | Service/data path | Missing/provenance behavior |
|---|---|---|---|---|---|
| `GET /health` | `health` (`routers/health.py`) | — | plain dict | reads `settings.app_env` | research flag only |
| `POST /v1/uploads/init` | `init_upload_session` (`routers/uploads.py`) | `UploadInitRequest` | `UploadInitResponse` | `ensure_case_exists` + insert `UploadSession` | no fallback; DB-backed |
| `POST /v1/uploads/files` | `attach_upload_files` | raw dict | stub dict | `research_stub_response` | deterministic stub |
| `POST /v1/analysis/jobs` | `create_analysis_job` (`routers/analysis.py`) | `AnalysisJobCreateRequest` | `AnalysisJobResponse` | validates upload session, `ensure_case_exists`, inserts `AnalysisJob` + `JobEvent` | hard errors on missing/mismatched upload session |
| `GET /v1/analysis/jobs/{job_id}` | `get_analysis_job` | path UUID | `AnalysisJobDetailResponse` | fetches `AnalysisJob`, `JobEvent`, `ModalityResult` | `404` if job missing |
| `GET /v1/analysis/jobs/{job_id}/artifacts` | `get_analysis_job_artifacts` | path UUID | stub dict | `research_stub_response` | deterministic stub |

### Pathology routes

| Method + path | Handler | Response schema/type | Service calls | Missing/provenance behavior |
|---|---|---|---|---|
| `GET /v1/pathology/slides/{slide_id}/tissue-composition` | `get_tissue_composition_route` | `PathologyTissueCompositionResponse` | `get_tissue_composition` | strict mode may `404`; non-strict deterministic fallback with provenance `data_source=deterministic_fallback` |
| `GET /v1/pathology/slides/{slide_id}/heatmap` | `get_slide_heatmap` | `PathologyHeatmapResponse` | `get_heatmap` | same strict/fallback semantics |
| `POST /v1/pathology/slides/{slide_id}/evidence` | `get_pathology_evidence` | `PathologyEvidenceResponse` | `get_evidence` | same strict/fallback semantics |
| `GET /v1/pathology/slides/{slide_id}/heatmap/image` | `get_slide_heatmap_image` | binary `Response` | `load_heatmap_image` | `404` if no image asset |
| `GET /v1/pathology/slides/{slide_id}/preview/image` | `get_slide_preview_image` | binary `Response` | `load_slide_preview_image` | `404` with explicit detail if no WSI/heatmap preview |
| `GET /v1/pathology/slides/{slide_id}/dzi` | `get_slide_dzi` | binary `Response` | `resolve_enso_slide_id` + `proxy_enso_asset` | maps Enso proxy failures to HTTPException |
| `GET /v1/pathology/slides/{slide_id}/tile/{level}/{tile_name}` | `get_slide_tile` | binary `Response` | same as above | same |
| `GET /v1/pathology/slides/{slide_id}/attention-heatmap` | `get_slide_attention_heatmap` | binary `Response` | same as above + forwarded query params | forwards selected upstream headers |
| `GET /v1/pathology/slides/{slide_id}/viewer-config` | `get_slide_viewer_config` | plain dict | `resolve_enso_slide_id` | deterministic URL template contract |

### Transcriptomics, clinical, fusion, and agent routes

| Method + path | Handler | Response schema | Core service calls | Behavior highlights |
|---|---|---|---|---|
| `GET /v1/transcriptomics/coverage` | `get_transcriptomics_coverage` | `TranscriptomicsCoverageResponse` | `get_transcriptomics_coverage_report` | cohort-level missingness/release-gate summary |
| `GET /v1/transcriptomics/{case_id}/cyt` | `get_cyt` | `TranscriptomicsMetricResponse` | `get_cyt_signature` | availability-coded metric |
| `GET /v1/transcriptomics/{case_id}/gep` | `get_gep` | `TranscriptomicsMetricResponse` | `get_gep_signature` | includes frozen-reference governance |
| `GET /v1/transcriptomics/{case_id}/tide` | `get_tide` | `TranscriptomicsMetricResponse` | `get_tide_signature` | requires `experimental=true`, else `400` |
| `POST /v1/transcriptomics/{case_id}/evidence` | `get_evidence` | `TranscriptomicsEvidenceResponse` | `get_transcriptomic_evidence` | evidence + QC + availability |
| `GET /v1/clinical/{case_id}/patient-summary` | `get_patient_summary` | `ClinicalPatientSummaryResponse` | `get_clinical_patient_summary` | source-aware availability/provenance |
| `GET /v1/clinical/{case_id}/eligibility` | `get_patient_eligibility` | `ClinicalEligibilityResponse` | `get_clinical_eligibility` | precomputed override or deterministic rule engine |
| `GET /v1/clinical/{case_id}/survival-baseline` | `get_survival_baseline` | `ClinicalSurvivalBaselineResponse` | `get_clinical_survival_baseline` | precomputed override or deterministic baseline logic |
| `POST /v1/fusion/{case_id}/score` | `score_case` | `FusionScoreResponse` | `get_fusion_score` | provisional/refined mode with modality contributions |
| `GET /v1/fusion/{case_id}/attribution` | `get_case_attribution` | `FusionAttributionResponse` | `get_fusion_attribution` | returns active score + modality-level attribution |
| `GET /v1/fusion/{case_id}/similar-cases` | `get_similar_cases` | `FusionSimilarCasesResponse` | `get_fusion_similar_cases` | deterministic candidate generation + distance policy |
| `POST /v1/agent/query` | `query_agent` | `AgentQueryResponse` | fusion + pathology + transcriptomics services | composes grounded narrative + citations + missing-modality acknowledgment |

---

## 2.5 Router module deep dive

### `apps/api/routers/uploads.py`

- `init_upload_session` is the ingestion entrypoint:
  - Validates optional `case_id`/`cohort` through `UploadInitRequest` validator.
  - Calls `ensure_case_exists` when `case_id` is present.
  - Creates persisted `UploadSession` row.
- `attach_upload_files` is currently scaffolded and intentionally returns a typed research stub.

### `apps/api/routers/analysis.py`

- `create_analysis_job` enforces upload/session integrity:
  - `404` when `upload_session_id` does not exist.
  - `409` when payload `case_id` conflicts with session `case_id`.
  - Mutates upload session case binding if session had no case.
- Job creation writes both `analysis_jobs` row and first `job_events` row (`event_type="job_created"`).
- Detail retrieval composes relational view from `analysis_jobs`, `job_events`, and `modality_results`.

### `apps/api/routers/pathology.py`

- Distinguishes **typed JSON panels** (tissue/heatmap/evidence) from **binary/image/proxy panel endpoints**.
- Catches `PathologyDataUnavailableError` and converts it to HTTP `404` with explicit detail.
- Uses `_proxy_enso_response(...)` wrapper to normalize upstream proxy errors into user-facing API errors.

### `apps/api/routers/transcriptomics.py`

- A thin contract layer over `services/transcriptomics.py`.
- `GET .../tide` has explicit route-level feature gate (`experimental=true`), preventing accidental production interpretation.

### `apps/api/routers/clinical.py`

- Delegates all source resolution and deterministic fallback logic to `services/clinical.py`.
- Router surface remains intentionally minimal to keep source precedence centralized in one service module.

### `apps/api/routers/fusion.py`

- Exposes score/attribution/similarity as separate endpoint responsibilities.
- `FusionScoreRequest.include_rna` controls **requested** mode; service decides **actual mode used**.

### `apps/api/routers/agent.py`

- Orchestrates multi-endpoint retrieval and synthesis into one grounded response.
- Builds:
  - `answer` (human-readable summary),
  - `citations` (endpoint-backed references),
  - `modalities` (availability snapshots),
  - `acknowledged_missing_modalities` (explicit missingness acknowledgement).

---

## 2.6 Service-layer deep dive (module-by-module)

### 2.6.1 Shared utility services

| Path | Functions | Purpose |
|---|---|---|
| `services/cases.py` | `ensure_case_exists` | Idempotent case bootstrap in `cases` table from any entrypoint |
| `services/responses.py` | `research_stub_response` | Uniform placeholder shape for scaffolded routes |

### 2.6.2 Pathology ID resolution (`services/pathology_id_resolution.py`)

This module is critical because it enforces deterministic matching of short/full identifiers across nested directories.

**Resolver abstraction table**

| Function | Abstraction role | Determinism/constraints |
|---|---|---|
| `derive_short_case_id` | Normalizes arbitrary identifiers to stable case token (e.g., TCGA triplet) | Handles DX suffix stripping and path tokenization |
| `derive_short_slide_id` | Produces compact slide id (`...-DX1`) | Uses regex extraction with case-id reconstruction |
| `enumerate_candidate_identifiers` | Expands full/short/stem/case variants | Preserves order and de-duplicates |
| `resolve_best_matching_file` | Generic recursive resolver across suffix class | Ordered matching: exact → prefix → contains; prefers non-symlink, shallower path, lexical tie-break |
| `iter_artifact_json_paths` | Artifact-specific multi-identifier lookup | At most one best hit per identifier; preserves identifier priority |

### 2.6.3 Pathology asset and proxy service (`services/pathology_assets.py`)

Key functions and structure:

- `resolve_heatmap_path` / `resolve_slide_path` read from env-configured asset directories.
- `load_heatmap_image` returns `ImagePayload` bytes + media type.
- `load_slide_preview_image` attempts WSI preview generation via OpenSlide, then falls back to heatmap image.
- `resolve_enso_slide_id` maps caller slide IDs into Enso embedding IDs via deterministic candidate scoring.
- `proxy_enso_asset` fetches upstream binary payloads with controlled timeout and optional header forwarding.

This module provides the binary-serving boundary and upstream proxy boundary, cleanly separated from typed pathology JSON semantics.

### 2.6.4 Pathology typed-output service (`services/pathology.py`)

**Public API:** `get_tissue_composition`, `get_heatmap`, `get_evidence`.

**Internal resolver flow:**

```text
Input slide_id
  -> derive_case_id_from_slide_id
  -> iterate artifact JSON candidates (slide_id + case_id variants)
  -> section-specific extraction + Pydantic model validation
  -> if valid artifact section: return artifact-backed response + artifact provenance
  -> else if strict_missing enabled: raise PathologyDataUnavailableError
  -> else: return deterministic fallback payload + deterministic provenance
```

**Section abstraction table**

| Section function | Artifact extractor | Deterministic fallback | Provenance mode |
|---|---|---|---|
| `get_tissue_composition` | `_artifact_tissue_composition` | `_deterministic_tissue_composition` | artifact or deterministic_fallback |
| `get_heatmap` | `_artifact_heatmap` | `_deterministic_heatmap` | artifact or deterministic_fallback |
| `get_evidence` | `_artifact_evidence` | `_deterministic_evidence` | artifact or deterministic_fallback |

Important helpers:

- `_raise_if_strict_missing(...)` differentiates four failure classes (env missing, no artifact, no section, invalid section).
- `_normalize_evidence_tiles(...)` augments tile payloads with inferred `tile_coordinates` and `bbox` when absent.
- `_build_artifact_provenance(...)` harvests model/checkpoint/run/embedding metadata from section + artifact payload blocks.

### 2.6.5 Transcriptomics service (`services/transcriptomics.py`)

This is the densest service module and encodes both metric derivation and governance semantics.

#### Source precedence and resolver strategy

| Stage | Function(s) | Precedence/order | Output impact |
|---|---|---|---|
| Candidate ID expansion | `_candidate_identifiers` | case_id + short id + DB-linked aliases | broad matching for all downstream sources |
| Artifact payload load | `_load_artifact_payloads` | first-class priority | can directly satisfy CYT/GEP/TIDE/evidence |
| Modality payload load | `_load_modality_payloads` | second priority | fallback typed source |
| Counts expression load | `_load_expression_from_counts_directory` | third priority | compute CYT/GEP/evidence from expression |
| Expression source choice | `_choose_expression_source` | artifact > modality_result > counts_tsv | determines `data_source` for computed metrics |

#### Metric/evidence abstraction table

| Function | Primary behavior | Availability semantics |
|---|---|---|
| `_resolve_cyt` | artifact value → modality value → compute from GZMA/PRF1 | returns `missing_input` or `insufficient_gene_coverage` when unavailable |
| `_resolve_gep` | artifact value → modality value → compute 18-gene proxy (+ frozen-reference normalization if available) | can return `frozen_reference_unavailable`, `missing_input`, or `insufficient_gene_coverage` |
| `_resolve_tide` | only accepts precomputed artifact/modality TIDE | never computes from counts; returns `precompute_missing` or `missing_input` |
| `_resolve_evidence` | artifact top genes → modality top genes → derive top genes from expression | returns `evidence_unavailable` or `missing_input` if no evidence |
| `get_transcriptomics_coverage_report` | case-level audit of RNA presence + metric coverage + release blockers | summarizes cohort readiness and governance blockers |

#### Governance and release controls

- `_load_gep_reference_data()` reads frozen reference stats from `TRANSCRIPTOMICS_GEP_REFERENCE_STATS_JSON` and computes:
  - `required`, `available`, `valid`
  - `reference_id`, `reference_sha256`, `source_path`
- `TRANSCRIPTOMICS_GEP_REFERENCE_REQUIRED=true` can hard-block computed GEP when reference is invalid/missing.
- Coverage endpoint emits `missing_components` and `release_gate_blockers` to support pipeline gating.

### 2.6.6 Clinical service (`services/clinical.py`)

Clinical logic is organized around explicit source precedence and deterministic rule engines.

#### Source resolver chain

| Resolver | Function | Trigger | Success condition |
|---|---|---|---|
| Artifact JSON | `_resolve_from_artifacts` | `CLINICAL_ARTIFACT_DIR` configured | extracted features exist or precomputed sections exist |
| Modality payload | `_resolve_from_modality_results` | DB available + clinical modality rows | same as above |
| XML + report | `_resolve_from_xml_and_reports` | `CLINICAL_XML_DIR` configured | XML/report parsing yields features or precomputed sections |
| Case/file metadata | `_resolve_from_case_metadata` | DB available + matching case rows | metadata/report fallback yields usable fields |
| Explicit unavailable | `_resolve_case` default | none resolved | returns empty feature set + unavailable notes |

#### Computation abstraction table

| Function | Behavior | Deterministic rules |
|---|---|---|
| `_extract_precomputed_eligibility` | uses payload-provided eligibility when valid | supports explicit `available=false` with reason |
| `_compute_eligibility` | rule-based criteria over stage/age/ECOG/smoking | emits criterion-level statuses + label mapping |
| `_extract_precomputed_survival` | uses payload-provided survival baseline when valid | validates risk group + confidence interval shape |
| `_compute_survival_baseline` | derives baseline months from observed death, stage, follow-up + modifiers | applies stage/age/ECOG/smoking adjustments with bounded CI |
| `_build_provenance` | constructs `ClinicalProvenance` with paths, records, extracted fields, notes | de-duplicates source references |

### 2.6.7 Fusion service (`services/fusion.py`)

Fusion combines modality signals with mode-aware weighting.

#### Scoring abstraction

| Function | Role | Notes |
|---|---|---|
| `_build_fusion_context` | canonical fusion state builder for score/attribution/similarity | computes provisional/refined, active mode, contributions, CIs, provenance |
| `_resolve_pathology_signal` | converts tissue + evidence outputs into signal | pathology effectively always available due pathology fallback chain |
| `_resolve_clinical_minimum` | extracts minimal clinical signal from DB payloads or deterministic synthetic features | deterministic fallback if no payload |
| `_resolve_transcriptomics_signal` | derives weighted signal from CYT/GEP/TIDE/evidence if available | can be unavailable with explicit reason |
| `_score_from_weights` | weighted sum with signal fallback to 0.5 when missing | clipped and rounded |
| `_build_confidence_interval` | score CI width policy based on data-source reliability | narrows with artifact-backed + transcriptomics-used context |

Mode semantics:

- `requested_mode = refined` when `include_rna=true`, else `provisional`.
- `mode_used = refined` **only** if transcriptomics signal is available; otherwise deterministic downgrade to provisional.

### 2.6.8 Cross-service dependency diagram

```text
clinical.py ---------------------> (Case, File, ModalityResult)
transcriptomics.py --------------> (Case, File, ModalityResult)
pathology.py --------------------> pathology_id_resolution.py
pathology_assets.py -------------> pathology_id_resolution.py + Enso API
fusion.py -----------------------> pathology.py + transcriptomics.py + DB clinical payloads
agent router --------------------> fusion.py + pathology.py + transcriptomics.py
```

---

## 2.7 Class-by-class reference (schemas + service structures)

## 2.7.1 Pydantic schema classes (`apps/api/schemas/*`)

### `schemas/uploads.py`

| Class | Purpose | Key validation/constraints |
|---|---|---|
| `UploadInitRequest` | Initialize upload session context | `case_id`/`cohort` optional but non-empty when provided; `extra="forbid"` |
| `UploadInitResponse` | Persisted upload session envelope | includes `research_use_only=True` |

### `schemas/analysis.py`

| Class | Purpose | Key validation/constraints |
|---|---|---|
| `AnalysisJobCreateRequest` | Job creation input | `case_id` must be non-empty after trim |
| `JobEventResponse` | Event timeline row | typed event/message/payload/timestamp |
| `ModalityResultResponse` | Modality result row | typed modality payload metadata |
| `AnalysisJobResponse` | Base job state | includes timestamps + research flag |
| `AnalysisJobDetailResponse` | Expanded job detail | extends base with `result_summary`, events, modality results |

### `schemas/pathology.py`

| Class | Purpose | Key validation/constraints |
|---|---|---|
| `MethodMetadata` | Method/version/timestamp envelope | `proxy_estimate` literal `True` |
| `PathologyProvenance` | Source/provenance contract | explicit data source + resolver + artifact/model metadata |
| `TissueFraction` | Tissue proportion row | fraction in `[0,1]` |
| `PathologyQc` | QC payload | coverage in `[0,1]` |
| `PathologyTissueCompositionResponse` | Tissue panel response | strict extra forbid |
| `ViewportHint` | Relative viewport coordinates | each component in `[0,1]` |
| `PathologyHeatmapResponse` | Heatmap panel response | includes URIs + viewport + provenance |
| `TileCoordinates` | Evidence tile grid coordinates | non-negative row/col |
| `EvidenceTile` | Evidence tile detail | score in `[0,1]`, optional bbox/coordinates |
| `PathologyEvidenceResponse` | Evidence panel response | list of top evidence tiles |

### `schemas/transcriptomics.py`

| Class | Purpose | Key validation/constraints |
|---|---|---|
| `TranscriptomicsPrecomputeStatus` | TIDE precompute metadata | required/available/source + optional run info |
| `GepReferenceGovernance` | Frozen-reference governance status | required/available/valid + reference ID/hash/path |
| `TranscriptomicsMetricResponse` | CYT/GEP/TIDE metric contract | model validator enforces `available` ↔ `value` and availability code consistency |
| `TranscriptomicsEvidenceGene` | Evidence gene row | normalized count + optional raw TPM |
| `TranscriptomicsEvidenceQc` | Evidence QC metrics | panel size and missing genes |
| `TranscriptomicsEvidenceResponse` | Evidence response contract | availability-coded with QC and governance |
| `TranscriptomicsCaseCoverage` | Per-case coverage audit row | includes release-gate blocker fields |
| `TranscriptomicsCoverageSummary` | Cohort aggregate coverage counts | all counters non-negative |
| `TranscriptomicsCoverageResponse` | Coverage endpoint envelope | summary + case list + meta |

### `schemas/clinical.py`

| Class | Purpose | Key validation/constraints |
|---|---|---|
| `ClinicalProvenance` | Clinical source trace | source paths/records/fields/notes |
| `ClinicalPatientSummaryResponse` | Summary panel contract | validator enforces populated fields when `available=true` |
| `ClinicalEligibilityCriterion` | Criterion-level decision row | status in `met/not_met/unknown` |
| `ClinicalEligibilityResponse` | Eligibility panel contract | validator requires trials+label when available |
| `ClinicalSurvivalBaselineResponse` | Survival panel contract | validator enforces baseline+risk+CI consistency |

### `schemas/fusion.py`

| Class | Purpose | Key validation/constraints |
|---|---|---|
| `FusionScoreRequest` | Score request control | `include_rna` toggle |
| `FusionProvenance` | Fusion provenance record | non-empty `source` and `field` |
| `FusionConfidenceInterval` | CI bounds | validator enforces `upper >= lower` |
| `FusionModalityContribution` | Modality contribution record | validator enforces availability/signal/usage consistency |
| `FusionScoreResponse` | Score endpoint envelope | provisional/refined scores + per-modality details |
| `FusionAttributionResponse` | Attribution endpoint envelope | active score + modality contributions |
| `FusionSimilarCase` | Similar-case row | similarity/score/delta bounds |
| `FusionSimilarCasesResponse` | Similar-case endpoint envelope | index score + neighbors + provenance |

### `schemas/agent.py`

| Class | Purpose | Key validation/constraints |
|---|---|---|
| `AgentQueryRequest` | Agent query input | required non-empty `case_id` + `question` |
| `AgentCitation` | Citation tuple | panel/field/source/value |
| `AgentModalityAvailability` | Modality availability card | modality + source + summary |
| `AgentQueryResponse` | Grounded response envelope | answer + citations + modality snapshot + missing list |

## 2.7.2 Service structures (dataclasses/exceptions)

| Path | Structure | Role |
|---|---|---|
| `services/pathology.py` | `PathologyDataUnavailableError` | strict-missing exception with section/slide/detail context |
| `services/pathology.py` | `_ArtifactPayloadRecord` | `(path, payload)` wrapper for artifact iteration |
| `services/pathology_assets.py` | `ImagePayload` | binary image payload + media type |
| `services/pathology_assets.py` | `ProxyBinaryPayload` | proxied binary content + media type + forwarded headers |
| `services/pathology_assets.py` | `EnsoProxyError` | normalized upstream proxy error type |
| `services/pathology_assets.py` | `EmbeddingCandidate` | Enso embedding candidate scoring tuple |
| `services/transcriptomics.py` | `_ResolvedPrecompute` | internal TIDE precompute state |
| `services/transcriptomics.py` | `_GepReferenceGovernance` | internal governance representation |
| `services/transcriptomics.py` | `_LoadedGepReference` | parsed reference stats + governance |
| `services/transcriptomics.py` | `_ResolvedMetric` | per-metric internal resolved state |
| `services/transcriptomics.py` | `_ResolvedEvidence` | internal evidence resolved state |
| `services/transcriptomics.py` | `_ResolvedCase` | canonical transcriptomics case bundle |
| `services/clinical.py` | `_ClinicalFeatures` | normalized clinical feature bundle + helper predicates |
| `services/clinical.py` | `_ResolvedCase` | canonical clinical resolved source object |
| `services/clinical.py` | `_EligibilityComputation` | deterministic eligibility compute output |
| `services/clinical.py` | `_SurvivalComputation` | deterministic survival compute output |
| `services/fusion.py` | `_ResolvedModality` | modality-level fusion signal object |
| `services/fusion.py` | `_FusionContext` | full fusion computation context reused by multiple endpoints |

---

## 2.8 Persistence layer: session, ORM models, migrations

### Session and base

- `apps/api/db/base.py`: defines shared declarative base `Base`.
- `apps/api/db/session.py`:
  - `engine = create_engine(settings.database_url, pool_pre_ping=True)`
  - `SessionLocal = sessionmaker(..., autoflush=False, autocommit=False, expire_on_commit=False)`
  - `get_db()` yields request-scoped session with guaranteed close.
- `apps/api/dependencies/db.py` re-exports `get_db` for router DI.

### ORM class inventory (`apps/api/models/core.py`)

| Class | Table | Responsibility | Key relationships |
|---|---|---|---|
| `Case` | `cases` | Canonical case identity and metadata | `files`, `upload_sessions` |
| `UploadSession` | `upload_sessions` | Upload workflow session state | FK `case_id -> cases.case_id`; `files`, `analysis_jobs` |
| `File` | `files` | File-level manifest/storage metadata | FK to `cases.case_id` and `upload_sessions.id` |
| `AnalysisJob` | `analysis_jobs` | Analysis orchestration state and result summary | FK `upload_session_id`; `job_events`, `modality_results` |
| `JobEvent` | `job_events` | Append-only job timeline events | FK `job_id -> analysis_jobs.id` (cascade delete) |
| `ModalityResult` | `modality_results` | Per-modality payload snapshots tied to jobs | FK `job_id -> analysis_jobs.id` (cascade delete) |

### Migration system (`infra/db/migrations`)

- `README.md` documents Alembic usage from repo root.
- `env.py` wires Alembic to backend config and `Base.metadata`; injects `apps/api` into `sys.path` for import safety.
- `versions/0001_initial_core.py` creates all six core tables and indexes corresponding to model definitions.
- `alembic.ini` sets script location and default local Postgres URL.

Constraint alignment: the migration uses `metadata` JSON columns, UUID primary keys, and indexed case/job lookup fields matching ORM expectations.

---

## 2.9 Missing-data semantics, deterministic fallbacks, and source precedence

### 2.9.1 Cross-modality missing-data contract

| Component | Precedence order | Strict missing behavior | Deterministic fallback |
|---|---|---|---|
| Pathology (`services/pathology.py`) | artifact section lookup by candidate IDs | if `strict_missing` (query or env default) and no valid section: raise `PathologyDataUnavailableError` → HTTP `404` | section-specific deterministic payloads (fractions, viewport, evidence tiles) |
| Transcriptomics (`services/transcriptomics.py`) | artifact payload → modality_result payload → counts-derived compute | no hard exception; returns typed unavailable response with `availability_code` and `unavailable_reason` | unavailable state is explicit (not silently synthesized score except where expression permits compute) |
| Clinical (`services/clinical.py`) | artifact → modality_result → XML/report → case metadata | no hard exception; returns typed unavailable response when features absent | deterministic eligibility/survival rules run when enough normalized features exist |
| Fusion (`services/fusion.py`) | pathology + clinical always resolved (deterministic fallbacks available), transcriptomics optional | requested refined mode downgrades to provisional if transcriptomics unavailable | deterministic synthetic clinical features and synthetic similar-case IDs |
| Agent (`routers/agent.py`) | consumes fusion/pathology/transcriptomics outputs | no exception for missing modality; exposes missing list | response text and citations explicitly acknowledge missing modalities |

### 2.9.2 Transcriptomics availability/provenance semantics

`TranscriptomicsMetricResponse` and `TranscriptomicsEvidenceResponse` expose explicit state:

- `available` + `value` consistency enforced by model validator.
- `availability_code` taxonomy includes:
  - `available`
  - `invalid_case_id`
  - `missing_input`
  - `insufficient_gene_coverage`
  - `precompute_missing`
  - `frozen_reference_unavailable`
  - `evidence_unavailable`
- `data_source`: `artifact | modality_result | counts_tsv | unavailable`.
- TIDE includes `precompute` block; GEP includes frozen-reference governance block.

### 2.9.3 Pathology strictness and provenance

Pathology responses always include `PathologyProvenance`, but its contents vary by source:

- Artifact-backed: includes artifact path/hash/timestamp + discovered model/run/checkpoint metadata.
- Deterministic fallback: marks `data_source=deterministic_fallback` with sentinel model/checkpoint metadata.

Strict mode can be toggled per-request (`strict_missing=true`) or globally (`PATHOLOGY_STRICT_MISSING_DATA=true`).

### 2.9.4 Source precedence rules to preserve

The codebase depends on explicit precedence ordering. Reordering without migration/docs/test updates would alter product behavior:

1. Pathology artifact first, deterministic fallback second.
2. Transcriptomics artifact > modality > counts for expression-backed computation.
3. Clinical artifact > modality > XML/report > case metadata > unavailable.
4. Fusion mode selection depends on transcriptomics availability, not only request flag.

---

## 2.10 Extension points and constraints for contributors

### High-value extension points

1. **Router-level expansion**
   - Add route modules under `apps/api/routers/` and register in `routers/__init__.py`.
   - Keep thin-router pattern: perform business logic in services, not handlers.

2. **Service-level enhancements**
   - Pathology: add new artifact sections by mirroring the existing pattern (`_artifact_*`, deterministic fallback, strict missing branch).
   - Transcriptomics: extend metric family by adding resolver functions and including availability/governance semantics.
   - Clinical: add richer extraction paths by extending `_extract_features_from_mapping` and parser helpers while preserving precedence.
   - Fusion: add calibrated models by replacing scoring internals but preserving `FusionModalityContribution` contract.

3. **Schema evolution**
   - Add fields with explicit validators and maintain `extra="forbid"` unless contract intentionally changes.
   - Preserve consistency validators (availability/value coupling) to avoid ambiguous API states.

4. **Persistence evolution**
   - Add new ORM entities in `models/core.py` (or new model modules) and create Alembic revisions under `infra/db/migrations/versions/`.

### Non-negotiable constraints

- Maintain research-only guardrails (`proxy_estimate`, response headers, non-clinical wording).
- Keep deterministic resolver tie-break behavior in `pathology_id_resolution.py`.
- Do not collapse unavailable states into silent defaults for transcriptomics/clinical; keep explicit typed missingness.
- Do not bypass provenance payloads; new outputs must remain auditable to source path/record/run where applicable.
- Preserve endpoint compatibility expected by UI flow (`/upload` → `/analysis/{job}` → `/patient/{case}` + agent chat).

---

## 2.11 Contributor checklist for backend changes

When modifying backend routers/services/schemas/db, contributors should minimally:

1. Update the relevant file in `apps/api/{routers,services,schemas,models,db}`.
2. If schema changes affect persistence, add Alembic migration under `infra/db/migrations/versions/`.
3. Preserve or intentionally update source-precedence and missing-data semantics in docs (`docs/architecture/plan.md` and execution status docs).
4. Ensure response contracts remain research-only and provenance-aware.
5. Run API tests (`apps/api/tests`) and CI checks before merge.

This preserves the current architecture goal: a deterministic, explainable, research-only tri-modal backend that can power UI workflows and grounded agent reasoning without hidden modality assumptions.