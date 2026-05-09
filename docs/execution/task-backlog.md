# Build Backlog (Hackathon)

Last updated: 2026-03-06 17:35 PST

## Goal
Ship a stable demo of tri-modal LUAD clinical decision support with:
- provisional score (H&E + clinical),
- refined score (+RNA),
- explainable evidence,
- natural-language agent output.

## Tech stack (decided)
- **Frontend:** Next.js (App Router) + Tailwind CSS
- **Backend API:** FastAPI (Python)
- **Database:** PostgreSQL (system of record)
- **ML:** PyTorch (pathology encoders), scikit-learn/XGBoost (fusion), TIDEpy (RNA)
- **Job queue:** Redis preferred (in-memory only for local quick testing)

## Build order (dependency chain)
```
P0.1 Data contracts ──→ P0.3 Pathology ──→ P0.6 Fusion ──→ P0.7 Agent
                    ├──→ P0.4 Transcriptomics ──↗
                    ├──→ P0.5 Clinical ──────────↗
                    └──→ P0.2 UI shell (parallel; stub endpoints first)
```
P0.1 (data contracts) unblocks everything. P0.2 (UI) can start in parallel with stub/mock endpoints.
P0.6 (fusion) requires at least pathology + clinical outputs. P0.7 (agent) requires fusion + evidence endpoints.

> Live progress snapshot: see [`implementation-status.md`](implementation-status.md) for branch/commit-level status.
>
> Latest validated baseline (main):
> - `pytest tests/ci` ✅
> - backend smoke + `apps/api` tests ✅
> - frontend test/typecheck/build ✅
> - `make ci` ✅

---

## P0 — Must complete

### 1) Data contracts + cohort integrity
- [x] Finalize canonical join schema (`case_id`, `slide_id`, `sample_id`, `gdc_file_id`)
- [x] Create PostgreSQL baseline schema + initial migration (cases/files/jobs/results)
- [x] Wire API config/env to PostgreSQL connection
- [x] Extract MVP50 validation/lock workflows into detachable module (`packages/mvp50`) with stable script wrappers
- [ ] Merge MVP50 bughunt hardening branches (`feat/mvp50-bughunt-*`) into main
- [ ] Lock 50-case MVP manifest
- [ ] Validate modality completeness per case (H&E / RNA / clinical)
- [ ] Add manifest version hash + provenance metadata

**Done when:** same 50 cases reproducibly load across all branches and core entities persist in Postgres, with operator tooling modularized and backward-compatible.

### 2) Web UI shell (display + upload + analysis + chat)
- [x] Build `/upload` flow (cohort select + drag/drop file upload)
- [x] Build `/analysis/{job_id}` progress page (queued/running/done/failed)
- [x] Build `/patient/{case_id}` workspace layout (header + modality panels)
- [x] Add pathology heatmap viewer + transcriptomics plots + clinical summary cards *(shell-level placeholders; real model outputs pending)*
- [x] Add right-side chat panel wired to evidence-grounded agent endpoint *(route wired; full grounded logic pending)*
- [ ] Add provenance drawer per panel (show source fields/snippets)

**Done when:** user can upload/select case, run analysis, inspect results, and ask chat questions in one continuous UI flow.

### 3) Pathology MVP endpoints
- [x] Tissue composition endpoint (`tumor/stroma/necrosis`)
- [ ] Immune infiltration proxy endpoint
- [x] Heatmap endpoint + top evidence tiles
- [x] QC fields (`coverage`, `artifact warning`, `method/version`)
- [x] Strict missing-data semantics toggle (`strict_missing` query + env default)
- [x] Stronger provenance payload fields (`model/checkpoint/run/embedding` + resolver strategy + artifact hash/path)
- [x] Deterministic non-symlink resolution preserved in recursive artifact/file lookups

**Done when:** dashboard shows heatmap + fractions for all demo patients with explicit missing-data semantics and provenance.

### 4) Transcriptomics MVP endpoints
- [x] CYT endpoint (GZMA/PRF1)
- [x] 18-gene GEP proxy endpoint
- [x] TIDE endpoint behind `experimental=true` gate (local only; typed unavailable when no precompute)
- [x] Transcriptomic evidence endpoint (scores + gene panel + QC)
- [x] Transcriptomics coverage audit/report endpoint (`GET /v1/transcriptomics/coverage`) with per-case missingness semantics
- [x] TIDE precompute availability semantics (`precompute` block + typed availability codes)
- [x] Frozen-reference governance for GEP (`required/available/valid`, reference id/hash/path)
- [x] Coverage-output release gate CLI (`scripts/check_transcriptomics_coverage_gate.py`)

**Done when:** per-patient RNA panel is deterministic/reproducible and release-gate semantics are enforceable from coverage outputs.

### 5) Clinical MVP endpoints
- [x] Parse available TCGA clinical XML into deterministic extraction logic (on-demand parser service; persistent feature-store materialization still pending)
- [x] Stage + summary endpoint
- [x] Eligibility summary endpoint (rule-based + rationale; supports precomputed payload override)
- [x] Survival baseline endpoint
- [x] Cox PH survival model endpoint (RNA-augmented; lifelines; 1/2/5yr OS probabilities + risk tier) — `GET /v1/clinical/{case_id}/survival`
- [x] Kaplan-Meier strata returned alongside Cox predictions (Low/Intermediate/High risk population curves)

**Done when:** each demo patient has a usable clinical summary card, or an explicit typed unavailable state with source-aware provenance.

### 6) Fusion MVP
- [x] Provisional score endpoint (no RNA)
- [x] Refined score endpoint (with RNA)
- [x] Delta + modality attribution endpoint (SHAP)
- [x] Confidence interval output
- [x] IO Immune Score (Hot/Warm/Cold tier) — `GET /v1/io-immune/{case_id}/score`
- [x] IO similar-patient k-NN retrieval (15-dim structured, no FAISS) — `GET /v1/io-immune/{case_id}/similar-cases`

**Done when:** “before vs after RNA” panel is live for demo patients.

### 7) Agent MVP
- [ ] Tool wrappers for evidence endpoints
- [ ] Prompt + response schema for grounded explanations
- [ ] Fail-safe behavior when a modality is missing
- [ ] Natural-language Q&A box wired to tool calls

**Done when:** agent answers “why did RNA change the score?” with cited evidence fields.

### 8) Foundation test hardening (backend + frontend)
- [x] Add backend pytest suite for health, uploads init, and analysis job create/get endpoints
- [x] Add sqlite in-memory test fixture to avoid external Postgres dependency in local/CI test runs
- [x] Add service helper tests for `ensure_case_exists` and `research_stub_response`
- [x] Add frontend vitest + React Testing Library setup with component and page smoke coverage
- [x] Extend existing CI conditional checks to run backend/frontend tests when corresponding app directories exist

**Done when:** backend and frontend foundational tests run green locally and in CI without changing product/API behavior.

---

## P1 — High-value additions

- [x] Similar patient retrieval — implemented as structured 15-dim k-NN (TME signals + staging + demographics); see `apps/api/services/io_similar.py`
- [x] Survival analysis panel (Cox + KM) — SurvivalPanel UI component with 1/2/5yr OS, KM chart, model info
- [ ] Histologic subtype output
- [ ] RNA deconvolution (cell fractions)
- [ ] Pathway activity panel
- [ ] Treatment ranking card

---

## P2 — Post-hackathon / stretch

- [ ] Adverse event risk modeling
- [ ] Pathologic stage proxy from pathology-only model
- [ ] Multi-cancer portability
- [ ] External guideline retrieval grounding

---

## Suggested owner split (fill in real names)

| Owner | Name | Tasks |
|-------|------|-------|
| **Pathology** | _(fill in)_ | P0.3 + P1 subtype |
| **Transcriptomics** | _(fill in)_ | P0.4 + P1 deconv/pathways |
| **Fusion/API** | _(fill in)_ | P0.1 + P0.6 + P1 retrieval |
| **Agent/UI** | _(fill in)_ | P0.2 + P0.5 + P0.7 |

> Cross-ref: [`../context/project-context.md`](../context/project-context.md) § 5 has team split signals from meetings (Hanson: RNA plots + agent-input viz).

---

## Demo acceptance checklist

- [x] Upload/select flow works without manual backend intervention
- [ ] Analysis job progress page updates correctly (queued/running/done) — progress page exists; polling integration pending
- [x] 3 preselected hero patients render end-to-end (mock data path confirmed)
- [x] Provisional vs refined score shown for each (IO Immune Score panel)
- [x] Heatmap + tissue fractions visible for each (PathologyPanel)
- [x] Transcriptome panel visible for each (CYT/GEP/TIDE)
- [x] Survival predictions visible (SurvivalPanel — Cox 1/2/5yr OS + KM chart)
- [x] IO Immune Score Hot/Warm/Cold tier and component breakdown
- [x] Similar patients panel (standalone 15-dim k-NN cards)
- [ ] Agent explanation references concrete evidence fields — route wired; grounding depth pending
- [ ] Provenance drawer shows source fields/snippets for major cards
- [x] **Research-only disclaimer visible** in UI footer, API response headers, and agent system prompt
- [x] **No clinical validity claims** in any visible text (scores are "proxy estimates", not "predictions")
- [x] Missing modality states render gracefully (not blank/error)
