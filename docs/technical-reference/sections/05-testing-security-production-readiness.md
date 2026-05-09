# Section 05 — Testing, Security, and Production Readiness

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
