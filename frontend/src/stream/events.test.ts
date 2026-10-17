import { describe, expect, it } from "vitest";

import { decode } from "./events";

const wire = (type: string, payload: Record<string, unknown>, seq: number | null = null) =>
  JSON.stringify({ run_id: "r1", seq, after_seq: 0, ts: "2026-10-17T12:00:00Z", epoch: 1, type, payload });

describe("decode", () => {
  it("decodes a persisted message", () => {
    const data = wire("message.created", { seq: 3, message_id: "m3", run_id: "r1", type: "tool_result", role: "tool", created_at: "t",
      content: { tool_call_id: "c1", tool: "calculator", result: { value: 42 }, cached: true, duration_ms: 3 } }, 3);
    expect(decode("message.created", data)).toEqual({ kind: "message", message: {
      seq: 3, messageId: "m3", runId: "r1", createdAt: "t", type: "tool_result", toolCallId: "c1", tool: "calculator",
      result: { value: 42 }, error: null, cached: true, durationMs: 3 } });
  });

  it("decodes transient tokens, turn status and helpers", () => {
    expect(decode("token", wire("token", { text: "Hi" }))).toEqual({ kind: "token", runId: "r1", text: "Hi" });
    expect(decode("turn.status", wire("turn.status", { run_id: "r2", status: "waiting_approval", reason: null }))).toEqual(
      { kind: "turn", runId: "r2", status: "waiting_approval", reason: null });
    expect(decode("subagent.spawned", wire("subagent.spawned", { handle: "h", agent: "researcher", task: "q" }))).toEqual(
      { kind: "helper", runId: "r1", handle: "h", agent: "researcher", task: "q", status: "running" });
    expect(decode("subagent.progress", wire("subagent.progress", { handle: "h", message: "reading", percent: 50 }))).toEqual(
      { kind: "helper", runId: "r1", handle: "h", progress: "reading", percent: 50 });
    expect(decode("subagent.completed", wire("subagent.completed", { handle: "h", status: "timed_out" }))).toMatchObject({ status: "timed_out" });
  });

  it("drops what it can't use: bad JSON, unknown names and types, wrong shapes", () => {
    expect(decode("token", "{not json")).toBeNull();
    expect(decode("token", '"a string"')).toBeNull();
    expect(decode("token", JSON.stringify({ run_id: "r", payload: null }))).toBeNull();
    expect(decode("mystery", wire("mystery", {}))).toBeNull();
    expect(decode("token", wire("token", { text: 3 }))).toBeNull();
    expect(decode("turn.status", wire("turn.status", { status: "exploded" }))).toBeNull();
    expect(decode("subagent.progress", wire("subagent.progress", { message: "no handle" }))).toBeNull();
    expect(decode("message.created", wire("message.created", { type: "hologram", content: {} }))).toBeNull();
  });
});
