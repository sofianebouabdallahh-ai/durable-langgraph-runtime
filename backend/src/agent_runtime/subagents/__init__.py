"""Sub-agents (CR-005): leaf agents a main agent runs in-process, durably.

- `store`: the `subagent_invocations` table (fenced; one row per handle)
- `orchestrator`: spawn, track, limit, cancel, stop, recover (Supervisor)
- `tools`: the six harness-granted tools
"""
