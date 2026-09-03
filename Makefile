SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PYTHON ?= python3
DOCKER_ENV_FILE ?= $(if $(wildcard .env.docker),.env.docker,.env.docker.example)

.PHONY: help ci test-ci test-api test-web lint-shell backend-smoke frontend-smoke format-check dev-bootstrap dev-check infra-up infra-down infra-logs docker-config docker-up docker-down docker-logs metrics-verify

help:
	@echo "Common developer commands"
	@echo "  make ci             # full local CI-equivalent checks"
	@echo "  make test-ci        # pytest guardrails + architecture + data-contract checks"
	@echo "  make metrics-verify # re-run the reduction and check released metrics.json reproduce"
	@echo "  make test-api       # backend smoke checks"
	@echo "  make test-web       # frontend npm/type/build checks"
	@echo "  make lint-shell     # bash -n (+ shellcheck if installed)"
	@echo "  make format-check   # run formatter checks when configured"
	@echo "  make dev-bootstrap  # local non-destructive setup helper"
	@echo "  make dev-check      # local environment readiness checks"
	@echo "  make infra-up       # start local postgres + redis"
	@echo "  make infra-down     # stop local postgres + redis"
	@echo "  make infra-logs     # tail local infra logs"
	@echo "  make docker-config  # validate full-stack docker compose config"
	@echo "  make docker-up      # start web + api + postgres + redis"
	@echo "  make docker-down    # stop full-stack docker compose services"
	@echo "  make docker-logs    # tail full-stack docker compose logs"

ci: format-check lint-shell test-ci backend-smoke frontend-smoke

test-ci:
	$(PYTHON) -m pytest tests/ci -q
	$(PYTHON) scripts/ci/check_architecture_coherence.py
	$(PYTHON) scripts/ci/check_data_contract_tooling.py

metrics-verify:
	$(PYTHON) scripts/eval/verify_metrics_reproducible.py

test-api: backend-smoke

test-web: frontend-smoke

backend-smoke:
	$(PYTHON) scripts/ci/run_backend_smoke.py

frontend-smoke:
	bash scripts/ci/run_frontend_checks.sh

lint-shell:
	@echo "==> bash -n shell syntax checks"
	@script_files="$$(find scripts -type f -name '*.sh' | sort)"; \
	if [[ -z "$$script_files" ]]; then \
		echo "No shell scripts found under scripts/."; \
		exit 0; \
	fi; \
	while IFS= read -r file; do \
		[[ -n "$$file" ]] || continue; \
		bash -n "$$file"; \
	done <<< "$$script_files"; \
	echo "bash -n passed for all shell scripts."
	@if command -v shellcheck >/dev/null 2>&1; then \
		echo "==> shellcheck lint"; \
		shellcheck $$(find scripts -type f -name '*.sh' | sort); \
	else \
		echo "shellcheck not found; skipped (bash -n completed)."; \
	fi

format-check:
	@echo "==> format checks (if configured)"
	@if [[ -f "apps/web/package.json" ]] && grep -q '"format:check"' apps/web/package.json; then \
		( cd apps/web && npm run format:check ); \
	else \
		echo "No frontend format:check script configured; skipping."; \
	fi
	@if [[ -f "pyproject.toml" ]] && grep -q '\[tool\.ruff\]' pyproject.toml; then \
		$(PYTHON) -m ruff format --check .; \
	else \
		echo "No Python formatter check configured; skipping."; \
	fi

dev-bootstrap:
	bash scripts/dev/bootstrap.sh

dev-check:
	bash scripts/dev/check.sh

infra-up:
	docker compose -f infra/dev/docker-compose.yml up -d

infra-down:
	docker compose -f infra/dev/docker-compose.yml down

infra-logs:
	docker compose -f infra/dev/docker-compose.yml logs -f

docker-config:
	docker compose --env-file $(DOCKER_ENV_FILE) -f docker-compose.yml config -q

docker-up:
	docker compose --env-file $(DOCKER_ENV_FILE) -f docker-compose.yml up --build -d

docker-down:
	docker compose --env-file $(DOCKER_ENV_FILE) -f docker-compose.yml down

docker-logs:
	docker compose --env-file $(DOCKER_ENV_FILE) -f docker-compose.yml logs -f
