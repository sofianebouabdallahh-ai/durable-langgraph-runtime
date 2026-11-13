# Architecture decision records

Short records of significant decisions: the context, what we chose, the alternatives and the consequences. An accepted ADR is never rewritten. To change a decision, add a new ADR that supersedes it.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-repository-layout.md) | Repository layout: a monorepo split by deliverable | Accepted |
| [0002](0002-configuration-and-secrets.md) | Configuration and secrets across environments | Accepted |
| [0003](0003-agents-as-definition-files.md) | Agents as definition files; hooks as registered code | Accepted |
| [0004](0004-live-events-redis-pubsub.md) | Live events: Redis Pub/Sub as a hint, Postgres as the record | Accepted |
| [0005](0005-fan-out-child-runs.md) | Fan-out: child runs for distribution, sub-agents for delegation | Accepted |
| [0006](0006-memory-across-chats.md) | Memory across chats: the runtime puts it in the prompt, scoped by the run | Accepted |
| 0007 | Reserved for phase H9 (a stronger sandbox), written on its branch | Pending |
| [0008](0008-provenance-and-skill-approval.md) | Provenance comes from fields a trusted party wrote; a skill's text needs a reader | Accepted |

Requirement changes (what the system must do) are change requests in [../requirements/](../requirements/); ADRs record *how* we build it.
