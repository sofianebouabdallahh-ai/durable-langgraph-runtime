# ADR-0009 — Client SDKs: generated calls under a hand-written Facade; the spec is the product

| | |
|---|---|
| **Status** | Accepted (2026-11-15, with CR-007) |
| **Date** | 2026-11-15 |
| **Requirements** | [CR-007](../requirements/CR-007-client-sdks.md) R19.1–R19.9 |

## Context

Nuria's API is the only way into it, and so far its one client is the web app. CR-007 asks for SDKs in Python and TypeScript. Three things make that harder than running a generator:

- **The stream is Nuria's own protocol.** Persisted events carry `id: <seq>` and are replayed after `Last-Event-ID`; transient ones (tokens, turn status) carry none; a draining replica sends `event: reconnect` with the `after_seq` to resume from; a turn can wait hours for approval with only `: ping` comments on the wire.
- **Approvals belong to a person**, bound server-side to the pending call (H1), and the API has no login yet.
- **One maintainer**, so whatever is chosen has to be cheap to keep.

In 2026 the generator market moved under us: Stainless closed to new users (2026-05-18), Speakeasy's free route makes the generated runtime AGPL-3.0-only, Fern keeps SSE for Enterprise, and the web app's own `openapi-typescript` and `openapi-fetch` were frozen by their maintainers.

## Decision

1. **The OpenAPI spec is the product.** Streams, errors and operation ids are described in it (R19.1), a contract test holds the server to it, and CI fails a pull request that breaks it (R19.2, `oasdiff`).
2. **Generate the typed calls; never edit what is generated** (R19.3). Python: `openapi-python-client` into `nuria/_generated`. TypeScript: the types-only generation the web app already uses, with a vendored copy of `openapi-fetch`. Each is regenerated in CI and fails on a diff.
3. **Hand-write a thin Facade** for what no generator does for Nuria: the resumable stream (a sans-IO state machine, one tested core), a run handle another process can rebuild, `wait()` with typed results, idempotent sends, and the retry policy.
4. **No SDK path decides an approval** until the API knows a person from a program (R19.7).
5. **Protocols are adapters**, added on demand at the API layer (R19.10), never Nuria's client.

## Alternatives considered

| Option | Why not |
|---|---|
| A commercial generator (Stainless, Speakeasy, Fern) | Closed to new users, an AGPL runtime, or SSE behind Enterprise. None follows `event: reconnect` |
| Hand-write the whole SDK | 106 operations by hand would drift from the API; a generator keeps the plain calls exact for free |
| Adopt a protocol's SDK (LangGraph, A2A, MCP, AG-UI, OpenAI) | None replays a stream after `Last-Event-ID`; LangGraph's client resumes a paused run with any value, which would bypass approvals bound to the call |
| Wait for a hosted version | The spec fixes (described streams and errors) help the web app today, and they gate every later choice |

## Consequences

- The generator becomes a CI detail that can be swapped: the Facade depends on a private generated package, not on a vendor.
- The spec's description is now tested like code. A new event type, error or status is a contract change, reviewed as one.
- The Facade is the hardest code and nothing generates it: it gets a sans-IO core, recorded-stream tests, and a drain test on the real stack.
- Until identity exists (P7), the SDKs can watch approvals but not decide them.
- The frozen TypeScript generator stays a build-only tool. It blocks TypeScript 7 until it is replaced.
