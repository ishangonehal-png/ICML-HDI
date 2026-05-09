# Tri-Modal TCGA-LUAD IO Immune Readiness Demo

> **⚠️ Research-only prototype.** All outputs are proxy scores and signatures from public TCGA data. This is not a clinical assay, diagnostic tool, or treatment recommendation engine. See [Research Disclaimer](#research-disclaimer) below.

A hackathon project building a **tri-modal immunotherapy-readiness demo** from public TCGA-LUAD data:
- **Pathology:** H&E whole-slide images (SVS) → tile embeddings, heatmaps, tissue composition
- **Transcriptomics:** Bulk RNA-seq (STAR counts) → CYT, GEP, TIDE proxy scores
- **Clinical:** XML + pathology reports → stage, eligibility, survival baseline

**Core product story:** Classify the tumor microenvironment as **Hot / Warm / Cold** from H&E alone; refine with RNA when available; explain everything with a tool-grounded LLM agent.

---

## Table of Contents

- [Features & Calculations](#features--calculations)
  - [IO Immune Score](#1-io-immune-score)
  - [Cox Survival Model](#2-cox-proportional-hazards-survival-model)
  - [Kaplan-Meier Stratification](#3-kaplan-meier-stratification)
  - [RNA Transcriptomics Metrics](#4-rna-transcriptomics-metrics)
  - [Pathology Analysis](#5-pathology-analysis)
  - [Clinical Feature Extraction](#6-clinical-feature-extraction)
  - [Trial Eligibility](#7-trial-eligibility-evaluation)
  - [Similar Cases Search](#8-similar-cases-search)
  - [Agent Multimodal Query](#9-agent-multimodal-query)
  - [Analysis Job Lifecycle](#10-analysis-job-lifecycle)
  - [Upload & Session Management](#11-upload--session-management)
- [UI Components](#ui-components)
- [API Endpoints](#api-endpoints)
- [Data Models](#data-models-orm)
- [Architecture](#architecture)
- [Setup & Operations](#setup--operations)
  - [Docker Quick Start](#docker-quick-start)
  - [CI Guardrails](#ci-guardrails)
  - [Data Workflow](#core-data-workflow)
  - [Download Scripts](#download-script-usage)
  - [MVP50 Data Contract](#data-contract-validation--deterministic-mvp50-lock)
- [Research Disclaimer](#research-disclaimer)

---

## Features & Calculations

### 1. IO Immune Score

The central feature of the platform. Classifies the tumor microenvironment (TME) as **Hot**, **Warm**, or **Cold** based on immune infiltration signals from WSI and RNA. Implemented in [`apps/api/services/io_score.py`](apps/api/services/io_score.py).

#### Tiers
| Tier | Score range | Interpretation |
|---|---|---|
| **Hot** | ≥ 65% | Inflamed TME — higher likelihood of IO benefit |
| **Warm** | 40–65% | Intermediate — IO benefit uncertain |
| **Cold** | < 40% | Excluded/desert TME — IO less likely to respond |

#### Provisional Score (WSI only)

```
score = clip(TIL_fraction)
```

`TIL_fraction` = lymphocyte-rich fraction from WSI tissue segmentation.

#### Refined Score (with RNA)

Renormalized weighted average across all available components:

| Component | Weight | Transformation |
|---|---|---|
| GEP (18-gene IFNγ) | 0.35 | sigmoid(gep_value) |
| CYT (GZMA × PRF1) | 0.25 | sigmoid(cyt_value) |
| TIDE (exclusion) | 0.20 | sigmoid(−tide_value) — inverted so high TIDE = low score |
| TIL fraction | 0.15 | raw fraction |
| PD-L1 TPS | 0.05 | raw fraction (if IHC available) |

Weights are renormalized over whichever components are available:
```
score = Σ(value_i × weight_i) / Σ(weight_i)   [clipped to 0–1]
```

When RNA is unavailable the refined score is omitted and the provisional score is used as the active IO score.

---

### 2. Cox Proportional Hazards Survival Model

Trained via an offline Cox model training pipeline (`fit_survival_model.py`) on the TCGA-LUAD cohort using `lifelines.CoxPHFitter` (L2 penalizer = 0.1).

#### Clinical-Only Model (`cox_model.pkl`) — 11 features

| Feature | Encoding |
|---|---|
| `stage_ordinal` | I=1, II=2, III=3, IV=4 |
| `age_at_diagnosis` | continuous (years) |
| `smoking_ordinal` | never=0, former=1, current=2 |
| `is_female` | binary |
| `pack_years` | continuous; median-imputed if missing |
| `subtype_*` | 5 one-hot flags (lepidic, micropapillary, papillary, solid, mucinous; acinar = reference) |

#### RNA-Augmented Model (`cox_rna_model.pkl`) — adds 3 RNA features

| Feature | Description |
|---|---|
| `cyt_score` | Cytolytic activity (GZMA + PRF1) |
| `gep_score` | 18-gene IFNγ inflamed signature |
| `tide_score` | T-cell dysfunction/exclusion; median-imputed if missing |

Requires ≥ 20 cases with all three RNA scores to train.

#### Patient Prediction Pipeline

1. Build feature vector from clinical data
2. If RNA model available: augment with CYT / GEP / TIDE (zero-fill missing columns)
3. `partial_hazard = cph.predict_partial_hazard(row)`
4. Risk tier:
   - ph < 0.8 → **high**
   - 0.8 ≤ ph < 1.5 → **intermediate**
   - ph ≥ 1.5 → **low**
5. Survival probabilities at 1yr, 2yr, 5yr from `predict_survival_function`
6. Median survival = time at which S(t) = 0.5
7. Concordance index from training reported alongside predictions

---

### 3. Kaplan-Meier Stratification

Cohort split into tertiles by proxy score. Stored in `km_strata.json`.

```
Clinical proxy = stage_ordinal + 0.5 × smoking_ordinal
RNA proxy      = stage + 0.5×smoking − 0.5×gep − 0.3×cyt + 0.3×tide
```

Per stratum: time points, survival rates, n_at_risk, median OS.
Returned as population reference curves alongside each patient's individual prediction.

---

### 4. RNA Transcriptomics Metrics

Implemented in [`apps/api/services/transcriptomics.py`](apps/api/services/transcriptomics.py).

#### CYT (Cytolytic Activity)
```
CYT = log2( sqrt[(GZMA + ε) × (PRF1 + ε)] )
```
Proxy for tumor-infiltrating lymphocytes. Range ~4–8. Higher = more cytolytic immune activity.

#### GEP (18-gene IFNγ Signature)
Genes: CCL5, CD27, CD274, CD276, CD8A, CMKLR1, CXCL9, CXCL10, GZMA, HLA-DRA, IFNG, PRF1, STAT1, TBX21, TNFSF10, TNFSF9, XCL1, XCL2

```
for each gene:
    x = log2(TPM + 1)
    x = (x − mean_ref) / std_ref   # z-score using reference stats if available
    if gene == CD276: x = −x        # CD276 is inverse-weighted
GEP = mean(x across ≥15 of 18 genes)
```

#### TIDE (Tumor Immune Dysfunction and Exclusion)
- Precomputed artifacts only — not computed on-the-fly
- Higher = worse IO response; negated in fusion scoring
- Median-imputed for Cox model when missing

#### Data Source Priority (all three metrics)
1. Precomputed artifact JSON files
2. `ModalityResult` records in database
3. Raw counts TSV (TRANSCRIPTOMICS_COUNTS_DIR)
4. Unavailable

---

### 5. Pathology Analysis

Implemented in [`apps/api/services/pathology.py`](apps/api/services/pathology.py). Data from precomputed WSI artifacts.

**Tissue composition fractions:**
- Tumor, Stroma, Necrosis, Lymphocyte-rich (from artifact JSON)

**Evidence tiles (top 3):**
- `tile_id`, `score` (0–1), bounding box (x/y/w/h normalized to 0–1), row/col coordinates, rationale text

**Heatmap:** viewport hint (x, y, width, height) for initial WSI zoom

**QC:** coverage %, artifact warnings

**Pathology signal for fusion:**
```
S_path = 0.25 + 0.45 × tumor_fraction
              + 0.30 × lymphocyte_fraction
              + 0.20 × max(tile scores)
```

When artifacts are missing, a deterministic fallback provides predefined values.

---

### 6. Clinical Feature Extraction

Implemented in [`apps/api/services/clinical.py`](apps/api/services/clinical.py).

**Source priority:**
1. Artifact JSON (CLINICAL_ARTIFACT_DIR)
2. Database `ModalityResult`
3. TCGA XML parsing + text report extraction
4. Hash-based deterministic proxy

**Fields:** stage, smoking status, age (clamped 35–90), diagnosis, sex, vital status, pack-years, TNM (T/N/M), days to death / follow-up, path report fields (grade, margins, LVI, tumor_size_cm, IHC PDL1 TPS, TIL score).

**Survival baseline (deterministic fallback, no Cox model):**
```
base: I → 60mo, II → 42mo, III → 26mo, IV → 12mo
adjustments:
  age ≥ 75:        −8mo
  age ≥ 65:        −4mo
  ECOG ≥ 3:        −12mo
  ECOG == 2:       −6mo
  current smoker:  −5mo
  former smoker:   −2mo

risk group: ≥40mo → low, 20–40mo → intermediate, <20mo → high
CI: ±20% of baseline months
```

---

### 7. Trial Eligibility Evaluation

Rule-based heuristic (research proxy only).

| Criterion | Rule |
|---|---|
| Stage II–IV | met |
| Age 18–85 | met (blocking if outside range) |
| ECOG 0–1 | met (blocking criterion if available) |
| Smoking documented | met |

Returns: `eligible_trials` count, `eligibility_label` (eligible/ineligible/indeterminate), per-criterion `{status, observed_value, rationale}`.

---

### 8. Similar Cases Search

Multimodal k-NN over a precomputed cohort feature matrix. Implemented in [`apps/api/services/io_similar.py`](apps/api/services/io_similar.py).

#### Feature vector (15 dimensions)

| Axis | Description |
|---|---|
| GEP_z | IFNγ gene expression program (z-scored cohort) |
| CYT_z | Cytolytic activity GZMA×PRF1 (z-scored) |
| −TIDE_z | Immune exclusion/dysfunction (negated — lower TIDE = better) |
| TIL_z | WSI-derived lymphocyte fraction (z-scored) |
| Tumor_z | Tumor fraction from WSI (z-scored) |
| Necrosis_z | Necrosis fraction from WSI (z-scored) |
| Age_z | Age at diagnosis (z-scored) |
| Gender_z | Sex (binary) |
| Smoking_z | Ordinal: never=0, reformed>15yr=1, smokeless=1.5, reformed≤15yr=2, current=3 |
| PackYears_z | Pack-years smoked (z-scored; missing→0) |
| Stage_z | TNM stage ordinal I=1…IV=4 (z-scored) |
| T_z | T-stage ordinal (z-scored; missing→0) |
| N_z | N-stage ordinal (z-scored; missing→0) |
| M_z | M-stage ordinal (z-scored; missing→0) |
| ECOG_z | ECOG performance status (z-scored; missing→0) |

All features z-scored against cohort → missing values imputed to 0 (= cohort mean) → L2-normalized → cosine similarity via `matrix @ query_vec`.

For cases missing RNA, uses a 10-dim subspace (TIL, Tumor, Necrosis, Age, Gender, Smoking, PackYears, Stage, T/N/M, ECOG).

Demographics and staging parsed from TCGA BCR XML files (`data/clinical/full/xmls/`). Cohort matrix is a lazy singleton (built on first request, cached with `threading.Lock`).

Returns top-k cases with: case_id, similarity %, IO tier, GEP/CYT/TIDE z-scores, TIL fraction, stage, age, smoking, rationale.

---

### 9. Agent Multimodal Query

`POST /v1/agent/query` — assembles a natural language research summary:

1. Fusion score (provisional + refined + delta)
2. Tissue composition narrative
3. Top evidence tiles
4. CYT / GEP / TIDE values
5. Generates structured citations and only queries PubMed when the prompt explicitly asks for literature.

---

### 10. Analysis Job Lifecycle

**States:** queued → running → completed / failed

**Steps:** queue → pathology → transcriptomics → clinical → fusion → evidence_packaging

Each step logs a `JobEvent`; results are stored as `ModalityResult` records per modality.

---

### 11. Upload & Session Management

1. `POST /v1/uploads/init` → create session (returns session_id, accepted_modalities)
2. `POST /v1/uploads/files` → validate & store files (per-file accept/reject status)
3. `POST /v1/analysis/jobs` → trigger async analysis, return job_id for polling

---

## UI Components

### Patient Workspace (`/patient/[case_id]`)

3-column layout: sidebar | main panels | agent chat rail

**PatientHeader**
- Case ID, diagnosis, stage, smoking status
- 3 metric cards: IO Immune Tier (Hot/Warm/Cold colored), IO Score (%), Data sources (WSI / RNA / missing components)

**PathologyPanel**
- 4 metric cards: Tumor %, TIL %, Necrosis %, Top tile score
- Deep-zoom WSI viewer (OpenSeadragon)
- Viewport hint sets initial zoom location
- Tissue composition table (tissue type → %)
- Evidence tiles list (tile_id, score %, rationale) — clicking a tile highlights its bounding box on the WSI

**TranscriptomicsPanel**
- 3 metric cards: CYT, GEP, TIDE (with gene info labels)
- Top genes table (symbol → normalized count)
- Interpretation notes

**ClinicalSummaryPanel**
- Patient summary: stage, age, diagnosis
- Eligibility criteria checklist (met / not_met / unknown per criterion)
- Survival baseline: risk group, baseline months, 95% CI

**SurvivalPanel** *(after ClinicalSummaryPanel)*
- 4 metric cards: 1-yr, 2-yr, 5-yr OS probabilities (with 95% CI) + median OS
- SVG step-function Kaplan-Meier chart: Low / Intermediate / High risk strata; patient's own tier highlighted with bold stroke
- Model info card: version (`cox-ph-rna-v1` / `cox-ph-clinical-v1`), concordance index (C-index), feature tags

**IOImmunePanel**
- Tier badge (Hot / Warm / Cold) with color coding
- Provisional score card (WSI-only) and Refined score card (RNA-augmented)
- Component breakdown: bar chart per signal (GEP, CYT, TIDE, TIL, PD-L1) with weight and sigmoid-normalized value
- Interpretation legend: tier thresholds and clinical meaning
- Missing component list

**SimilarPatientsPanel** *(standalone, after IOImmunePanel)*
- k-NN neighbor cards: case ID, IO tier badge, stage, age, smoking, similarity % progress bar
- Feature space badge: lists which of the 15 dimensions were active for this query
- Rationale text per neighbor (GEP/CYT/TIL delta string)

**AgentChatRail** (right sidebar)
- Freeform chat interface → `POST /v1/agent/query`
- Displays multimodal narrative + structured citations linking back to source panels

---

### Upload Page (`/upload`)
- Case selector dropdown (from cohort)
- Drag-and-drop file upload area
- Modality selector: pathology / transcriptomics / clinical
- Triggers analysis job creation on submit

---

### Analysis Status Page (`/analysis/[job_id]`)
- Job timeline card (step-by-step progress)
- Per-modality status grid
- Error messages on failure
- Link to patient workspace on completion

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/v1/io-immune/{case_id}/score` | IO Immune Score (Hot/Warm/Cold tier + components) |
| GET | `/v1/fusion/{case_id}/score` | Fusion score (legacy — provisional + refined + delta) |
| GET | `/v1/fusion/{case_id}/attribution` | Per-modality contribution breakdown |
| GET | `/v1/fusion/{case_id}/similar-cases` | K-nearest similar cases (legacy fusion-based) |
| GET | `/v1/io-immune/{case_id}/similar-cases` | IO-signal k-NN similar patients (15-dim multimodal) |
| GET | `/v1/clinical/{case_id}/patient-summary` | Stage, smoking, age, path report fields |
| GET | `/v1/clinical/{case_id}/eligibility` | Trial eligibility evaluation |
| GET | `/v1/clinical/{case_id}/survival` | Cox model survival prediction |
| GET | `/v1/clinical/{case_id}/survival-baseline` | Deterministic survival baseline |
| GET | `/v1/transcriptomics/{case_id}/cyt` | Cytolytic activity score |
| GET | `/v1/transcriptomics/{case_id}/gep` | 18-gene IFNγ GEP score |
| GET | `/v1/transcriptomics/{case_id}/tide` | TIDE score (experimental) |
| GET | `/v1/pathology/slides/{slide_id}/tissue` | Tissue composition fractions |
| GET | `/v1/pathology/slides/{slide_id}/heatmap` | Heatmap URI + viewport hint |
| GET | `/v1/pathology/slides/{slide_id}/evidence` | Top evidence tiles |
| POST | `/v1/agent/query` | Multimodal natural language summary |
| POST | `/v1/analysis/jobs` | Trigger analysis job |
| GET | `/v1/analysis/jobs/{job_id}` | Job status + events |
| POST | `/v1/uploads/init` | Create upload session |
| POST | `/v1/uploads/files` | Upload files to session |

All endpoints return `meta.proxy_estimate: true` and response headers `X-Research-Use-Only: true`.

---

## Data Models (ORM)

| Table | Key Fields |
|---|---|
| `cases` | case_id, cohort, metadata |
| `files` | case_id, file_name, file_type, storage_uri, checksum |
| `upload_sessions` | case_id, status |
| `analysis_jobs` | case_id, status, requested_modalities, result_summary |
| `job_events` | job_id, event_type, message, payload |
| `modality_results` | job_id, case_id, modality, payload (metrics), metadata |

---

## Architecture

**Key design patterns:**
- **Artifact-first** data resolution: precomputed JSON takes priority; deterministic fallback if missing
- **IO Immune Score:** TME hotness classifier (Hot/Warm/Cold); provisional from WSI alone, refined when RNA available
- **Cox survival model:** RNA-augmented Cox PH (lifelines) with KM population strata; patient-level 1/2/5yr OS and tier assignment
- **Structured k-NN similarity:** 15-dim z-scored feature vector (TME signals + staging + demographics) — cohort-level L2-normalized cosine similarity; no text embeddings
- **Provenance tracking:** every metric includes source, field, method version, note
- **All outputs** tagged `proxy_estimate: true`

**Stack:**
- Backend: FastAPI + SQLAlchemy + PostgreSQL + Redis
- Frontend: Next.js (App Router) + Tailwind CSS + OpenSeadragon (WSI viewer)
- ML: lifelines (Cox PH, KM), numpy (k-NN cosine similarity), scikit-learn

**Project layout:**
```
apps/api/          FastAPI backend (routers, services, schemas, models)
apps/web/          Next.js frontend (pages, components, lib)
scripts/           Data acquisition, Cox model training, FAISS indexing
scripts/ci/        CI smoke checks and architecture guardrails
tests/ci/          Repository safety and docs guardrail tests
packages/schemas/  Canonical data contract definitions
packages/mvp50/    Detachable MVP50 validate/lock module
data/manifests/    Reproducibility artifact output root
docs/              Architecture, execution, context, operator runbooks
infra/db/          Alembic migrations
```

---

## Setup & Operations

### Docker Quick Start

```bash
# 1. Copy env file
cp .env.docker.example .env.docker

# 2. (Optional) Point to your TCGA full475 data root
# Edit .env.docker and set:
# TCGA_FULL475_HOST_PATH=/absolute/path/to/your/full475-root

# 3. Start the stack
docker compose --env-file .env.docker up --build

# Web UI:  http://localhost:3000/upload
# API docs: http://localhost:8000/docs

# 4. Stop
docker compose --env-file .env.docker down
```

Expected data subpaths under the mounted root:
- `pathology_artifacts/full475`
- `embeddings/level0`
- `transcriptomics/artifacts`
- `transcriptomics/counts`
- `clinical/artifacts`
- `clinical/xml`
- `clinical/reports`
- `tcga_luad_exact_matched_manifest_slides.tsv`

---

### CI Guardrails

Main CI workflow: [`.github/workflows/ci.yml`](.github/workflows/ci.yml)

What it enforces:
- **Always-on guardrails** (`pytest tests/ci`): docs structure, legacy-doc bans, script presence, markdown local-link validity
- **Architecture coherence** ([`scripts/ci/check_architecture_coherence.py`](scripts/ci/check_architecture_coherence.py)): docs ↔ API ↔ UI route consistency
- **Data contract tooling** ([`scripts/ci/check_data_contract_tooling.py`](scripts/ci/check_data_contract_tooling.py)): cohort/download scripts + MVP50 entrypoints
- **Conditional backend checks** (when `apps/api/` exists): compile + import smoke + pytest
- **Conditional frontend checks** (when `apps/web/` exists): `npm ci`, test, typecheck, build

Run locally:
```bash
python -m pip install -r requirements-ci.txt
python -m pytest tests/ci -q
python scripts/ci/check_architecture_coherence.py
python scripts/ci/check_data_contract_tooling.py
python scripts/ci/run_backend_smoke.py      # auto-skips if apps/api is absent
bash scripts/ci/run_frontend_checks.sh      # auto-skips if apps/web is absent
```

---

### Core Data Workflow

1. Build matched cohort and manifest from fixed LUAD filters
2. Write to `hansons-context/tcga_downloads/`:
   - `tcga_luad_exact_matched_cohort.csv`
   - `tcga_luad_exact_matched_manifest.tsv`
3. Filter manifest by modality flags
4. Download to `hansons-context/tcga_downloads/files/`

---

### Download Script Usage

```bash
# All modalities
bash scripts/download_tcga_matched_data.sh

# Modality subsets
bash scripts/download_tcga_matched_data.sh --rna
bash scripts/download_tcga_matched_data.sh --he
bash scripts/download_tcga_matched_data.sh --context
bash scripts/download_tcga_matched_data.sh --rna --he

# Custom output root
bash scripts/download_tcga_matched_data.sh --output-root data/tcga_downloads --rna --he
```

Validation is strict: exact matched case count = 475, exact manifest size per modality, exact file-type composition.

```bash
# Build cohort
python3 scripts/build_tcga_matched_cohort.py
python3 scripts/build_tcga_matched_cohort.py --project TCGA-LUAD --patient TCGA-05-4244
python3 scripts/build_tcga_matched_cohort.py --out-csv outputs/custom.csv --out-manifest outputs/custom.tsv
```

---

### Data Contract Validation + Deterministic MVP50 Lock

```bash
# Unified operator entrypoint
python3 scripts/mvp50.py validate \
  --cohort-csv hansons-context/tcga_downloads/tcga_luad_exact_matched_cohort.csv \
  --report-json data/manifests/validation/cohort_completeness_report.json \
  --fail-on-missing

python3 scripts/mvp50.py lock \
  --cohort-csv hansons-context/tcga_downloads/tcga_luad_exact_matched_cohort.csv \
  --manifest-tsv hansons-context/tcga_downloads/tcga_luad_exact_matched_manifest.tsv \
  --output-root data/manifests \
  --lock-name tcga_luad_mvp50_v1 \
  --subset-size 50 \
  --seed tcga-luad-mvp50-v1
```

Legacy wrappers: `scripts/validate_matched_cohort.py` and `scripts/lock_mvp50_manifest.py`

See [`docs/data-contract/p0-contract-and-mvp50-ops.md`](docs/data-contract/p0-contract-and-mvp50-ops.md) for full operator notes.

---

### Docs Index

All project docs are consolidated under [`docs/`](docs/).

- [`docs/README.md`](docs/README.md) — master index + reading order
- [`docs/architecture/plan.md`](docs/architecture/plan.md) — product/repo architecture
- [`docs/architecture/ui-architecture.md`](docs/architecture/ui-architecture.md) — UI source of truth
- [`docs/architecture/predictive-tasks-data-flow.md`](docs/architecture/predictive-tasks-data-flow.md) — full endpoint/dataflow spec
- [`docs/execution/task-backlog.md`](docs/execution/task-backlog.md) — build backlog and acceptance criteria
- [`docs/execution/implementation-status.md`](docs/execution/implementation-status.md) — current implementation snapshot
- [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) — contributor workflow, docs-first policy, validation checklist
- [`docs/data-contract/p0-contract-and-mvp50-ops.md`](docs/data-contract/p0-contract-and-mvp50-ops.md) — operator guide

---

## Research Disclaimer

This project is a **research-only prototype** built for the YC AIxBio hackathon.

- All scores, signatures, and predictions are **proxy estimates** derived from public TCGA data.
- Outputs have **not been validated in a clinical setting** and must not be used for patient care decisions.
- Surrogate labels (TIDE, GEP, CYT) are computed from RNA expression, not from measured treatment response — TCGA-LUAD lacks direct immunotherapy response records.
- Uncertainty, QC, and provenance metadata are surfaced in every endpoint to support auditability.

Any demo or presentation should clearly state these limitations.
