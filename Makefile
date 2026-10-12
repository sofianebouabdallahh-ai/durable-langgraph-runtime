# Developer entry points (R9.2). `make help` lists them.

# Export .env (if present) to every command, so local tools see the same
# settings Compose does (R9.1: config comes from the environment only).
ifneq (,$(wildcard .env))
include .env
export
endif

# Docker Desktop installs its CLI in ~/.docker/bin when it can't write to
# /usr/local/bin. Resolve the binary explicitly: make 3.81 (macOS default)
# ignores an exported PATH when it looks up commands.
DOCKER := $(shell command -v docker 2>/dev/null || echo $(HOME)/.docker/bin/docker)
COMPOSE := $(DOCKER) compose

.DEFAULT_GOAL := help
.PHONY: help env up down nuke ps logs migrate migration lint fmt typecheck test test-unit test-integration check

help: ## List targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")

# ------------------------------------------------------------------ services
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

# ---------------------------------------------------------------- migrations
migrate: ## Apply all migrations (alembic upgrade head)
	uv run alembic upgrade head

migration: ## Create a new empty migration: make migration m="add foo"
	@test -n "$(m)" || (echo 'usage: make migration m="message"' && exit 1)
	uv run alembic revision -m "$(m)"

# --------------------------------------------------------------- code quality
lint: ## Ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Auto-format and fix lint
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## mypy --strict
	uv run mypy

# ---------------------------------------------------------------------- tests
test-unit: ## Unit tests (no services needed)
	uv run pytest -m "not integration"

test-integration: ## Integration tests (needs `make up`)
	uv run pytest -m integration

test: ## All tests (needs `make up`)
	uv run pytest

check: lint typecheck test ## Everything CI runs
