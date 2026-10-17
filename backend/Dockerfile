# syntax=docker/dockerfile:1.7
# The runtime image: API, workers and the CLI (the command picks the role).
#
#   builder:  uv resolves the locked dependencies into /app/.venv (cached layer),
#             then installs the package itself, non-editable.
#   runtime:  a slim Python with only the venv, migrations, agents and fixtures;
#             no uv, no compiler, no tests; non-root; tini as PID 1 so SIGTERM
#             reaches the process (graceful release, R10.7).
#
# Base images are pinned by digest; uv by version, at least two weeks old (as uv.lock).

ARG PYTHON_IMAGE=python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.20@sha256:100047e74f30778ab704942321a09750d6158739573ff58bf3924085cc6cd2d8

FROM ${UV_IMAGE} AS uv

# ------------------------------------------------------------------ builder
FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# 1. Dependencies only: this layer is reused until uv.lock changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project
# 2. The package itself, as a regular (non-editable) install.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ------------------------------------------------------------------ runtime
FROM ${PYTHON_IMAGE} AS runtime
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 runtime \
 && useradd --system --uid 10001 --gid runtime --no-create-home --home-dir /app runtime
WORKDIR /app
COPY --from=builder --chown=root:root /app/.venv /app/.venv
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root migrations ./migrations
COPY --chown=root:root agents ./agents
COPY --chown=root:root fixtures ./fixtures
ENV PATH=/app/.venv/bin:$PATH \
    RUNTIME_HOME=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
ENTRYPOINT ["tini", "--", "runtime"]
CMD ["--help"]
LABEL org.opencontainers.image.title="durable-agent-runtime" \
      org.opencontainers.image.description="Durable, distributed runtime for LangGraph agents: API, workers, CLI" \
      org.opencontainers.image.source="https://github.com/sofianebouabdallahh-ai/durable-langgraph-runtime" \
      org.opencontainers.image.licenses="MIT"
