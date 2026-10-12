# Agent definitions

One folder per **main agent**; each sub-folder is one of its **sub-agents** ([CR-004](../../docs/requirements/CR-004-agent-definitions-and-hooks.md), [CR-005](../../docs/requirements/CR-005-subagents.md)).

```
agents/
└── example/                 main agent "example"
    ├── agent.md
    └── summarizer/          sub-agent "example/summarizer" (a leaf: no folders below)
        └── agent.md
```

`agent.md` = YAML frontmatter (configuration) + Markdown body (the system prompt).

| Field | Main | Sub | Notes |
|---|---|---|---|
| `name` | required | required | kebab-case; must equal the folder name |
| `description` | required | required | for sub-agents, tells the main agent when to use it |
| `version` | required | required | bump on every change; recorded on each run |
| `model` | required | required | alias (`chat`, `planner`, `researcher`, `critic`, `synthesizer`) or `provider:model-id` |
| `temperature` | 0.2 | 0.2 | 0 – 2 |
| `max_turns` | required | required | max model calls per run; ≤ `CEILING_MODEL_CALLS` |
| `max_session_turns` | optional | — | max user messages per session |
| `limits` | optional | optional | `max_tool_calls`, `max_tokens`, `max_cost_usd`, `timeout_s`; each ≤ its server ceiling |
| `tools` | `[]` | `[]` | `- name` or `- name: {max_calls: N}`; deny by default |
| `output_schema` | optional | optional | name of a registered structured-output schema |
| `hooks` | all points | `pre_tool`, `post_tool`, `pre_model`, `post_model` | registered hook names only |

Prompt placeholders: `{{date}}`, `{{agent.name}}`, `{{tools}}`, and `{{session.title}}` (main agents only). Anything else is an error.

Check every definition with:

```bash
cd backend && uv run runtime agents validate
```

Unknown keys, unknown tools, hooks or schemas, limits above the server ceilings, a folder/name mismatch, or a nested agent inside a sub-agent all fail validation, and the services refuse to start.
