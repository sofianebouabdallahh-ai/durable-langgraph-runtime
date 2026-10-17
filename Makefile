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
# Docker runs its credential helpers (docker-credential-desktop) from PATH; they sit
# next to the docker binary, which may not be on PATH itself (Docker Desktop on macOS).
export PATH := $(dir $(DOCKER)):$(PATH)
COMPOSE := $(DOCKER) compose --file infra/compose/docker-compose.yml --env-file $(ENV_FILE)

# Python commands run inside backend/ with the locked environment (--frozen: never
# re-resolve). BACKEND_ENV also loads .env, for commands that talk to services.
BACKEND     := cd backend && uv run --frozen
BACKEND_ENV := cd backend && uv run --frozen --env-file $(ENV_FILE)

.DEFAULT_GOAL := help
.PHONY: help env hooks up down nuke ps logs setup image app-stop doctor demo-compose llm-up llm-down migrate migration api worker run-toy demo-crash demo-zombie demo-release demo-replicas demo-tools demo-approval demo-fanout demo-subagents demo-chat demo-chat-crash demo-chat-live chat demo-e2e lint fmt typecheck agents-validate test test-unit test-integration test-live coverage check

help: ## List targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example, or add keys that .env is missing (never overwrites)
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")
	@grep -E '^[A-Z_]+=' .env.example | while IFS='=' read -r key value; do \
		grep -q "^$$key=" .env || { echo "$$key=$$value" >> .env; echo "added $$key to .env"; }; \
	done

hooks: ## Install git pre-commit hooks (gitleaks, ruff, file hygiene)
	uvx pre-commit@4.6.2 install

# ------------------------------------------------------------ infra (compose)
up: env ## Start Postgres + Redis, migrate, provision per-component DB users
	$(COMPOSE) up -d --wait
	$(MAKE) migrate
	$(BACKEND_ENV) runtime db provision-users

down: ## Stop services (data is kept)
	$(COMPOSE) down

nuke: ## Stop services and DELETE their data volumes
	$(COMPOSE) down -v

ps: ## Show service status
	$(COMPOSE) ps

logs: ## Follow service logs
	$(COMPOSE) logs -f

# ------------------------------------------------- the product in containers (L1)
setup: ## The tester path: checks, .env, model, start everything in Docker, smoke test
	./setup.sh

image: ## Build the runtime image (API, workers, CLI) locally
	$(DOCKER) build -t ghcr.io/sofianebouabdallahh-ai/durable-langgraph-runtime/runtime:latest backend

app-stop: ## Stop the containerised stack (data kept)
	./setup.sh --stop

doctor: ## Diagnostics bundle, secrets redacted (attach it to an issue)
	./setup.sh --doctor

demo-compose: ## Container e2e: kill / stop a worker container mid-turn; least privilege
	cd backend && API_PORT=$$(awk -F= '$$1=="API_PORT"{print $$2}' ../$(ENV_FILE)) uv run --frozen python -m tests.e2e.compose_e2e all --repeat $(or $(REPEAT),1)

llm-up: env ## Start the local model server (Ollama, profile llm) and pull OLLAMA_MODEL
	$(COMPOSE) --profile llm up -d --wait ollama
	$(COMPOSE) --profile llm exec ollama ollama pull $(or $(OLLAMA_MODEL),qwen2.5:7b)

llm-down: ## Stop the local model server (downloaded models are kept)
	$(COMPOSE) --profile llm stop ollama

# --------------------------------------------------------- backend: migrations
migrate: env ## Migrate our schema (Alembic) and LangGraph's checkpoint tables
	$(BACKEND_ENV) runtime db upgrade

migration: ## Create a new empty migration: make migration m="add foo"
	@test -n "$(m)" || (echo 'usage: make migration m="message"' && exit 1)
	$(BACKEND_ENV) alembic revision -m "$(m)"

# ---------------------------------------------------------- backend: running
API_PORT ?= 8000
api: env ## Serve the API on http://127.0.0.1:$(API_PORT) (docs at /docs); make api API_PORT=8765
	$(BACKEND_ENV) runtime api --port $(API_PORT)

worker: env ## Run worker processes (WORKERS=2 CONCURRENCY=4)
	$(BACKEND_ENV) runtime worker --workers $(or $(WORKERS),2) --concurrency $(or $(CONCURRENCY),4)

run-toy: env ## Create and execute one run of the toy graph
	$(BACKEND_ENV) runtime run --graph toy --input '{"question": "What is a fencing token?"}'

# ---------------------------------------------------- end-to-end demos (AC2, AC5)
# Each starts a throw-away cluster (fresh DB, own stream, API + 2 worker processes),
# runs one scenario and prints PASS/FAIL per check. REPEAT=5 to repeat.
demo-crash: env ## AC2: SIGKILL the owning worker mid-run; another finishes it
	cd backend && uv run --frozen --env-file $(ENV_FILE) python -m tests.e2e crash --repeat $(or $(REPEAT),1)

demo-zombie: env ## AC5: SIGSTOP the owner past its lease, then SIGCONT: its writes are refused
	cd backend && uv run --frozen --env-file $(ENV_FILE) python -m tests.e2e zombie --repeat $(or $(REPEAT),1)

demo-release: env ## SIGTERM the owner: graceful hand-off in < 5 s, not a reclaim
	cd backend && uv run --frozen --env-file $(ENV_FILE) python -m tests.e2e release --repeat $(or $(REPEAT),1)

demo-replicas: env ## AC3: stream from any replica; Pub/Sub off stalls; replica shutdown mid-stream
	cd backend && for s in replicas stall api-shutdown; do \
		uv run --frozen --env-file $(ENV_FILE) python -m tests.e2e $$s --repeat $(or $(REPEAT),1) || exit 1; done

demo-tools: env ## SIGKILL right after a tool's side effect: it still happens exactly once
	cd backend && uv run --frozen --env-file $(ENV_FILE) python -m tests.e2e tool-crash --repeat $(or $(REPEAT),1)

demo-approval: env ## AC4: approval survives killing every worker; resumes with the edits
	cd backend && uv run --frozen --env-file $(ENV_FILE) python -m tests.e2e approval-restart --repeat $(or $(REPEAT),1)

demo-fanout: env ## AC6: child runs spread over workers; a crashed child doesn't break the fan-in
	cd backend && uv run --frozen --env-file $(ENV_FILE) python -m tests.e2e fanout --repeat $(or $(REPEAT),1)
	cd backend && uv run --frozen --env-file $(ENV_FILE) python -m tests.e2e child-crash --repeat $(or $(REPEAT),1)

demo-subagents: env ## AC37 + AC41: parallel sub-agents in a chat; SIGKILL mid sub-agent task
	cd backend && uv run --frozen --env-file $(ENV_FILE) python -m tests.e2e chat-subagents --repeat $(or $(REPEAT),1)
	cd backend && uv run --frozen --env-file $(ENV_FILE) python -m tests.e2e subagents-crash --repeat $(or $(REPEAT),1)

demo-chat: env ## AC18: 3 chat sessions x 3 turns over 2 workers; context carries; any replica streams
	cd backend && uv run --frozen --env-file $(ENV_FILE) python -m tests.e2e chat-sessions --repeat $(or $(REPEAT),1)

demo-chat-crash: env ## AC19: SIGKILL mid chat turn; zero duplicate messages
	cd backend && uv run --frozen --env-file $(ENV_FILE) python -m tests.e2e chat-crash --repeat $(or $(REPEAT),1)

demo-chat-live: env ## Chat on the REAL local model (needs `make llm-up`): context, tools, sub-agents
	cd backend && MODEL_PROVIDER=ollama uv run --frozen --env-file $(ENV_FILE) runtime chat \
	  --message "What is 1234 * 5678? Use the calculator." \
	  --message "Now add 1000 to that result." \
	  --message "In parallel: have your researcher find what Redis Streams are used for (search 'redis streams vs kafka') and your data-analyst compute 12 workers times 4 slots. Then combine their answers."

chat: env ## Chat with an agent in this terminal (MODEL_PROVIDER=ollama for the real model)
	cd backend && uv run --frozen --env-file $(ENV_FILE) runtime chat --agent $(or $(AGENT),chat)

demo-e2e: env ## All end-to-end scenarios
	cd backend && uv run --frozen --env-file $(ENV_FILE) python -m tests.e2e all --repeat $(or $(REPEAT),1)

# ------------------------------------------------------ backend: code quality
lint: ## Ruff lint + format check
	$(BACKEND) ruff check .
	$(BACKEND) ruff format --check .

fmt: ## Auto-format and fix lint
	$(BACKEND) ruff format .
	$(BACKEND) ruff check --fix .

typecheck: ## mypy --strict
	$(BACKEND) mypy

agents-validate: ## Validate every agent definition in backend/agents (no services needed)
	$(BACKEND) runtime agents validate

# -------------------------------------------------------------- backend: tests
test-unit: ## Unit tests (no services, no .env: proves they need neither)
	$(BACKEND) pytest tests/unit

# REQUIRE_SERVICES=1: a missing database fails the run instead of skipping it.
test-integration: env ## Integration tests (needs `make up`)
	cd backend && REQUIRE_SERVICES=1 uv run --frozen --env-file $(ENV_FILE) pytest -m integration

coverage: env ## All tests with branch coverage; fails under the floor (needs `make up`)
	cd backend && REQUIRE_SERVICES=1 uv run --frozen --env-file $(ENV_FILE) pytest --cov --cov-report=term --cov-report=html
	@echo "HTML report: backend/htmlcov/index.html"

test-live: env ## Tests against the real local model (needs `make llm-up`); never in CI
	cd backend && MODEL_PROVIDER=ollama uv run --frozen --env-file $(ENV_FILE) pytest -m live

test: env ## All tests (needs `make up`)
	cd backend && REQUIRE_SERVICES=1 uv run --frozen --env-file $(ENV_FILE) pytest

check: lint typecheck agents-validate test ## Everything CI runs
