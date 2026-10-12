# Repository entry point (R9.2). Run from the repo root; `make help` lists targets.
#
# Layout: backend/ (Python service), frontend/ (UI), infra/ (compose, k8s, helm).
# This file orchestrates them; each part keeps its own tool config.

# Export the root .env (if present) to every command, so local tools see the same
# settings Compose does (R9.1: config comes from the environment only).
ifneq (,$(wildcard .env))
include .env
export
endif

# Docker Desktop installs its CLI in ~/.docker/bin when it can't write to
# /usr/local/bin. Resolve the binary explicitly: make 3.81 (macOS default)
# ignores an exported PATH when it looks up commands.
DOCKER  := $(shell command -v docker 2>/dev/null || echo $(HOME)/.docker/bin/docker)
COMPOSE := $(DOCKER) compose --file infra/compose/docker-compose.yml --env-file .env

# Every Python command runs inside backend/ with its locked environment.
BACKEND := cd backend && uv run

.DEFAULT_GOAL := help
.PHONY: help env up down nuke ps logs migrate migration lint fmt typecheck test test-unit test-integration check

help: ## List targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")

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
migrate: ## Apply all migrations (alembic upgrade head)
	$(BACKEND) alembic upgrade head

migration: ## Create a new empty migration: make migration m="add foo"
	@test -n "$(m)" || (echo 'usage: make migration m="message"' && exit 1)
	$(BACKEND) alembic revision -m "$(m)"

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
test-unit: ## Unit tests (no services needed)
	$(BACKEND) pytest tests/unit

test-integration: ## Integration tests (needs `make up`)
	$(BACKEND) pytest -m integration

test: ## All tests (needs `make up`)
	$(BACKEND) pytest

check: lint typecheck test ## Everything CI runs
