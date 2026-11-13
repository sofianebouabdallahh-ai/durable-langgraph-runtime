# Phase H10 — The external review's findings

**Completed:** 2026-11-12 · **Branch:** `feat/h10-review-fixes` (on `main`) · **Plan:** [plans/phase-H10.md](../plans/phase-H10.md) · **Decision:** [ADR-0008](../adr/0008-provenance-and-skill-approval.md) · **Review filed:** [reviews/2026-11-12-external-review.md](../reviews/2026-11-12-external-review.md) · **Tests:** backend 1,083 (+56 since H8) · UI unit 86 · coverage 91.84%

On 2026-11-12 an outside reader reviewed the code at `ef7dfad` with five agents and replayed
the findings he considered faults on our own pipeline and policy against a real Postgres.
We re-read every claim against the code the same day: the five headline findings hold; of
the twenty hypotheses, fifteen hold, four hold in a narrower sense, one is refuted. Two of
them let a planted instruction carry data out:
- an address the model *searched for* passed the provenance check, because the check read
  the whole stored search result, which carries the model's own query;
- a skill nobody had read could enter the system prompt as plain instructions, because the
  scan (English regexes) decided, and an imported agent's skills were never read by anyone.

This phase closes both, fixes everything else the review found that needed code, and
records the rest with its reason. The sandbox item went into H9, whose branch has the file
open.

## What we built

**Provenance reads fields, not blobs** (`tools/policy.py`).
- Of a stored `web_search` result, only each hit's `url` vouches for an address: the query
  is the model's, titles and snippets can be written by a page. The address is matched
  inside a returned url, so a dropped tracking parameter still passes. A result that isn't
  a list of hits vouches for nothing and raises nothing.
- On the person's side, only their words vouch: the `message` of the run's input and the
  `text` of their messages in the chat. With the scripted test model the input also holds
  the model's replies (`script`, `subagent_scripts`). The first version of this fix still
  searched the whole input as text, and a whole scripted turn on a running stack read the
  page unasked ([what running it found](#what-running-it-found)).
- A control run with the old query (a scratch pytest plugin swapping `_SEEN` back) fails
  exactly the eleven attack tests and passes every legitimate one. The reviewer's replay
  (the real `web_search` tool, a provider with zero hits, then `read_webpage`) is now a
  regression test; `exfiltrate-by-search.yaml` runs the two-step chain through the
  injection runner, which learnt a `prior:` list of obeyed calls.

**A skill's text needs a reader** (migration 0029, `skills/`, `graphs/assistant.py`).
- `skill_approvals` holds the hash of every version a person approved. Plain text in a
  prompt needs a clean scan **and** an approved hash; everything else stays `<data>`.
- Built-in skills are approved by the sync; skills written or edited in the Studio at save
  (the person typed the text); uploaded and imported ones wait for "I've read this" on the
  Skills page, which shows the text and the scan's findings. A new version asks again. An
  imported agent's draft lists the skills waiting; it publishes anyway, with them as data.
- `POST /skills/{id}/approve`, audited once per version. The scan's header and the prompt
  builder's docstring now say the same thing: the scan informs, the approval decides.

**The page reader unwraps NAT64** (`net.effective_address`, `web/fetch.py`): the well-known
prefix and RFC 8215's local-use prefix are judged as the IPv4 address they reach, so
`[64:ff9b::a9fe:a9fe]` is the metadata address.

**Secrets** (`redaction.py`, `tools/pipeline.py`, `runs/approvals.py`, migration 0030).
- The post-tool hooks run **before** the ledger write: `tool_invocations.result` holds what
  the model was shown, a replay is byte for byte the same, and a result a hook withheld is
  stored as a failed call with the note in its place.
- Twelve patterns shaped after gitleaks' rules (Google, Slack, JWT, Hugging Face, GitLab,
  npm, Stripe, Azure AD, Tavily), each with a near-miss test, and `known_secrets`: the exact
  value of every key Nuria opens (`keys.open_secret`) or holds in settings is masked
  wherever redaction runs. No pattern can miss a value it was given.
- The approval card carries `hidden`, the number of values redaction took out of the shown
  arguments, and says so; the hash still binds the real arguments (H1).

**Four Compose networks and a Redis password** (`infra/compose/`, `setup.sh`, `setup.ps1`,
the Helm charts).
- `data` (internal: Postgres, Redis, API, workers, migrate), `app` (UI, API, workers,
  sandboxd, observability), `egress` (workers, API, SearXNG, Ollama), `reader` (the page
  reader and the workers, which alone ask it). From SearXNG and from the page reader,
  Postgres, Redis and sandboxd neither resolve nor answer; from the page reader the API
  doesn't either; the stores can't reach out.
- What Compose doesn't close: a Docker network has no direction. The API asks SearXNG and
  Ollama, so they share `egress` with it and can open its port, and the API has no login.
  The chart's NetworkPolicies close it on Kubernetes ([security](../security.md)).
- Redis asks for `REDIS_PASSWORD`, generated by setup and written into an existing `.env`;
  the health check no longer passes unauthenticated (`redis-cli ping` exits 0 on NOAUTH).
  Helm gets the Secret key, the env and KEDA's `TriggerAuthentication`.
- A published port needs a network with a gateway, which means egress (measured in a
  throwaway project). So `./setup.sh` no longer publishes 5432 and 6379; the dev loop does,
  through `docker-compose.dev.yml`, which the Makefile adds.

**Retention** (migration 0031, `runs/retention.py`, `worker.py`): `RETENTION_DAYS` (90;
`0` keeps everything). A sweep claims one finished run at a time (`SKIP LOCKED`), deletes
its events and tool calls in batches of 1,000, then marks `details_pruned_at`; delivered
notifications go after 7 days. The run, the chat, its summary, the notes and the audit trail
stay; "What happened?" says when details were removed. The worker role may delete from
those three tables and nothing else.

**Small hardening** (`runs/executor.py`, `config.py`, `untrusted.py`, the messages API).
- A heartbeat failing for longer than the lease stops the worker locally, as its docstring
  promised. A Stop pressed between taking the lease and starting the run ends it cancelled
  and acks the message. `session_end` hooks run under the lease.
- `run_max_depth` is capped at 2 (the roll-up charges three rows). A test pins the
  LangGraph write methods the fenced checkpointer wraps. `</ data>` and zero-width
  spellings of the delimiter are escaped; emoji sequences pass through. `script` is refused
  outside the scripted provider and capped at 64 turns. `check_fence`'s docstring states the
  lock-order rule.

**The docs can't drift silently** (`scripts/check_docs.py`, `make check-docs`, CI's lint
job): the README's clone tag, the CHANGELOG and `pyproject.toml` must be at `VERSION`, and
the roadmap must name every phase plan. The roadmap now knows H1 to H10; the README says how
a call is found since H7.

**In H9:** sandboxd removes only sandboxes of older epochs and answers 409 to an older
worker, whose call ends as `FencedError` (the pipeline lets it through instead of turning
it into a tool error); the worker's goodbye carries its epoch and removes that epoch's
sandbox and older ones, never a newer one; the bearer token is compared in constant time.
All of it is uncommitted in the H9 worktree.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| 1 | The two-step leak asks | **Met, after a second fix** ([below](#what-running-it-found)). Search for an address, then read it → approval asked, nothing read: at the policy level, through the injection runner in both wirings, as a whole scripted turn (`SessionService.send`, `RunExecutor`), and through the API of a running stack. A returned address passes, with or without a dropped parameter; so does one from an earlier message of the chat. Control run on the old search query: 11 attack tests fail, every legitimate one passes; the three whole-turn tests fail on the first version of the fix. The helper path is covered at the pipeline level, not by a real agent turn. |
| 2 | A skill nobody read stays data | **Met.** The reviewer's French trap, imported in an agent zip, scans `clean`, renders inside `<data>` in a test chat's system prompt, is plain text after approve, data again after a new upload, plain text after a Studio edit. A flagged skill stays data even when approved. In a browser, on the running stack: upload on the Skills page, data in the prompt the model got, "I've read this", plain text, a new version, data again. |
| 3 | Docs can't drift silently | **Met** for the check: three deliberate breaks each fail it with a plain message; CI runs it. v0.3.0 itself waits for H9 and H10 to merge (the README still installs v0.2.0 until then, which the check requires). |
| 4 | An older epoch can't remove a newer sandbox | **Met** (H9 branch, uncommitted there): 409, the new owner's sandbox untouched, the stale call raises `FencedError`, and an older worker's goodbye leaves a newer sandbox alone. 52 sandbox unit tests (two fail with the fence taken out), 47 integration tests, and 9 of 9 checks with real containers on this Mac's Docker. |
| 5 | Tiers hold | **Met on Compose, after a fix; on Kubernetes rendered, never run.** On a running stack the `tiers` scenario passes: from the page reader's and SearXNG's containers Postgres, Redis and sandboxd neither resolve nor answer, from the page reader the API doesn't either, the stores can't reach out, and each probe first shows it can see an open port. Redis answers `NOAUTH` without the password, inside its container and on the dev loop's host port. A second `./setup.sh` leaves `.env` byte for byte the same. A dev loop from before this phase moved over with `make up`: the password was generated and put into `REDIS_URL`, Redis was recreated, migrations went 0028 → 0031, and a marker in each store survived. The update from v0.2.0 passes (criterion 10). Still open on Compose: SearXNG and Ollama can open the API's port. The Helm side (the Secret key, the env, KEDA's `TriggerAuthentication`) lints and renders and has not run on a cluster ([below](#what-running-it-found)). |
| 6 | NAT64 refused | **Met.** Both prefixes refused by the fetcher and by `check_destination`; the NAT64 form of a public address still passes. On the running stack: a turn that reads `http://[64:ff9b::a9fe:a9fe]/`, approved by hand, is refused by the page reader; inside its container the reader calls both prefixes' metadata forms not public and the NAT64 form of `8.8.8.8` public. |
| 7 | Secrets | **Met.** The ledger row holds `[REDACTED]`; a key Nuria holds is masked in the ledger and the events; each pattern masked, nine near-misses untouched; the card for a `notify` carrying a key shows `[REDACTED]` and `hidden: 1`, `0` with the default hook on. On the running stack (default hook on): a key printed by sandboxed code is masked in the ledger, the transcript, a dump of the whole database and the logs; a key in a `notify` call's arguments is masked in the stored approval, what the page gets, the ledger, the events and the webhook's body. `hidden: 1` is measured in the unit and integration tests only, with the hook off. |
| 8 | Retention | **Met.** Two-day-old runs lose events and invocations and keep everything else; `0` prunes nothing; a running run is never touched; idempotent; delivered notifications go after a week; the worker role can delete only what the sweep needs. On the running stack: the worker's own sweep prunes a run aged to 200 days, keeps the run, the chat and the audit trail, leaves a run that ended today alone, and the API returns `details_pruned_at`. |
| 9 | Each small change has its test | **Met.** 27 unit and 39 integration tests across the nine items; the fenced-method test fails when a wrapped method is removed (checked by deleting one at runtime). |
| 10 | Quality bar | **Met, except the Kubernetes job.** Backend 1,083 passed, 3 skipped, 91.84% branch coverage (through the dev loop, against Redis with a password); ruff, format and mypy `--strict` clean; UI lint, types, 86 unit tests and the build green. Runtime e2e × 5: 15 scenarios, 75 of 75 verdicts PASS. Container e2e: 9 of 9 scenarios, 56 checks. Browser suite with observability on: 63 passed, 1 skipped (the live-model spec). `infra/ci/upgrade.sh` from v0.2.0: the update adds the Redis password and drops the stores' host ports, 2 chats and 14 messages survive it, and its backup restores them exactly. The runtime image these ran on holds the branch head's backend code, file for file (152 files, one hash). **Not run:** the kind job, `setup.ps1`, the live-model spec ([why](#what-running-it-found)). |

## What running it found

The first version of this write-up said the end-to-end suites were "not run here; CI runs
them", and that there was "no stack on this Mac". The owner asked whether everything had
been validated. It had not. The suites of criterion 10 were then run on this Mac, all but
the Kubernetes job, against a tester-style stack (`./setup.sh` in a throwaway clone, its own
Compose project), and the review's chains were replayed by hand through the API. The runs
found what the unit and integration tests had not:

| Found by | What was wrong | Where it's fixed |
|---|---|---|
| The `tiers` scenario, first real run | From the page reader's and SearXNG's containers the API's port was open and `GET /sessions` answered: all three shared `egress`. The docs said the opposite | A fourth network, `reader`. The SearXNG and Ollama side stays open on Compose and is written down |
| The same run | The SearXNG half of the probe passed without probing: that image's `nc` has no `-z`, so every target looked closed | A Python socket loop inside each container, with a control (the container's own port must answer) |
| Replaying the review's chain as a whole scripted turn | **The provenance fix did not hold.** The turn searched for an address, read it, and nobody was asked: the check searched `runs.input` as text, and with the scripted model the input holds the model's replies. A real model's turn stores no script (the API refuses one), so no page could use it; a replay could not see the fix work, and the code broke its own rule | Named fields on the person's side too; three tests, each seen failing before |
| A real Docker backend (H9 branch) | The worker's goodbye (`DELETE`) carried no epoch: an older worker could remove the sandbox a newer one had just started | The epoch goes with the goodbye: it removes that epoch's sandbox and older ones, and a newer one stays |
| Reading the browser suite against criterion 2 | Nothing drove the Skills page's "I've read this" | A browser spec: upload, data in the prompt, read, plain text, new version, data again |
| Reading this write-up against the runs | It said the suites couldn't be run here (they could); a comment named migration 0030 for the retention index (it is 0031) | Corrected; the header gives the measured coverage |
| The upgrade job, run on a laptop | Not from this phase: the job's cleanup takes down the `app` profile only, so `sandboxd` and its network stay behind (on CI the runner is thrown away). After an update from v0.2.0 the old release's `default` network also stays, empty | Not changed here; noted for the owner |

What the hand replay checked on the running stack, each "nothing happened" with a control
beside it showing the probe can see the opposite:
- search for an address, then read it: the turn waits for approval, nothing is read; the
  search's stored result does carry the address (its query), and no returned url does;
- search, then read a returned address: read through the real page reader, no approval;
- a key printed by sandboxed code: `[REDACTED]` in the ledger, the transcript, a dump of
  the whole database (as text and as the checkpoints' hex) and the containers' logs;
- a key in a `notify` call's arguments: masked in the stored approval, in what the page
  gets, and in the webhook's body once approved;
- `http://[64:ff9b::a9fe:a9fe]/`: approved by hand, still refused by the page reader. Inside
  the reader's container, Python alone calls that address global; `effective_address`
  doesn't;
- a run aged to 200 days: the running worker's own sweep removes its events and tool calls,
  keeps the run, the chat and the audit trail, and the API says when.

**Not run, and why.**
- The Kubernetes job. A three-node kind cluster loads every image into each node, and this
  Mac had 3.2 GB of disk free (CI's job clears runner disk for the same reason). So the
  chart's side of the Redis password has never run: the Secret key, the env and KEDA's
  `TriggerAuthentication` lint, render and were read, nothing more. CI's Kubernetes job on
  the pull request is its first real run, and a failure there would be new information.
- `setup.ps1`: no PowerShell here. Its `.env` migration mirrors `setup.sh`'s, which was run.
- The live-model browser spec: it needs a real model.
- `hidden: 1` on an approval card, on a running stack: with the default hook on, the
  arguments are already masked when the card is built, so the stack shows `hidden: 0`. The
  count is measured in the unit and integration tests, with the hook off.

## Review

- **Of the review's method, applied to us:** every claim was re-read against the cited lines
  before anything was built, by a reading separate from the one that fixed it; the
  verdicts are filed next to the report, and the three refutations or narrowings (#2, #9,
  #12, #17, #20) are written down with their reasons.
- **Replays, not assertions:** the leak and the skill trap each have a test that fails on the
  code before this phase and passes after.
- **The three decisions the plan left open:** the sandbox fix went into H9 as planned;
  retention landed rather than slipping; `AGENTS.md` is still a decision for the owner.

## Design notes

- **Substring on the url field, not equality.** Equality would ask for every address the
  model normalises (a dropped `utm_` parameter); a substring inside a *returned* url can't be
  satisfied by an address the engine never returned.
- **Studio edits approve at save.** The form shows the whole text, so the person who saves
  it has read it; an upload replaces text nobody has shown them, so it waits.
- **`hidden` is persisted** (migration 0030) because an approval's card is rebuilt from its
  row, and the count can't be derived from stored arguments: with the default pre-tool hook
  on, the real arguments already carry `[REDACTED]`, and counting markers would claim
  something is hidden when nothing is.
- **GRANT DELETE, not a `SECURITY DEFINER` function.** The plan asked for grants; a function
  that could only prune by the rule would be stricter. Noted for later.
- **Known values live in process memory** for the process's lifetime, never written; the
  alternative, re-reading settings on every redaction, would put the key path on every tool
  call.
- **Published ports imply egress** on Compose; the stores' localhost ports moved to a dev
  override rather than giving the stores a gateway in the tester stack.
