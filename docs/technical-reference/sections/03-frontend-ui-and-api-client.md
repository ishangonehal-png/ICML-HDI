# Section 03 — Frontend UI and API Client

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
