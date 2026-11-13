import { describe, expect, it } from "vitest";

import { parseMessage } from "./messages";

const view = (type: string, content: Record<string, unknown>) => ({
  seq: 1, message_id: "m", run_id: null, type, role: "x", content, created_at: "t",
});

describe("parseMessage", () => {
  it("narrows each type's content, with safe defaults for missing fields", () => {
    expect(parseMessage(view("user", { text: "hi" }))).toMatchObject({ type: "user", text: "hi", runId: null });
    expect(parseMessage(view("assistant", { text: "a", interrupted: true }))).toMatchObject({ model: null, interrupted: true, budgetLimited: false });
    expect(parseMessage(view("tool_call", { tool: "search", args: [1] }))).toMatchObject({ toolCallId: "", args: {} });
    expect(parseMessage(view("tool_result", { error: "nope" }))).toMatchObject({ error: "nope", cached: false, durationMs: null });
    expect(parseMessage(view("interrupt", { interrupt_type: "tool_approval", payload: { tool: "notify", args: { to: "x" }, reason: "r", hidden: 2 } })))
      .toMatchObject({ kind: "tool_approval", tool: "notify", args: { to: "x" }, reason: "r", hidden: 2 });
    expect(parseMessage(view("interrupt", {}))).toMatchObject({ kind: null, tool: null, args: {}, hidden: 0 });
    expect(parseMessage(view("approval", { decision: "approve" }))).toMatchObject({ decision: "approve", reason: null });
    expect(parseMessage(view("approval", { decision: "maybe" }))).toMatchObject({ decision: "reject" });
    expect(parseMessage(view("error", { reason: "x", budget_limited: true }))).toMatchObject({ reason: "x", budgetLimited: true, canRetry: false });
    expect(parseMessage(view("error", { reason: "error", can_retry: true }))).toMatchObject({ canRetry: true });
    expect(parseMessage(view("system", {}))).toMatchObject({ text: "", retry: null });
    expect(parseMessage(view("system", { text: "Tried again", retry: 2 }))).toMatchObject({ retry: 2 });
    expect(parseMessage(view("future", {}))).toBeNull();
  });
});
