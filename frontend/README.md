# frontend

The web UI: the chat view (CR-001 R12.11) over the runtime's API, built by `frontend/Dockerfile` and served by unprivileged nginx (the `ui` service in Compose). The Agent Studio (local-release L4) will join it.

**Stack (R6.5):** React 19, TypeScript `strict`, Vite, Tailwind, TanStack Query, Vitest + Testing Library, Playwright, and an API client generated from the backend's OpenAPI spec. The plan is in [docs/plans/phase-L2.md](../docs/plans/phase-L2.md).

| Command (from the repo root) | What it does |
|---|---|
| `make ui-check` | Lint, types, unit tests with coverage, production build (in a Node container) |
| `make ui-dev` | Dev server on http://127.0.0.1:5173, proxying `/api` to the running stack |
| `make ui-api` | Regenerate `src/api/schema.d.ts` from the API (CI fails if it drifts) |
| `make ui-e2e` | Playwright against the Compose stack (`./setup.sh` first) |

No Node is needed on the host: the toolchain runs in a pinned `node:24` container. With Node 24 installed, `cd frontend && corepack enable && pnpm install && pnpm dev` works the same.

**Layout:** `src/api` (generated types, client, typed messages) · `src/stream` (the SSE adapter and the connection state machine) · `src/chat` (the transcript reducer, selectors, the hook, the view and its cards) · `src/sessions` (sidebar, route) · `src/ui` (safe Markdown, plain words, primitives).

**Supply chain:** pnpm via Corepack, verified by hash; a 14-day `minimumReleaseAge`; dependencies' install scripts blocked; `--frozen-lockfile` everywhere.
