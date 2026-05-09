# Documentation Index

Last updated: 2026-03-06 17:35 PST

This folder is the **single source of truth** for project documentation.

## Structure

- `architecture/` — system design, dataflow, API surface, UI architecture
- `execution/` — task backlog and implementation progress
- `archive/` — expired documents kept for historical reference
- `data-contract/` — canonical schema + operator runbooks for deterministic manifests
- `context/` — meeting-derived context, deep-research notes, decision history
- `technical-reference/` — long-form module-by-module technical documentation
- `../packages/mvp50/` — detachable MVP50 operator module (validate/lock core + CLIs)
- `CONTRIBUTING.md` — contributor workflow and local validation checklist

## Required docs (CI enforced)

These files must always exist and stay current:
- `README.md`
- `docs/README.md`
- `docs/architecture/plan.md`
- `docs/architecture/ui-architecture.md`
- `docs/data-contract/p0-contract-and-mvp50-ops.md`
- `docs/execution/task-backlog.md`
- `packages/mvp50/README.md`

## Suggested reading order

1. [`context/project-context.md`](context/project-context.md) — current scope + constraints
2. [`architecture/plan.md`](architecture/plan.md) — architecture + modular boundaries
3. [`execution/task-backlog.md`](execution/task-backlog.md) — what to build next
4. [`execution/implementation-status.md`](execution/implementation-status.md) — what is done vs pending (main + feature-branch commit refs)
6. [`CONTRIBUTING.md`](CONTRIBUTING.md) — branch workflow, docs-first policy, local checks
7. [`data-contract/p0-contract-and-mvp50-ops.md`](data-contract/p0-contract-and-mvp50-ops.md) — contract validation + deterministic manifest lock operations
8. [`../packages/mvp50/README.md`](../packages/mvp50/README.md) — detachable MVP50 module boundaries + public entrypoints
9. [`architecture/ui-architecture.md`](architecture/ui-architecture.md) — UI behavior (upload, analysis, display, chat)
10. [`architecture/predictive-tasks-data-flow.md`](architecture/predictive-tasks-data-flow.md) — full endpoint matrix and flow
11. [`technical-reference/TECHNICAL_REFERENCE_50P.md`](technical-reference/TECHNICAL_REFERENCE_50P.md) — consolidated long-form module/class/method documentation
12. `context/deep-research-*.md` — implementation references
13. `context/meeting-notes/` — origin decisions and rationale

## Developer workflow references (maintainability lane)

- [`../Makefile`](../Makefile) — unified local commands (`make ci`, `make test-ci`, `make test-api`, `make test-web`, `make lint-shell`, `make docker-up`)
- [`../docker-compose.yml`](../docker-compose.yml) — full-stack Docker dev run (web + api + postgres + redis)
- [`../.env.docker.example`](../.env.docker.example) — portable Docker env template (ports, CORS, data mounts)
- [`../infra/dev/docker-compose.yml`](../infra/dev/docker-compose.yml) — infra-only Postgres + Redis stack
- [`../scripts/dev/bootstrap.sh`](../scripts/dev/bootstrap.sh) — non-destructive setup/bootstrap helper
- [`../scripts/dev/check.sh`](../scripts/dev/check.sh) — local readiness and validation checks
- [`../scripts/mvp50.py`](../scripts/mvp50.py) — unified operator CLI (`validate` / `lock`) backed by detachable module code
- [`../scripts/validate_matched_cohort.py`](../scripts/validate_matched_cohort.py) — legacy-compatible validation wrapper
- [`../scripts/lock_mvp50_manifest.py`](../scripts/lock_mvp50_manifest.py) — legacy-compatible lock wrapper
- [`../scripts/audit_luad_embedding_coverage.py`](../scripts/audit_luad_embedding_coverage.py) — deterministic full475 pathology coverage report (manifest ↔ embeddings ↔ artifacts)
- [`../scripts/validate_pathology_artifacts.py`](../scripts/validate_pathology_artifacts.py) — pathology artifact schema/alignment validator
- [`../scripts/check_transcriptomics_coverage_gate.py`](../scripts/check_transcriptomics_coverage_gate.py) — transcriptomics coverage-output release-gate validator

## Naming convention

- lowercase kebab-case filenames
- no dates in core architecture/execution docs
- dates only in meeting notes and deep-research snapshots

## Guardrail

All docs must preserve this positioning:
- **research-only prototype**
- **proxy scores/signatures** (not clinical predictions)
- provenance + uncertainty surfaced in outputs

## Architecture coherence guardrails

`python scripts/ci/check_architecture_coherence.py` enforces cross-layer coherence for:
- core docs-first files (`docs/README.md`, architecture plan/UI spec, execution backlog)
- required docs listed in `docs/README.md`
- required API route groups across `plan.md`, `ui-architecture.md`, and backend router prefixes
- core UI workflow routes from `ui-architecture.md` against `apps/web/app` route tree (when web app exists)

## CI + local validation

Repository CI runs `pytest tests/ci`, architecture coherence checks, and data-contract tooling checks to protect docs structure, module entrypoints, and link integrity.

Run locally before opening a PR:

```bash
python -m pip install -r requirements-ci.txt
# if running backend smoke locally, also install API deps in a virtualenv:
# python -m pip install -r apps/api/requirements.txt
make ci
```

Equivalent explicit commands:

```bash
python -m pytest tests/ci -q
python scripts/ci/check_architecture_coherence.py
python scripts/ci/check_data_contract_tooling.py
python scripts/mvp50.py --help
python scripts/validate_matched_cohort.py --help
python scripts/lock_mvp50_manifest.py --help
python scripts/check_transcriptomics_coverage_gate.py --help
python scripts/ci/run_backend_smoke.py
bash scripts/ci/run_frontend_checks.sh
```

## App-level foundation tests (maintainability)

- Backend: `apps/api/tests/` (pytest + FastAPI TestClient + sqlite in-memory fixtures)
- Frontend: `apps/web` vitest + React Testing Library smoke/component tests
- CI policy: keep app test execution conditional on `apps/api` and `apps/web` presence, extending existing layout detection rather than replacing it
