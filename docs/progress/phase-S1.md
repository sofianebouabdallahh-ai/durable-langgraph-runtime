# Phase S1 — The API contract

**Completed:** 2026-11-15 · **Branch:** `feat/s1-api-contract` · **Plan:** [plans/phase-S1.md](../plans/phase-S1.md) · **Requirements:** [CR-007](../requirements/CR-007-client-sdks.md) R19.1, R19.2, R19.3, R19.9 · **Decision:** [ADR-0009](../adr/0009-client-sdks.md)

The first phase of the client SDKs. An SDK is generated from the API's OpenAPI spec, so the spec has to say what the API really does. Before this phase it didn't: the two streams were `unknown`, no operation declared a 404 or a 409, and the 422s described a shape the API never sent. Now the spec describes the streams and every error, the tests hold the server to it, and CI fails a pull request that breaks it.

## What we built

**The streams, described** ([`api/stream_schemas.py`](../../backend/src/agent_runtime/api/stream_schemas.py)).
- Pydantic models for what one SSE event's `data` carries: the envelope (`run_id`, `seq`, `after_seq`, `ts`, `epoch`, `type`, `payload`); the run stream's event, whose `type` is one of the 28 run event types or `token`; the session stream's six events as a union on `type`, each with its payload (`message.created` → `MessageView`, `token`, `turn.status`, `subagent.spawned`, `subagent.progress`, `subagent.completed`); and `reconnect`'s `{after_seq}`.
- The spec references them the way FastAPI's own SSE routes do (OpenAPI 3.2's `itemSchema`, inside the 3.1 document): `text/event-stream` → `itemSchema` → `data` as JSON, whose `contentSchema` is the event or `ReconnectData`. `TurnStatus`, `HelperStatus` and `HelperResultStatus` are enums, so the spec names them.
- The models describe the wire; they don't produce it. `streaming/session.py` is unchanged.

**The errors, described** ([`api/contract.py`](../../backend/src/agent_runtime/api/contract.py), [`api/problems.py`](../../backend/src/agent_runtime/api/problems.py)).
- `Problem` and `ValidationProblem` publish the RFC 9457 shape the API already sent: `type` to branch on, `title`, `status`, `detail`, and a problem's own fields. `errors` is there when the request's fields didn't validate; other 422s say why in fields of their own (a limit's `field` and `maximum`).
- Every route declares the statuses a client branches on (`responses=contract.problems(404, 409)`), from the exceptions its code can raise: 69 of the 106 operations declare at least one, 105 declarations in all (404 on 61, 409 on 25, 503 on 12, 429 on 7), and the 87 422s are `ValidationProblem`. Every operation also gets `default: Problem`: the guard's 403 and 421 and an unexpected 500 are problems too.
- A route's own `HTTPException` (ten of them, plus Starlette's 404 and 405) is now rendered as problem details. It used to come back as `{"detail": "..."}`; `detail` is unchanged, so the web app reads it as before.

**Operation ids are the routes' names** (`send_message`, not `send_message_sessions__session_id__messages_post`). Ten were used twice (`edit`, `add`, `approve`, ...); those route functions, and the other generic ones, were renamed to say what they act on (`update_connection`, `approve_mcp_tool`, `list_skills`). 106 operations, all unique and snake_case.

**The server held to the spec (provider contract tests).**
- [`tests/sse.py`](../../backend/tests/sse.py): the one SSE reader every stream test already used now parses each event with the published models, checks that its SSE `event` is its `type` and its `id` is its `seq`, and fails on any field the models don't declare (the models themselves ignore unknown fields, so a newer server doesn't break an older client).
- [`tests/problem_contract.py`](../../backend/tests/problem_contract.py): installed for the whole session, it wraps `httpx.ASGITransport`, which every API test's client goes through. Each error response of Nuria's API must be problem details, validate as `Problem` (or `ValidationProblem` for a 422), and have a status its operation declares. A failure names the operation and the status, in the test that caused it.
- [`tests/unit/test_api_contract.py`](../../backend/tests/unit/test_api_contract.py): ids unique and readable, no `HTTPValidationError`, every error as problem details, every `$ref` resolving, both streams typed, and the schemas' enums equal to the code's (a new run event type, turn status or helper status needs its schema).

**Breaking changes fail CI** ([`scripts/api_breaking.sh`](../../scripts/api_breaking.sh), `make api-breaking`). `oasdiff breaking --fail-on ERR` between the base's `frontend/openapi.json` and the pull request's, in the CI `ui` job after the drift check. oasdiff 1.35.0 (Apache-2.0) is the newest release past the two-week cooldown, its checksum pinned in the script like the Kubernetes tools. [`scripts/api_breaking.accepted`](../../scripts/api_breaking.accepted) lists changes a reviewer accepted, each with its reason.

**The web app.**
- `openapi-fetch` 0.17.0 and its one dependency are vendored in [`frontend/src/api/vendor/`](../../frontend/src/api/vendor/README.md): both tarballs matched the sha512 the lockfile pinned, the files are unchanged except one import path, with their MIT licences and the vendored sha256. Neither is installed any more.
- [`events.ts`](../../frontend/src/stream/events.ts) takes its types from the spec: `SessionEvent`, `TurnStatus` (the spec's, plus the UI's own `ended`), `HelperStatus`. Records over the spec's unions make `tsc` fail if the spec adds an event or a status the UI doesn't list. The client's `Problem` type is the spec's.
- The pnpm override's note ("remove when it declares 6", which a frozen package never will) now says to replace the generator before TypeScript 7.

## Success criteria: results

Every run below is mine, on the committed branch (`ad09548`, plus this summary), on 2026-11-15.

| # | Criterion | Result |
|---|---|---|
| 1 | **AC49:** every event emitted in the tests matches the published schemas | ✅ The integration suite (478) and the runtime e2e ×5 (15 scenarios, 75/75, 450 checks) read every stream through the contract parser, and all pass. **Control:** one undeclared field added to the server's envelope failed 9 stream tests, on both streams, naming the field |
| 2 | **AC49:** the web app's stream types come from the generated schema | ✅ `events.ts` declares no wire types of its own; `tsc --strict`, ESLint, 86 Vitest tests and the build pass |
| 3 | Every error response matches its declaration | ✅ The API suite passes with every error checked. **Control:** `cancel_run` declared without its 409 failed `test_cancel_endpoint`: "cancel_run doesn't declare 409" |
| 4 | **AC50:** breaking changes fail CI | ✅ oasdiff exits 1 on a removed `RunView.status` (7 errors) and on a removed `cancel_run` (1 error); 0 on this phase's own diff, with the 87 accepted lines below |
| 5 | Nothing else changes | ✅ All the suites in the table below |

| Check | Result |
|---|---|
| Backend: unit and integration, with coverage | 1,088 passed, 3 skipped, **91.92 %** |
| `ruff check`, `ruff format`, `mypy --strict`, agent definitions, docs check | clean |
| CI's API drift step (`make ui-api`, then no diff) | no drift |
| `make api-breaking` against `origin/main` | no breaking change |
| Web app (`pnpm check`: lint, types, tests, build) | 86 tests, build passes |
| Runtime e2e ×5 | 15 scenarios, 75/75, 450 checks |
| Tester setup twice (built from the branch) | both healthy; `.env` identical; a chat turn in 1.1 s |
| Container e2e | 9/9, 56 checks |
| Browser suite, observability on | 63 passed, 1 skipped (the live-model spec) |

**Not run, and why:** the Kubernetes job and `infra/ci/upgrade.sh`. S1 changes no chart, migration, Compose file or stored data; the API's behaviour changes only in how a route's own `HTTPException` is rendered, which the container e2e and the browser suite exercised. Helm lint and template: no chart changed.

## What running it found

- **The spec described 422s the API never sent.** All 87 declared FastAPI's `HTTPValidationError` (`application/json`, `detail` an array), while `problems.py` has always answered 422 with problem details (`detail` a string). A client generated from that spec would have mis-read every validation error. Found by reading `problems.py` while declaring the errors.
- **Ten routes answered with a different error shape.** A route's own `HTTPException` (a turn that doesn't exist in Activity, a reply that can't be rated, the Studio's not-founds) came back as `{"detail": "..."}`, not problem details, although `problems.py` promised one shape. The error contract test flagged them on its first run; they now go through the same handler.
- **The first run of the error contract test found 21 undeclared statuses** (404 on 8 routes, 409 on 6 of them, one twice, 503 on 2, 429 on 1, and 3 limit errors that carry `field` and `maximum` instead of `errors`). They and the rest, from reading each route's code, are declared now.
- **The streams matched.** Not one event of the 478 integration tests or the 75 e2e runs had a field the new schemas didn't declare, or a payload of the wrong shape: the server and the web app's hand-written decoder had stayed in step. The schemas now make that checkable.
- **The checker first held fakes to Nuria's contract.** The fake model, sandboxd and small test apps also go through `httpx.ASGITransport`; five of their tests failed. The checker now holds only apps that publish the contract (`app.state.contract`).
- **oasdiff calls the 422 correction breaking** (87 `response-property-type-changed`), which it is for a client generated from the old spec. It was already wrong for the real API, so the 87 lines are accepted in `scripts/api_breaking.accepted`, with the reason, to be removed once this merges.

## Design notes

- **Describe the wire, don't generate it from the models.** The stream models are a description held to the server by tests, not the code that writes events. Rewriting `streaming/session.py` around them would have touched the replay and drain logic for no behavioural gain; the contract test gives the same guarantee.
- **Two catch points, no per-test opt-in.** The stream check sits in the one SSE reader and the error check in the one transport every test client uses, so a new test is checked without anyone remembering to.
- **Strict at test time, tolerant on the wire.** The models ignore unknown fields (a newer server mustn't break an older client, R19.4); the tests reject them (the server mustn't send what it doesn't publish).
- **`default: Problem` everywhere, explicit statuses where a client branches.** The edges' errors (the guard's 403 and 421, a 500) are typed without cluttering 106 operations, and the statuses that need handling are named per route.
