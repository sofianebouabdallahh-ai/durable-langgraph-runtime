import { describe, expect, it } from "vitest";

import type { Message } from "../api/messages";
import { call, msg, reply, result, RUN, RUN2, user } from "../test/fixtures";
import { pendingApproval, turns } from "./selectors";
import { chat, type ChatState, initialChat } from "./transcript";

const state = (messages: Message[], extra: Partial<ChatState> = {}): ChatState => ({
  ...messages.reduce((s, message) => chat(s, { kind: "message", message }), initialChat),
  ...extra,
});

describe("turns", () => {
  it("groups by turn and pairs each tool call with its result", () => {
    const s = state([
      user(1, "6*7?"), msg(2, "system", { text: "ctx" }), call(3, "calculator", "c1"), result(4, "calculator", "c1", { value: 42 }), reply(5, "42"),
      user(6, "again", RUN2), call(7, "search", "c2", {}, RUN2),
    ]);
    const [first, second] = turns(s);
    expect(first?.user?.text).toBe("6*7?");
    expect(first?.items.map((i) => i.kind)).toEqual(["tool", "text"]); // system hidden
    const tool = first?.items[0];
    expect(tool?.kind === "tool" && tool.result?.result).toEqual({ value: 42 });
    expect(second?.items[0]?.kind === "tool" && second.items[0].result).toBeNull(); // still running
  });

  it("shows a sent turn before its first message arrives, and the draft in its turn", () => {
    const s: ChatState = { ...initialChat, turn: { runId: RUN, status: "queued", reason: null }, draft: { runId: RUN, text: "typing" } };
    expect(turns(s)).toEqual([{ runId: RUN, user: null, items: [], draft: "typing", active: true }]);
    expect(turns({ ...initialChat, draft: { runId: RUN2, text: "x" } })[0]?.active).toBe(false);
  });

  it("shows helpers as one group instead of their tool calls, even without the tool call", () => {
    const helper = { handle: "h", runId: RUN, agent: "researcher", task: "", status: "running" as const, progress: null, percent: null, summary: null };
    const s = state([user(1, "research"), call(2, "spawn_subagent", "s1"), call(3, "spawn_subagent", "s2"), call(4, "wait_subagents", "w")], { helpers: { h: helper } });
    expect(turns(s)[0]?.items.map((i) => i.kind)).toEqual(["helpers"]);
    const live = { ...initialChat, turn: { runId: RUN, status: "running" as const, reason: null }, helpers: { h: helper } };
    expect(turns(live)[0]?.items.map((i) => i.kind)).toEqual(["helpers"]);
    expect(turns(state([call(1, "wait_subagents", "w")]))[0]?.items).toEqual([]); // no helpers known yet
  });

  it("pairs an approval request with its decision; errors and empty replies", () => {
    const s = state([
      user(1, "notify"), call(2, "notify", "n1"), msg(3, "interrupt", { kind: "tool_approval", tool: "notify", args: {}, reason: null }),
      msg(4, "approval", { decision: "approve", reason: null }), reply(5, "  "), msg(6, "error", { reason: "boom", budgetLimited: false }),
    ]);
    const kinds = turns(s)[0]?.items.map((i) => i.kind);
    expect(kinds).toEqual(["tool", "approval-request", "error"]);
    const request = turns(s)[0]?.items[1];
    expect(request?.kind === "approval-request" && request.decided?.decision).toBe("approve");
    expect(turns(state([msg(1, "user", { text: "x" }, null as unknown as string)]))[0]?.runId).toBe("none");
  });
});

describe("pendingApproval", () => {
  const ask = msg(3, "interrupt", { kind: "tool_approval", tool: "notify", args: { to: "ops" }, reason: null });
  it("is the request the waiting turn hasn't had decided", () => {
    const waiting = { runId: RUN, status: "waiting_approval" as const, reason: null };
    expect(pendingApproval(state([user(1, "x"), ask], { turn: waiting }))?.messageId).toBe(ask.messageId);
    expect(pendingApproval(state([user(1, "x"), ask, msg(4, "approval", { decision: "reject", reason: "no" })], { turn: waiting }))).toBeNull();
    expect(pendingApproval(state([user(1, "x"), ask], { turn: { ...waiting, status: "running" } }))).toBeNull();
    expect(pendingApproval(state([user(1, "x", RUN2), msg(2, "interrupt", { kind: null, tool: null, args: {}, reason: null }, RUN2)], { turn: waiting }))).toBeNull();
  });
});
