# Changelog

All notable changes to this project. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/). Each phase is tagged `phase-NN`; `v1.0.0` is tagged when every acceptance criterion passes.

## [Unreleased]

### Phase 0 — Foundations
#### Added
- Requirements: CR-001 (chat sessions) and CR-002 (per-run sandboxes) on top of the v1.0 + Kubernetes spec; `docs/roadmap.md`.
- Python 3.12 project managed by `uv` with a locked dependency set; `ruff`, `mypy --strict`, `pytest`.
- `runtime.config.Settings`: environment-only configuration with `pydantic-settings`, plus `.env.example`.
- Docker Compose with Postgres 16 + pgvector and Redis 7 (AOF), bound to localhost.
- Makefile: `up`, `down`, `nuke`, `migrate`, `migration`, `lint`, `fmt`, `typecheck`, `test`, `check`.
- Alembic migration `0001`: `sessions`, `runs`, `run_events`, `run_results`, `tool_invocations`, `findings`, `documents`, `chunks`, `session_messages`.
- GitHub Actions CI: lint, type-check, unit tests, migrations and integration tests.
- Apache-2.0 license, README.
