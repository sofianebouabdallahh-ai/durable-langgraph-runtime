# Phase H3 — An API only you can drive

**Completed:** 2026-11-09 · **Branch:** `feat/h3-api-identity` · **Plan:** [plans/phase-H3.md](../plans/phase-H3.md) · **Tests:** backend 760 (+49 since H2) · container e2e +1 scenario (`outsiders`) · injection cases +1

Found by the platform review of 2026-11-08, security findings 9–13: any web page could drive Nuria's API through DNS rebinding, the cloud chart put it on the internet with no login, a saved key followed a changed URL, `read_webpage` could carry data out without asking, and only the page reader had an SSRF guard.

## What we built

**Only Nuria's own pages reach it.**
- nginx's default server answers **421** to any `Host` that isn't `localhost`, `127.0.0.1`, `[::1]`, `host.docker.internal` or one of `UI_HOSTNAMES`. A DNS-rebinding page sends its own name, so it is refused. `/healthz` answers any name (probes).
- The API refuses a browser request from another site (**Fetch Metadata**): `Sec-Fetch-Site: cross-site` or `same-site`, or a foreign `Origin` or `Host` → **403** `not-nurias-page`. The CLI and scripts send none of those headers and are unchanged.

**The cloud chart can't expose Nuria without a password.** With `ingress.host` set, the chart refuses to render unless `ingress.basicAuthSecret` (nginx-ingress or Traefik basic auth) or `ingress.unauthenticated: true` is set. The admin API is off in the chart; the kill switch works through the agents API.

**A saved key stays with its address.** Changing a model connection's host (scheme, host or port), or an MCP server's address or header, without entering the key again → 422 "Enter the key again for the new address".

**One outbound guard for every address Nuria is given** (`net.py`).
- MCP servers, model connections and SearXNG.
- The host is resolved and **every** address it resolves to is checked: no cloud metadata, link-local, reserved, multicast, NAT64 or IPv4-mapped forms of them, and none of Nuria's own services, by name and by resolved address.
- Decimal, hex and octal IPs are read by the resolver and checked like any other.
- Inside the containers, 127.0.0.1 is Nuria itself: the message says to use `host.docker.internal`.

**A page address nobody gave the agent asks first** (`ProvenancePolicy`, a Decorator on the run's policy).
- `read_webpage` runs without asking for an address you wrote, one a search in this chat returned, or an allowed site.
- Anything else, such as an address planted in a page that could carry your chat out, waits for your approval, with the full address shown.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| 1 | Host and CSRF | ✅ Container e2e `outsiders`: a foreign Host → 421; the health check answers any name; a cross-site request → 403 and changed nothing; Nuria's own page and the CLI are served. Unit (`test_guard.py`): `Sec-Fetch-Site: cross-site` / `same-site`, a foreign `Origin` or `Host` on `POST /admin/cancel-all` → 403; same-origin and header-less requests pass |
| 2 | Chart | ✅ The cloud values without a password fail to render, with the message (now a CI step); with `basicAuthSecret` the nginx annotations render; `unauthenticated: true` renders; `ADMIN_API_ENABLED=false` |
| 3 | Keys | ✅ A changed host without a key → 422 and the stored key isn't used; with a key → saved. The same for MCP (URL and header) |
| 4 | SSRF | ✅ `http://2852039166/`, `0xa9fea9fe`, `0251.0376.0251.0376`, `169.254.169.254.nip.io`, `metadata.google.internal.`, the stack's names and IPs, `fd00:ec2::254`, `100.100.100.200` are refused for MCP, models and SearXNG; loopback and private addresses still work outside a container |
| 5 | Egress | ✅ A planted URL → `read_webpage` asks, full URL on the card; a URL from you or a search → no question. New injection case `exfiltrate-by-url` |
| 6 | Quality | ✅ Backend 760 passed (3 heartbeat-timing tests failed once while the browser suite loaded the machine, then passed 4/4 alone); lint, mypy `--strict`; container e2e 6/6 on images built from H3 |

## Testing record

- **Backend:** 757 passed, 3 skipped (live model, Redis kill, malformed message); `test_worker.py`'s 3 timing tests failed on the first run under load (the browser suite and the container e2e at the same time), then passed 11/11 four times alone.
- **Container e2e** on `nuria-runtime:h3` / `nuria-ui:h3`: 6/6, including `outsiders`.
- **Runtime e2e** (`all` × 5): every scenario passed every run except the stream-latency checks of `stream from any replica` and `Pub/Sub disabled` (p95 ≈ 390 ms against 250 ms) while the machine's load average was ~15. Run side by side under the same load, `main` failed the same check (p95 514 ms) and H3 passed (p95 25–65 ms): load, not H3.
- **Browser:** 58/58 on images built from H3, and 58/58 on H2's images, on the same stack, back to back. Earlier runs timed out (up to 15 failures): a crash-looping local kind cluster was using about 3 of Docker's 8 CPUs, so every commit on the test stack was slow (an agent draft took 21.6 s instead of 0.3 s). With it stopped, a full run takes 7.4 minutes.

## Design notes

- **Why Fetch Metadata, not CSRF tokens:** no state, nothing for the UI to carry, and it covers every route at once. `Origin` is the fallback for browsers that don't send `Sec-Fetch-Site`.
- **Why re-entering the key, not binding the origin into the encryption context:** simpler, and just as strict: a key never moves to a host it wasn't typed for.
- **Remaining window** (SECURITY.md): the OpenAI and MCP SDK clients resolve the name again when they connect, so a name that changes its answer in between (DNS rebinding against Nuria's own outbound calls) is checked at save, test and call time, not at connect time.
