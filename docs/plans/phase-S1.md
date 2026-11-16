# Phase S1 plan — The API contract

**Goal:** the OpenAPI spec says what the API really does, so an SDK can be generated from it, and CI keeps it that way.

**Why:** the SDK research of 2026-11-15 ([CR-007](../requirements/CR-007-client-sdks.md) §2) found the spec can't support an SDK yet:

| Gap | Today |
| --- | --- |
| Streams | Both stream responses are `text/event-stream: {}`: the web app's generated type is `unknown`, so [events.ts](../../frontend/src/stream/events.ts) re-declares the wire format by hand |
| Errors | No operation declares a 404, 409 or 503, though the API sends 44 kinds of problem. The 87 declared 422s say FastAPI's `HTTPValidationError` (`application/json`, `{detail: [...]}`), but the API sends RFC 9457 problem details (`application/problem+json`, `{type, title, status, detail, errors}`) |
| Method names | Operation ids are FastAPI's defaults (`send_message_sessions__session_id__messages_post`), so generated methods would be unreadable |
| Drift | Nothing stops a pull request from removing a field a client reads |
| Supply chain | The web app ships `openapi-fetch` 0.17.0, whose maintainers stopped updating it |

**Requirements:** CR-007 R19.1, R19.2, R19.3 (for the web app's generated types), R19.9. **Acceptance:** AC49, AC50.

---

## 1. Design

### 1.1 Streams as schemas (R19.1)
- **Pydantic models are the single source:** `api/stream_schemas.py` defines the envelope every SSE event's `data` carries (`run_id`, `seq`, `after_seq`, `ts`, `epoch`, `type`, `payload`), the session stream's events as a union discriminated on `type` (`message.created`, `token`, `turn.status`, `subagent.spawned`, `subagent.progress`, `subagent.completed`) with their payloads, the run stream's event (its `type` one of the run event types or `token`), and `reconnect`'s data (`after_seq`).
- **The spec references them** the way FastAPI's own SSE support does (OpenAPI 3.2's `itemSchema`, emitted inside 3.1 documents): `text/event-stream` → `itemSchema` → `data` as JSON whose `contentSchema` is the event. The models are added to `components`, so generators emit them as named types.
- **The server is held to them (contract test):** every SSE event a test reads is parsed with the same models. One helper parses SSE for all tests, so no stream test can skip the check.
- **Enums stay in sync:** a unit test fails when a run event type, a turn status or a helper status exists in the code but not in the schema, or the other way round.
- **Pattern:** Published Language (DDD): the stream's events become a documented, versioned language between the server and its clients, instead of a format each client reverse-engineers.

### 1.2 Errors as schemas (R19.1)
- **One `Problem` model** (`type`, `title`, `status`, `detail`, extensions allowed) and **`ValidationProblem`** (`errors`), under `application/problem+json`.
- **Declared per operation,** from what each route can raise. FastAPI's default 422 is replaced everywhere it appears.
- **Held to it (contract test):** in the API tests, every error response is checked against its operation's declared responses and the problem schema. An undeclared status fails the test that caused it, naming the route.

### 1.3 Operation ids (R19.1)
`generate_unique_id_function` uses each route's function name (`send_message`), checked unique and snake_case by a test. The web app calls by path, so only `schema.d.ts`'s `operations` keys change.

### 1.4 Breaking changes (R19.2)
A CI step runs [oasdiff](https://github.com/oasdiff/oasdiff) (Apache-2.0) `breaking --fail-on ERR` between `main`'s `frontend/openapi.json` and the pull request's, pinned to a release by checksum.

### 1.5 The web app (R19.3, R19.9)
- **`openapi-fetch` vendored** into `frontend/src/api/vendor/openapi-fetch/` with its MIT licence and version, and dropped from `package.json`: no runtime dependency on a frozen package.
- **The stream types generated:** `events.ts` takes its event and payload types from `Schemas`; `TurnStatus` becomes the schema's statuses plus the UI's own `ended`.
- **The pnpm override's exit condition** ("remove when it declares 6", which can't happen) becomes a revisit trigger: replace the generator before TypeScript 7.

---

## 2. Tasks

| # | Task | Done when |
|---|---|---|
| 1 | Stream schemas and the shared SSE test parser | Both stream responses reference the event schemas; every stream test parses through the models |
| 2 | Enum sync test | Adding a run event type without its schema fails a test |
| 3 | `Problem` / `ValidationProblem`, declared on every operation | No operation declares `HTTPValidationError`; each declares its error statuses |
| 4 | The error contract test | The API suite passes with every error response declared and well-formed |
| 5 | Operation ids | Every operation id unique, snake_case, the route's function name |
| 6 | Web app: vendored `openapi-fetch`, generated stream types, the override's note | `make ui-check` passes; `pnpm why openapi-fetch` finds nothing |
| 7 | `oasdiff` in CI | A mutated spec (a removed response field, a removed operation) fails the check; the real diff of this phase passes |
| 8 | Docs | `design.md` patterns, the CHANGELOG, the summary with each criterion's measured result |

## 3. Success criteria

| # | Criterion | How it's measured |
|---|---|---|
| 1 | **AC49:** every event emitted in the tests matches the published schemas | The integration suite and the runtime e2e ×5 pass with the contract parser; a mutation (a payload field renamed in the server) fails them |
| 2 | **AC49:** the web app's stream types come from the generated schema | `events.ts` declares no wire types of its own; `tsc --strict` passes |
| 3 | Every error response matches its declaration | The error contract test passes; a mutation (an undeclared 409) fails it |
| 4 | **AC50:** breaking changes fail CI | oasdiff exits non-zero on the two mutations, zero on this phase's own diff |
| 5 | Nothing else changes | Backend suite with coverage ≥ 90 %, lint, format, `mypy --strict`, `make ui-check`, the runtime e2e ×5, the container e2e and the browser suite all pass |

## 4. Out of scope
The SDKs themselves (S2, S3); typing every run event's payload (S1 types the envelope and the events clients act on; the rest keep `payload: object` until a client needs them); a new TypeScript generator (backlog, before TypeScript 7).
