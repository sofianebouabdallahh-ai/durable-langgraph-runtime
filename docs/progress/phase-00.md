# Phase 0 — Foundations

**Completed:** 2026-10-11 · **Tag:** `phase-00` · **Commits:** `97960bf` … `8ffb6f5`

## What we built

**Project tooling** ([pyproject.toml](../../pyproject.toml), [uv.lock](../../uv.lock)). A Python 3.12 package called `runtime`, managed by `uv`. `uv.lock` records the exact version of every dependency, including indirect ones, so every machine and CI installs identical packages (R9.3). `ruff` checks style and common bugs, `mypy --strict` requires full type annotations, and `pytest` runs the tests. So far the only dependencies are what this phase uses (pydantic-settings, SQLAlchemy, Alembic, psycopg). LangGraph, FastAPI and Redis arrive in the phase that first uses them.

**Configuration** ([runtime/config.py](../../runtime/config.py), [.env.example](../../.env.example)). One `Settings` class reads every setting from environment variables, and only from there (R9.1). Compose, Kubernetes and the Makefile each deliver those variables in their own way, and the code never knows which one did. The Postgres password is a `SecretStr` with no default, so it never appears in logs and is never baked into code or images. The class enforces one rule from the spec: the heartbeat interval must be at most a third of the lease TTL (R2.3).

**Local services** ([docker-compose.yml](../../docker-compose.yml)). Postgres 16 with the pgvector extension, and Redis 7 with its append-only file (AOF) turned on. Both have healthchecks, so `make up` waits until they're actually ready. Both bind to `127.0.0.1` only, so they aren't reachable from your network.

**Makefile** ([Makefile](../../Makefile)). One entry point for everything: `make up`, `down`, `nuke`, `migrate`, `migration`, `lint`, `fmt`, `typecheck`, `test`, `check`, and `make help` to list them. It exports `.env` to every command, so `uv run …` sees the same settings Compose does.

**Database schema** ([migrations/versions/0001_initial_schema.py](../../migrations/versions/0001_initial_schema.py)). Alembic migration `0001` creates every table from spec §9 and CR-001, written as explicit SQL:

| Table | Role |
|---|---|
| `runs` | Status index for every execution: state machine, lease (`owner`, `lease_expires_at`), fencing `epoch`, cancel flag, fan-out counters, cost |
| `run_events` | Append-only event log, `PK (run_id, seq)`, used for replay |
| `run_results` | Final output of a run; parents read children's results here |
| `tool_invocations` | Idempotency ledger for tool calls, keyed by a 64-char sha256 |
| `findings` | Research findings, keyed by the idempotency key so a retry can't duplicate a row |
| `documents` · `chunks` | Retrieval corpus; `chunks.embedding` is a `vector(768)` with an HNSW index |
| `sessions` · `session_messages` | Chat sessions and their transcript, with a deterministic `message_id` |

**Integration tests** ([tests/integration/](../../tests/integration/)). They create a throwaway `agent_runtime_test` database, so they never touch your dev data. They check that the migration chain applies, reverses and re-applies, and they exercise the constraints that later phases depend on.

**CI** ([.github/workflows/ci.yml](../../.github/workflows/ci.yml)). Two jobs. `quality` runs lint, type-check and unit tests. `integration` runs migrations and the integration tests against a pgvector service container. The integration job **fails if any test is skipped**, so a missing database can't produce a false pass.

**Project docs.** [LICENSE](../../LICENSE) (Apache-2.0), [README.md](../../README.md) with a quickstart and the security posture, and [CHANGELOG.md](../../CHANGELOG.md).

## How it fits

```
 your shell ── make ──► uv run (pytest, alembic, mypy, ruff)
                 │            │ reads env (.env exported by make)
                 ▼            ▼
         docker compose   runtime.config.Settings ──► database_url()
            ├── postgres:5432  ◄── alembic upgrade head (schema 0001)
            └── redis:6379        (unused until phase 2)
```

Everything after this phase builds on two contracts set here: **all configuration comes from the environment**, and **every schema change is a reviewed migration**.

## Requirements covered

| Req | Status |
|---|---|
| R9.1 Configuration | ✅ Done for the settings phases 0–5 need; provider settings arrive in phase 6 |
| R9.2 Compose & Make | 🟡 Partial: postgres and redis only. api, worker, ui and the `observability` profile come in phases 2/3/9/11; the `demo*`, `eval` and `ingest` targets come with their phases |
| R9.3 Code standard | 🟡 Partial: uv, ruff, mypy strict, pinned dependencies, Apache-2.0, conventional commits and CHANGELOG are done. The README naming the LangGraph version comes in phase 1 |
| R9.4 Security posture | ✅ Stated in the README, accurate for today and for the planned sandbox |
| §9 Tables | ✅ All of them, plus CR-001 §6 and F3 columns. LangGraph's checkpoint tables are created by LangGraph itself in phase 1 |
| CI skeleton (R7.4) | ✅ Lint, types, unit and integration jobs. The eval gate comes in phase 10 |

## Concepts learned

- **Lock files and reproducible builds.** `pyproject.toml` says what you *want* (`alembic>=1.20`); `uv.lock` records what you *got* (exact versions and hashes). CI installs with `--locked`, so it fails if the two disagree instead of quietly installing something different.
- **Twelve-factor configuration.** Config comes from the environment, so the same code and image run on a laptop, in CI and in Kubernetes. Secrets are kept out of the code and are typed as secrets, so they don't get logged.
- **Database migrations** (Alembic, roughly Liquibase for Python). A versioned chain of schema changes, plus an `alembic_version` table recording where each database is in the chain. Each migration must be reversible.
- **Putting invariants in the database.** Several rules are enforced by Postgres itself rather than by our code, because the database is the one place every worker and replica goes through:
  - A **partial unique index** allows at most one active turn per session.
  - **CHECK constraints** make sure a run's status is valid, and that a run has `finished_at` exactly when it has ended.
  - A **unique `message_id`** makes rewriting the same message a no-op.
- **Partial indexes for hot queries.** The reaper's question, "running runs with an expired lease", is answered by an index that only contains running runs, so it stays small no matter how many runs have finished.
- **Health-gated startup.** `docker compose up --wait` blocks until the healthchecks pass. Phase 12 builds on the same idea with Kubernetes readiness probes.

## Decisions & trade-offs

- **Migrations as explicit SQL instead of autogenerate.** It's more typing, but every constraint and index shows up in review, and there are no ORM models to keep in sync. The cost is that we have no ORM models yet; queries will be written with SQLAlchemy Core or plain SQL. That suits a runtime whose correctness depends on exact SQL, such as the lease `UPDATE … RETURNING epoch`.
- **Fencing columns now, the fencing trigger in phase 2.** The `epoch` columns exist, but nothing rejects a stale write yet. The trigger gets its own migration in phase 2, alongside the explanation of why it's needed.
- **Embedding dimension fixed at 768.** Ollama's `nomic-embed-text` produces 768 dimensions natively, and OpenAI's `text-embedding-3-small` will be asked for 768. Changing it later means a migration and re-ingesting the documents.
- **IDs are generated by the app (UUIDv7).** Postgres 16 has no built-in UUIDv7 function (Postgres 18 adds one), so the app will generate them in phase 1.
- **`documents.collection` added.** The spec doesn't list it, but fixture sets (R4.6, R6.4, R7.3) need to scope retrieval to one corpus.
- **Extra `runs` columns beyond §9:** `last_event_seq` (allocates event sequence numbers), `started_at` (where the timeout clock starts), and `tokens`. Each one is needed by a requirement we'll implement.

## Known issues & follow-ups

- **CI has never run on GitHub.** The repo has no remote yet. I linted the workflow with `actionlint` and reproduced the integration job locally (it passed), but its first real run happens when we push.
- **`docker` isn't on your shell's `PATH`.** Docker Desktop put the CLI in `~/.docker/bin`. `make` finds it on its own, but to run `docker` by hand, add this to `~/.zshrc`: `export PATH="$HOME/.docker/bin:$PATH"`.
- **Running `uv run pytest` without `make` skips the integration tests,** because the database settings come from `.env`, which only `make` exports. CI sets the variables directly. This is by design (R9.1), but it can surprise you.
- **Redis isn't used yet.** It's in Compose now so `make up` already matches the shape later phases need.

## How to try it

```bash
make up                 # Postgres + Redis, migrations applied
make check              # 16 tests: 8 unit, 8 integration
docker compose exec postgres psql -U agent -d agent_runtime -c '\d runs'   # inspect the schema
make migration m="try it"   # creates migrations/versions/0002_try_it.py (delete it afterwards)
```
