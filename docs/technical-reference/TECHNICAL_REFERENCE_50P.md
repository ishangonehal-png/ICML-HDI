# YC AIxBio Technical Reference (Comprehensive)

This consolidated document joins the five deep-dive technical sections into a single long-form reference.

It is intended for maintainers, contributors, and reviewers who need module-by-module, class-by-class, and method-level understanding of the codebase.

## Table of Contents

- [Section 01 — System Architecture and Abstractions](#section-01--system-architecture-and-abstractions)
- [Section 02 — Backend Routers, Services, and Schemas](#section-02--backend-routers-services-and-schemas)
- [Section 03 — Frontend UI and API Client](#section-03--frontend-ui-and-api-client)
- [Section 04 — Data Pipelines, Contracts, CI, and Ops](#section-04--data-pipelines-contracts-ci-and-ops)
- [Section 05 — Testing, Security, and Production Readiness](#section-05--testing-security-and-production-readiness)


---

## Section 01 — System Architecture and Abstractions

## 1.1 Scope, docs-first grounding, and what this section defines

This section establishes the **system-level architecture contract** for the current repository state, with emphasis on:

1. end-to-end platform layers and data movement,
2. module boundaries across backend, frontend, data tooling, and CI/ops,
3. method-level contracts between layers,
4. core interaction sequences (`upload -> analysis -> patient view -> agent query`), and
5. explicit research-only boundaries and production hardening gaps.

Per docs-first requirements, this section was written after reviewing:

- `docs/README.md`
- `docs/architecture/plan.md`
- `docs/execution/task-backlog.md`
- `docs/execution/implementation-status.md`

It is also grounded in the implemented code surface under:

- backend: `apps/api/*`
- frontend: `apps/web/*`
- data tooling: `scripts/*`, `packages/mvp50/*`
- CI/ops: `.github/workflows/ci.yml`, `Makefile`, `infra/dev/docker-compose.yml`, `scripts/ci/*`, `scripts/dev/*`

This section is intentionally **architectural** (not line-by-line code commentary). Deep dives are delegated to:

- Section 02 — backend routers/services/schemas
- Section 03 — frontend UI + API client
- Section 04 — data contracts/pipelines/CI/ops

---

## 1.2 End-to-end architecture in one view

The repository implements a practical variant of the plan’s **specialist branches + fusion + agent** model (`docs/architecture/plan.md`):

- modality branches compute evidence independently (pathology, transcriptomics, clinical),
- fusion composes branch-level signals into provisional/refined risk narratives,
- agent returns grounded, citation-bearing explanations over API outputs.

### 1.2.1 Runtime topology (implemented)

```text
Browser (Next.js App Router)
  ├─ /upload
  ├─ /analysis/[job_id]
  └─ /patient/[case_id]
         │
         ▼
API client boundary (apps/web/lib/api-client/client.ts)
  - requestWithMock(...)
  - typed parsers + fallback semantics
         │
         ▼
FastAPI gateway (apps/api/main.py + apps/api/routers/*)
  - /v1/uploads, /v1/analysis, /v1/pathology, /v1/transcriptomics,
    /v1/clinical, /v1/fusion, /v1/agent
         │
         ▼
Domain service layer (apps/api/services/*)
  - source resolution (artifact/modality/db/file)
  - deterministic fallback policies
  - availability/provenance contracts
         │
   ┌─────┴───────────────────────────────────────────────┐
   ▼                                                     ▼
PostgreSQL system-of-record                         Filesystem/external assets
(apps/api/models/core.py + migrations)             (counts, artifacts, XML/reports,
(cases, files, upload_sessions, jobs, etc.)         WSI/heatmaps, Enso deep-zoom proxy)
```

### 1.2.2 Why this architecture is used

Compared to an end-to-end monolith, this architecture trades model purity for demo-time reliability and explainability:

- each branch can fail independently while returning typed unavailable states,
- fusion can degrade from refined to provisional mode when RNA is unavailable,
- agent can acknowledge missing modalities explicitly rather than hallucinating hidden context.

This behavior is visible in concrete interfaces like:

- `apps/api/schemas/transcriptomics.py` (`availability_code`, `precompute`, `gep_reference`),
- `apps/api/schemas/fusion.py` (`requested_mode`, `mode_used`, `rna_applied`),
- `apps/api/schemas/agent.py` (`citations`, `acknowledged_missing_modalities`),
- `apps/web/lib/patient-workspace.ts` (`missingModalities`, `panelSummary`).

---

## 1.3 Platform layers, boundaries, and guarantees

The architecture is best understood as a contract stack. Each layer guarantees a stable surface to the next layer.

| Layer | Primary modules | What it consumes | What it guarantees to next layer |
|---|---|---|---|
| UX/Page orchestration | `apps/web/app/upload/page.tsx`, `apps/web/app/analysis/[job_id]/page.tsx`, `apps/web/app/patient/[case_id]/page.tsx` | route params, API client methods | renderable workflow states (upload/session, job timeline, patient workspace) even under partial data |
| UI component layer | `apps/web/components/*` (upload, analysis, panels, chat) | typed UI models from API client + helper mapping | deterministic visual semantics for available/missing/error states |
| Frontend API boundary | `apps/web/lib/api-client/client.ts`, `types.ts`, `patient-workspace.ts` | backend JSON, environment base URL | normalized typed payloads; controlled fallback via `requestWithMock` when backend absent/stubbed |
| HTTP routing boundary | `apps/api/main.py`, `apps/api/routers/*` | validated request schemas, DB sessions | stable endpoint contracts, HTTP status mapping, research headers |
| Domain service layer | `apps/api/services/pathology.py`, `transcriptomics.py`, `clinical.py`, `fusion.py`, `pathology_assets.py` | DB rows, artifact files, optional Enso proxy responses | modality-specific typed outputs with provenance + explicit missingness semantics |
| Persistence layer | `apps/api/models/core.py`, `apps/api/db/session.py`, `infra/db/migrations/versions/0001_initial_core.py` | ORM writes/queries from routers/services | canonical relational state for cases, uploads, jobs, events, modality outputs |
| Data contract tooling | `scripts/build_tcga_matched_cohort.py`, `packages/mvp50/*`, `scripts/check_transcriptomics_coverage_gate.py` | raw manifests/files and contract YAML/CSV | reproducible cohort selection, lock artifacts, release-gate checks |
| CI/ops guardrail layer | `.github/workflows/ci.yml`, `scripts/ci/*`, `Makefile`, `scripts/dev/*`, `infra/dev/docker-compose.yml` | repo content + local/CI environments | coherence checks, repeatable smoke tests, deterministic dev bootstrap |

### 1.3.1 Contract shape pattern reused across layers

A recurring architecture pattern appears across backend and frontend:

1. **typed schema** (Pydantic or TS interface),
2. **availability + provenance metadata**,
3. **deterministic fallback instead of implicit nulls**,
4. **research-use markers propagated to UI/API responses**.

That pattern is central to system composability. It allows independent module hardening without rewriting every consumer.

---

## 1.4 Module-by-module map across backend, frontend, data tooling, and CI/ops

## 1.4.1 Backend map (`apps/api`)

| Module path | Key exported functions/classes | Architectural role |
|---|---|---|
| `apps/api/main.py` | `app` (FastAPI), `lifespan`, middleware setting `X-Research-Use-Only` + `X-Clinical-Use` | gateway construction, router mount, global response policy |
| `apps/api/routers/uploads.py` | `init_upload_session`, `attach_upload_files` | ingestion session bootstrap + file-attach scaffold |
| `apps/api/routers/analysis.py` | `create_analysis_job`, `get_analysis_job`, `get_analysis_job_artifacts` | analysis orchestration entry + status timeline retrieval |
| `apps/api/routers/pathology.py` | `get_tissue_composition_route`, `get_slide_heatmap`, `get_pathology_evidence`, image/deep-zoom proxy routes | pathology panel API (typed JSON + binary asset/proxy surface) |
| `apps/api/routers/transcriptomics.py` | `get_transcriptomics_coverage`, `get_cyt`, `get_gep`, `get_tide`, `get_evidence` | RNA metric/evidence + release-gate visibility |
| `apps/api/routers/clinical.py` | `get_patient_summary`, `get_patient_eligibility`, `get_survival_baseline` | clinical summary/rules endpoints |
| `apps/api/routers/fusion.py` | `score_case`, `get_case_attribution`, `get_similar_cases` | multimodal score composition and explainability |
| `apps/api/routers/agent.py` | `query_agent` | grounded narrative synthesis over modality/fusion outputs |
| `apps/api/services/cases.py` | `ensure_case_exists` | idempotent case bootstrap contract |
| `apps/api/services/responses.py` | `research_stub_response` | consistent scaffold payload contract |
| `apps/api/services/pathology_id_resolution.py` | `derive_short_case_id`, `derive_short_slide_id`, `resolve_best_matching_file`, `resolve_artifact_json_path`, `resolve_heatmap_file`, `resolve_wsi_file` | deterministic identifier normalization + recursive file resolution |
| `apps/api/services/pathology_assets.py` | `resolve_heatmap_path`, `resolve_slide_path`, `load_heatmap_image`, `load_slide_preview_image`, `resolve_enso_slide_id`, `proxy_enso_asset` | pathology binary asset + Enso bridge |
| `apps/api/services/pathology.py` | `get_tissue_composition`, `get_heatmap`, `get_evidence`, `build_pathology_metadata`, `PathologyDataUnavailableError` | typed pathology domain outputs with strict-missing/fallback policies |
| `apps/api/services/transcriptomics.py` | `get_cyt_signature`, `get_gep_signature`, `get_tide_signature`, `get_transcriptomic_evidence`, `get_transcriptomics_coverage_report`, `build_transcriptomics_metadata` | RNA resolver chain, computed signatures, governance fields, coverage summaries |
| `apps/api/services/clinical.py` | `get_clinical_patient_summary`, `get_clinical_eligibility`, `get_clinical_survival_baseline`, `build_clinical_metadata` | clinical source precedence and deterministic rule outputs |
| `apps/api/services/fusion.py` | `get_fusion_score`, `get_fusion_attribution`, `get_fusion_similar_cases`, `build_fusion_metadata` | modality blending, mode fallback (refined -> provisional), neighbor attribution |
| `apps/api/models/core.py` | `Case`, `File`, `UploadSession`, `AnalysisJob`, `JobEvent`, `ModalityResult` | persistence schema that anchors orchestration and results |
| `apps/api/schemas/*.py` | e.g., `UploadInitRequest`, `AnalysisJobResponse`, `TranscriptomicsMetricResponse`, `FusionScoreResponse`, `AgentQueryResponse` | strict API contract classes for all route surfaces |

## 1.4.2 Frontend map (`apps/web`)

| Module path | Key exported functions/components | Architectural role |
|---|---|---|
| `apps/web/app/upload/page.tsx` | `UploadPage` | SSR entrypoint to load cohort summaries and mount upload shell |
| `apps/web/components/upload/upload-shell.tsx` | `UploadShell` | upload state machine (case selection, init/upload/job transition) |
| `apps/web/components/upload/uploader.tsx` | `Uploader` | file intake + modality inference + upload progress UX |
| `apps/web/app/analysis/[job_id]/page.tsx` | `AnalysisPage` | job timeline status visualization and next-step navigation |
| `apps/web/components/analysis/analysis-status-timeline-card.tsx` | `AnalysisStatusTimelineCard` | cross-step orchestration timeline card |
| `apps/web/components/analysis/modality-status-grid.tsx` | `ModalityStatusGrid` | per-step status grid abstraction |
| `apps/web/app/patient/[case_id]/page.tsx` | `PatientPage` | multimodal workspace composition root |
| `apps/web/lib/patient-workspace.ts` | `loadPatientWorkspaceData`, `buildPatientWorkspaceViewModel` | fan-out query orchestration + missing-modality synthesis |
| `apps/web/components/patient/patient-workspace-panels.tsx` | `PatientWorkspacePanels` | center-column modality panel orchestration |
| `apps/web/components/panels/pathology-panel.tsx` | `PathologyPanel` | pathology evidence and heatmap panel contract |
| `apps/web/components/panels/enso-pathology-viewer.tsx` | `EnsoPathologyViewer` | OpenSeadragon viewer + DZI/tile/attention-heatmap proxy integration |
| `apps/web/components/panels/transcriptomics-panel.tsx` | `TranscriptomicsPanel` | CYT/GEP/TIDE/evidence rendering with source badges |
| `apps/web/components/panels/clinical-summary-panel.tsx` | `ClinicalSummaryPanel` | stage/diagnosis/eligibility/survival card rendering |
| `apps/web/components/panels/fusion-panel.tsx` | `FusionPanel` | score, delta, contribution, and neighbor summaries |
| `apps/web/components/chat/agent-chat-rail.tsx` | `AgentChatRail` | question/answer loop over `apiClient.queryAgent` |
| `apps/web/lib/api-client/client.ts` | `apiClient` object (`initUpload`, `createAnalysisJob`, `getCyt`, `getFusionScore`, `queryAgent`, etc.), `requestWithMock` | browser-side API abstraction + payload coercion fallback |
| `apps/web/lib/api-client/types.ts` | TS interfaces for all endpoint payloads | frontend contract safety boundary |
| `apps/web/components/layout/research-disclaimer.tsx` | `ResearchDisclaimer` | UI-level research-use policy banner |

## 1.4.3 Data tooling map (`scripts`, `packages/mvp50`)

| Module path | Key functions/classes | Architectural role |
|---|---|---|
| `scripts/build_tcga_matched_cohort.py` | `build_matched_cohort`, `_build_*_filters`, `_best_*_file` | source-of-truth cohort construction from GDC APIs |
| `scripts/download_tcga_matched_data.sh` | deterministic download routine (manifest-locked inputs) | reproducible data acquisition from locked manifest |
| `packages/mvp50/data_contract_utils.py` | `resolve_schema_and_modalities`, `evaluate_cohort_completeness`, `deterministic_subset`, hash helpers | shared contract/evaluation primitives |
| `packages/mvp50/validate.py` | `run`, `main`, parser helpers | contract compliance report generation |
| `packages/mvp50/lock.py` | `_build_selected_assets`, `run`, deterministic hashing/writes | reproducible subset lock + metadata digest outputs |
| `packages/mvp50/cli.py` | unified `validate`/`lock` command dispatch | detachable module CLI boundary |
| `scripts/mvp50.py` | wrapper entrypoint | backward-compatible script surface |
| `scripts/validate_matched_cohort.py` | wrapper into module validate entrypoint | legacy compatibility boundary |
| `scripts/lock_mvp50_manifest.py` | wrapper into module lock entrypoint | legacy compatibility boundary |
| `scripts/audit_luad_embedding_coverage.py` | `collect_embedding_files`, `collect_artifacts`, `build_audit_rows`, strict gate flags | pathology embedding/artifact coverage audit |
| `scripts/validate_pathology_artifacts.py` | `ArtifactValidationIssue`, section validators | pathology artifact schema/manifest consistency gate |
| `scripts/check_transcriptomics_coverage_gate.py` | `_evaluate_failures`, `main` | transcriptomics release threshold enforcement |

## 1.4.4 CI/ops map

| Module path | Key checks/tasks | Architectural role |
|---|---|---|
| `.github/workflows/ci.yml` | backend tests, frontend checks, architecture/data-contract guards | authoritative CI execution graph |
| `scripts/ci/check_architecture_coherence.py` | route extraction and doc-vs-code checks (`_extract_plan_required_api_endpoints`, `_extract_backend_route_endpoints`, etc.) | prevents architectural drift across docs/backend/frontend |
| `scripts/ci/check_data_contract_tooling.py` | script/module existence + help text + symbol contract checks | prevents contract-tooling regression |
| `scripts/ci/run_backend_smoke.py` | import smoke + pytest invocation | backend runtime sanity gate |
| `scripts/ci/run_frontend_checks.sh` | frontend lint/type/test/build smoke wrapper | frontend release sanity gate |
| `Makefile` | `ci`, `backend-smoke`, `frontend-smoke`, `test-ci`, `lint-shell`, etc. | local reproducibility front door |
| `infra/dev/docker-compose.yml` | local `postgres` + `redis` | minimal shared infra contract |
| `scripts/dev/bootstrap.sh`, `scripts/dev/check.sh` | idempotent environment setup + local validation routine | deterministic developer onboarding/health checks |

---

## 1.5 Abstraction of methods and contracts across layers

## 1.5.1 Contract chain (who guarantees what)

| Producer layer | Contract artifact | Consumer layer | Guaranteed semantics |
|---|---|---|---|
| Frontend page/components | route params + user events | API client | case/job identifiers passed in canonical URL form (`/upload`, `/analysis/[job_id]`, `/patient/[case_id]`) |
| API client (`apiClient`) | typed UI model (`UploadInitResponse`, `AnalysisJobResponse`, modality responses) | page/panel components | parser-normalized shape; mock fallback on network/schema/stub failure |
| FastAPI routers | endpoint-level request validation + schema-bound responses | API client / tests | stable route signatures, explicit HTTP errors, research-use response markers |
| Service modules | modality/fusion/agent typed payload objects | routers | source precedence logic, deterministic fallback, provenance metadata |
| ORM/persistence | relational rows (`cases`, `analysis_jobs`, `modality_results`, etc.) | services/routers | durable state and event history for orchestration |
| Artifact/filesystem resolvers | resolved files/URIs + strict errors | services | deterministic matching with explicit missing-data behavior |
| Data tooling scripts | manifests, lock artifacts, coverage reports | runtime + release process | reproducible cohort selection and release threshold visibility |
| CI guardrail scripts | pass/fail checks | maintainers/PR pipeline | docs-code coherence and tooling invariants |

## 1.5.2 Method responsibility matrix (cross-layer critical path)

| Method/function | Layer | Responsibility | Downstream dependency it enables |
|---|---|---|---|
| `apiClient.initUpload(...)` (`apps/web/lib/api-client/client.ts`) | frontend API boundary | emits normalized upload-init request and parses backend payload | `UploadShell` can start session state machine |
| `init_upload_session(...)` (`apps/api/routers/uploads.py`) | router | validates request and creates upload session | `create_analysis_job(...)` has valid session anchor |
| `ensure_case_exists(...)` (`apps/api/services/cases.py`) | service utility | idempotently ensures `Case` row exists | job creation and modality retrieval share stable case key |
| `create_analysis_job(...)` (`apps/api/routers/analysis.py`) | router | enforces upload/case consistency, writes `AnalysisJob` + `JobEvent` | analysis status page can show timeline |
| `apiClient.getAnalysisJob(...)` | frontend API boundary | maps backend job details into timeline-safe shape | analysis page renders status steps robustly |
| `loadPatientWorkspaceData(...)` (`apps/web/lib/patient-workspace.ts`) | frontend orchestration | fan-out calls across pathology/transcriptomics/clinical/fusion; computes missing modality set | patient workspace panels can render complete + degraded states |
| `get_tissue_composition` / `get_heatmap` / `get_evidence` (`apps/api/services/pathology.py`) | service | typed pathology payload + provenance, strict/fallback policy | pathology panel and agent citations can rely on consistent fields |
| `get_cyt_signature`, `get_gep_signature`, `get_tide_signature` (`apps/api/services/transcriptomics.py`) | service | RNA metrics with source/availability/governance semantics | transcriptomics panel and fusion refined mode |
| `get_clinical_patient_summary` / `get_clinical_eligibility` / `get_clinical_survival_baseline` (`apps/api/services/clinical.py`) | service | source-aware clinical typed outputs | clinical panel + fusion clinical signal extraction |
| `get_fusion_score(...)` (`apps/api/services/fusion.py`) | service | provisional/refined scoring + modality contributions + CI | fusion panel + agent reasoning |
| `query_agent(...)` (`apps/api/routers/agent.py`) | router/orchestrator | composes modality + fusion evidence into grounded answer/citations | chat rail interactive Q&A |

## 1.5.3 Core domain model contract (backend persistence)

The persistence contract from `apps/api/models/core.py` defines the architectural spine:

- `Case`: canonical case identity and baseline metadata
- `File`: file-level metadata linked to case and optionally upload session
- `UploadSession`: ingest transaction envelope
- `AnalysisJob`: orchestration unit with requested modalities and summary state
- `JobEvent`: timeline events for analysis progress
- `ModalityResult`: persisted modality payload snapshots

This model gives the platform a stable event/history surface even when individual modality branches are still partly heuristic.

---

## 1.6 End-to-end data flow by concern

## 1.6.1 Identity normalization and key propagation

A key architecture invariant is **case identity continuity** across layers.

- Frontend routes and state use `case_id` (`/patient/[case_id]`, query params from upload/analysis).
- Backend services normalize slide/case IDs using `derive_short_case_id` and `derive_short_slide_id` (`apps/api/services/pathology_id_resolution.py`) to reconcile short/full TCGA forms.
- Fusion and transcriptomics services call shared identifier candidate builders so artifact, DB, and file-system lookups remain aligned.

This prevents a common multimodal failure mode where branch outputs exist but cannot be joined due to token mismatch.

## 1.6.2 Source precedence semantics (modality-level)

The system encodes precedence rather than ad-hoc `if/else` in UI:

- **Pathology (`services/pathology.py`)**: artifact-backed section -> deterministic fallback, with optional strict-missing hard error.
- **Transcriptomics (`services/transcriptomics.py`)**: artifact -> modality result -> counts TSV -> unavailable, with explicit `availability_code` and governance fields.
- **Clinical (`services/clinical.py`)**: artifact -> modality result -> XML/report parse -> case metadata -> unavailable.

Because each modality returns source/provenance metadata, fusion and agent can reason over confidence and missingness without hidden assumptions.

## 1.6.3 Fusion as a policy-aware composition layer

`apps/api/services/fusion.py` does more than weighted averaging:

- resolves each modality through explicit adapter functions,
- computes both provisional and refined score modes,
- switches mode based on transcriptomics availability (`requested_mode` vs `mode_used`),
- reports modality contribution percentages and confidence interval,
- provides typed unavailable semantics for missing transcriptomics when refined mode is requested.

This keeps reasoning policy centralized instead of duplicated in frontend cards or agent prompts.

## 1.6.4 Agent as an orchestrated read model (not hidden model endpoint)

`POST /v1/agent/query` in `apps/api/routers/agent.py` pulls from pathology/transcriptomics/clinical/fusion service outputs and emits:

- `answer` (natural language),
- `citations` (panel + field + evidence text),
- `modalities` (availability snapshots),
- `acknowledged_missing_modalities`,
- `meta` (method/version/timestamp/proxy flag).

Architecturally, this is a **read-model orchestrator** over typed evidence, not an opaque autonomous reasoner.

---

## 1.7 Sequence-style walkthroughs for core flows

## 1.7.1 Flow A — Upload -> analysis job creation

```text
User
  -> /upload page (apps/web/app/upload/page.tsx)
  -> UploadShell + Uploader
  -> apiClient.initUpload / apiClient.uploadFiles / apiClient.createAnalysisJob
  -> FastAPI /v1/uploads/init, /v1/uploads/files, /v1/analysis/jobs
  -> Postgres tables: cases, upload_sessions, analysis_jobs, job_events
  -> browser redirects to /analysis/[job_id]?case_id=...
```

Step detail:

1. `/upload` page fetches cohort candidates using `apiClient.listCohortCases()`.
2. `UploadShell` selects/locks a case context and triggers `initUpload`.
3. `POST /v1/uploads/init` validates payload (`UploadInitRequest`) and calls `ensure_case_exists` when case is provided.
4. Router inserts `UploadSession` with status `initialized`.
5. `Uploader` captures dropped files, infers modalities from filename extensions/tokens, and calls `apiClient.uploadFiles(...)` (currently scaffold path).
6. `UploadShell` triggers `apiClient.createAnalysisJob(...)`.
7. `POST /v1/analysis/jobs` validates upload-session linkage, backfills missing session case id if needed, inserts `AnalysisJob` and initial `JobEvent`.
8. UI routes to `/analysis/{job_id}` with case query context.

**Contract checkpoints:**

- Upload/analysis orchestration is persisted (not ephemeral UI-only state).
- `create_analysis_job` enforces case/session integrity (404 for unknown session, 409 for mismatch).
- `upload_files` is intentionally scaffolded; downstream analysis should not assume uploaded file persistence yet.

## 1.7.2 Flow B — Analysis status page rendering

```text
/analysis/[job_id] page
  -> apiClient.getAnalysisJob(jobId, caseId?)
  -> GET /v1/analysis/jobs/{job_id}
  -> returns job + events + modality_results
  -> apiClient parser normalizes into timeline steps
  -> AnalysisStatusTimelineCard + ModalityStatusGrid render state
```

Step detail:

1. Analysis page reads path param `job_id` and optional query `case_id`.
2. API call fetches job detail.
3. Backend composes payload from `AnalysisJob`, related `JobEvent` rows, and `ModalityResult` rows.
4. Frontend parser converts backend statuses into UI-safe step states (`queued/running/completed/failed`) and fills absent steps deterministically.
5. Timeline/grid components render progression and route actions (open patient workspace, retry upload path on failure).

**Contract checkpoints:**

- UI does not need backend event-shape internals; it receives a normalized step vector.
- Error semantics remain actionable (failed jobs route to upload retry using case id).

## 1.7.3 Flow C — Patient workspace assembly

```text
/patient/[case_id]
  -> loadPatientWorkspaceData(caseId)
     -> parallel calls:
        pathology (tissue/heatmap/evidence)
        transcriptomics (cyt/gep/tide/evidence)
        clinical (summary/eligibility/survival)
        fusion (score/attribution/similar-cases)
  -> aggregate panelSummary + missingModalities
  -> render PatientHeader + panel stack + AgentChatRail
```

Step detail:

1. `PatientPage` calls `loadPatientWorkspaceData(caseId)` in `apps/web/lib/patient-workspace.ts`.
2. Helper executes fan-out queries in parallel to reduce patient-page latency.
3. For each modality, helper computes both raw payload inclusion and panel-level missingness semantics.
4. `buildPatientWorkspaceViewModel` produces:
   - `panelSummary` (availability by modality),
   - `missingModalityReasons`,
   - display labels used by header/sidebar.
5. `PatientWorkspacePanels` renders modality cards conditionally:
   - available -> full card content,
   - unavailable -> `MissingModalityState` with reason and source cues.
6. Pathology deep-zoom path (`EnsoPathologyViewer`) requests viewer config, DZI, tile, and attention-heatmap endpoints from backend proxy routes.

**Contract checkpoints:**

- Patient view is robust to partial modality completion.
- Viewer access is mediated by backend proxy endpoints, keeping external Enso details outside frontend routing logic.

## 1.7.4 Flow D — Agent query over multimodal evidence

```text
AgentChatRail (client)
  -> apiClient.queryAgent({ case_id, query })
  -> POST /v1/agent/query
  -> backend orchestrates modality/fusion service calls
  -> builds answer + citations + modality availability summary
  -> chat rail appends response + citations/source badges
```

Step detail:

1. User submits a question in `AgentChatRail`.
2. `apiClient.queryAgent` sends `{ case_id, question }` to `/v1/agent/query`.
3. Router calls service surfaces:
   - pathology evidence (`get_evidence`),
   - transcriptomics evidence (`get_transcriptomic_evidence`),
   - clinical summary (`get_clinical_patient_summary`),
   - fusion score (`get_fusion_score`).
4. Router synthesizes grounded response:
   - text answer with explicit research-only framing,
   - citations tied to modality panel fields,
   - modality availability map,
   - missing modality acknowledgement.
5. Frontend displays response bubble + citation snippets and preserves turn history locally.

**Contract checkpoints:**

- Agent route is evidence-grounded by construction.
- Missing modalities are explicit data, not hidden failure.
- `meta` method/version/timestamp keeps agent output auditable.

---

## 1.8 Research-only boundaries and required production hardening

## 1.8.1 Explicit research-only boundaries already implemented

| Boundary | Implementation location | Current behavior |
|---|---|---|
| HTTP-level research marker | `apps/api/main.py` middleware | sets `X-Research-Use-Only: true`, `X-Clinical-Use: not-intended` on all responses |
| Route payload research fields | multiple schemas/routes (e.g., upload/analysis responses) | exposes `research_use_only` where applicable |
| UI disclaimer | `apps/web/components/layout/research-disclaimer.tsx` | persistent user-visible research-only notice |
| Agent response framing | `apps/api/routers/agent.py` + `apps/api/tests/test_agent.py` assertions | answer text includes non-clinical, research-only caveats |
| Proxy estimate metadata | modality/fusion/agent metadata builders | `proxy_estimate` included in method metadata |
| Missing modality semantics | service + UI contracts (`availability_code`, missing state components) | missing data shown explicitly, not silently imputed in UI |

## 1.8.2 Architectural limits that remain intentionally non-production

The current platform is robust for research demos but still not a production clinical decision-support system.

1. **Security/compliance envelope is incomplete**
   - no end-to-end authN/authZ boundary around sensitive endpoints,
   - no full audit trail linking every read/write to user identity and policy,
   - no PHI governance guarantees or regulatory controls.

2. **Ingestion/orchestration lifecycle is partial**
   - `POST /v1/uploads/files` remains scaffolded,
   - job execution lifecycle is represented in DB shape, but full worker-driven modality pipeline lifecycle is not yet integrated end-to-end.

3. **Heuristic and fallback-heavy modality logic**
   - pathology/clinical/transcriptomics services correctly expose deterministic outputs and provenance but remain primarily research heuristics in many branches,
   - fusion and agent rely on these branch-level proxy semantics; they are explainable but not clinically validated.

4. **Frontend fallback policy favors continuity over strict failure**
   - `requestWithMock` in API client can fallback to mock data when backend is unavailable/stubbed/unexpected,
   - this is useful for development continuity but unsuitable for strict production truthfulness unless tightly gated by environment.

## 1.8.3 Production hardening priorities by layer

| Priority | Layer | Required hardening |
|---|---|---|
| P0 | Security and governance | authN/authZ, tenant-aware access control, audit logging, rate limiting, secrets management |
| P0 | Ingestion/orchestration | implement real uploaded-file persistence and job worker lifecycle with retry/idempotency |
| P0 | Artifact serving | object-store-backed signed URL strategy for WSI/heatmap assets, integrity checks, cache policy |
| P0 | Model governance | frozen reference lifecycle ownership, model/version registry, calibration + drift monitoring |
| P1 | Contract strictness | environment-gated disablement of frontend mock fallback for production channels |
| P1 | Observability | distributed request tracing (upload->analysis->patient->agent), SLO dashboards, alerting |
| P1 | Data quality | automated completeness gates for pathology/transcriptomics/clinical artifacts before release |
| P1 | Documentation coherence | keep `implementation-status.md` synchronized with merged code reality to avoid stale status drift |

Notably, `docs/execution/implementation-status.md` and `docs/execution/task-backlog.md` contain some status lag versus currently merged code (for example, fusion/agent functionality now has implemented service/test surfaces). The architecture itself remains coherent, but process hardening should include stricter status-document upkeep.

---

## 1.9 Architectural conclusions and invariants to preserve

1. **Keep specialist branches independent and typed.**
   Pathology/transcriptomics/clinical should continue returning explicit availability + provenance rather than opaque blobs.

2. **Keep fusion as policy composition, not hidden monolith.**
   Preserve `requested_mode` vs `mode_used`, contribution percentages, and confidence interval semantics.

3. **Keep agent grounded to endpoint fields.**
   `POST /v1/agent/query` should remain a typed evidence orchestrator with citations, not a free-form black box.

4. **Keep identity normalization centralized.**
   `pathology_id_resolution` style case/slide normalization is a cross-modality reliability foundation.

5. **Keep docs-code CI coherence guardrails active.**
   `scripts/ci/check_architecture_coherence.py` and `scripts/ci/check_data_contract_tooling.py` are architecture-level controls, not optional lint.

6. **Preserve research-only transparency while hardening.**
   The platform already exposes research boundaries clearly (headers, disclaimers, metadata). Productionization should add governance/security around this transparency, not replace it with opaque behavior.

In short: the repository already has a strong layered architecture with explicit contracts and good degradation semantics. The next stage is less about redesign, and more about **operationalizing** the existing architecture under production-grade governance, security, and lifecycle automation.

---

## Section 02 — Backend Routers, Services, and Schemas

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

---

## Section 03 — Frontend UI and API Client

## 3.1 Scope, docs-first inputs, and architecture position

This section documents the implemented frontend and client-side integration layer for:

- `apps/web/app/*` (Next.js App Router route modules)
- `apps/web/components/*` (layout, panel, workflow, and chat components)
- `apps/web/lib/api-client/*` (typed contracts, parse/coercion, fallback strategy)
- `apps/web/lib/patient-workspace.ts` (route-level data composition)
- `apps/web/types/openseadragon.d.ts` and frontend runtime config files where they affect architecture

It is written after reviewing required docs-first inputs:

- `docs/README.md`
- `docs/architecture/plan.md`
- `docs/execution/task-backlog.md`
- `docs/execution/implementation-status.md`

Within the architecture defined in `docs/architecture/plan.md`, this layer is the **user-facing orchestration shell** for the critical loop:

1. upload/select case (`/upload`),
2. start and monitor analysis (`/analysis/[job_id]`),
3. inspect multimodal evidence (`/patient/[case_id]`),
4. ask the grounded agent (right rail).

Per the backlog and implementation status, the frontend is intentionally resilient to partial backend completion: it can run against live API routes when available and degrade to typed mock responses when routes are scaffolded, unavailable, or schema-incompatible.

---

## 3.2 Frontend architecture overview

### 3.2.1 Runtime stack and guiding constraints

`apps/web` is a Next.js 15 App Router app (`apps/web/package.json`) using:

- React 19,
- TypeScript,
- Tailwind CSS,
- OpenSeadragon (`openseadragon@^5.0.1`) for WSI deep zoom.

Architecture constraints visible in implementation:

- **Research-only posture is always visible**: global disclaimer banner/footer in `app/layout.tsx` via `ResearchDisclaimerBanner` and `ResearchDisclaimerFooter`.
- **Typed contract-first API access**: `lib/api-client/types.ts` defines frontend-consumed data contracts.
- **Fail-soft integration mode**: `requestWithMock()` in `lib/api-client/client.ts` transparently falls back to deterministic mocks when API is absent or unsafe.
- **Server/component split by interaction needs**:
  - server components for route-level fetch and composition,
  - client components for local interaction state (upload drag-drop, tile selection, chat input, deep-zoom controls).

### 3.2.2 Route map and page responsibilities

| Route | File | Rendering role | Primary data entrypoint |
|---|---|---|---|
| `/` | `app/page.tsx` | redirect-only | `redirect("/upload")` |
| `/upload` | `app/upload/page.tsx` | server wrapper around interactive uploader shell | `apiClient.listCohortCases()` |
| `/analysis/[job_id]` | `app/analysis/[job_id]/page.tsx` | server-rendered job-state view | `apiClient.getAnalysisJob(job_id, case_id?)` |
| `/patient/[case_id]` | `app/patient/[case_id]/page.tsx` | server composition of a full-bleed responsive sidebar + workspace + chat shell | `loadPatientWorkspaceData(case_id)` |

### 3.2.3 High-level composition graph

```text
RootLayout (research banner + main container + research footer)
  └── route page
      ├── /upload: UploadShell (client)
      ├── /analysis/[job_id]: timeline + modality status + action links
      └── /patient/[case_id]
           ├── PatientListSidebar
           ├── PatientHeader
           ├── PatientWorkspacePanels
           │    ├── PathologyPanel (client, includes EnsoPathologyViewer)
           │    ├── TranscriptomicsPanel
           │    ├── ClinicalSummaryPanel
           │    └── FusionPanel
           └── AgentChatRail (client)
```

### 3.2.4 Data-flow strategy

There are two dominant data-flow patterns:

1. **Route prefetch + prop drilling for page-scope data**
   - `/patient/[case_id]` calls `loadPatientWorkspaceData()` once and passes typed slices into downstream panels.
   - Avoids duplicate API calls across sibling cards.

2. **Local UI state for interaction-only concerns**
   - Upload file list and drag state in `Uploader`.
   - Selected evidence tile in `PathologyPanel`.
   - Viewer controls (mode, opacity, interpolation, overlays) in `EnsoPathologyViewer`.
   - Chat draft/loading/message log in `AgentChatRail`.

This keeps remote data state mostly route-scoped and local interaction state component-scoped.

---

## 3.3 Route-level deep dive (app routes, panels, and flow)

## 3.3.1 `app/layout.tsx` and global UX frame

`app/layout.tsx` defines a single-shell frame:

- top banner: `ResearchDisclaimerBanner`,
- constrained content area: `main` with max width (`1480px`),
- footer: `ResearchDisclaimerFooter`.

This ensures every route inherits research-only framing without repeated page code.

## 3.3.2 Upload flow: `/upload`

### Entry and data bootstrap

`app/upload/page.tsx` is async server-side and resolves:

- `cases = await apiClient.listCohortCases()`
- optional `searchParams.case_id` for preselection

then renders `UploadShell` with `cases` and `initialCaseId`.

### Interactive shell behavior (`components/upload/upload-shell.tsx`)

`UploadShell` is a client component and orchestrates the upload-start transaction:

1. Case selection (`selectedCaseId`),
2. Optional file capture (`selectedFiles`),
3. Start action:
   - `apiClient.initUpload(...)`
   - `apiClient.uploadFiles(...)` (only when files exist)
   - `apiClient.createAnalysisJob(...)`
   - route transition to `/analysis/{job_id}?case_id={selectedCaseId}`.

Key implementation details:

- `resolveInitialCaseId()` prevents invalid initial case selection.
- `uploadFilePayload()` converts browser `File` objects into contract-compatible descriptors.
- `startAnalysis()` wraps transaction in try/catch, exposes user-safe error text, and avoids leaving loading state active after failure.

### Upload widget internals (`components/upload/uploader.tsx`)

`Uploader` handles drag/drop and file input while inferring modality from filename suffix:

- pathology: `.svs`, `.tif`, `.tiff`
- transcriptomics: `.tsv`, `.csv`
- default fallback: clinical

It computes modality coverage badges (`pathology/transcriptomics/clinical detected|missing`) and deduplicates selected files by deterministic `id = name-size-lastModified`.

## 3.3.3 Analysis flow: `/analysis/[job_id]`

`app/analysis/[job_id]/page.tsx` pulls one job payload and renders:

- `AnalysisStatusTimelineCard` (ordered stage progression)
- `ModalityStatusGrid` (modality-level card status)
- optional error panel if `job.errors` exists
- context-specific action links:
  - back to upload,
  - open patient workspace when complete,
  - retry when failed,
  - manual refresh anchor otherwise.

Notable details:

- `modalitySteps` explicitly filters out `queue` for grid display, keeping queue only in timeline.
- no client-side polling loop is implemented; refresh is explicit via link.

## 3.3.4 Patient workspace flow: `/patient/[case_id]`

`app/patient/[case_id]/page.tsx` fetches a full workspace bundle through `loadPatientWorkspaceData(caseId)` and composes a 3-column layout:

- left: `PatientListSidebar`,
- center: `PatientHeader` + `PatientWorkspacePanels`,
- right: `AgentChatRail`.

`loadPatientWorkspaceData()` (in `lib/patient-workspace.ts`) is the core aggregation point:

- resolves selected case from `listCohortCases()` with fallback to `apiClient.getDefaultCase()`,
- issues all panel data requests concurrently via `Promise.all` across pathology, transcriptomics, clinical, and fusion endpoints,
- returns a single typed object (`PatientWorkspaceData`) consumed by panel components.

This is the central cross-panel consistency guarantee: all cards on a page render from one coordinated snapshot.

---

## 3.4 Module-by-module and component-by-component map (`apps/web`)

This section catalogs runtime-relevant modules (excluding generated `.next/*` output).

## 3.4.1 Route and layout modules

| File | Exports | Responsibility |
|---|---|---|
| `app/layout.tsx` | `RootLayout`, `metadata` | Global HTML/body shell + research disclaimer framing |
| `app/page.tsx` | `HomePage` | Redirects `/` → `/upload` |
| `app/upload/page.tsx` | `UploadPage` | Server data preload for upload route |
| `app/analysis/[job_id]/page.tsx` | `AnalysisPage` | Job timeline/status route |
| `app/patient/[case_id]/page.tsx` | `PatientPage` | Full workspace route composition |
| `app/globals.css` | stylesheet | Global dark theme, base body + anchor styling |

## 3.4.2 Shared UI primitives and layout utilities

| File | Exports | Responsibility |
|---|---|---|
| `components/common/page-section.tsx` | `PageSection` | Standard section container styling |
| `components/common/content-card.tsx` | `ContentCard` | Standard card surface styling |
| `components/common/panel-shell.tsx` | `PanelShell` | Panel header/subtitle/meta shell with proxy-estimate badge |
| `components/common/missing-modality-state.tsx` | `MissingModalityState` | Consistent not-available panel treatment |
| `components/layout/research-disclaimer.tsx` | `ResearchDisclaimerBanner`, `ResearchDisclaimerFooter` | Global trust/safety messaging |
| `lib/utils.ts` | `cn(...)` | Minimal class concatenation helper |

## 3.4.3 Workflow and domain components

| Domain | Files | Key responsibility |
|---|---|---|
| Upload | `components/upload/upload-shell.tsx`, `components/upload/uploader.tsx` | Upload/select interaction and analysis job start |
| Analysis | `components/analysis/analysis-status-timeline-card.tsx`, `components/analysis/modality-status-grid.tsx`, `components/analysis/status-styles.ts` | Status rendering and visual state mapping |
| Patient workspace assembly | `components/patient/patient-workspace-panels.tsx`, `components/patient/patient-header.tsx`, `components/patient/patient-list-sidebar.tsx` | Cross-panel composition and navigation |
| Pathology panel | `components/panels/pathology-panel.tsx`, `components/panels/enso-pathology-viewer.tsx` | Slide viewer, viewport/evidence overlays, tissue/evidence cards |
| Transcriptomics panel | `components/panels/transcriptomics-panel.tsx` | CYT/GEP/TIDE cards + top genes + notes |
| Clinical panel | `components/panels/clinical-summary-panel.tsx` | summary/eligibility/survival presentation |
| Fusion panel | `components/panels/fusion-panel.tsx` | provisional/refined score display + attribution bars + neighbors |
| Chat rail | `components/chat/agent-chat-rail.tsx` | Query UI and citation-bearing responses |

## 3.4.4 API and data modules

| File | Exports | Responsibility |
|---|---|---|
| `lib/api-client/types.ts` | contract interfaces | Frontend data contract source |
| `lib/api-client/mock-data.ts` | `MOCK_CASES`, `mock*` factories | Deterministic fallback payload generation |
| `lib/api-client/client.ts` | `apiClient` object | Fetch/parsing/fallback orchestration |
| `lib/api-client/index.ts` | re-exports | Stable import surface for app/components |
| `lib/patient-workspace.ts` | `loadPatientWorkspaceData` | Route-level parallel data aggregator |
| `types/openseadragon.d.ts` | module declaration | TS compatibility shim for OpenSeadragon import |

## 3.4.5 Test modules that define behavior guardrails

| File | Focus |
|---|---|
| `lib/api-client/client.test.ts` | parser coercion and fallback behavior under backend schema drift/stub payloads |
| `app/upload/page.test.tsx` | upload route data wiring |
| `app/analysis/[job_id]/page.test.tsx` | analysis route navigation/error behavior |
| `components/common/missing-modality-state.test.tsx` | missing-modality messaging invariants |
| `components/layout/research-disclaimer.test.tsx` | mandatory research-only text visibility |

---

## 3.5 Component composition and state/data flow by panel

## 3.5.1 `PatientWorkspacePanels` as center-column orchestration

`app/patient/[case_id]/page.tsx` now uses a full-bleed responsive grid so the left patient rail, center workspace, and right chat rail can expand with browser width instead of staying capped inside a fixed desktop shell.

On wide screens the side rails use viewport-height sticky containers with internal scrolling, while narrower widths fall back to normal document flow so zoom changes and smaller windows do not crush the center workspace.

Within that shell, `components/patient/patient-workspace-panels.tsx` remains intentionally thin: it maps the preloaded `PatientWorkspaceData` object into the tabbed workspace content without owning route-level sizing policy.

This is important for consistency:

- all panel props come from one loader call,
- panel ordering is deterministic and stable for demo narration,
- panel internals own only presentation/local interaction state.

## 3.5.2 Pathology panel internals

`PathologyPanel` receives three nullable domain payloads (`tissue`, `heatmap`, `evidence`) and computes:

- `hasPathologyData` gate for missing-state rendering,
- `meta` preference chain for `PanelShell` provenance badge,
- `slideId` resolution chain,
- `activeTile` from selected tile state with default to first evidence tile.

Composition:

1. **Viewer block** (`EnsoPathologyViewer`) with:
   - `viewportHint` from heatmap payload,
   - `selectedEvidenceBbox` from active tile.
2. **Tissue card** (fractions + QC coverage/artifact warning).
3. **Top evidence tile list** (clickable tile selector).

This panel is the only center panel that is both data-rich and heavily interactive at render time.

## 3.5.3 Transcriptomics panel internals

`TranscriptomicsPanel` calculates `rnaAvailable` from CYT/GEP/TIDE `available` flags.

Behavior rules:

- Always render panel shell (transparency over hidden state).
- Render `MissingModalityState` when RNA is absent.
- Render three metric cards regardless, with explicit “Not available for this case” text when unavailable.
- Render evidence/top genes and interpretation notes, including empty-case messaging.

## 3.5.4 Clinical panel internals

`ClinicalSummaryPanel` gates on `summary` presence:

- if missing: explicit `MissingModalityState` with clinical-specific message,
- if present: stage/smoking/eligibility cards + highlights + survival block.

Clinical panel therefore follows a binary availability model at panel level (summary absent/present) but allows partial nested nulls for eligibility/survival blocks.

## 3.5.5 Fusion panel internals

`FusionPanel` derives `hasRna` from `score.refined_score !== null` and displays:

- provisional/refined/delta cards,
- attribution bars from `contributions`,
- similar case list.

When no RNA: warning banner is shown and refined/delta values present as `N/A` through `asPercent` helper behavior.

## 3.5.6 Chat rail internals

`AgentChatRail` is fully client-side with local message history.

Flow:

1. user enters prompt or clicks suggested prompt chip,
2. local user message appended,
3. `apiClient.queryAgent` called,
4. assistant message appended with optional citations,
5. failure path appends retry-safe error text.

It intentionally does not depend on websocket/stream transport yet; loading is represented as a temporary “Agent is drafting...” row.

---

## 3.6 API client abstraction deep dive (`apps/web/lib/api-client/client.ts`)

## 3.6.1 Design goals

The client layer optimizes for three constraints simultaneously:

1. **Typed frontend consumption** (`types.ts` contracts).
2. **Resilience to backend incompleteness** (automatic mock fallback).
3. **Schema drift tolerance** (normalizers/parsers for known mismatch patterns).

## 3.6.2 Request pipeline (`requestWithMock`)

All endpoint methods eventually pass through `requestWithMock<T>(path, init, fallback, parser?)`.

Pipeline steps:

1. If `NEXT_PUBLIC_API_BASE_URL` is unset → return `fallback()` immediately.
2. Perform `fetch` with `withJsonHeaders(...)`:
   - `Content-Type: application/json`
   - `cache: "no-store"` (freshness over cache).
3. On non-2xx status → throw and fallback.
4. Parse JSON payload.
5. If payload has `status === "stub"` → throw and fallback.
6. If parser exists:
   - parse and validate coercion,
   - on parse failure → throw and fallback.
7. If no parser exists: cast payload as `T` and return.
8. Any exception path resolves to fallback (silent fail-soft behavior).

## 3.6.3 Parser/normalizer layer

| Parser/helper | Purpose | Key coercions |
|---|---|---|
| `parseUploadInitResponse` | upload init compatibility | supports `session_id` or `upload_session_id`; injects default accepted modalities |
| `parseUploadFilesResponse` | file-status shape guard | validates file rows + modality/status enums |
| `parseAnalysisJobResponse` | analysis job normalization | supports explicit `steps[]` shape or backend detail shape (`status`, `requested_modalities`, `modality_results`) |
| `parseAgentQueryResponse` | chat response compatibility | supports `answer` or `message`, strict citation extraction |
| `toJobState` | state harmonization | maps `done/succeeded/success`→`completed`, `error`→`failed`, `pending/created`→`queued` |
| `parseMethodMetadata` | safe metadata fallback | emits fallback `method/version/timestamp` when malformed/absent |

`buildAnalysisStepsFromState(...)` is particularly important: it synthesizes a full UI step timeline even when backend returns only coarse status.

## 3.6.4 Endpoint method map (frontend perspective)

| `apiClient` method | Backend target | Parser? | Fallback source |
|---|---|---|---|
| `listCohortCases` | none (local only) | n/a | `MOCK_CASES` always |
| `initUpload` | `POST /v1/uploads/init` | yes | `mockUploadInit` |
| `uploadFiles` | `POST /v1/uploads/files` | yes | `mockUploadFiles` |
| `createAnalysisJob` | `POST /v1/analysis/jobs` | yes | `mockCreateAnalysisJob` |
| `getAnalysisJob` | `GET /v1/analysis/jobs/{job_id}` | yes | `mockGetAnalysisJob` |
| `getPathologyTissueComposition` | `GET /v1/pathology/slides/{slide_id}/tissue-composition` | no | `mockPathologyTissue` |
| `getPathologyHeatmap` | `GET /v1/pathology/slides/{slide_id}/heatmap` | no | `mockPathologyHeatmap` |
| `getPathologyEvidence` | `POST /v1/pathology/slides/{slide_id}/evidence` | no | `mockPathologyEvidence` |
| `getCyt` | `GET /v1/transcriptomics/{case_id}/cyt` | no | `mockCyt` |
| `getGep` | `GET /v1/transcriptomics/{case_id}/gep` | no | `mockGep` |
| `getTide` | `GET /v1/transcriptomics/{case_id}/tide?experimental=true` | no | `mockTide` |
| `getTranscriptomicEvidence` | `POST /v1/transcriptomics/{case_id}/evidence` | no | `mockTranscriptomicEvidence` |
| `getClinicalPatientSummary` | `GET /v1/clinical/{case_id}/patient-summary` | no | `mockClinicalPatientSummary` |
| `getClinicalEligibility` | `GET /v1/clinical/{case_id}/eligibility` | no | `mockClinicalEligibility` |
| `getClinicalSurvivalBaseline` | `GET /v1/clinical/{case_id}/survival-baseline` | no | `mockClinicalSurvivalBaseline` |
| `getFusionScore` | `POST /v1/fusion/{case_id}/score` | no | `mockFusionScore` |
| `getFusionAttribution` | `GET /v1/fusion/{case_id}/attribution` | no | `mockFusionAttribution` |
| `getFusionSimilarCases` | `GET /v1/fusion/{case_id}/similar-cases` | no | `mockFusionSimilarCases` |
| `queryAgent` | `POST /v1/agent/query` | yes | `mockAgentQuery` |

## 3.6.5 Typing contracts and consumer surfaces

`lib/api-client/types.ts` defines UI-facing contracts. These contracts are narrower than some backend schemas and deliberately UI-centric.

| Type | Consumed by | Critical fields |
|---|---|---|
| `CohortCaseSummary` | upload selector, patient sidebar | case identity + modality availability flags |
| `AnalysisJobResponse` + `AnalysisStepStatus` | analysis page cards | state machine + step detail |
| `Pathology*Response` | pathology panel/viewer | `slide_id`, `viewport_hint`, `top_tiles` |
| `Cyt/Gep/TideResponse` | transcriptomics panel | value + `available` flag + `meta` |
| `Clinical*Response` | clinical panel + patient header | summary/eligibility/survival fields |
| `FusionScoreResponse` | patient header + fusion panel | provisional/refined/delta/CI/missing modalities |
| `FusionAttributionResponse` | fusion panel | modality contribution list |
| `FusionSimilarCasesResponse` | fusion panel | neighbor list |
| `AgentQueryResponse` | chat rail | answer + citations + acknowledged missing modalities |

Notable contract design choice: frontend contracts preserve `meta` everywhere and enforce `proxy_estimate: true` in `MethodMetadata`.

---

## 3.7 Pathology viewer architecture (OpenSeadragon + deep-zoom proxy)

## 3.7.1 Component boundary

`components/panels/enso-pathology-viewer.tsx` is a dedicated client component encapsulating all deep-zoom behavior. `PathologyPanel` only provides data inputs:

- `slideId`
- optional `viewportHint` (heatmap focus)
- optional `selectedEvidenceBbox` (tile-linked highlight)

This separation keeps pathology presentation logic decoupled from viewer engine internals.

## 3.7.2 Proxy request flow

The viewer constructs pathology URLs through helper builders:

- `buildDziUrl(slideId)` → `/v1/pathology/slides/{slide_id}/dzi`
- `buildTileUrl(slideId, level, tileSpec)` → `/v1/pathology/slides/{slide_id}/tile/{level}/{x_y.format}`
- `buildHeatmapUrl(...)` → `/v1/pathology/slides/{slide_id}/attention-heatmap?...`

When `NEXT_PUBLIC_API_BASE_URL` exists, `resolveApiUrl()` prefixes these relative paths to target backend host.

Backend path (implemented in `apps/api/routers/pathology.py` + `services/pathology_assets.py`):

1. resolve incoming slide ID to Enso embedding-native ID (`resolve_enso_slide_id`),
2. proxy DZI/tile/heatmap asset calls to Enso API (`proxy_enso_asset`),
3. forward selected cache/geometry headers (`X-Coverage-Width`, etc.) back to frontend.

## 3.7.3 Viewer initialization and tile source setup

Initialization sequence in `useEffect`:

1. dynamic import `openseadragon` (client-only),
2. fetch DZI XML descriptor and parse via `parseDziDescriptor`,
3. instantiate OpenSeadragon with custom `getTileUrl(level,x,y)` that targets proxy tile endpoint,
4. on `open` event, cache base layer (`viewer.world.getItemAt(0)`) and mark ready.

If DZI fetch/parse fails, viewer enters explicit error overlay state.

## 3.7.4 Heatmap overlay pipeline

Second effect handles heatmap overlay lifecycle:

1. request attention heatmap image blob from backend proxy endpoint,
2. decode image dimensions,
3. compute overlay world dimensions using:
   - base layer content size,
   - `X-Coverage-Width` / `X-Coverage-Height` headers if present,
   - fallback grid coverage estimate otherwise,
4. `viewer.addSimpleImage(...)` to place overlay layer,
5. apply smoothing/pixelated interpolation controls (`applyHeatmapInterpolation`).

Mode controls then adjust opacity relationships:

- `slide`: base visible, heatmap hidden,
- `overlay`: base visible, heatmap alpha-adjusted,
- `heatmap`: heatmap visible, base optionally hidden if overlay loaded cleanly.

## 3.7.5 Overlay interaction model (viewport + evidence)

The viewer maintains two HTML overlay divs positioned in pixel space:

- viewport overlay (cyan)
- evidence overlay (amber)

Algorithm:

1. receive normalized box (`x,y,width,height` in `[0,1]`),
2. clamp via `clampBox`,
3. map normalized image coords → OpenSeadragon viewport coords (`imageToViewportCoordinates`),
4. map viewport coords → screen pixels (`pixelFromPoint`),
5. update absolutely-positioned overlay DOM element.

Synchronization handlers are attached to OSD `open`, `animation`, and `resize` events so overlays track pan/zoom transitions continuously.

## 3.7.6 Controls and failure handling

User controls include:

- model selector (`model_id`),
- mode toggle (Original / Overlay / Heatmap),
- smoothing toggle,
- opacity slider,
- sensitivity slider (`alpha_power`),
- per-overlay visibility toggles.

Failure handling includes:

- viewer init errors (DZI/tile issues),
- heatmap-specific errors parsed from upstream JSON/text (`getErrorMessage`),
- loading masks while viewer startup is incomplete,
- robust cleanup on unmount (destroy viewer, revoke object URLs, hide overlays).

---

## 3.8 UI behavior boundaries: real backend data vs mock fallback semantics

This is the most important operational boundary for current P0 delivery.

## 3.8.1 Fallback trigger conditions

Fallback occurs when any of the following holds:

- `NEXT_PUBLIC_API_BASE_URL` not set,
- network/transport failure,
- non-2xx response,
- payload explicitly marked as scaffold stub (`status: "stub"`),
- parser rejects payload shape (for parser-enabled methods).

When fallback triggers, the UI receives deterministic typed mock data with valid `meta` and research-only semantics.

## 3.8.2 Boundary matrix by domain

| Domain | Backend implementation state (per docs/status) | Frontend behavior boundary |
|---|---|---|
| Cohort case list | no frontend API call; static mock source | always local `MOCK_CASES` (backend-independent) |
| Upload init | persisted backend route exists | parsed live response if valid; else fallback |
| Upload files | backend route currently scaffold/stub | parser rejects stub or shape mismatch; fallback accepted file list |
| Analysis create/get | persisted backend routes exist | parser normalizes backend detail shape into UI timeline model |
| Pathology tissue/heatmap/evidence | typed backend routes implemented with strict/fallback semantics | client consumes live payload directly when available; falls back only on request failure |
| Deep zoom tile/DZI/attention endpoints | proxy-backed backend routes implemented | viewer uses live proxy endpoints; no mock equivalent inside viewer component |
| Transcriptomics | typed backend routes implemented | client consumes live payload directly when available; fallback on request failure |
| Clinical | typed backend routes implemented | same pattern as transcriptomics |
| Fusion | backend route implemented but schema differs from frontend contract shape | works reliably in pure mock mode; live mode requires schema alignment/parser to avoid contract drift issues |
| Agent | grounded backend route implemented | parser supports response coercion; fallback to mock agent answer on failure |

## 3.8.3 User-visible semantics of “missing” vs “failed” vs “mocked”

- **Missing modality (real semantic):** panel remains visible with explicit missing-state messaging (`MissingModalityState` / RNA warning banners / provisional-only fusion cues).
- **Backend failure/stub (integration semantic):** request silently falls back to mock payload, preserving UI continuity.
- **Analysis failure (workflow semantic):** explicit job errors shown on analysis page with retry links.

This distinction is critical: missing modality is a data truth; fallback is an integration resilience tactic.

## 3.8.4 Current integration tradeoff

The current client intentionally favors demo continuity over strict runtime validation for non-parser endpoints. This enables rapid progress but creates a known risk surface where backend schema evolution can break UI assumptions (especially fusion payload shape). Parser coverage extension would close this gap.

---

## 3.9 Data contracts table (frontend-facing)

The following table captures core frontend contracts as implemented in `lib/api-client/types.ts`.

| Contract | Required guarantees expected by UI | Typical nullable fields |
|---|---|---|
| `MethodMetadata` | `method`, `version`, `timestamp`, `proxy_estimate=true` | none |
| `AnalysisJobResponse` | `job_id`, `case_id`, `state`, `steps[]` | `errors` |
| `PathologyTissueCompositionResponse` | fractions sum-like composition + QC + metadata | none |
| `PathologyHeatmapResponse` | `slide_id`, `heatmap_uri`, `viewport_hint`, `meta` | `slide_preview_uri` |
| `PathologyEvidenceResponse` | `top_tiles` with score/rationale | tile `bbox` optional |
| `Cyt/Gep/TideResponse` | numeric-or-null value + availability boolean + metadata | `value` nullable |
| `ClinicalPatientSummaryResponse` | diagnosis context + highlights + metadata | most demographics fields nullable |
| `ClinicalEligibilityResponse` | trial count + rationale + metadata | route may be null at page level |
| `ClinicalSurvivalBaselineResponse` | risk group + baseline + CI + metadata | route may be null at page level |
| `FusionScoreResponse` | provisional/refined/delta/CI/missing modalities + metadata | refined/delta may be null |
| `FusionAttributionResponse` | per-modality contribution array | none |
| `FusionSimilarCasesResponse` | neighbor case list with distance/note | none |
| `AgentQueryResponse` | answer text + citation array + missing-modality acknowledgment + metadata | citation array may be empty |

---

## 3.10 Verification hooks and quality guardrails

Frontend test coverage is still intentionally lightweight but aligned to high-value behavior:

- **Contract coercion/fallback tests** (`lib/api-client/client.test.ts`)
  - verifies upload-init schema normalization,
  - verifies analysis-detail → timeline mapping,
  - verifies stub payload fallback path.

- **Route smoke tests** (`app/upload/page.test.tsx`, `app/analysis/[job_id]/page.test.tsx`)
  - ensure route-level data wiring and action links remain correct.

- **Trust/messaging guardrails** (`research-disclaimer.test.tsx`, `missing-modality-state.test.tsx`)
  - prevent accidental removal of research-only and missing-modality language.

Given current fallback-heavy strategy, these tests are essential to keep integration behavior stable while backend contracts continue evolving.

---

## 3.11 Key architectural conclusions and near-term hardening priorities

1. **The App Router shell is structurally sound and coherent with docs goals**
   - `/upload` → `/analysis` → `/patient` is fully implemented and composable.

2. **The API client is intentionally a compatibility firewall**
   - parser-enabled endpoints already absorb backend shape drift,
   - global fallback keeps demo operational under partial backend readiness.

3. **Pathology viewer is the most advanced frontend subsystem**
   - complete deep-zoom + heatmap proxy architecture,
   - overlay synchronization model tied to OSD viewport events,
   - robust cleanup and error surfacing.

4. **Current weakest boundary is parser coverage breadth**
   - many modality/fusion endpoints bypass runtime shape parsing,
   - this is acceptable for mock-first demo mode but not for strict live integration.

5. **Behavior boundaries are explicit and user-friendly**
   - missing modality is rendered transparently,
   - research-only framing is global and persistent,
   - analysis failures produce actionable retry paths.

In short, `apps/web` currently functions as a resilient, research-safe, workflow-complete shell with one major technical debt axis: expanding parser/contract coercion for all live endpoints (especially fusion) to match the robustness already present in upload/analysis/agent paths.

---

## Section 04 — Data Pipelines, Contracts, CI, and Ops

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

---

## Section 05 — Testing, Security, and Production Readiness

## 5.1 Scope, docs-first grounding, and framing

This section evaluates how close the current system is to production-grade reliability from three angles:

1. **Testing architecture** (backend, frontend, CI guardrails, and contract/coherence checks)
2. **Quality gates and release readiness** (what is currently enforced vs what is still trust-based)
3. **Security and operations hardening** (module-by-module roadmap and staged rollout criteria)

Docs-first inputs used for this section:

- `docs/README.md`
- `docs/architecture/plan.md`
- `docs/execution/task-backlog.md`
- `docs/execution/implementation-status.md`

Repository evidence used for this section includes:

- `apps/api/tests/*`
- `apps/web/**/*.test.ts(x)`
- `tests/ci/*`
- `scripts/ci/check_architecture_coherence.py`
- `scripts/ci/check_data_contract_tooling.py`
- `scripts/check_transcriptomics_coverage_gate.py`
- `scripts/audit_luad_embedding_coverage.py`
- `scripts/validate_pathology_artifacts.py`
- `.github/workflows/ci.yml`
- `Makefile`

This analysis is deliberately candid: the platform has **strong docs/contract guardrails and good typed API behavior coverage**, but still has **major production blockers in auth, operational controls, and end-to-end reliability testing**.

---

## 5.2 Testing architecture (current state)

### 5.2.1 Test-layer topology

The test architecture currently resembles a practical “foundation-first” pyramid:

- **App behavior tests (backend, frontend)**
  - Validate endpoint contracts, source precedence, typed missingness semantics, and core UI render behavior.
- **Repo/contract guardrail tests (`tests/ci`)**
  - Validate documentation presence/coherence, script contracts, workflow reliability assumptions, and release-gate tooling behavior.
- **Script-level deterministic checks**
  - Validate data-contract and modality-coverage gates through executable CLIs.

What is strong:

- Testing is directly tied to architecture/doc contracts, not just implementation internals.
- Behavior around missing modalities and typed unavailable states is explicitly tested (a major reliability and trust requirement).
- Data-contract and reproducibility scripts are unusually well covered for a hackathon-stage system.

What is still thin:

- No E2E workflow testing for the full UI → API → DB journey.
- No load, stress, or soak testing.
- No security test lane (SAST/DAST/dependency policy gate) in CI.
- No migration/backward-compatibility test lane tied to deployment readiness.

### 5.2.2 `apps/api` test architecture

Backend tests are service-rich and contract-oriented, organized under `apps/api/tests` with in-memory sqlite fixtures.

#### Coverage domains currently implemented

| Test file(s) | Primary behavior validated | Why it matters for readiness |
|---|---|---|
| `test_health.py` | Liveness response shape and research-use header posture baseline | Ensures non-business critical health contract stability |
| `test_uploads.py` | Upload session initialization contract and metadata persistence semantics | Protects entrypoint integrity for all downstream workflows |
| `test_analysis.py` | Job create/get flow, event wiring, and status detail serialization | Guards orchestration backbone contract |
| `test_pathology.py` | Artifact-backed pathology responses, strict missing semantics, provenance shape, Enso endpoint-related behavior | Critical for explainability and safe degradation when pathology assets are absent |
| `test_transcriptomics.py` | CYT/GEP/TIDE/evidence semantics, source precedence, frozen-reference governance metadata, coverage route semantics | Directly protects the “refined score depends on RNA” story and release-gate semantics |
| `test_clinical.py` | Clinical source fallback chain (`artifact → modality_result → XML/report → case metadata → unavailable`) | Ensures deterministic behavior under partial data conditions |
| `test_fusion.py` | Provisional/refined mode switching, modality contribution semantics, similarity output contracts | Protects high-visibility scoring outputs used by UI and agent |
| `test_agent.py` | Agent response shape, citation grounding, missing-modality acknowledgement | Prevents regressions that silently drop attribution/citation quality |
| `test_services.py` | `ensure_case_exists` idempotency and stub response consistency | Stabilizes shared helpers used across routers |

#### Architecture characteristics

- **In-memory DB tests** via sqlite lower setup friction and allow fast local/CI runs.
- **Endpoint + service-level blend** catches more than unit-level logic while avoiding heavy integration cost.
- **Typed availability semantics** are tested as first-class behavior (not incidental assertions).
- **Deterministic fallback behavior** is intentionally encoded in tests (important for reproducible demos).

#### Backend test blind spots

- No tests for **authn/authz** because those controls are not yet present.
- No concurrent-job race testing on analysis lifecycle transitions.
- No schema migration tests (Alembic upgrade/downgrade compatibility).
- No “real Postgres + Redis” integration lane in CI; sqlite-only hides some production behavior classes.
- No chaos/fault-injection tests for Enso upstream proxy failures beyond basic response handling.

### 5.2.3 `apps/web` test architecture

Frontend tests are currently smoke + contract-normalization focused (Vitest + RTL), which is appropriate for this maturity level but incomplete for release-grade confidence.

#### Current test inventory

- `apps/web/lib/api-client/client.test.ts`
  - Verifies payload coercion/normalization from backend schema into UI-safe models.
  - Verifies stub fallback behavior when backend returns scaffold payloads.
- `app/upload/page.test.tsx`
  - Verifies route-level render with cohort data and selected case propagation.
- `app/analysis/[job_id]/page.test.tsx`
  - Verifies analysis status rendering and retry path behavior on failures.
- `components/common/missing-modality-state.test.tsx`
  - Verifies explicit missing-modality messaging semantics.
- `components/layout/research-disclaimer.test.tsx`
  - Verifies research-only disclaimer visibility.

#### What this gives confidence in

- Basic UI route rendering won’t regress silently.
- API client parsing layer can absorb modest backend schema drift.
- Research-only and missing-data UX guardrails are visible and tested.

#### What remains untested but is production-critical

- No Playwright/Cypress E2E tests for upload → analysis → patient workspace → chat.
- No browser-level tests for pathology viewer deep-zoom controls and overlay behavior.
- No resilience tests for slow/failing API responses under realistic network conditions.
- No accessibility regression checks (keyboard nav, aria semantics, color contrast) in CI.

### 5.2.4 `tests/ci` architecture: contracts, coherence, and reliability

The `tests/ci` suite is a major strength of this repo: it encodes **repository and architecture invariants** that many projects only document informally.

#### Guardrail categories

| CI guardrail area | Representative tests/scripts | Enforcement focus |
|---|---|---|
| Repo structure and docs invariants | `test_repo_guardrails.py`, `docs/README.md` required-doc list | Prevents doc-structure drift and missing foundation docs |
| Architecture/docs/code coherence | `test_architecture_coherence.py`, `scripts/ci/check_architecture_coherence.py` | Ensures required API groups/endpoints and UI route expectations stay aligned across docs + code |
| Data-contract script integrity | `test_data_contract_tooling.py`, `scripts/ci/check_data_contract_tooling.py` | Ensures CLI contracts, delegation wrappers, symbols, and required literals remain stable |
| MVP50 determinism/hardening | `test_data_contract_edge_cases.py`, `test_mvp50_module_detachability.py` | Validates edge cases, deterministic outputs, wrapper behavior, and lock artifacts |
| Pathology release tooling | `test_pathology_data_scripts.py` | Validates coverage/validation script behavior and strict failure semantics |
| Transcriptomics release-gate tooling | `test_transcriptomics_release_gate.py` | Validates threshold and blocker semantics for transcriptomics gate outputs |
| Workflow reliability quality | `test_ci_workflow_reliability.py` | Ensures timeout and cache hygiene in CI jobs |
| Documentation link integrity | `test_markdown_links.py` | Catches broken local documentation links |

This lane is not just “CI for code syntax”; it is effectively **CI for project coherence**.

### 5.2.5 Contract/coherence checks as release primitives

Two scripts deserve explicit callout as release primitives:

1. **`scripts/ci/check_architecture_coherence.py`**
   - Ensures required docs exist.
   - Verifies docs index (`docs/README.md`) resolves to real files.
   - Verifies required API route groups and endpoint inventory are coherent between architecture docs and backend router implementation.
   - Verifies core UI routes in docs are represented in `apps/web/app` route tree.

2. **`scripts/ci/check_data_contract_tooling.py`**
   - Verifies required cohort/download/MVP50 files exist.
   - Checks syntax and `--help` callability of critical CLIs/wrappers.
   - Verifies wrapper delegation contracts and public symbol contracts.
   - Protects backward-compatible operator workflow expectations.

These checks do not replace runtime validation, but they significantly reduce “silent architecture drift” risk.

---

## 5.3 Quality gates and release readiness model

### 5.3.1 Current quality gates (as implemented)

The current quality gate stack is strongest at **structural correctness and deterministic behavior**, less strong at **operational and security readiness**.

| Gate | Command/Workflow | Current signal | Current blind spots |
|---|---|---|---|
| Repo guardrails | `pytest tests/ci -q` | Strong repo/docs/contracts invariants | No runtime, load, or security exploit simulation |
| Architecture coherence | `python scripts/ci/check_architecture_coherence.py` | Strong docs↔code API/UI coherence | Doesn’t validate behavioral correctness or performance |
| Data-contract tooling | `python scripts/ci/check_data_contract_tooling.py` | Strong script-level continuity and CLI behavior | Doesn’t validate real-world data quality at scale |
| Backend smoke + app tests | `python scripts/ci/run_backend_smoke.py` | Compile/import + `apps/api/tests` behavior | No Postgres/Redis integration lane in CI |
| Frontend checks | `bash scripts/ci/run_frontend_checks.sh` | test + typecheck + build | No browser E2E and no UI load/accessibility gates |
| Modality release scripts (operator) | pathology/transcriptomics gate scripts | Deterministic threshold/blocker gating | Not yet mandatory in automated release pipeline for all release candidates |

From `implementation-status.md` latest validated baseline:

- `apps/api/tests` → **85 passed**
- `tests/ci` → **60 passed**
- targeted pathology/transcriptomics suite → **68 passed**

This is a good baseline for a prototype, but not yet a production bar.

### 5.3.2 Proposed readiness model (from current state)

A practical maturity model for this repository:

| Level | Name | Required characteristics |
|---|---|---|
| R0 | Prototype scaffold | Route skeletons, typed schemas, deterministic stubs/fallbacks |
| R1 | Internal engineering demo-ready | App-level tests green, CI guardrails green, deterministic missing-data semantics |
| R2 | Controlled research pilot-ready | Authn/authz baseline, observability, release-gate automation, E2E happy-path tests |
| R3 | External multi-user research beta-ready | Security hardening complete, incident response runbooks, load-tested infra, backup/restore drills |
| R4 | Regulated production candidate | Validation lifecycle, governance/compliance controls, formal model lifecycle controls |

#### Current projected position by subsystem

- **Overall platform**: ~**R1.3**
- Stronger at contract/test determinism than many peers, but held back by missing security and ops controls.

### 5.3.3 Release gate decision model (go/no-go)

Use a three-axis release decision instead of a single test pass/fail:

1. **Correctness axis** (tests + schema contracts)
2. **Safety axis** (security controls + provenance + missingness handling)
3. **Operability axis** (monitoring, deployment reliability, rollback readiness)

A release candidate should be blocked when:

- Any axis score is below minimum threshold for target stage.
- Any “hard blocker” remains open (e.g., no authn for external beta, no backup drill for persistent-state rollout).

---

## 5.4 Security and operations hardening roadmap (module-by-module)

### 5.4.1 Cross-cutting baseline controls (must land before external users)

Before subsystem-specific hardening, the platform needs these cross-cutting controls:

- **AuthN/AuthZ** for all non-health API routes.
- **Role policy** for researcher vs operator vs admin actions.
- **Secrets management** (no default credential assumptions in deploy envs).
- **Structured audit logging** with request IDs and actor IDs.
- **Rate limiting/quota controls** on expensive or abuse-prone endpoints (pathology tile proxy, agent query).
- **Dependency scanning gate** (Python + Node advisories with severity policy).
- **Observability baseline** (metrics, traces, error budgets, alert routing).
- **Backup/restore + migration safety** (especially PostgreSQL state).

### 5.4.2 Subsystem hardening matrix (gaps → mitigations → validation evidence)

| Subsystem | Current gap | Mitigation | Validation evidence required |
|---|---|---|---|
| Pathology | Proxy endpoints and asset serving lack auth/rate limits for high-cost tile traffic | Add auth middleware + per-user rate limiting + signed/expiring asset token strategy | Security test suite proving unauthorized and over-quota requests are blocked; load test report for tile endpoints |
| Pathology | Heatmap/WSI serving strategy not fully standardized for production storage topology | Standardize object storage + immutable artifact URI contract + checksum verification at fetch time | Artifact integrity check logs, S3/object-store policy docs, checksum mismatch alert test |
| Transcriptomics | Frozen-reference governance exists, but reference lifecycle ownership is process-fragile | Add governed reference registry (version, checksum, approval metadata) and promotion workflow | Reference registry entries + signed approval record + CI check that deployed reference matches registry |
| Transcriptomics | TIDE precompute semantics exist but pipeline lifecycle integration is incomplete | Add job orchestration with run IDs, retries, timeout policy, and status telemetry | Job success/error dashboards, reproducibility replay report, coverage gate pass artifact in CI |
| Clinical | XML/report parsing is deterministic but lacks hardened parser threat controls and audit depth | Use hardened XML parsing (`defusedxml`), schema/field validation, and parser provenance IDs | Static analysis + malicious fixture tests + parser-run provenance in API payload |
| Clinical | On-demand extraction can drift and is hard to audit longitudinally | Materialize a versioned clinical feature store with lineage to source files | Feature-store snapshot manifest + row-level lineage checks + migration tests |
| Fusion | Score logic is deterministic but heuristic and not model-governed | Introduce model registry/version pinning, calibration checks, and monotonicity test suite | Calibration report, model card, regression thresholds, gated release artifact |
| Fusion | Confidence intervals are heuristic and not statistically validated | Replace heuristic CI with empirically derived uncertainty estimation from validation cohort | Validation notebook/report committed artifact + CI threshold checks |
| Agent | Agent endpoint currently deterministic synthesis; eventual LLM integration risks prompt injection/data leakage | Implement strict tool-call sandbox, input sanitization, response policy checks, citation-required output validator | Red-team prompt-injection test suite, citation-coverage metrics, blocked unsafe output logs |
| UI | API client falls back to mocks on broad failure classes, which can mask backend incidents | Gate fallback behavior by environment and surface explicit degraded-mode banner + telemetry event | UI integration tests for degraded mode + monitoring dashboard showing fallback rate |
| UI | No auth/session model in frontend flows | Add OIDC/session integration + route guards + token refresh handling | E2E auth flow tests and token-expiry behavior tests |
| Infra | CI validates build/test but no deployment reliability lane | Add deploy pipeline with canary + rollback + post-deploy smoke checks | Deployment runbooks + automated rollback drill evidence |
| Infra | No explicit SLO/error budget framework | Define SLOs per critical endpoint group and wire alert thresholds | SLO dashboard snapshots + monthly error-budget review logs |

### 5.4.3 Security hardening priorities by horizon

#### Horizon A (0–2 weeks): “minimum safe external demo”

- Add authentication middleware and API key/JWT guardrails for `/v1/*` except `/health`.
- Add basic per-IP/per-user rate limits for pathology proxy routes and `/v1/agent/query`.
- Add dependency advisory gate in CI (`pip-audit`, `npm audit` policy) with block thresholds.
- Add structured request logging with correlation IDs and standardized error response envelope.
- Disable broad mock fallback in production UI mode.

#### Horizon B (2–6 weeks): “controlled pilot safety”

- Add trace/metrics instrumentation for all modality endpoints and agent routes.
- Add backup/restore drill for PostgreSQL and test migration rollback path.
- Add E2E tests for core user journey and authorization boundaries.
- Add staged environment promotion with canary deployment and rollback automation.

#### Horizon C (6+ weeks): “external beta reliability”

- Model governance + uncertainty calibration for fusion outputs.
- Feature-store materialization and lineage for clinical and transcriptomics sources.
- Security review of pathology asset lifecycle and proxy architecture.
- Incident response playbooks and on-call alerting maturity.

---

## 5.5 Production-readiness gap analysis by subsystem

The table below scores each subsystem on a 1–5 scale:

- **1** = prototype only
- **3** = controlled research pilot capable
- **5** = production-grade for broad external reliability expectations

| Subsystem | Functional completeness | Test depth | Security posture | Ops posture | Overall readiness | Candid assessment |
|---|---:|---:|---:|---:|---:|---|
| Pathology | 3.2 | 3.5 | 1.8 | 2.0 | **2.6** | Strong typed behavior and provenance semantics, but exposure controls and serving hardening are not yet production-grade |
| Transcriptomics | 3.4 | 3.4 | 2.0 | 2.2 | **2.8** | Availability semantics and coverage gating are strong; operational lifecycle and governance automation are incomplete |
| Clinical | 2.8 | 3.1 | 2.1 | 2.0 | **2.5** | Deterministic and typed, but still heuristic and lacks durable feature-store + governance maturity |
| Fusion | 2.7 | 2.9 | 2.0 | 1.9 | **2.4** | Endpoint contract works, but model quality governance and uncertainty rigor are not yet sufficient |
| Agent | 2.6 | 2.6 | 1.7 | 1.8 | **2.2** | Grounded structure exists, but no hardened safety/policy perimeter for scale exposure |
| UI | 3.0 | 2.5 | 1.9 | 2.1 | **2.4** | Good shell + panel behavior, but no auth lane and no E2E reliability envelope |
| Infra/platform | 2.4 | 2.8 | 1.8 | 1.9 | **2.2** | CI guardrails are strong; deployment, observability, and resilience maturity are still low |

### 5.5.1 Pathology

**Strengths:** robust typed contracts, strict-missing semantics, deterministic recursive ID resolution, provenance expansion, artifact validation scripts.

**Blocking gaps:** secure asset delivery model, authenticated proxy access, load control for tile endpoints, and end-to-end artifact lifecycle automation.

### 5.5.2 Transcriptomics

**Strengths:** excellent typed availability semantics (including frozen reference and precompute status), explicit release-gate scripting.

**Blocking gaps:** reference governance operationalization, production precompute lifecycle, automated pipeline wiring for release gates.

### 5.5.3 Clinical

**Strengths:** deterministic source precedence and typed unavailable semantics are implemented clearly.

**Blocking gaps:** parser hardening + lineage depth + feature-store persistence for auditability and reproducibility under change.

### 5.5.4 Fusion

**Strengths:** clear provisional/refined mode contract and modality attribution surface.

**Blocking gaps:** heuristic signal/CI logic is not yet model-governed or externally validated to a robust statistical standard.

### 5.5.5 Agent

**Strengths:** grounded citation shape and missing-modality acknowledgment are already encoded.

**Blocking gaps:** no hardened policy/safety layer for eventual LLM-backed behavior and no adversarial test lane.

### 5.5.6 UI

**Strengths:** coherent route model and meaningful missingness/research disclaimers.

**Blocking gaps:** no auth/session controls, no full-browser E2E pipeline, and fallback semantics can mask backend failures if not environment-gated.

### 5.5.7 Infra/platform

**Strengths:** coherent CI, good docs guardrails, reproducibility scripts, deterministic release checks.

**Blocking gaps:** absent deployment hardening (canary/rollback automation), limited observability/SLO enforcement, and no formal incident workflow.

---

## 5.6 Concrete staged rollout plan with acceptance criteria

### 5.6.1 Stage model

| Stage | Target audience | Objective | Hard acceptance criteria | Exit artifacts |
|---|---|---|---|---|
| Stage 0 — Internal hardening baseline | Core engineering only | Stabilize safety + observability baseline | Authn for `/v1/*` (except health), rate limits on pathology/agent, dependency advisory gate, structured logs with request IDs | Security test report, CI pass with new gates, logging dashboard snapshot |
| Stage 1 — Trusted internal research demo | Internal research team | Reliable end-to-end demo with known cohort | Upload→analysis→patient→chat E2E happy-path test green; no critical runtime errors under smoke load; transcriptomics/pathology gate scripts automated in CI | E2E test report, release gate outputs, runbook v1 |
| Stage 2 — Controlled pilot (small external) | Selected collaborators | Safe constrained exposure | RBAC enforced, canary deploy + rollback tested, SLO/alerts live for critical endpoints, backup/restore drill passed | Deployment and rollback drill report, SLO dashboard, incident runbook |
| Stage 3 — External research beta | Broader external researchers | Multi-user reliability and governance | Model/version governance for fusion, clinical/transcriptomics lineage evidence, security review complete, monthly reliability review process active | Governance package, security review sign-off, monthly reliability reports |

### 5.6.2 Stage checklists (gaps → mitigation → evidence)

#### Stage 0 checklist

- [ ] **Gap:** unauthenticated API surface for all business routes  
      **Mitigation:** add auth middleware and policy enforcement on all `/v1` routers  
      **Evidence:** integration tests proving unauthorized access blocked (401/403)

- [ ] **Gap:** abuse exposure on expensive endpoints  
      **Mitigation:** add rate limiting for pathology proxy and agent query routes  
      **Evidence:** load test + limit-trigger audit logs

- [ ] **Gap:** hidden dependency risk (notably Node advisory surface)  
      **Mitigation:** dependency policy gate in CI with severity threshold  
      **Evidence:** CI artifact with advisory scan and enforced policy result

- [ ] **Gap:** low observability for incident triage  
      **Mitigation:** structured logs + correlation IDs + standardized error envelope  
      **Evidence:** traceable request log samples linked to endpoint failures

#### Stage 1 checklist

- [ ] **Gap:** no browser-level assurance of full workflow  
      **Mitigation:** add Playwright E2E for upload, analysis polling, patient workspace, chat query  
      **Evidence:** CI E2E job output with deterministic fixtures

- [ ] **Gap:** release gates partially manual/operator-driven  
      **Mitigation:** run pathology/transcriptomics gate scripts in release workflow  
      **Evidence:** stored JSON/CSV gate artifacts attached to release candidate

- [ ] **Gap:** fallback semantics can obscure outages  
      **Mitigation:** disable broad fallback in production mode; expose degraded-mode banner  
      **Evidence:** integration tests + telemetry showing fallback event count

#### Stage 2 checklist

- [ ] **Gap:** deployment reliability not validated  
      **Mitigation:** canary rollout + automated rollback on SLO breach  
      **Evidence:** executed rollback drill and change-failure-rate report

- [ ] **Gap:** persistent data resilience not demonstrated  
      **Mitigation:** backup/restore exercises and migration rollback testing  
      **Evidence:** documented RTO/RPO drill result and migration test log

- [ ] **Gap:** ops alerting not tied to user-impact SLOs  
      **Mitigation:** define endpoint SLOs and paging thresholds  
      **Evidence:** live dashboard + alert test events

#### Stage 3 checklist

- [ ] **Gap:** fusion uncertainty and model governance are heuristic-heavy  
      **Mitigation:** model registry, calibration checks, approved model card process  
      **Evidence:** versioned model governance artifact and threshold pass report

- [ ] **Gap:** clinical/transcriptomics provenance not fully audit-grade  
      **Mitigation:** feature-store lineage, parser run IDs, source checksum linkage  
      **Evidence:** lineage query examples + audit report

- [ ] **Gap:** security review not institutionalized  
      **Mitigation:** periodic threat model + penetration testing cadence  
      **Evidence:** signed security review findings and remediation closure logs

### 5.6.3 Gate ownership model (recommended)

| Gate cluster | Primary owner | Backup owner | Review cadence |
|---|---|---|---|
| API correctness + schema contracts | Backend lead | Fusion lead | Per PR |
| Data-contract and modality release gates | Data contracts owner | Transcriptomics owner | Per RC cut |
| Frontend workflow and UX reliability | UI lead | Agent lead | Per PR + pre-demo |
| Security controls and dependency policy | Infra/security owner | Backend lead | Weekly |
| Ops readiness (deploy, rollback, SLO, backup) | Infra owner | Platform lead | Weekly + pre-release |

Without explicit ownership, even strong scripted gates degrade over time.

---

## 5.7 Practical conclusions and immediate execution order

### 5.7.1 What is objectively strong already

1. **Contract/coherence discipline is excellent** for a project at this stage.
2. **Typed missingness and provenance semantics** are treated as first-class behavior and tested.
3. **Data-contract and deterministic tooling** are unusually robust and CI-visible.

### 5.7.2 What blocks production-readiness most

1. **Security perimeter is incomplete** (auth/rate limiting/secrets policy).
2. **Operational maturity is incomplete** (observability/SLO/rollback/backups).
3. **End-to-end workflow confidence is incomplete** (no full-browser E2E and no scale validation).

### 5.7.3 Next 10 execution items (ordered)

1. Add authentication/authorization middleware for all non-health API routes.
2. Add rate limiting on pathology proxy and agent routes.
3. Add dependency vulnerability policy gate to CI.
4. Add structured request/error logging + correlation IDs.
5. Add Playwright E2E happy-path tests for upload→analysis→patient→chat.
6. Wire transcriptomics and pathology release-gate scripts into release workflows.
7. Environment-gate API client mock fallback behavior (no silent prod fallback).
8. Add canary deploy + rollback automation and rehearsal.
9. Add backup/restore drill and migration rollback tests.
10. Define endpoint SLOs and activate alerting tied to user-impact.

If these 10 items are completed with evidence, the platform can credibly move from an internal engineering demo baseline to a controlled external research pilot posture.

---

**Bottom line:** The repository is already stronger than typical prototypes in documentation coherence and deterministic behavior gating. The fastest path to real-world readiness is not adding more model complexity first; it is adding the missing security and operational guardrails around the functionality that already exists.
