# Architecture decision records

Short records of significant decisions: the context, what we chose, the alternatives and the consequences. An accepted ADR is never rewritten. To change a decision, add a new ADR that supersedes it.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-repository-layout.md) | Repository layout: a monorepo split by deliverable | Accepted |
| [0002](0002-configuration-and-secrets.md) | Configuration and secrets across environments | Accepted |
| [0003](0003-agents-as-definition-files.md) | Agents as definition files; hooks as registered code | Accepted |
| [0004](0004-live-events-redis-pubsub.md) | Live events: Redis Pub/Sub as a hint, Postgres as the record | Accepted |

Requirement changes (what the system must do) are change requests in [../requirements/](../requirements/); ADRs record *how* we build it.
