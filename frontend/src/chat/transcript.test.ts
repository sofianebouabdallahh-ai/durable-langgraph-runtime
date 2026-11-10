import { describe, expect, it } from "vitest";

import { call, reply, result, RUN, RUN2, user } from "../test/fixtures";
import { chat, type ChatAction, type ChatState, initialChat, isBusy } from "./transcript";

const fold = (actions: ChatAction[], state: ChatState = initialChat) => actions.reduce(chat, state);
const m = (message: ReturnType<typeof user>): ChatAction => ({ kind: "message", message });
const seqs = (s: ChatState) => s.messages.map((x) => x.seq);

describe("messages: exactly-once, in order (AC20)", () => {
  const all = [user(1, "hi"), call(2, "calculator", "c1"), result(3, "calculator", "c1", { value: 42 }), reply(4, "42")];

  it("keeps every message once whatever the delivery: replayed, doubled, reordered", () => {
    const delivered = [all[0], all[2], all[1], all[1], all[3], all[0], all[3], all[2]].map((x) => m(x!));
    const s = fold(delivered);
    expect(seqs(s)).toEqual([1, 2, 3, 4]);
    expect(s.lastSeq).toBe(4);
  });

  it("is idempotent: a replay of what it holds returns the same state object", () => {
    const s = fold(all.map(m));
    expect(fold(all.map(m), s)).toBe(s);
  });

  it("lastSeq stops below a hole, so a reconnect asks for the missing message again", () => {
    const s = fold([m(all[0]!), m(all[1]!), m(all[3]!)]);
    expect(seqs(s)).toEqual([1, 2, 4]);
    expect(s.lastSeq).toBe(2);
    expect(chat(s, m(all[2]!)).lastSeq).toBe(4);
  });

  it("an any-order delivery of 1..N always ends with 1..N (generated orders)", () => {
    const n = 12;
    const msgs = Array.from({ length: n }, (_, i) => user(i + 1, `m${String(i)}`));
    for (let trial = 0; trial < 200; trial++) {
      let seed = trial + 1;
      const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
      const order = [...msgs, ...msgs.filter(() => rand() < 0.3)].sort(() => rand() - 0.5);
      const s = fold(order.map(m));
      expect(seqs(s)).toEqual(msgs.map((x) => x.seq));
      expect(s.lastSeq).toBe(n);
    }
  });
});

describe("the streamed draft", () => {
  it("builds from tokens and is replaced by the persisted reply, never shown twice", () => {
    let s = fold([{ kind: "sent", runId: RUN }, m(user(1, "hi")), { kind: "token", runId: RUN, text: "Hel" }, { kind: "token", runId: RUN, text: "lo" }]);
    expect(s.draft).toEqual({ runId: RUN, text: "Hello" });
    s = chat(s, m(reply(2, "Hello")));
    expect(s.draft).toBeNull();
    expect(s.messages.at(-1)?.type).toBe("assistant");
  });

  it("ignores a late token of a turn that has ended", () => {
    const s = fold([
      { kind: "turn", runId: RUN, status: "completed", reason: null },
      { kind: "token", runId: RUN, text: "late" },
    ]);
    expect(s.draft).toBeNull();
  });

  it("keeps a stopped reply's draft until the persisted partial reply replaces it", () => {
    let s = fold([{ kind: "sent", runId: RUN }, { kind: "token", runId: RUN, text: "Half a" }]);
    s = chat(s, { kind: "turn", runId: RUN, status: "cancelled", reason: "cancel_requested" });
    expect(s.draft?.text).toBe("Half a"); // no flicker between the stop and the persisted text
    s = chat(s, m(reply(2, "Half a", RUN, { interrupted: true })));
    expect(s.draft).toBeNull();
  });

  it("drops a draft the runtime made into a tool call: it was never the answer", () => {
    // qwen2.5:7b streams `save_note({...})`, or "I've sent it", and the runtime makes the
    // call instead: without this the text stayed under the card (until a reload).
    let s = fold([{ kind: "sent", runId: RUN }, { kind: "token", runId: RUN, text: 'save_note({"text": "x"})' }]);
    s = chat(s, m(call(2, "save_note", "c1", { text: "x" })));
    expect(s.draft).toBeNull();
  });

  it("a new turn's tokens start a new draft; sending clears an old one", () => {
    let s = fold([{ kind: "token", runId: RUN, text: "old" }, { kind: "token", runId: RUN2, text: "new" }]);
    expect(s.draft).toEqual({ runId: RUN2, text: "new" });
    s = chat(s, { kind: "sent", runId: RUN });
    expect(s.draft).toBeNull();
  });
});

describe("the turn's status", () => {
  it("follows the stream and says when the composer is busy", () => {
    let s = chat(initialChat, { kind: "sent", runId: RUN });
    expect(isBusy(s)).toBe(true);
    s = fold([
      { kind: "turn", runId: RUN, status: "running", reason: null },
      { kind: "turn", runId: RUN, status: "waiting_approval", reason: null },
      { kind: "turn", runId: RUN, status: "queued", reason: null },
      { kind: "turn", runId: RUN, status: "completed", reason: null },
    ], s);
    expect(s.turn?.status).toBe("completed");
    expect(isBusy(s)).toBe(false);
  });

  it("ignores late news: an earlier turn's end, or a status after this turn ended", () => {
    let s = fold([{ kind: "sent", runId: RUN2 }, { kind: "turn", runId: RUN, status: "completed", reason: null }]);
    expect(s.turn).toEqual({ runId: RUN2, status: "queued", reason: null });
    s = fold([{ kind: "turn", runId: RUN2, status: "failed", reason: "x" }, { kind: "turn", runId: RUN2, status: "running", reason: null }], s);
    expect(s.turn?.status).toBe("failed");
  });

  it("the session's view is the safety net for a lost status", () => {
    let s = chat(initialChat, { kind: "sent", runId: RUN });
    s = chat(s, { kind: "session", activeRunId: null, activeRunStatus: null });
    expect(s.turn?.status).toBe("ended");
    expect(chat(s, { kind: "session", activeRunId: null, activeRunStatus: null })).toBe(s);
    s = chat(s, { kind: "session", activeRunId: RUN2, activeRunStatus: "waiting_children" });
    expect(s.turn).toEqual({ runId: RUN2, status: "running", reason: null });
    expect(chat(s, { kind: "session", activeRunId: RUN2, activeRunStatus: "waiting_children" })).toBe(s);
    expect(chat(s, { kind: "session", activeRunId: RUN2, activeRunStatus: "waiting_approval" }).turn?.status).toBe("waiting_approval");
    expect(chat(s, { kind: "session", activeRunId: RUN2, activeRunStatus: "weird" }).turn?.status).toBe("queued");
  });
});

describe("helpers", () => {
  it("merges live progress, then the run's results", () => {
    let s = fold([
      { kind: "helper", runId: RUN, handle: "h1", agent: "researcher", task: "q", status: "running" },
      { kind: "helper", runId: RUN, handle: "h1", progress: "reading", percent: 60 },
    ]);
    expect(s.helpers.h1).toMatchObject({ agent: "researcher", status: "running", progress: "reading", percent: 60 });
    s = chat(s, { kind: "helper", runId: RUN, handle: "h1", status: "completed" });
    s = chat(s, { kind: "helpers", runId: RUN, helpers: [{ handle: "h1", agent: "researcher", task: "", status: "completed", progress: "done", percent: 100, summary: "Found it." }] });
    expect(s.helpers.h1).toMatchObject({ status: "completed", summary: "Found it.", runId: RUN });
    s = chat(s, { kind: "helper", runId: RUN, handle: "h2" });
    expect(s.helpers.h2).toMatchObject({ agent: "helper", status: "running", summary: null });
  });

  it("keeps newer live progress when the run view is older", () => {
    const s = fold([
      { kind: "helper", runId: RUN, handle: "h1", agent: "a", status: "running", progress: "step 3" },
      { kind: "helpers", runId: RUN, helpers: [{ handle: "h1", agent: "a", task: "", status: "running", progress: "step 1", percent: 10, summary: null }] },
    ]);
    expect(s.helpers.h1?.progress).toBe("step 3");
  });
});
