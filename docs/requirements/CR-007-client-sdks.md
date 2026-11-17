# CR-007 — Client SDKs: Nuria from code

| | |
|---|---|
| **Status** | **Accepted** (2026-11-15) |
| **Date** | 2026-11-15 |
| **Base document** | [`Project_4_Detailed_Requirements_K8s.pdf`](Project_4_Detailed_Requirements_K8s.pdf) (v1.0 + Kubernetes) |
| **Depends on** | Phase 3 (SSE with `Last-Event-ID`), H1 (approvals bound to the call), CR-001 (sessions), CR-006 §18 (identity, for R19.7) |
| **Amends** | R6.5 (the UI's client generated from the spec): the spec becomes a published contract, checked in CI |
| **Scope** | New §19 Client SDKs; acceptance criteria AC49–AC54 |

## 1. Motivation

Today Nuria is used through its web app. Its HTTP API is complete (106 operations), but a program that wants to use it has to hand-write what the web app's stream adapter does: follow a reply as it streams, pick the stream back up after a dropped connection without losing or repeating anything, wait through an approval that can take hours, and tell a finished turn from a failed or stopped one. Our own test scripts do exactly that by hand.

A client SDK makes that one call, for scripts, CI jobs, evals and other services. It also makes the API a **contract**: once other people's code depends on it, a breaking change has to be caught before it ships.

## 2. Research summary (2026-11-15)

The full report compares 14 generators and 5 protocols; the decisions it supports:

- **No generator, free or paid, handles Nuria's stream.** Stainless, which builds the OpenAI and Anthropic SDKs, joined Anthropic and takes no new projects since 2026-05-18 ([Stainless](https://www.stainless.com/blog/stainless-is-joining-anthropic)). Speakeasy's free route makes the generated runtime AGPL-3.0-only ([LICENSING.md](https://github.com/speakeasy-api/openapi-generation/blob/main/LICENSING.md)). Fern keeps SSE for its Enterprise plan ([pricing](https://buildwithfern.com/pricing)). The free TypeScript generator with SSE (hey-api) ends the stream on a clean close, so a drain's `event: reconnect` would stop it. **Decision:** generate the typed calls; hand-write the stream, the waits and the results.
- **Python:** [openapi-python-client](https://github.com/openapi-generators/openapi-python-client) is MIT, runs offline, supports OpenAPI 3.1 and generates sync and async calls. **Decision:** use it, pinned exactly (its 0.x releases break).
- **TypeScript:** the web app's generator, [openapi-typescript](https://github.com/openapi-ts/openapi-typescript), was frozen by its author on 2026-09-19, security patches included ([#2874](https://github.com/openapi-ts/openapi-typescript/issues/2874)), and `openapi-fetch` has been in maintenance mode since 2025-12-29 ([#2559](https://github.com/openapi-ts/openapi-typescript/discussions/2559)). Their maintainers' advice is to keep a copy of `openapi-fetch` (2.9 kB, MIT) in the project. **Decision:** copy it in; keep the generator as a pinned build tool until a vetted successor exists.
- **The spec doesn't describe what an SDK needs.** Both stream responses are `text/event-stream: {}` (typed `unknown`), and no operation declares a 404 or a 409. **Decision:** the spec first.
- **No protocol replaces an SDK.** A2A v1.0 defines no event ids or replay; MCP's 2026-07-28 revision removed `Last-Event-ID` resumption; AG-UI says "a broken stream cannot be re-entered"; LangGraph's client resumes a paused run with any value it is handed. **Decision:** protocols come later, as adapters at the API layer, never as Nuria's client.
- **Approvals belong to a person, and the API has no login yet** ([security.md](../security.md)). An SDK `approve()` would let any program on the machine approve. **Decision:** the SDK shows pending approvals; deciding waits for identity (CR-006 §18, phase P7).

## 3. New section — §19 Client SDKs

### R19.1 The API is a published contract — MUST
- **Streams are described.** Each stream endpoint declares the events it sends, as component schemas: the envelope (`run_id`, `seq`, `after_seq`, `ts`, `epoch`, `type`, `payload`), the session stream's events as a union on `type` with their payloads, and the `reconnect` event's data.
- **Errors are described.** Every operation declares the error responses it can give (400, 404, 409, 503 as they apply), with one problem-details model (RFC 9457).
- **Operation ids are stable and readable** (`send_message`, not `send_message_sessions__session_id__messages_post`), since SDK method names come from them.
- **What the server sends matches what it publishes:** a contract test validates every event the server emits in the tests against the published schemas.

### R19.2 Breaking changes are caught in CI — MUST
Every pull request compares its spec with the base branch's. A breaking change (a removed field, operation or enum value, a narrowed input) fails the build.

### R19.3 Generated code is never edited by hand — MUST
Generated code lives in its own directory, is regenerated in CI and fails on any difference. Hand-written code lives elsewhere and the generator never touches it. The fix for wrong generated code is in the spec.

### R19.4 A Python SDK — MUST
Sync and async clients with the same API, typed (`py.typed`, `mypy --strict` clean):
- sessions, agents, sending a message (with an `Idempotency-Key`), a turn's messages;
- a **run handle** that another process can rebuild from the run's id;
- a **stream** of the turn's events and text, that resumes by R19.5;
- **`wait()`** that returns a typed result: completed, failed (with its reason), cancelled, or **awaiting approval** (with the approval's id, the tool and its arguments). Waiting on an approval is a result, never a timeout;
- unknown event types and statuses are passed through, never an error, so a newer server doesn't break an older client.

### R19.5 Streams resume without loss or repeats — MUST
- the cursor moves only on events that carry an `id`;
- `event: reconnect` (a replica draining) reconnects at once, from its `after_seq`;
- an event at or below the cursor is dropped;
- a dropped connection, a refused one, a 429 or a 5xx is retried with jittered backoff; progress earns a fresh set of attempts;
- a clean close without a terminal event asks the run its status;
- 401, 403 and 404 are fatal;
- the read timeout is above the server's ping interval;
- a stream is never recovered by sending the message again.

### R19.6 Sends are safe to retry — MUST
Each send carries one `Idempotency-Key`, reused on every retry of that send; `409 duplicate-send` means "retry with the same key". A 409 on an approval is final and never retried.

### R19.7 No SDK path decides an approval — MUST, until identity exists
Until the API can tell a person from a program (CR-006 §18), the SDKs list pending approvals and wait for them, and offer no way to approve or reject. When identity exists, deciding is added, bound server-side to the person's credentials, and callbacks defer by default.

### R19.8 A TypeScript SDK — SHOULD
The same Facade for Node (≥ 22) and the browser, with auth headers on streams. It shares one generated type source with the web app.

### R19.9 Tooling the project can keep — MUST
Only MIT- or Apache-2.0-licensed tooling. Every tool pinned to an exact version, under the repository's two-week cooldown. The web app doesn't depend at runtime on an unmaintained package.

### R19.10 Protocol adapters — MAY, on demand
A2A first (approvals through `AUTH_REQUIRED`, decided in Nuria), then AG-UI from the API layer, then MCP tasks once hosts support them. Each is an adapter over the same API, with a conformance suite against a pinned SDK.

## 4. Acceptance criteria (§11)

| AC | What | Phase |
|---|---|---|
| **AC49** | Every event the server emits in the integration and e2e tests validates against the published stream schemas, and the web app's stream types come from the generated schema | S1 |
| **AC50** | A pull request that removes a field from a response, or an operation, fails CI; shown by a mutation of the spec | S1 |
| **AC51** | A Python script sends a message, streams the reply through a replica drain (`event: reconnect`) and a cut connection, sees every persisted event exactly once, and gets a typed completed result; 5/5 on the real stack | S2 |
| **AC52** | For a turn that asks for approval, `wait()` returns "awaiting approval" with its approval id and the SDK offers no way to decide. After the person approves in Nuria, a handle rebuilt in a new process gets the completed result | S2 |
| **AC53** | A send retried with the same idempotency key, including after a 409, makes one turn | S2 |
| **AC54** | AC51 passes in Node with the TypeScript SDK, and the web app and the SDK build from one generated type source | S3 |
