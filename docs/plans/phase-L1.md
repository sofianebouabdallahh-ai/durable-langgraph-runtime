# Phase L1 plan — Containerise & one-command setup

**Goal:** a person with only Docker installed clones the repository, runs `./setup.sh` (or `.\setup.ps1`), and has the whole system running: API, two workers, Postgres, Redis, and a model of their choice. It is proven by an automatic end-to-end check. No Python, uv, Node or make on their machine; no file edited by hand.

**Part of:** the [local release](local-release.md) (L1 of L1–L5). **Decisions used** (local-release §7, the recommended defaults): pre-built images on GitHub Container Registry; feedback through GitHub issues (L5); the licence stays MIT; kind for local Kubernetes (L4).

---

## 1. Research findings

| Topic | Finding | Consequence |
|---|---|---|
| Packaging a uv project | Multi-stage: `uv sync --frozen --no-install-project` on the lockfile first (a cached dependency layer), then the source, then `uv sync --frozen --no-editable`; `UV_COMPILE_BYTECODE=1` for faster start-up, `UV_LINK_MODE=copy` with cache mounts; copy only the `.venv` into a slim runtime stage; a non-root user ([pydevtools](https://pydevtools.com/handbook/tutorial/build-a-production-docker-image-for-a-uv-project/), [Depot](https://depot.dev/docs/languages/python-uv-dockerfile)) | The runtime image has no uv, no compiler, no source tree beyond the package |
| Migrations at start-up | A one-shot service with `restart: "no"`; the app services `depends_on` it with `condition: service_completed_successfully` ([Docker docs: init containers](https://docs.docker.com/compose/how-tos/init-containers/)). Newer Compose has `pre_start`, but testers' Compose versions vary | A `migrate` one-shot service; API and workers start only after it succeeds |
| Multi-arch images | `docker/build-push-action` with Buildx does multi-platform builds and attaches provenance and SBOM attestations ([build-push-action](https://gitea.com/docker/build-push-action)) | amd64 + arm64 images (Intel and Apple Silicon Macs, Windows, Linux) |
| Image scanning | Trivy: a gating scan (`HIGH,CRITICAL`, `ignore-unfixed`, `exit-code 1`), SARIF uploaded with `if: always()` ([trivy-action](https://gitea.com/ikoral/trivy-action)) | CI fails on fixable high and critical vulnerabilities |
| CI supply chain | Third-party GitHub Actions have been hijacked through mutable tags (e.g. `tj-actions/changed-files`, 2025) | Every third-party action is **pinned to a full commit SHA**; base images are pinned by digest |
| Testing setup on every OS in CI | GitHub's macOS runners have no Docker, and Windows runners run Windows containers only | CI tests the Linux path end to end; macOS is tested by hand here; **Windows is written but untested** until a Windows machine is available (stated, not hidden) |
| From the code | API and workers connect as the database **owner**: the least-privilege users from phase 2 (`agent_api`, `agent_worker`) are provisioned but not used. The CLI binds to `127.0.0.1` by default | In containers each service uses **its own** database user; the API binds `0.0.0.0` inside its container, while the published port binds `127.0.0.1` on the host |

## 2. Design

```
 ./setup.sh ── checks ─ .env (generated secrets) ─ model questions ─ docker compose --profile app up
                │
   postgres ─healthy─► migrate (one-shot: db upgrade + provision-users, as the owner)
   redis ───healthy─┐        │ completed_successfully
                    ├──► api      (agent_api login)    127.0.0.1:8000 → /readyz healthcheck
                    └──► worker×2 (agent_worker login) graceful stop = release (R10.7)
   model: scripted (offline) │ Ollama on the host (host.docker.internal) or in Docker (profile llm)
          │ OpenAI │ Azure AI Foundry / any OpenAI-compatible (base URL + key + model)
 └── smoke: `runtime smoke` in a container: session → turn → completed through the workers
```

- **One image, `runtime`** (Python backend), whose command picks the role: `api`, `worker`, `db upgrade`, `smoke`, `doctor`.
  - Multi-stage on a pinned `python:3.12-slim` digest; uv copied from its pinned image in the builder only.
  - Runs as a non-root UID 10001, with a read-only root filesystem (a `tmpfs` at `/tmp`), `PYTHONUNBUFFERED`, and `tini` as PID 1, so signals reach the process: the graceful release on SIGTERM depends on it.
- **Compose: the app services sit behind a profile** (`app`).
  - `make up` keeps starting only Postgres and Redis for the developer loop (processes run on the host with `uv`), so nothing changes for contributors.
  - Inside the network, services reach each other by name: the `environment:` entries override the host-oriented values in `.env`.
- **Least privilege, for real:** `migrate` uses the owner; `api` uses `API_POSTGRES_*`; `worker` uses `WORKER_POSTGRES_*`. The whole stack running green under those logins proves the grants are sufficient (R14.13), and a forbidden statement from a worker container proves they restrict.
- **Models come from `.env`** in L1; L2 moves them into the UI as connections.
  - `MODEL_PROVIDER=scripted` works offline.
  - `ollama`: on macOS and Windows the **native** Ollama on the host (`OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`); on Linux the Compose profile `llm`, or the host.
  - `openai`: `OPENAI_API_KEY`.
  - **Foundry and other OpenAI-compatible endpoints:** `MODEL_PROVIDER=openai` + `OPENAI_BASE_URL` + `OPENAI_API_KEY` + `MODEL_CHAT=<deployment>` (Foundry's `/openai/v1/` route takes the deployment as the model).
- **`setup.sh`** (bash 3.2-compatible, for macOS's default shell) and **`setup.ps1`** (PowerShell 5.1+):
  - **Checks:** Docker running, Compose v2, free ports, disk space.
  - **Creates `.env`:** from the example; every `change-me` secret is replaced with a random one; file mode `600`; existing values are never overwritten.
  - **Asks about the model,** or takes `--model …` flags for `--non-interactive` installs.
  - **Starts the stack:** pulls the images, or builds them with `--build`; brings up the stack; waits for health; runs the smoke check.
  - **Other modes:** `--update` (back up first, then pull and migrate; L5 completes it), `--doctor`, `--reset` (confirmation required), `--stop`.
- **`runtime smoke`:** creates a session through the API, sends a turn, and waits until it is `completed` with an assistant reply. With a real model, the reply only needs to be non-empty, plus the capability check from 6c (a tool call). It exits non-zero with the reason otherwise.
- **`runtime doctor`:** versions, the health of every service, the effective configuration with **every secret redacted** (passwords, keys, URLs with credentials) by the runtime's redaction, and the recent errors from each service's logs. The output is a zip for an issue. A known-secret test proves nothing leaks.
- **CI:**
  - **On every PR:** build the image (amd64); run Trivy (`HIGH,CRITICAL` gate); run `./setup.sh --non-interactive --model scripted --build` on the runner, then a **container e2e** (a worker container killed mid-turn).
  - **On a tag `v*`:** a multi-arch build (amd64 + arm64), pushed to `ghcr.io/<owner>/durable-langgraph-runtime/runtime:<tag>`, with provenance and SBOM.

## 3. Tasks

| # | Task | Verification |
|---|---|---|
| L1.1 | `backend/Dockerfile`, `.dockerignore`, tini, non-root, read-only; `runtime api --host 0.0.0.0` | Image builds; runs as UID 10001; `runtime --help` works; size recorded |
| L1.2 | Compose: `migrate`, `api`, `worker` (×2) under the `app` profile; component logins; healthchecks; graceful stop period; host-gateway for host models | `docker compose --profile app up` → all healthy |
| L1.3 | `runtime smoke` and `runtime doctor` (redacted); tests | Unit + integration; the known-secret test |
| L1.4 | `setup.sh`: checks, `.env` generation (idempotent), model questions and flags, start, wait, smoke, `--stop` / `--reset` / `--doctor` / `--update` (backup) | Fresh-clone run; second run is a no-op; failure messages for a stopped Docker and a used port |
| L1.5 | `setup.ps1` (the same steps) | Reviewed; marked untested until a Windows machine is available |
| L1.6 | A container e2e: `docker kill` a worker mid-turn → the turn completes on the other (AC19 in Compose); `docker compose stop worker-1` → released, resumed elsewhere | 5× locally; in CI |
| L1.7 | CI: build + Trivy + setup + container e2e on PRs; multi-arch publish with SBOM and provenance on tags; all actions pinned by SHA | Green PR; a test tag publishes |
| L1.8 | Docs: README "Try it", `docs/setup/` (macOS, Windows, Linux, models incl. Foundry, troubleshooting); summary; PR | A clean-machine walkthrough following only the docs |

## 4. Success criteria

| # | Criterion | How | Pass when |
|---|---|---|---|
| SC1 | **Clone → working chat with only Docker** | Fresh clone, `./setup.sh --non-interactive --model scripted` | Healthy stack and a completed smoke turn; cold (images built) and warm times recorded; **< 10 min** cold |
| SC2 | Idempotent setup | Run it twice | The second run changes no secret, applies no migration, exits 0 |
| SC3 | Actionable failures | Docker stopped; port 8000 taken | One clear message each, with the fix, and a non-zero exit |
| SC4 | **Least privilege at runtime** | The full stack under the component logins | The smoke and the container e2e pass as `agent_api` / `agent_worker`; `DROP TABLE runs` from the worker container fails |
| SC5 | A sound image | Inspect + Trivy | UID 10001; no uv, compiler or tests in the runtime image; no fixable HIGH/CRITICAL; amd64 + arm64 manifest with SBOM and provenance (on a tag) |
| SC6 | **Crash in containers** (AC19) | `docker kill` the owning worker mid-turn | The turn completes on the other worker; zero duplicate messages; **5/5** |
| SC7 | Graceful stop in containers (R10.7) | `docker compose stop` a worker mid-turn | `run.released`, resumed on the other worker, no reclaim |
| SC8 | Models through setup | `--model scripted`; `--model ollama` (the native app on this Mac); `--model openai` / `--model compatible` | Scripted offline; the live Ollama smoke passes (a tool call); OpenAI-compatible configuration written correctly (live only with a key) |
| SC9 | **No secret in the doctor bundle** | A known password and key in `.env` | Neither appears anywhere in the bundle |
| SC10 | The developer loop is unchanged | `make up`, `make check`, `make demo-e2e` | All green, as before |
| SC11 | CI | A PR and a test tag | The PR job runs build + scan + setup + container e2e; the tag publishes multi-arch images |
| SC12 | Docs | Follow `docs/setup/` on a clean clone | It works without any step that isn't written down |

## 5. Risks

| Risk | Mitigation |
|---|---|
| The component logins lack a grant somewhere | SC4 runs everything under them; a missing grant is a migration, found now, not in production |
| macOS `bash` 3.2 and BSD tools differ from Linux | Only POSIX-safe constructs; tested on macOS (here) and Linux (CI) |
| Windows is untested | Stated in the docs; tested as soon as a Windows machine is available |
| Signals inside containers (graceful release) | `tini` as PID 1; SC7 proves it |
| Image size or a slow cold build | Cached dependency layer; pulling pre-built images is the default once published |
