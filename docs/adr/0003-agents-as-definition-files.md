# ADR-0003 — Agents as definition files; hooks as registered code

| | |
|---|---|
| **Status** | Accepted (2026-10-11, with CR-004) |
| **Date** | 2026-10-11 |
| **Amends** | [ADR-0001](0001-repository-layout.md): the `backend/src/agents/` entry |
| **Amended by** | [CR-005](../requirements/CR-005-subagents.md): one folder per agent (`agents/<name>/agent.md`); sub-agents are leaf sub-folders |

## Context

CR-004 makes agents declarative: one `.agent.md` file per agent (frontmatter configuration + prompt body), with hooks referenced by name. ADR-0001 had planned a Python package `backend/src/agents/` for agent code. Most of what that package would have held (prompts, tool lists, limits) is now data, and the rest is either reusable hooks or multi-step workflow graphs.

## Decision

```
backend/
├── agents/                      agent definitions (data, reviewed like code)
│   ├── chat.agent.md
│   ├── planner.agent.md · researcher.agent.md · critic.agent.md · synthesizer.agent.md
│   └── README.md                the frontmatter schema, with an example
└── src/
    ├── runtime/
    │   ├── agents/              loader, schema, validation, snapshotting, middleware builder
    │   └── hooks/               hook registry + built-in hooks
    └── workflows/
        └── research/            the research graph (routing, fan-out); its nodes name agent files
```

1. **Definitions are data, outside `src/`.** They aren't importable code. They ship in the worker image as package data (`backend/agents/` is in the Docker build context, ADR-0001 rule 1).
2. **Folder name `agents/` (plural)**, matching the common convention (`.github/agents/`, `.claude/agents/`) and the rest of this repo (`migrations/`, `tests/`).
3. **File suffix `.agent.md`**, so tooling (and people) can tell agent files from other Markdown, such as the folder's `README.md`.
4. **Hooks are Python in `runtime/hooks/`, never inline in definitions.** Definitions reference hooks by name only, so editing Markdown can't execute code.
5. **Workflows are Python in `src/workflows/`.** Control flow (routing, fan-out, loops) stays in tested code; behaviour (prompt, tools, limits) lives in the definitions.

## Alternatives considered

- **Everything in Python** (the original plan). Prompts and limits would be harder to review and diff, and couldn't be listed by the API without importing code.
- **One YAML file per agent, with the prompt as a string.** Long prompts in YAML strings are awkward to read and diff. Markdown with frontmatter is what Copilot custom agents and Claude Code subagents use.
- **Hooks as shell commands in the definition** (as in Claude Code or Copilot CLI hook config). Flexible, but every definition would become an execution surface. Rejected for v1.0 (CR-004 §6).

## Consequences

- ADR-0001's `backend/src/agents/` row is replaced by the layout above. The spec mapping `examples/research` → `backend/src/workflows/research` + `backend/agents/*.agent.md`.
- `runtime agents validate` runs in CI, so a broken definition fails the PR, not a deploy.
