# Repository entry point (R9.2). Run from the repo root; `make help` lists targets.
#
# Layout: backend/ (Python service), frontend/ (UI), infra/ (compose, k8s, helm).
# This file orchestrates them; each part keeps its own tool config.

# Configuration (ADR-0002): the app reads environment variables only (R9.1).
# Locally they come from the root .env, handed to each tool's own dotenv parser
# (`uv run --env-file`, `compose --env-file`). We deliberately don't `include .env`:
# make would mangle values containing `$` or `#` and export every secret to every
# command. Variables already set in the shell (e.g. CI) win over the file.
ENV_FILE := $(CURDIR)/.env

# Docker Desktop installs its CLI in ~/.docker/bin when it can't write to
# /usr/local/bin. Resolve the binary explicitly: make 3.81 (macOS default)
# ignores an exported PATH when it looks up commands.
DOCKER  := $(shell command -v docker 2>/dev/null || echo $(HOME)/.docker/bin/docker)
COMPOSE := $(DOCKER) compose --file infra/compose/docker-compose.yml --env-file $(ENV_FILE)

# Python commands run inside backend/ with the locked environment (--frozen: never
# re-resolve). BACKEND_ENV also loads .env, for commands that talk to services.
BACKEND     := cd backend && uv run --frozen
BACKEND_ENV := cd backend && uv run --frozen --env-file $(ENV_FILE)

.DEFAULT_GOAL := help
.PHONY: help env hooks up down nuke ps logs migrate migration lint fmt typecheck test test-unit test-integration check

help: ## List targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")

hooks: ## Install git pre-commit hooks (gitleaks, ruff, file hygiene)
	uvx pre-commit@4.6.2 install

# ------------------------------------------------------------ infra (compose)
up: env ## Start Postgres + Redis, wait until healthy, apply migrations
	$(COMPOSE) up -d --wait
	$(MAKE) migrate

down: ## Stop services (data is kept)
	$(COMPOSE) down

nuke: ## Stop services and DELETE their data volumes
	$(COMPOSE) down -v

ps: ## Show service status
	$(COMPOSE) ps

logs: ## Follow service logs
	$(COMPOSE) logs -f

# --------------------------------------------------------- backend: migrations
migrate: env ## Apply all migrations (alembic upgrade head)
	$(BACKEND_ENV) alembic upgrade head

migration: ## Create a new empty migration: make migration m="add foo"
	@test -n "$(m)" || (echo 'usage: make migration m="message"' && exit 1)
	$(BACKEND_ENV) alembic revision -m "$(m)"

# ------------------------------------------------------ backend: code quality
lint: ## Ruff lint + format check
	$(BACKEND) ruff check .
	$(BACKEND) ruff format --check .

fmt: ## Auto-format and fix lint
	$(BACKEND) ruff format .
	$(BACKEND) ruff check --fix .

typecheck: ## mypy --strict
	$(BACKEND) mypy

# -------------------------------------------------------------- backend: tests
test-unit: ## Unit tests (no services, no .env: proves they need neither)
	$(BACKEND) pytest tests/unit

test-integration: env ## Integration tests (needs `make up`)
	$(BACKEND_ENV) pytest -m integration

test: env ## All tests (needs `make up`)
	$(BACKEND_ENV) pytest

check: lint typecheck test ## Everything CI runs
