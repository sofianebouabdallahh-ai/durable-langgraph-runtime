---
name: napper
description: Test sub-agent with a 2-second timeout, for exercising sub-agent timeouts.
version: 1
model: chat
max_turns: 4
limits:
  timeout_s: 2
tools:
  - save_note
---
You keep notes, slowly.
