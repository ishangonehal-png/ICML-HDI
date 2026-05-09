# Database Migrations (Alembic)

This folder contains PostgreSQL schema migrations for backend structured state.

## Usage

From repo root:

```bash
source apps/api/.venv/bin/activate
alembic -c infra/db/migrations/alembic.ini upgrade head
```

Create a new migration:

```bash
source apps/api/.venv/bin/activate
alembic -c infra/db/migrations/alembic.ini revision -m "describe change"
```

PostgreSQL is the system of record for all API-managed entities (jobs, upload sessions, modality outputs, provenance metadata).
