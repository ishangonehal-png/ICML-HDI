# UI Architecture (Source of Truth)

Last updated: 2026-03-05

> This is the **canonical UI spec**. [`plan.md`](plan.md) § 3.1 summarizes and links here.
> If there's a conflict, this file wins.

## Tech stack
- **Frontend:** Next.js (App Router) + Tailwind CSS
- **API client:** fetch-based; typed schemas from `packages/schemas/`
- **Charts:** Recharts or similar lightweight library
- **WSI viewer:** OpenSeadragon (for heatmap overlays)

## Goal
A web UI that supports one continuous loop:

1. **display/select or upload data**
2. **run analysis**
3. **inspect multimodal evidence**
4. **chat with the agent for explanation**

## Core pages

## 1) `/upload`
- Cohort case selector (for preloaded TCGA-LUAD patients)
- Drag/drop upload area (WSI, RNA TSV, clinical XML/TXT/PDF)
- File validation and modality detection badges
- "Start analysis" CTA

## 2) `/analysis/{job_id}`
- Job state timeline (queued → running → completed / failed)
- Per-modality status cards:
  - pathology,
  - transcriptomics,
  - clinical extraction,
  - fusion,
  - evidence packaging
- Error surface with retry action

## 3) `/patient/{case_id}` (main workspace)

### Layout
- **Left rail:** patient list + quick filters; viewport-height on wide screens
- **Center:** modality and fusion panels; flexes to remaining width
- **Right rail:** agent chat panel; viewport-height on wide screens
- **Responsive shell:** full-bleed patient page grid that expands to browser width and collapses naturally at narrower breakpoints/zoom levels

### Center panels (top→bottom)
1. **Patient header**
   - stage, smoking status, provisional score, refined score, confidence interval
2. **Pathology panel**
   - WSI heatmap viewer
   - tissue composition fractions
   - top evidence tiles
3. **Transcriptomics panel**
   - CYT / GEP / TIDE cards
   - RNA plots
4. **Clinical panel**
   - structured summary + extracted report highlights
5. **Fusion panel**
   - score delta (without RNA vs with RNA)
   - modality attribution bars
   - similar patient retrieval

### Right rail (chat)
- Query input with suggested prompts
- Streaming answer area
- Evidence citations linking to cards + source snippets
- Quick actions:
  - "Why did RNA change score?"
  - "Show source for this claim"
  - "Compare to similar cases"

## Provenance and trust UX
- Every card includes `method`, `version`, `timestamp`.
- "Show source" opens field-level provenance (XML node, report snippet, file id).
- Missing modality states are explicit and non-blocking.

## API dependencies

All modality endpoints are keyed by `case_id` (see [`plan.md`](plan.md) § 4 for full route list):

| Domain | Key routes |
|--------|-----------|
| Upload | `POST /v1/uploads/init`, `POST /v1/uploads/files` |
| Analysis | `POST /v1/analysis/jobs`, `GET /v1/analysis/jobs/{job_id}` |
| Pathology | `GET /v1/pathology/slides/{slide_id}/tissue-composition`, `/heatmap`, `/evidence` |
| Transcriptomics | `GET /v1/transcriptomics/{case_id}/cyt`, `/gep`, `/tide`, `POST .../evidence`, `GET /v1/transcriptomics/coverage` |
| Clinical | `GET /v1/clinical/{case_id}/patient-summary`, `/eligibility`, `/survival-baseline` |
| Fusion | `POST /v1/fusion/{case_id}/score`, `GET .../attribution`, `.../similar-cases` |
| Agent | `POST /v1/agent/query` |

## Missing modality UX
- If a modality is absent (e.g., no RNA data), show the panel with a clear "Not available" state — not hidden, not error.
- Fusion score falls back to provisional (H&E + clinical only) with an explicit label.
- Agent must acknowledge missing modality in responses ("RNA data not available; score is provisional").

## Non-goals (hackathon)
- Pixel-perfect enterprise design system
- Real-time collaborative editing
- Full clinician auth/role management

## Research disclaimer UX
- Persistent footer banner: "Research-only prototype — not for clinical use"
- Every score card shows method + version + "proxy estimate" label
- Agent system prompt includes research-only guardrails

## Demo bar
UI is demo-ready when a user can:
1. pick/upload a case,
2. run analysis,
3. see heatmap + RNA plots + score delta,
4. ask chat questions and get evidence-grounded answers,
5. see research-only disclaimer visible at all times.
