# Contributing Guide

Last updated: 2026-03-05

Thanks for contributing. This repo is optimized for rapid iteration with explicit guardrails.

## 1) Branch workflow

1. Sync your local main branch:
   ```bash
   git checkout main
   git pull --ff-only
   ```
2. Create a focused branch:
   ```bash
   git checkout -b feat/<short-scope-name>
   ```
3. Keep changes scoped to one concern (e.g., API scaffolding, UI shell, docs, or dev tooling).
4. Open a PR early; keep it reviewable and small enough to validate quickly.

Recommended prefixes:
- `feat/` for additive work
- `fix/` for bug fixes
- `chore/` for tooling/docs/maintenance
- `docs/` for documentation-only changes

## 2) Docs-first rule (mandatory)

Before code changes, update relevant docs first.

For platform-level work, update these in order:
1. `docs/README.md`
2. `docs/architecture/plan.md`
3. `docs/execution/p0-next-24h-plan.md`
4. `docs/execution/implementation-status.md`

Then implement code/scripts and return to docs for final status updates.

## 3) Local setup (non-destructive)

### Docker-first full stack (recommended)

```bash
cp .env.docker.example .env.docker
# edit TCGA_FULL475_HOST_PATH in .env.docker when using full475 assets
make docker-up
```

Validate compose configuration only:

```bash
make docker-config
```

Stop the stack:

```bash
make docker-down
```

### Native host setup (without Docker app services)

Bootstrap and check your environment:

```bash
make dev-bootstrap
make dev-check
```

Install local check dependencies inside a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-ci.txt
python -m pip install -r apps/api/requirements.txt   # if apps/api checks are needed
```

Start local infrastructure (Postgres + Redis):

```bash
make infra-up
```

Stop local infrastructure:

```bash
make infra-down
```

## 4) Required environment variables

Set these in your shell (or local `.env` files), never in committed secrets:

- `DATABASE_URL` — SQLAlchemy-compatible Postgres URL
- `REDIS_URL` — Redis connection URL

Example shape only (replace placeholders):

```bash
export DATABASE_URL='postgresql+psycopg://<db_user>:<db_password>@localhost:5432/<db_name>'
export REDIS_URL='redis://localhost:6379/0'
```

## 5) Local validation checklist (before PR)

Preferred single command:

```bash
make ci
```

Equivalent explicit checks:

```bash
make format-check
make lint-shell
make test-ci
make backend-smoke
make frontend-smoke
```

At minimum, all of the following must pass:
- `python3 -m pytest tests/ci -q`
- `python3 scripts/ci/check_architecture_coherence.py`
- `python3 scripts/ci/check_data_contract_tooling.py`
- backend smoke checks (if `apps/api` exists)
- frontend checks (if `apps/web` exists)

## 6) Safe-merge checklist

Before requesting merge:

- [ ] Scope is limited and intentional (no unrelated refactors)
- [ ] Docs updated and links resolve
- [ ] CI/local checks pass
- [ ] No secrets or credentials committed
- [ ] Research-only disclaimers remain intact where applicable
- [ ] Rollback path is clear (revertable commit structure)

## 7) Reviewer expectations

Reviewers should be able to answer quickly:
1. What changed?
2. Why now?
3. How was it validated?
4. Is there any user-visible behavior change?

If those answers are not obvious in the PR description, update the PR before merge.
