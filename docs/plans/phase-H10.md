# Phase H10 plan — The external review's findings

**Goal:** every finding of the external review of 2026-11-12 is either fixed and measured,
or recorded as a decision with its reason. The two that let a planted instruction carry
data out are closed first.

**Why:** on 2026-11-12 an external reviewer (Yanis) read the code at `ef7dfad` with five
agents, then **replayed** the findings on our own `ToolPipeline`, `RunRepository` and
policy against a real Postgres. We verified every claim against the code the same day:
all five headline findings hold; of the twenty hypotheses in the review's part 3, fifteen
are confirmed, four hold in a narrower sense, one is refuted (the deadlock the review
suspected was fixed in phase 5b). The report and our verdicts are filed under
`docs/reviews/2026-11-12-external-review.md` (task 0).

| Gap | Today |
| --- | --- |
| A planted instruction can read an address nobody gave the agent | The provenance query (`tools/policy.py` `_SEEN`) looks for the address in the **whole** stored `web_search` result, and that result carries the model's own `query`. Search for the address, then read it: no approval asked. The researcher helper has both tools. |
| A skill nobody read can become system-prompt text | A skill the scan calls `clean` goes into the prompt as plain text (`graphs/assistant.py` `always_section`). The scan is English regexes; an imported agent's skills are scanned, stored and used, and no step makes a person read them. |
| The README installs a version without the hardening | `README.md` clones `--branch v0.2.0` (2026-10-24): 45 commits and H1 to H8 behind, H1 included. |
| The roadmap stopped on 2026-10-24 | "Where we are" doesn't know H1 to H9; the phase write-ups do. |
| A stale worker can destroy the new owner's sandbox | `sandboxd.ensure` removes every sandbox whose epoch **differs** (`!=`), the newer one included. Reachable between `invocations.begin` and `finish`. H9 keeps the loop. |
| Compose: one network, Redis without a password, an API without a login | No `networks:` in `docker-compose.yml`; SearXNG (a third-party image that goes to the internet) can reach Redis, the API and sandboxd. The Helm chart has NetworkPolicies; Compose has none. |
| The page reader lets NAT64 addresses through | `web/fetch.py` `public()` unwraps IPv4-mapped addresses only; `net.py` already handles `64:ff9b::/96`. |
| Secrets: stored raw, six patterns, a card that hides what the hash binds | The ledger stores the raw tool result (a test even says `# stored unredacted`); the patterns miss Google, Slack, Tavily, Hugging Face, GitLab, npm, Stripe, Azure and bare JWTs; the approval card shows redacted arguments while the hash binds the real ones. |
| Nothing prunes `runs`, `run_events`, `tool_invocations`, `outbox_notifications` | Only checkpoints are pruned (0025). Roadmap P10 knows. |
| Small: a heartbeat that never gives up, a cancel race, hooks outside the lease, an unbounded depth, an unpinned method list, a plain `==` on a token, a test field in the API, a `</ data>` variant | Each confirmed in the code; each low on its own. |

**Requirements:** R14.15 (untrusted text stays data), CR-003 (harness guardrails),
R14.13 (least privilege), R14.17 (audit), R13 (sandbox), OWASP LLM01 / LLM02 / LLM06.

---

## 1. Research (2026-11-12)

- **Our verification of the review.** Each headline finding re-read in the code; each
  part-3 hypothesis checked by an independent reading with the deciding lines quoted. The
  verdicts (confirmed / partial / refuted, severity, existing test coverage) go in the
  review file. The reviewer's replay scripts (annexes A to C) were not run here: they need
  the Compose stack. Task 0 turns them into regression tests.
- **Provenance must come from fields a trusted party wrote, never from text the model
  wrote.** The `query` is the model's. Titles and snippets are the engine's but a page can
  influence them (search poisoning), so only each hit's `url` counts. Postgres's
  `jsonb_array_elements` makes that one query. Matching the given address *inside* a
  returned `url` (substring) keeps "the model dropped a tracking parameter" working, while
  an address the engine never returned can't qualify. Child runs (R2.8) carry a
  model-written `input`; today only the fan-out demo graph makes them and it has no
  `read_webpage`; if that changes, the `runs.input` branch of `_SEEN` must be restricted
  to root runs.
- **A skill is an instruction, so a scan can't tell a bad one from a good one.** Anthropic's
  own guidance for skills: install only from trusted sources, read `SKILL.md` and its files
  before enabling one, audit untrusted skills thoroughly. Independent studies
  ([arXiv 2601.10338](https://arxiv.org/html/2601.10338),
  [arXiv 2510.26328](https://arxiv.org/html/2510.26328),
  [SafeDep's threat model](https://safedep.io/agent-skills-threat-model/)) find that
  detecting "instructions in data" is void for skills, since skills *are* instructions, and
  that a quarter to a third of published skills carry injection. So the boundary is a
  person's reading, not the scan: the scan stays what its header says it is (it informs),
  and plain-text status becomes an explicit act, like H6's publish gate for agents.
- **Secret patterns.** [gitleaks' default rules](https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml)
  are the de-facto reference (our CI already runs gitleaks on commits): one regex per
  vendor, each with a word boundary and a trailing delimiter to limit false positives.
  Regexes stay best-effort; the one rule that can't miss is **redact the values you hold**:
  the keys saved in Settings are known to the runtime, so their exact values can be masked
  wherever they appear, no pattern needed.
- **Network segmentation on Compose.** A network with `internal: true` has no gateway and
  no masquerade rule, so its members have no egress; a service on two networks is the only
  bridge between them ([Compose networks
  reference](https://docs.docker.com/reference/compose-file/networks/),
  [Compose networking](https://docs.docker.com/compose/how-tos/networking/)). The
  guidance is to segment where a real boundary exists, not per service. Ours: the stores
  (no egress), the app, and the two services that go to the internet on the agent's behalf
  (SearXNG, the fetcher). The Helm chart's NetworkPolicies are the model. A published
  `ports:` needs a non-internal network, which touches the `make api` dev loop (Postgres and
  Redis on `localhost`); the spike settles how.
- **NAT64.** RFC 6052's well-known prefix `64:ff9b::/96` and RFC 8215's local-use prefix
  `64:ff9b:1::/48` both read as `is_global` in Python, so a guard must unwrap them. `net.py`
  does the first; the fetcher does neither.
- **Retention.** Prune the *details* (events, invocations) by age, in batches, and keep the
  run row and the chat; never the audit trail. H8 already made notes survive a run's
  deletion (`SET NULL`), which is what the retention item was waiting for.
- **The zombie.** The window between `invocations.begin` and `_execute` can be narrowed,
  not closed; what holds, and what the review confirmed, is "at most one effect, and it
  can't persist". The useful change is local: a worker that can't reach Postgres for longer
  than its lease should stop on its own, as the executor's docstring already promises.

## 2. Design

### 2.1 Provenance: only addresses the engine returned

`_SEEN`'s third branch becomes a match over each hit's `url`:

```sql
SELECT 1 FROM tool_invocations t,
     jsonb_array_elements(COALESCE(t.result -> 'results', '[]'::jsonb)) AS hit
WHERE t.tool = 'web_search' AND t.status = 'done'
  AND position(%(url)s IN (hit ->> 'url')) > 0
  AND (t.run_id = %(run)s OR t.run_id IN (…same session…))
```

- Tests (`tests/integration/test_provenance.py`): the address only in `query` asks; only
  in a `snippet` or `title` asks; in `results[].url` passes; the same with a tracking
  parameter dropped passes; from the person's message passes. The reviewer's annex A test 1
  becomes `test_an_address_the_model_searched_for_still_asks` (it fails today, passes
  after); annex B's legitimate case is kept.
- Evals: `backend/evals/cases/injection/exfiltrate-by-search.yaml` (the two-step chain,
  `expect: approval`), and the same through the researcher helper.
- Pattern: **parse, don't search** (the check reads named fields of a known shape, never
  the text of a blob). `docs/design.md` gets the row.

### 2.2 Skills: plain text needs a reader

- **A version is "read" when a person approved exactly that hash.** New table
  `skill_approvals (hash REFERENCES skill_versions, approved_at, note)`; the API may insert,
  the worker may read (least privilege, as 0012). Built-ins: approved by `sync_builtins`.
  Created or edited in the Studio: approved at save, since the person wrote the text.
  Uploaded or imported: **not approved** until the person opens the skill, sees its text and
  the scan's findings, and clicks "I've read this". Any edit makes a new hash, so approval
  lapses with the text, as H1's approval lapses with the arguments.
- `always_section`: plain text iff the scan is clean **and** the current hash is approved;
  otherwise `<data>`. `scanned_clean` becomes `trusted_text(skill)`, and the docstrings of
  `skills/scan.py` and `always_section` say the same thing: the scan informs, the approval
  decides.
- Studio: an imported agent's draft lists the skills "waiting for your review" (they work
  as data meanwhile); the skill page (`frontend/src/studio/skills.tsx`) gets the Approve
  action. API: `POST /skills/{id}/approve`; audit `skill.approved` with the hash.
- Optional, labelled hygiene: French and Spanish phrasings in the scan's `INJECTION` list.
  Not a criterion: the review showed why.
- Patterns: **promotion gate** (as the publish gate, H6) and **content-addressed approval**
  (as approvals bound to the args hash, H1).

### 2.3 The release and the docs tell the truth

- **v0.3.0** is cut once H9 merges: `VERSION`, `backend/pyproject.toml`, a `[0.3.0]`
  section in the CHANGELOG (H1 to H9 move out of `[Unreleased]`), the tag; the README's
  clone line points to it; the roadmap's "Where we are" is rewritten with H1 to H9 and
  what's next (`release.yml` already checks tag = VERSION = CHANGELOG).
- **A check that fails when they drift again**, in CI's lint job (`scripts/check_docs.py`,
  also `make check-docs`): the README's `--branch` equals `v$(cat VERSION)`; every
  `docs/plans/phase-*.md` is named in `docs/roadmap.md`; the CHANGELOG has a section for
  `VERSION`. The review suggested generating the status page; a check gives the same
  guarantee for a tenth of the code.
- README "Idempotent tool calls": since H7 a call is found by its **place** in the run
  (`call_key`); the key still carries the arguments so pre-H7 workers find their calls.
  `tools/pipeline.py`'s header and `idempotency_key`'s docstring are made to agree.
- Pattern: **executable documentation**.

### 2.4 The sandbox follows the newest epoch (in H9)

`ensure` removes only sandboxes with `epoch < requester`, and answers `409 Conflict` when
`requester < newest`; `sandbox/tools.py` maps 409 to `FencedError`, so the stale worker
stops instead of reporting "the sandbox refused the call". Unit test for both orders
(today's `test_one_sandbox_per_run_and_epoch` covers one). **Placed in H9**, whose branch
has `sandboxd.py` open; H10's criterion 4 checks it.

### 2.5 Compose: three networks and a Redis password

Property first, graph second. The property, checked by the container e2e: **from the
SearXNG and fetcher containers, Postgres, Redis, the API and sandboxd are unreachable;
Postgres and Redis have no egress; Redis refuses commands without a password.** The
proposed graph:

| Network | `internal` | Members |
| --- | --- | --- |
| `data` | yes | postgres, redis, api, worker, migrate |
| `app` | no | ui (nginx), api, worker, sandboxd (and sandbox-gate from H9), the observability profile |
| `egress` | no | worker, api (the Settings → Tools provider test), searxng, fetcher, ollama |

- Redis: `--requirepass ${REDIS_PASSWORD}`; `setup.sh` generates it like `SANDBOXD_TOKEN`
  and rewrites `REDIS_URL`; an existing `.env` is migrated in place (setup's second run is
  idempotent, CI checks that). Helm: a `redis` secret, the env, and KEDA's
  `TriggerAuthentication` for the Redis Streams scaler.
- The dev loop (`make up`, `make api`) publishes 5432 and 6379 on `localhost`; an
  internal-only network can't publish ports, so the dev override attaches the stores to a
  non-internal `dev` network, or keeps them on `app` with a comment. The spike decides;
  both keep the property above in the full stack.
- `docs/security.md` "What runs" gets a line per tier; the API's missing login (#7) stays
  documented as is, now with SearXNG unable to reach it.
- Pattern: **bulkhead** (network tiers as blast-radius limits).

### 2.6 The page reader unwraps NAT64

`net._effective` becomes `net.effective_address` and `web/fetch.py` `public()` uses it;
`NAT64` grows RFC 8215's `64:ff9b:1::/48`; `tests/unit/test_web_fetch.py` and
`test_net.py` get `64:ff9b::a9fe:a9fe` and `64:ff9b:1::a9fe:a9fe` (refused).

### 2.7 Secrets: redact before storing, know what you hold, say what's hidden

- **Store what the model is shown.** The `post_tool` hooks run **before** `invocations.finish`,
  so the ledger holds the hook-modified result (capped as today) and a replayed result is
  byte-for-byte what the model saw. `_shown` keeps running the hooks on cached results (a
  redaction is idempotent). The header of `redaction.py` is rewritten to what's true.
- **Patterns**, shaped after gitleaks' rules, each with a unit case and a near-miss case:
  Google `AIza[\w-]{35}`; Slack `xoxb-…`, `xox[pe]-…`, `xapp-…`, `hooks.slack.com/…`;
  JWT `ey…\.ey…\.…`; Hugging Face `hf_[A-Za-z]{34}`; GitLab `glpat-[\w-]{20}`;
  npm `npm_[a-z0-9]{36}`; Stripe `(sk|rk)_(test|live|prod)_…`; Azure AD client secret
  (`…Q~…`); Tavily `tvly-[\w-]{20,}`. Brave's key format is checked against their docs
  before a pattern is written.
- **Known values.** `KnownSecrets`: the exact values of the keys Nuria holds (model
  connections, search keys, webhook secrets, the sandboxd token), masked wherever
  `redact()` runs, refreshed from the settings service every 60 s. No regex can miss a
  value it was given.
- **The approval card says what it hides.** The interrupt payload carries
  `hidden: <count of redactions in the shown args>`; the card reads "n values that look like
  keys are hidden here and will be sent as they are". The hash stays on the real arguments
  (H1's contract: an edit or a changed call is still caught).
- Patterns: **allow-list of known values** next to the pattern list; the hooks as **pipes
  and filters**, now before the write.

### 2.8 Retention

`RETENTION_DAYS` (default 90; `0` keeps everything). A worker sweep next to `archive_idle`
deletes, for terminal runs older than N days, their `run_events` and `tool_invocations` in
batches of 1,000 rows, and `outbox_notifications` delivered more than 7 days ago. Kept:
`runs`, `session_messages` and summaries (the chat stays readable), notes (H8), the audit
trail (append-only, by design). "What happened?" on a pruned run says "details removed
after N days". Grants: `app_worker` gets DELETE on those tables only. May slip to H11
without hurting the rest.

### 2.9 Small hardening

| # | Change | Test |
| --- | --- | --- |
| 2 | `_heartbeat` returns (→ `LeaseLost`) after failures spanning `lease_ttl_s`, so a worker cut off from Postgres stops locally, as the docstring says | unit, with a failing pool |
| 8 | A test lists `AsyncPostgresSaver`'s public write coroutines (`a(put\|delete\|prune\|copy)*`, not `NotImplementedError`) and asserts `FencedCheckpointer` overrides each; the dependency bump that adds one fails this test | unit |
| 9 | Lock-order rule written in `fencing.py`'s docstring (lock `runs` before inserting a fenced row); the 0004 trigger's `FOR SHARE` left as is (no path today) | — |
| 10 | `run_max_depth` gets `le=2`, matching the three-row roll-up | unit |
| 11 | `execute` catches `InvalidTransition` when the run is already cancelled and acks | integration |
| 12 | `_session_end` runs under `_under_lease` | integration |
| 15 | `hmac.compare_digest` for the sandboxd token (as `notifications/delivery.py`) | unit |
| 19 | `script` and `subagent_scripts` refused with 422 unless `model_provider == "scripted"`; a size cap | API test |
| 20 | `_TAG` matches `<\s*/?\s*data\b` and `as_data` strips zero-width characters first | unit |

### 2.10 Method (the review's part 4): your call

- `docs/reviews/`: this review as received, with our verdict table; later reviews next to
  it. The verdict stays with the work.
- `AGENTS.md` at the root (vendor-neutral): the method (a plan with measurable criteria,
  the implementation, the measurement, the write-up, two readings), the constraints (no
  secrets, docs move with code, patterns named in `docs/design.md`). Whether to publish the
  method in a public repo is a decision, not a task.
- H10 ships as **three PRs**, each judged and revertible as a block: **A** 2.1 + 2.2 + 2.6
  (the leaks); **B** 2.5 + 2.7 + 2.9 (the walls and the secrets); **C** 2.3 + 2.8 + 2.10
  (the truth and the housekeeping).

## 3. Tasks

0. File the review and the verdicts (`docs/reviews/2026-11-12-external-review.md`). Turn
   annexes A and B into regression tests in our style; record which fail today.
1. 2.1: the query, the tests, the two eval cases. (PR A)
2. 2.2: migration `skill_approvals`, `trusted_text`, approve endpoint + audit, the Studio
   list and the skill page, the docstrings. (PR A)
3. 2.6: NAT64 in the fetcher. (PR A)
4. 2.4 in H9: the epoch rule and the 409, with its tests. (H9)
5. 2.5: the spike on the dev loop, then the networks, the Redis password in setup, Compose
   and Helm (KEDA auth), the e2e reachability checks, `docs/security.md`. (PR B)
6. 2.7: hooks before `finish`, the patterns, `KnownSecrets`, the card's `hidden`, the UI
   copy, the header. (PR B)
7. 2.9: the nine small changes, each with its test. (PR B)
8. 2.3: v0.3.0 (after H9 merges), README, roadmap, `check_docs.py` in CI, the idempotency
   wording. (PR C)
9. 2.8: retention sweep, grants, the "details removed" note. (PR C, may slip)
10. 2.10: `AGENTS.md` if wanted. Docs: `docs/design.md` rows for the new patterns, ADR 0008
    (provenance and skill approval), the CHANGELOG. (PR C)

## 4. Success criteria

| # | Criterion | Measured by |
|---|---|---|
| 1 | **The two-step leak asks:** search for an address, then read it → approval asked, nothing fetched; through the researcher helper too. An address from a result, with or without a dropped parameter, still passes. The reviewer's attack test fails; his correctif test passes. | integration, eval |
| 2 | **A skill nobody read stays data:** an imported trapped skill, in English or French, reaches the prompt inside `<data>` until a person approves exactly its text; after an edit it is data again. Built-in and Studio-written skills are unaffected. | integration, browser |
| 3 | **Docs can't drift silently:** README's tag = `VERSION` = the latest `v*` tag; the roadmap names every phase plan; CI fails on a stale README (shown by a deliberate break in the PR). | CI |
| 4 | **An older epoch can't remove a newer sandbox:** 409, the stale worker's call ends as fenced, the new owner's workspace is intact. | unit, integration (H9) |
| 5 | **Tiers hold:** from the SearXNG and fetcher containers, Redis, Postgres, the API and sandboxd are unreachable; Redis refuses an unauthenticated `PING`; Postgres and Redis have no egress; `setup.sh` on a fresh clone and on an existing `.env` both end green, twice; the kind install is unchanged. | container e2e, CI setup job |
| 6 | **NAT64 refused:** `http://[64:ff9b::a9fe:a9fe]/` and `http://[64:ff9b:1::a9fe:a9fe]/` are refused by the page reader with the metadata reason. | unit |
| 7 | **Secrets:** no row of `tool_invocations.result` holds a value `redact()` would mask, after a turn whose tool returned every listed pattern and a held key; the same values are masked in events and logs; the approval card for a `notify` carrying a key shows `[REDACTED]` and `hidden: 1`. | integration, unit |
| 8 | **Retention:** with `RETENTION_DAYS=1` and runs dated two days back, events and invocations are gone, the chat, its summary, the notes and the audit trail are intact; `0` prunes nothing. | integration |
| 9 | **Each small change has its test** (table 2.9), and the fenced-method test fails when a wrapped method is removed. | unit, integration |
| 10 | **Quality bar:** backend suite, ruff, mypy `--strict`, UI checks, runtime e2e × 5, container e2e, browser suite, kind job; coverage above the floor. | CI and locally |

## 5. Out of scope

- **A login for the API** (#7): comes with accounts (tenancy). Documented; 2.5 removes the
  only in-network third party that could reach it.
- **Multilingual claim detection** (#18): a quality heuristic for small models, not a
  control; documented as such.
- **Counting a zombie's model call** (#14): a deliberate trade-off (an unfenced write would
  let zombies write forever); a `docs/design.md` note.
- **Generating the roadmap from the plans:** the check in 2.3 gives the same guarantee.
- **The escape suite** (H9's AC22): stays H9's decision.
- **An LLM-based skill scan:** the research says it can't be the boundary; the approval is.
