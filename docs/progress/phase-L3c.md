# Phase L3c — Agent Studio: skills & "describe your agent"

**Completed:** 2026-10-18 · **Branch:** `feat/l3c-skills-and-builder` · **Plan:** [plans/phase-L3c.md](../plans/phase-L3c.md) · **Guides:** [Skills](../setup/skills.md), [Build your own agent](../setup/agents.md), [Tester script](../setup/tester-script.md) · **Tests:** backend 526 · UI unit 54 · browser 5 new scenarios

## What we built

**A skill library.** **Skills** in the sidebar holds reusable know-how: a checklist, a house style, how to do something well.
- **Two ways in:** write a skill in the app, or upload one in the open Agent Skills format (a zip of its folder, or a `SKILL.md`). Both go through one check against the standard and our limits.
- **The scan:** every save is scanned. A secret refuses it, and the secret is never echoed. Injection phrasing, links, encoded blobs, invisible characters, code and length are listed with file and line for a person to look at.
- **Scripts are kept but never run**, and agents can't read them: there is no sandbox yet.
- **Built-in skills:** `trip-planning` and `plain-writing` ship with Nuria and are read-only.

**Skills on agents and helpers.** The Studio has a **Skills** section, and each helper has its own picker.
- **What an agent sees:** only each skill's name and "when to use it". It loads a skill with `load_skill` when the task needs it, and reads its files with `read_skill_file`.
- **Own skills only:** each agent and helper sees only its own skills (R16.7).
- **Pinning:** a turn pins its skill versions in its bundle.
- **Drafts and published versions:** a draft follows the library, so editing a skill means testing again. Publishing locks the versions (`skill_lock`, frozen by the AC47 trigger), so editing a skill never changes a published agent.

**Describe it, improve it.** **New agent** now offers **Describe it** (the default), **From a template** and **Start blank**.
- **How a description becomes a draft:** a hidden builder agent answers through one tool, `propose_draft`, whose arguments are the draft.
- **Checking:** the tool runs the one validator and hands any problems back, so the agent's few turns are its repair rounds.
- **Nothing is saved early:** the person sees a summary, and nothing is saved until **Use this draft**.
- **Improve my instructions** works the same way, with a suggestion shown side by side.
- **Ordinary runs:** both builders run like any other run (the default model, budgets, breaker, crash recovery). Offline, a keyword drafter produces the same shape.

**Untrusted text stays data (R14.15).** This requirement was never implemented until now.
- Every tool result now reaches the model inside `<data>` delimiters that the text can't close.
- Every prompt ends with the rule.
- 11 planted-instruction cases, run through both a tool result and a skill (22 runs), assume a model that fully obeys. Each checks that the harness still denies the call, asks a person, or enforces the limit.

## Success criteria: results

| # | Criterion | Result |
|---|---|---|
| SC1 | **AC43, automated stand-in** | ✅ Browser, by visible labels only: Skills → New skill; New agent → Describe it → Use this draft; attach the skill to the agent and a built-in skill to the drafted helper; test chat ("Used a skill", then the answer); publish; chat with it. No Markdown on any screen; axe clean |
| SC2 | **AC43 with people** | ⏳ The [tester script](../setup/tester-script.md) is ready. **M2 is declared after 2–3 testers pass it** |
| SC3 | **Load only when needed, only their own** | ✅ Unit: the prompt has names and descriptions, never the body. Integration (fake model): the agent and its helper each load their own skill; the result arrives marked as data and the transcript shows the tool's real output |
| SC4 | **AC46 (instruction-only part)** | ✅ Browser and API: an upload with injection, a URL, a base64 blob and `scripts/run.sh` is flagged *Needs a look* and *Has code: never runs*; the script is never offered or readable. An upload with a key is refused and the key never shown |
| SC5 | **R14.15 holds** | ✅ 22 cases, 0 policy violations. The gate also found that a gated tool ran on any resume value, now fixed (fail closed) |
| SC6 | **Skill versions pinned** | ✅ Integration: a skill edit makes the draft untested; publish locks; a later edit or archive leaves the published agent on its version; a queued turn keeps its versions |
| SC7 | **Describe it works, safely** | ✅ Demo and fake: a valid draft, nothing saved until accepted; `fake-sloppy` proposes an unknown tool, gets the problem back and repairs it; a model that never proposes gets a plain message. Not yet checked on the live Ollama: see below |
| SC8 | **Improve my instructions** | ✅ Browser: Keep mine changes nothing; Use the suggestion edits the draft (autosaved) |
| SC9 | **Interoperable** | ✅ Export → upload gives the same skill hash; an agent zip carries its skills; import reuses identical skills, adds new ones (scanned) and refuses a clash |
| SC10 | **Durability unchanged** | ✅ Browser: the worker running a turn that uses a skill is killed, and the skill is edited meanwhile; the turn finishes on the locked version, with one reclaim, the skill loaded once, and the screen matching the transcript |
| SC11 | Quality | ✅ Backend `make check` 526 passed; UI check (54 unit tests); browser suite 5× (results on the PR) |
| SC12 | Docs | ✅ Skills guide, agents guide, tester script, design patterns |

## Bugs found by testing

- **R14.15 was missing:** tool output reached models as plain text. Implemented for every tool result.
- **A gated tool ran on any resume value.** The pipeline never read the person's decision. A rejection cancels the run through the API, so this was unreachable, but it no longer relies on that.
- **Workers exited on a Redis timeout** when the machine slept overnight; Docker restarted them. They now back off and keep serving.
- **Migration 0010's downgrade** deleted bundle snapshots that agent versions still referenced. It only showed once a test created agents before the migration test ran.
- **nginx capped uploads at 256 KB**, which would have blocked skills and agent imports above that size.
- **A draft's stored bundle hash went stale when a skill changed.** "Tested" is now checked against today's skills, and publish re-checks it.
- **Smaller fixes:**
  - demo drafts were named "Plan Trips For assistant";
  - the coach's "no change" still offered a switch;
  - the comparison dialog was cramped.

## Decisions & trade-offs

- **Skills are locked at publish, not followed.** It matches AC47: what was tested is what runs.
- **The builder answers through a tool call,** not a separate structured-output mode, because tool calling is exactly what the L3b test proves. The validator is the judge, and its problems are the repair prompt.
- **A name clash on import refuses the import** rather than silently giving an agent someone else's skill.
- **`allowed-tools` is shown, never enforced.** It's experimental upstream, and skills never grant tools anyway.

## Known issues & follow-ups

- **M2 needs the tester sessions** (SC2): about 20 minutes each, with 2 or 3 people.
- **Not yet checked on a live model:** "Describe it" with the local Ollama (the fake model covers the same path in CI).
- **Skill scripts** run once the sandbox exists (phase 7). Sharing skills with approval is in the hosted beta.
- **Carried over:**
  - the first `v*` tag;
  - `setup.ps1` on a real Windows machine;
  - an archive button for agents.

## How to try it

```bash
./setup.sh                                  # then Skills → New skill, Agents → New agent → Describe it
make ui-e2e ARGS=tests/skills.spec.ts       # needs the test profile: the fake model
```
