# backend

The Python service: the durable runtime (API and workers in later phases), its database migrations and its tests.

| Path | What |
|---|---|
| `src/runtime/` | The `runtime` package. `src/` layout, so tests import the installed package, never stray files from the working directory |
| `migrations/` | Alembic migrations, written as explicit SQL. Config in `alembic.ini` |
| `tests/unit/` | Fast tests, no services needed |
| `tests/integration/` | Need Postgres/Redis (`make up` from the repo root) |
| `pyproject.toml` · `uv.lock` | Dependencies (locked) and tool config: ruff, mypy, pytest |

Run everything from the **repository root** with `make` (`make help`). The Makefile exports the root `.env` and runs each command here. To work in this folder directly:

```bash
cd backend
uv sync                      # create .venv with the locked dependencies
uv run pytest tests/unit     # unit tests need no environment
```
