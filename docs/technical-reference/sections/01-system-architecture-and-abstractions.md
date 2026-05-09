# Section 01 — System Architecture and Abstractions

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
