#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/infra/dev/docker-compose.yml"

RUN_CI=0
FAIL_ON_ENV=1

usage() {
  cat <<'EOF'
Usage: bash scripts/dev/check.sh [--run-ci] [--no-env-fail]

Non-destructive readiness checks:
- required command availability
- shell script syntax validation (bash -n)
- docker compose config validation (if docker available)
- env var presence checks for DATABASE_URL and REDIS_URL

Options:
  --run-ci       Run make test-ci, backend-smoke, and frontend-smoke after checks
  --no-env-fail  Only warn (do not fail) when DATABASE_URL / REDIS_URL are missing
  -h, --help     Show this help text
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-ci)
      RUN_CI=1
      shift
      ;;
    --no-env-fail)
      FAIL_ON_ENV=0
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

status=0

echo "==> Required commands"
required_cmds=(bash python3 make git)
for cmd in "${required_cmds[@]}"; do
  if command -v "${cmd}" >/dev/null 2>&1; then
    echo "  - ${cmd}: ok"
  else
    echo "  - ${cmd}: missing" >&2
    status=1
  fi
done

echo "==> Shell script syntax checks (bash -n)"
script_files="$(find scripts -type f -name '*.sh' | sort)"
if [[ -z "${script_files}" ]]; then
  echo "  - no shell scripts found under scripts/"
else
  while IFS= read -r file; do
    [[ -n "${file}" ]] || continue
    if bash -n "${file}"; then
      echo "  - ${file}: ok"
    else
      echo "  - ${file}: failed" >&2
      status=1
    fi
  done <<< "${script_files}"
fi

echo "==> Environment variable checks"
required_env=(DATABASE_URL REDIS_URL)
for var_name in "${required_env[@]}"; do
  if [[ -n "${!var_name:-}" ]]; then
    echo "  - ${var_name}: set"
  else
    echo "  - ${var_name}: missing"
    if [[ ${FAIL_ON_ENV} -eq 1 ]]; then
      status=1
    fi
  fi
done

if command -v docker >/dev/null 2>&1; then
  if [[ -f "${COMPOSE_FILE}" ]]; then
    echo "==> Docker compose validation"
    if docker compose -f "${COMPOSE_FILE}" config -q; then
      echo "  - compose config: ok"
    else
      echo "  - compose config: failed" >&2
      status=1
    fi

    echo "==> Docker compose service status"
    if docker compose -f "${COMPOSE_FILE}" ps >/dev/null 2>&1; then
      docker compose -f "${COMPOSE_FILE}" ps
    else
      echo "  - unable to read docker compose status"
    fi
  else
    echo "==> Compose file missing: ${COMPOSE_FILE}" >&2
    status=1
  fi
else
  echo "==> docker not found; skipped compose checks"
fi

if [[ ${RUN_CI} -eq 1 ]]; then
  echo "==> Running CI-equivalent checks"
  if ! make test-ci backend-smoke frontend-smoke; then
    status=1
  fi
fi

if [[ ${status} -ne 0 ]]; then
  cat <<'EOF' >&2

Readiness checks failed.

Common fixes:
- export DATABASE_URL and REDIS_URL in your shell profile or current terminal
- run bash scripts/dev/bootstrap.sh
- start local infra with: make infra-up
EOF
  exit 1
fi

echo "All readiness checks passed."
