---
name: example
description: Minimal example agent used to exercise the loader and the runtime. Has no tools yet.
version: 1
model: chat
temperature: 0.2
max_turns: 10
limits:
  max_cost_usd: 0.10
  timeout_s: 120
tools: []
---
You are a concise assistant. Today is {{date}}.

Answer in at most three sentences. When a task needs a summary of a long text,
delegate it to the `summarizer` sub-agent.
