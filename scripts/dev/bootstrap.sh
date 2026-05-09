#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/infra/dev/docker-compose.yml"

START_INFRA=0

usage() {
  cat <<'EOF'
Usage: bash scripts/dev/bootstrap.sh [--start-infra]

Non-destructive local setup helper:
- checks required CLI tools
- creates apps/api/.env from .env.example only if missing
- validates docker compose file syntax (if docker is installed)
- prints env var setup hints for DATABASE_URL and REDIS_URL

Options:
  --start-infra   Start local postgres + redis after checks
  -h, --help      Show this help text
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --start-infra)
      START_INFRA=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

cd "${REPO_ROOT}"

echo "==> Checking required tooling"
required_cmds=(python3 make git)
missing_required=()
for cmd in "${required_cmds[@]}"; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    missing_required+=("${cmd}")
  fi
done

if [[ ${#missing_required[@]} -gt 0 ]]; then
  printf 'Missing required command(s): %s\n' "${missing_required[*]}" >&2
  exit 1
fi

echo "==> Optional tooling"
optional_cmds=(docker npm)
for cmd in "${optional_cmds[@]}"; do
  if command -v "${cmd}" >/dev/null 2>&1; then
    echo "  - ${cmd}: found"
  else
    echo "  - ${cmd}: not found (optional)"
  fi
done

if [[ -f "apps/api/.env" ]]; then
  echo "==> apps/api/.env already exists (left unchanged)"
elif [[ -f "apps/api/.env.example" ]]; then
  cp "apps/api/.env.example" "apps/api/.env"
  echo "==> Created apps/api/.env from apps/api/.env.example"
else
  echo "==> apps/api/.env.example not found; skipped env file bootstrap"
fi

if command -v docker >/dev/null 2>&1 && [[ -f "${COMPOSE_FILE}" ]]; then
  echo "==> Validating ${COMPOSE_FILE}"
  docker compose -f "${COMPOSE_FILE}" config -q
  echo "docker compose config validation passed"
else
  echo "==> Skipped docker compose validation (docker or compose file unavailable)"
fi

if [[ ${START_INFRA} -eq 1 ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "Cannot start infra: docker is not installed" >&2
    exit 1
  fi

  echo "==> Starting local infra (postgres + redis)"
  docker compose -f "${COMPOSE_FILE}" up -d
fi

cat <<'EOF'

Next steps:
1) Export backend connection env vars (replace placeholders, do not commit secrets):
   export DATABASE_URL='postgresql+psycopg://<db_user>:<db_password>@localhost:5432/<db_name>'
   export REDIS_URL='redis://localhost:6379/0'

2) Run readiness checks:
   bash scripts/dev/check.sh

3) Run local CI-equivalent checks:
   make ci
EOF
