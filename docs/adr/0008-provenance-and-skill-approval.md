# ADR-0008 — Provenance comes from fields a trusted party wrote; a skill's text needs a reader

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-11-12 |
| **Related** | CR-003 R14.15, R14.13, R14.17, OWASP LLM01, [phase H10 plan](../plans/phase-H10.md), [phase H3 plan](../plans/phase-H3.md) (provenance), [phase L3c plan](../plans/phase-L3c.md) (skills), [ADR-0006](0006-memory-across-chats.md) (data, never instructions) |

## Context

On 2026-11-12 an external reviewer read the code at `ef7dfad`, then replayed his findings
on our own `ToolPipeline`, `RunRepository` and policy against a real Postgres. Two of the
five headline findings let a planted instruction carry data out:

1. **A planted instruction can read an address nobody gave the agent.** Since H3,
   `read_webpage` on an address that came neither from the person, nor from a search
   result in this chat, nor from an allowed site asks first. The check (`tools/policy.py`
   `_SEEN`) looked for the address in the **whole** stored `web_search` result, and that
   result carries the model's own `query`. Search for the address, then read it: the
   address is "found", and nobody is asked. The researcher helper has both tools.
2. **A skill nobody read can become system-prompt text.** Since L8, an "Always use" skill
   the scan calls `clean` goes into the prompt as plain guidance, because a small model
   skipped it as data. The scan is a list of English regexes. An imported agent's skills
   are scanned, stored and used, and no step makes a person read them.

Both findings hold against the code; the review's attack test for the first fails today.
The research for H10 settled two facts. Titles and snippets are the search engine's, but a
page can shape them (search poisoning), so only each hit's `url` is the engine's own. And
a skill *is* instructions: studies of published skills find that detecting "instructions
in data" is void for them, and that a quarter to a third carry injection. Anthropic's own
guidance is to read `SKILL.md` and its files before enabling a skill.

## Decision

1. **Provenance reads fields a trusted party wrote, never text the model wrote.**
   - `_SEEN`'s search branch matches the given address inside each hit's `url`
     (`jsonb_array_elements` over `result -> 'results'`), with the substring match that
     keeps "the model dropped a tracking parameter" working.
   - The `query`, `title` and `snippet` fields never count. An address the engine never
     returned can't qualify, whatever the model typed.
   - On the person's side the same rule holds: the check reads the `message` of the run's
     input and the `text` of their messages in the chat, not the stored JSON as text.
     *Amended 2026-11-12, after replaying the chain on a real stack:* the first version
     kept the `runs.input` branch whole ("it is the person's message"). With the scripted
     test model the input also holds the model's replies (`script`), so a scripted turn
     that searched for an address and read it was never asked. A real model's turn stores
     no script (the API refuses one), so no page could use it; a test or a reviewer
     replaying the chain could not see the fix work.
   - Child runs (R2.8) carry a model-written `input`; today only the fan-out demo makes
     them and it has no `read_webpage`. If that changes, that branch is restricted to
     root runs.
2. **A skill's text is instructions only after a person read exactly it.**
   - A new table `skill_approvals (hash REFERENCES skill_versions, approved_at, note)`;
     the API may insert, the worker may read (least privilege, as 0012).
   - `always_section` gives plain text iff the scan is clean **and** the current hash is
     approved (`trusted_text`); otherwise the skill is `<data>`, and the agent still has
     it. The skill still can't change the agent's task, tools, limits or approvals: the
     app enforces those.
   - **Who approves what:** built-ins at `sync_builtins`; a skill created or edited in the
     Studio at save, since the person wrote the text; an upload or an import **not until
     the person opens it**, sees its text and the scan's findings, and clicks "I've read
     this" (`POST /skills/{id}/approve`, audited with the hash).
   - **Any edit makes a new hash, so the approval lapses with the text**, as H1's approval
     lapses with the arguments.
3. **The scan stays informational.** Its header, `always_section`'s docstring and the
   skill page say the same thing: the scan informs, the approval decides. French and
   Spanish phrasings may join the `INJECTION` list as hygiene, never as a criterion.

## Alternatives considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Match the address in each hit's `url`** (chosen) | The engine wrote it; one SQL query; a dropped tracking parameter still passes | A poisoned result page could carry the address in its `url` (it then shows in the result the person can see) | Chosen |
| **Keep the whole-blob search, strip the `query` first** | Smallest change | Titles and snippets are still shapeable by a page; the next field added to the result re-opens the hole | Rejected: search the shape, not the text |
| **An LLM-based skill scan** | Reads any language and intent | A model judging instructions is the thing being attacked; the studies show detection is void when the content *is* instructions; it can't be the boundary | Rejected as a boundary; nothing stops adding it as a hint |
| **Multilingual regexes** | Cheap; catches the obvious French or Spanish phrasing | A regex list is hygiene: it tells a reader where to look, it can't say a skill is safe | Kept as optional hygiene, never a criterion |
| **Refuse imported skills until re-typed in the Studio** | No approval table | Loses the Agent Skills format and sharing; the person still has to read what they type | Rejected |
| **Approve by skill name, not version hash** | One click covers future edits | An edit, or an import under a known name, inherits an approval given for other text | Rejected: the approval must lapse with the text |

## Consequences

- **An imported skill works as data until someone reads it.** The agent can load it and
  follow it like any tool result; it can't become the system prompt. An imported agent's
  draft lists the skills "waiting for your review". A small model that skips data (the
  reason L8 made clean skills plain text) is less helped by an unread skill; reading it is
  one click.
- **A search query can't launder an address.** Measured by H10's criterion 1: search for
  an address, then read it → approval asked, nothing fetched, through the researcher
  helper too; an address from a result, with or without a dropped parameter, still passes.
  The reviewer's attack test fails and his correctif test passes.
- **A skill nobody read stays data.** Measured by H10's criterion 2: an imported trapped
  skill, in English or French, reaches the prompt inside `<data>` until a person approves
  exactly its text, and is data again after an edit; built-in and Studio-written skills
  are unaffected.
- **One more table, one more query per turn with "Always use" skills** (the approvals of
  the pinned hashes). The API's role gains INSERT on `skill_approvals`, the worker's
  SELECT; nothing can UPDATE or DELETE a row.
- **The scan's findings keep their meaning:** `block` still refuses a save (a secret),
  `review` still informs. What changes is that `clean` no longer promotes.
- **Rolling deploys:** a worker of the release before doesn't know `skill_approvals` and
  gives a clean skill plain text, as it did; the newer worker is stricter. Nothing breaks,
  and the window closes with the deploy.
