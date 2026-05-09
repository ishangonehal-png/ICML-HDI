# `apps/web` — P0 Frontend Shell

Next.js (App Router + TypeScript + Tailwind) shell for the YC AIxBio hackathon flow:

1. `/upload` — cohort select + drag/drop uploader
2. `/analysis/[job_id]` — async progress timeline + modality status
3. `/patient/[case_id]` — patient workspace (pathology/transcriptomics/clinical/fusion) + chat rail

> Research-only prototype. All scores are proxy estimates and not for clinical use.

## Run locally

```bash
cd apps/web
npm install
cp .env.example .env.local  # optional API wiring defaults
npm run dev
```

Open: <http://localhost:3000/upload>

Run frontend tests:

```bash
npm run test
```

## Optional API wiring

Set backend base URLs to call real endpoints:

```bash
# Browser-facing URL (used in client components)
export NEXT_PUBLIC_API_BASE_URL="http://localhost:8000"

# Optional server-side URL for Next.js SSR routes (useful in Docker)
export INTERNAL_API_BASE_URL="http://localhost:8000"
```

When running with Docker Compose, a common setup is:
- `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`
- `INTERNAL_API_BASE_URL=http://api:8000`

If no API base URL is configured (or backend is unavailable), the UI uses typed mock responses from `lib/api-client/mock-data.ts`.
For deployment/runtime validation, set `NEXT_PUBLIC_DISABLE_MOCK_FALLBACK=true` to fail fast on backend errors.
The upload + analysis job endpoints already run in fail-fast mode even when non-critical panel mocks remain enabled.

## Structure highlights

- `app/upload`, `app/analysis/[job_id]`, `app/patient/[case_id]`
- Reusable UI components under `components/` (including shared card/section primitives)
- Route-level workspace composition/data helpers under `components/patient/` and `lib/patient-workspace.ts`
- Typed API client under `lib/api-client/`
