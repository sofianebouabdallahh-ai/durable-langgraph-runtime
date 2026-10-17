# Phase L1 — Containerise & one-command setup

**Completed:** 2026-10-17 · **Branch:** `feat/l1-containers-setup` · **Plan:** [plans/phase-L1.md](../plans/phase-L1.md) · **Part of:** the [local release](../plans/local-release.md) · **Tests:** 360 + the container e2e

## What we built

**The `runtime` image** ([backend/Dockerfile](../../backend/Dockerfile)). One image for the API, workers and CLI; the command picks the role.
- **Build:** multi-stage. uv resolves the locked dependencies into a cached layer, then installs the package non-editable. The runtime stage has only the venv, the migrations, the agents and the fixtures: no uv, no compiler, no tests.
- **Runtime:** runs as non-root UID 10001, with a read-only root filesystem, and `tini` as PID 1 so that SIGTERM reaches the worker (graceful release).
- **Pins:** the base is pinned by digest (Python 3.12.15 on **Debian 13**); uv is pinned to a release ≥ 2 weeks old.
- **Size:** 462 MB uncompressed (a 197 MB venv).

**The stack in Compose** ([infra/compose/docker-compose.yml](../../infra/compose/docker-compose.yml)).
- **Profiles:** a new `app` profile adds `migrate` (one-shot: `runtime db init` = migrate + provision the component logins), `api` and **2 workers**.
- **Developer loop unchanged:** `make up` still starts only Postgres and Redis.
- **Least privilege for real:** the API connects as `agent_api` and the workers as `agent_worker`. Until now these logins were provisioned but unused.
- **Hardening:** a healthcheck on `/readyz`; graceful stop periods; `no-new-privileges`; ports on `127.0.0.1` only; `host.docker.internal`, so a model server running on the host can be used.

**`./setup.sh`** (bash 3.2, so macOS's default shell works) **and `.\setup.ps1`** (PowerShell 5.1+).
- **Checks:** Docker installed, running, and Compose v2, with an OS-specific fix for each failure.
- **Creates `.env`:** from the example; each `change-me` is replaced by a random secret; mode `600`; nothing is ever overwritten.
- **Picks free ports:** for the API, Postgres and Redis it keeps a port that is free or already this stack's own, otherwise chooses a free one and saves it.
- **Asks for the model** (demo / Ollama / OpenAI / Azure AI Foundry / OpenAI-compatible), or takes flags.
- **Starts and proves it:** pulls the images (or builds them); waits for health; runs **`runtime smoke`**, a real chat turn through the API and the workers.
- **Other modes:** `--chat`, `--stop`, `--update` (database backup first), `--doctor`, `--reset` (asks first).

**`runtime smoke` / `runtime doctor`** ([ops.py](../../backend/src/agent_runtime/ops.py)).
- **smoke** creates a session, sends a turn, and waits until the workers finish it. With the scripted model, the calculator must also run through the tool pipeline.
- **doctor** reports versions, Postgres / Redis / API health and the effective configuration, **with every secret redacted**. Setup adds the services' logs and packs a bundle for an issue.

**The container e2e** ([tests/e2e/compose_e2e.py](../../backend/tests/e2e/compose_e2e.py)): `docker kill` and `docker stop` a worker container mid-turn, plus a least-privilege probe.

**CI.**
- **A new `containers` job:**
  - `setup.ps1` parse + PSScriptAnalyzer;
  - `./setup.sh` from scratch, exactly as a tester runs it;
  - a second run must leave `.env` unchanged;
  - a Trivy scan (fails on fixable HIGH/CRITICAL);
  - the image must run as UID 10001;
  - the container e2e;
  - a diagnostics bundle as an artifact.
- **A `release` workflow:** a tag `v*` publishes **amd64 + arm64** images to GHCR, with an SBOM and provenance, scanned after the push.
- **Pinning:** every action, existing ones included, is pinned to a full commit SHA; Trivy runs from its image, pinned by digest.

**Docs.** "Try it" at the top of the README; [docs/setup/](../setup/) has guides for macOS, Windows and Linux, the models (including Foundry) and troubleshooting.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| SC1 | Clone → working chat with only Docker | ✅ A fresh clone, `./setup.sh --non-interactive --model scripted`: healthy stack and a completed smoke turn; **cold: 48 s** on CI's fresh runner (no cache, the image built from scratch, through the smoke turn; target < 10 min); **warm: 21.8 s** on this Mac |
| SC2 | Idempotent | ✅ Re-runs leave `.env` byte-identical (checksums) and recreate nothing. **This took a fix** (below) |
| SC3 | Actionable failures | ✅ Docker unreachable → "Docker is installed but not running" + the fix, exit 1; an `--api-port` that's taken → a clear message, exit 1; a busy default port → a free one is chosen automatically, with a warning |
| SC4 | **Least privilege at runtime** | ✅ The smoke turn and the container e2e run as `agent_api` / `agent_worker`; from a worker container `DROP TABLE runs` and `DELETE FROM runs` → `InsufficientPrivilege` |
| SC5 | A sound image | ✅ UID 10001; no uv or compiler. Trivy: **no fixable HIGH/CRITICAL**; Python packages clean; the base has 44 unfixed (moving from Debian 12 to 13 cut that from 63). ⏳ The multi-arch publish with SBOM/provenance runs on the first tag (after merge) |
| SC6 | **Crash in containers (AC19)** | ✅ **5/5** `docker kill` of the owning worker mid tool call: completed on the other; zero duplicate messages; one note; exactly one reclaim |
| SC7 | Graceful stop (R10.7) | ✅ **5/5** `docker stop` mid-turn: shut down in ~4 s (grace 40 s), `run.released`, resumed elsewhere, no reclaim. `tini` passes SIGTERM through |
| SC8 | Models through setup | ✅ scripted (offline); **live: `--model ollama` found the Ollama on this machine, and the smoke turn passed on `qwen2.5:7b` (40.2 s, CPU)**; the OpenAI / Foundry / compatible paths write the right `.env` (live only with a key) |
| SC9 | No secret in the doctor bundle | ✅ A scan of the bundle for every generated password: **0 hits**; unit test with a known password, key and URL credential |
| SC10 | Developer loop unchanged | ✅ `make up` / `make check` (360 passed) |
| SC11 | CI | ✅ PR #15: all 4 jobs green (containers job 2 m 48 s: setup, idempotency, Trivy, non-root, container e2e 3/3). ⏳ The tag publish after merge |
| SC12 | Docs | ✅ Written; the setup was exercised by following them on this Mac |

## Bugs found by testing

- **The CLI couldn't find its migrations once installed.** It located `alembic.ini` relative to its own source file, which lives inside `site-packages` in a real (non-editable) install. `RUNTIME_HOME` now names the directory (`/app` in the image).
- **A busy port on a tester's machine.** Port 8000 here belongs to another project; Postgres 5432 and Redis 6379 were taken by the dev stack. Setup now picks free ports for all three (on a tester's machine, a local Postgres or Redis is just as likely).
- **Setup moved its own ports on every re-run.** It didn't recognise ports held by its own containers, so it changed them and recreated the stack, which isn't idempotent. It now asks Compose (`compose port`).
- **A warning was swallowed into a variable** (`$(…)` captured it); it now goes to stderr.
- **The doctor reported Postgres as down when it wasn't.** It read `alembic_version`, which the API's least-privilege login can't read. The check is now privilege-aware.
- **A misleading message:** "GPU-accelerated" was shown for an Ollama that, here, is the CPU-only Docker one.

## Decisions & trade-offs

- **One image, many roles,** instead of separate API and worker images: one build, one scan, one version.
- **Build when the pull fails.** Until the first tag publishes images, setup builds locally (a few minutes, once).
- **Debian 13 over Debian 12, and not distroless:** fewer unfixed CVEs with the same tooling. Distroless would cut more but loses the shell the doctor and backups use; it's a later option.
- **Windows is written, not run.** CI can parse and lint it but has no Linux containers on Windows. It's marked untested in the docs, with WSL as the tested route.

## Known issues & follow-ups

- **The GHCR package must be made public once** (GitHub → Packages → visibility) after the first tag, so testers can pull without logging in.
- **`setup.ps1` needs a run on a real Windows machine.**
- **No UI yet:** testers use the API docs or `./setup.sh --chat` until L2 (the chat UI, re-ordered ahead of the Studio).
