# Product Architecture & Repository Structure

Last updated: 2026-03-05

## A) Recommended product architecture

## 1. Architecture principle
Use a **specialist-branches + fusion + agent** architecture:
- each modality computes evidence independently,
- fusion model combines branch outputs,
- agent only reasons over structured API outputs.

This matches your meeting constraints: fast build, explainability, and no risky end-to-end multimodal pretraining.

## 2. Runtime architecture (high level)

```text
Raw Data (TCGA-LUAD)
  ├─ H&E SVS
  ├─ RNA STAR Counts
  └─ Clinical XML + pathology report text
        │
        ▼
[Ingestion + Harmonization]
(case_id keyed manifest + quality checks)
        │
        ├───────────────┬────────────────┬────────────────
        ▼               ▼                ▼
 [Pathology]      [Transcriptomics]   [Clinical/EHR-lite]
 - tile embeds    - CYT/GEP/TIDE      - tabular features
 - tissue fractions - subtype/deconv  - text embedding
 - heatmap tiles  - pathways          - eligibility rules
        └───────────────┬────────────────┘
                        ▼
                 [Fusion Layer]
          provisional vs refined score
          survival/progression + SHAP + CI
                        │
             ┌──────────┴──────────┐
             ▼                     ▼
      [Similarity Index]      [Evidence Store]
         FAISS k-NN           patient JSON bundles
             └──────────┬──────────┘
                        ▼
                   [API Gateway]
   /pathology /transcriptomics /clinical /fusion /agent-tools
                        ▼
                [LLM Reasoning Agent]
       tool-calls only; no raw embedding access
                        ▼
               [Clinician-facing Dashboard]
```

## 3. Data/compute modes

- **Batch mode (default for hackathon):** precompute all branch outputs for cohort.
- **Online mode (demo interaction):** read cached outputs + run fast fusion/agent calls.

This avoids online WSI bottlenecks and keeps the demo stable.

## 3.1 Web UI architecture (critical path)

The UI is a first-class product surface (not a last-mile wrapper). It must support **display + upload + analysis + chat** in one workflow.

> **Source of truth for UI:** [`ui-architecture.md`](ui-architecture.md)
> That doc owns page layout, panel specs, interaction requirements, and demo acceptance bar.
> This section provides only the high-level UX flow for architectural context.

### UX flow (summary)
1. **Upload / Select** → `/upload`
2. **Run analysis job** → `/analysis/{job_id}` (async, per-modality progress)
3. **Review results workspace** → `/patient/{case_id}` (heatmap + RNA plots + clinical + fusion + chat)
4. **Ask agent** → right-rail chat panel with evidence-grounded answers

### Key interaction rules
- Every card has a "show source/provenance" affordance.
- Missing modality gracefully degrades with explicit messaging.
- Agent responses must reference endpoint fields (not hidden chain-of-thought).

### Tech stack (recommended)
- **Frontend:** Next.js (App Router) + Tailwind CSS
- **Backend:** FastAPI (Python)
- **Database:** PostgreSQL (**system of record**)
- **Queue/State:** Redis for async job queue (fallback: in-memory only for local quick tests)

## 3.2 Persistence model (PostgreSQL-first)

Use PostgreSQL as the canonical backend store for all structured state.

Store in PostgreSQL:
- Cohort entities: `cases`, `slides`, `samples`, `files`
- Analysis orchestration: `upload_sessions`, `analysis_jobs`, `job_events`
- Branch outputs (typed JSON + metadata): pathology/transcriptomics/clinical/fusion result rows
- Agent traces (request/response metadata + citations, no hidden reasoning text)

Store outside PostgreSQL (filesystem/object storage) and reference by URI:
- Large raw files (SVS, RNA TSV, XML/PDF/TXT)
- Generated artifacts (heatmap images, plot images, logs)

This keeps Postgres compact and queryable while avoiding BLOB-heavy DB usage.

## 3.3 Developer tooling + local environment architecture

To reduce setup variance and make checks repeatable, keep a single local workflow contract:

- **Entrypoint:** root `Makefile` with stable targets for CI-equivalent checks.
- **Docker-first full stack:** root `docker-compose.yml` + `.env.docker.example` for one-command web + api + postgres + redis.
- **Local infra (optional):** `infra/dev/docker-compose.yml` for Postgres + Redis only.
- **Bootstrap/check scripts:** `scripts/dev/bootstrap.sh` and `scripts/dev/check.sh` (non-destructive, idempotent).
- **Formatting baseline:** `.editorconfig` for cross-editor consistency.

### Local service contract

- PostgreSQL service name: `postgres`
  - host port: `5432`
  - default database: `yc_aixbio`
  - auth via env vars (never hardcoded secrets in docs)
- Redis service name: `redis`
  - host port: `6379`
- API service name: `api`
  - host port: `8000`
- Web service name: `web`
  - host port: `3000`

Expected local environment variables:
- `DATABASE_URL` (e.g., Postgres SQLAlchemy URL)
- `REDIS_URL` (e.g., redis connection URL)
- `CORS_ALLOW_ORIGINS` (comma-separated browser origins)
- `NEXT_PUBLIC_API_BASE_URL` / `INTERNAL_API_BASE_URL` (web↔api wiring)

### Validation contract

The local developer workflow should always pass these gates before PR:
1. `make lint-shell`
2. `make test-ci`
   - includes `scripts/ci/check_data_contract_tooling.py` coverage for locked cohort/download scripts and detachable MVP50 module entrypoints.
3. `make backend-smoke`
4. `make frontend-smoke`

`make ci` should chain the full set for one-command reproducibility.

## 3.4 Test architecture (foundation hardening)

To keep delivery velocity while preserving behavior, maintain a lightweight app-level test stack:

- **Backend (`apps/api/tests`)**
  - pytest + FastAPI TestClient coverage for health, uploads init, and analysis job create/get flows
  - sqlite in-memory fixture as default test database (no external Postgres required)
  - service helper unit tests for case bootstrap idempotency and research-stub payload shaping
- **Frontend (`apps/web`)**
  - vitest + React Testing Library for foundational component behavior and route-level smoke rendering
  - explicit coverage for missing-modality UX and research-only disclaimer visibility
- **CI integration**
  - extend existing conditional checks so backend/frontend tests run only when corresponding app folders exist
  - avoid workflow rewrites; keep guardrail structure stable

## 4. Required API surface

### Upload + Analysis orchestration
- `POST /v1/uploads/init` (create upload session)
- `POST /v1/uploads/files` (attach files to session)
- `POST /v1/analysis/jobs` (start analysis run)
- `GET /v1/analysis/jobs/{job_id}` (status/progress/errors)
- `GET /v1/analysis/jobs/{job_id}/artifacts` (logs + generated outputs)

### Pathology
- `GET /v1/pathology/slides/{slide_id}/tissue-composition` *(supports `strict_missing` semantics)*
- `GET /v1/pathology/slides/{slide_id}/heatmap` *(supports `strict_missing` semantics)*
- `POST /v1/pathology/slides/{slide_id}/evidence` *(supports `strict_missing` semantics)*

### Transcriptomics
- `GET /v1/transcriptomics/{case_id}/cyt`
- `GET /v1/transcriptomics/{case_id}/gep` *(with frozen-reference governance fields)*
- `GET /v1/transcriptomics/{case_id}/tide` (experimental; `experimental=true` gate; precompute availability semantics)
- `POST /v1/transcriptomics/{case_id}/evidence`
- `GET /v1/transcriptomics/coverage` (per-case presence + missingness audit + release-gate fields)

### Clinical
- `GET /v1/clinical/{case_id}/patient-summary`
- `GET /v1/clinical/{case_id}/eligibility`
- `GET /v1/clinical/{case_id}/survival-baseline`

### Fusion
- `POST /v1/fusion/{case_id}/score` (provisional + refined)
- `GET /v1/fusion/{case_id}/attribution`
- `GET /v1/fusion/{case_id}/similar-cases`

### Agent tool façade
- `POST /v1/agent/query`
- internally calls tool endpoints (`get_patient_summary`, `get_pathology_evidence`, `get_transcriptomic_evidence`, `get_model_score`, `get_similar_cases`, `compare_with_without_rna`)

## 5. Feature coverage map (meeting-context aligned)

- **Immunotherapy responder narrative** → fusion score + transcriptomic signatures + agent explanation
- **Provisional vs refined story** → fusion endpoint with missingness flags
- **Heatmap + explainability** → pathology heatmap endpoint + top evidence tiles
- **Clinical report style output** → agent synthesis over structured branch JSON
- **Chat/query mode** → agent endpoint grounded by tool APIs

---

## B) Target directory structure

```text
yc-aixbio-hackathon/
├── apps/
│   ├── api/                         # FastAPI serving layer
│   │   ├── main.py
│   │   ├── routers/
│   │   │   ├── uploads.py
│   │   │   ├── analysis.py
│   │   │   ├── pathology.py
│   │   │   ├── transcriptomics.py
│   │   │   ├── clinical.py
│   │   │   ├── fusion.py
│   │   │   └── agent.py
│   │   └── dependencies/
│   ├── web/                         # Next.js UI app
│   │   ├── app/
│   │   │   ├── upload/
│   │   │   ├── analysis/[job_id]/
│   │   │   └── patient/[case_id]/
│   │   ├── components/
│   │   └── lib/api-client/
│   └── worker/                      # async jobs
│
├── pipelines/
│   ├── ingestion/
│   ├── pathology/
│   ├── transcriptomics/
│   ├── clinical/
│   ├── fusion/
│   └── evaluation/
│
├── packages/
│   ├── schemas/
│   ├── mvp50/                       # detachable MVP50 contract-validation + lock module
│   ├── db/                          # Postgres models, queries, repository layer
│   ├── feature_store/
│   ├── retrieval/
│   ├── prompts/
│   └── utils/
│
├── data/
│   ├── manifests/
│   ├── raw/
│   ├── interim/
│   ├── processed/
│   └── cache/
│
├── models/
│   ├── pathology/
│   ├── transcriptomics/
│   ├── clinical/
│   ├── fusion/
│   └── metadata/
│
├── infra/
│   └── db/
│       ├── migrations/              # Alembic or SQL migrations
│       └── seed/
│
├── docs/
│   ├── README.md
│   ├── architecture/
│   │   ├── plan.md
│   │   ├── predictive-tasks-data-flow.md
│   │   └── ui-architecture.md
│   ├── execution/
│   │   └── task-backlog.md
│   └── context/
│       ├── README.md
│       ├── project-context.md
│       ├── deep-research-dataset-feasibility.md
│       ├── deep-research-pathology-mvp.md
│       ├── deep-research-transcriptomics-mvp.md
│       ├── chatgpt-roadmap.md
│       └── meeting-notes/
│
├── scripts/
│   ├── build_tcga_matched_cohort.py
│   ├── download_tcga_matched_data.sh
│   ├── mvp50.py
│   ├── validate_matched_cohort.py
│   ├── lock_mvp50_manifest.py
│   └── ci/
│       ├── check_architecture_coherence.py
│       └── check_data_contract_tooling.py
│
└── README.md
```

---

## C) Non-negotiable implementation choices

1. **Case-keyed contracts everywhere** (`case_id`, `slide_id`, `sample_id`) to keep tri-modal joins deterministic.
2. **Freeze reference normalization** for transcriptomics to prevent score drift (50-case MVP → 475-case scaling).
3. **Cache-first serving** for demo reliability.
4. **Tool JSON > raw model outputs** for the agent.
5. **Research-only guardrails** in all endpoint responses.
6. **UI-first integration**: upload → analysis → workspace → chat must work end-to-end before optional model upgrades.
7. **Async job orchestration**: analysis runs cannot block the UI thread; always expose progress/state APIs.
8. **PostgreSQL as source of truth**: do not use ad-hoc JSON files as primary state for jobs/results once API is active.
9. **Detachable operator modules with stable wrappers**: reusable data-contract workflows (for example MVP50 validate/lock) should live under `packages/` and be surfaced via simple script wrappers for operator continuity.
