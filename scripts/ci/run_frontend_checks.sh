#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WEB_DIR="$REPO_ROOT/apps/web"

retry_with_backoff() {
  local max_attempts="$1"
  local delay_seconds="$2"
  shift 2

  local attempt=1
  while true; do
    if "$@"; then
      return 0
    fi

    local exit_code=$?
    if (( attempt >= max_attempts )); then
      echo "Command failed after ${attempt} attempt(s): $*"
      return "$exit_code"
    fi

    echo "Attempt ${attempt}/${max_attempts} failed (exit=${exit_code}): $*"
    echo "Retrying in ${delay_seconds}s..."
    sleep "$delay_seconds"
    attempt=$((attempt + 1))
    delay_seconds=$((delay_seconds * 2))
  done
}

if [[ ! -d "$WEB_DIR" ]]; then
  echo "apps/web not present; skipping frontend checks."
  exit 0
fi

if [[ ! -f "$WEB_DIR/package.json" ]]; then
  echo "ERROR: apps/web exists but package.json is missing."
  exit 1
fi

if [[ ! -f "$WEB_DIR/package-lock.json" ]]; then
  echo "ERROR: apps/web/package-lock.json is required for deterministic npm ci in CI."
  exit 1
fi

# Tolerate transient npm registry/network hiccups in CI.
export NPM_CONFIG_FETCH_RETRIES="${NPM_CONFIG_FETCH_RETRIES:-5}"
export NPM_CONFIG_FETCH_RETRY_FACTOR="${NPM_CONFIG_FETCH_RETRY_FACTOR:-2}"
export NPM_CONFIG_FETCH_RETRY_MINTIMEOUT="${NPM_CONFIG_FETCH_RETRY_MINTIMEOUT:-10000}"
export NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT="${NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT:-120000}"

pushd "$WEB_DIR" >/dev/null

echo "[frontend-ci] npm ci"
retry_with_backoff 3 5 npm ci --prefer-offline --no-audit --fund=false

echo "[frontend-ci] npm run test --if-present"
npm run test --if-present

echo "[frontend-ci] npm run typecheck --if-present"
npm run typecheck --if-present

echo "[frontend-ci] npm run build --if-present"
npm run build --if-present

popd >/dev/null

echo "apps/web npm ci + test + typecheck + build checks passed."
