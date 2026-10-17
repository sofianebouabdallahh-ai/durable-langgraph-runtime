import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ConnectionEvent } from "./connection";
import type { StreamAction } from "./events";
import { openSessionStream } from "./sessionStream";

/** A fake EventSource: records listeners, lets the test emit events and errors. */
class FakeSource {
  static CLOSED = 2;
  readyState = 0;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  listeners = new Map<string, ((e: MessageEvent<string>) => void)[]>();
  constructor(readonly url: string) {}
  addEventListener(name: string, fn: (e: MessageEvent<string>) => void) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), fn]);
  }
  emit(name: string, data: unknown) {
    for (const fn of this.listeners.get(name) ?? []) fn({ data: JSON.stringify(data) } as MessageEvent<string>);
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
}

describe("openSessionStream", () => {
  let sources: FakeSource[];
  let actions: StreamAction[];
  let conn: ConnectionEvent["type"][];
  let lastSeq: number;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", FakeSource);
    sources = [];
    actions = [];
    conn = [];
    lastSeq = 0;
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  const open = () =>
    openSessionStream(
      "s 1",
      { onAction: (a) => actions.push(a), onConnection: (e) => conn.push(e.type), lastSeq: () => lastSeq },
      (url) => {
        const s = new FakeSource(url);
        sources.push(s);
        return s as unknown as EventSource;
      },
    );

  it("resumes from the last message held, and decodes events", () => {
    lastSeq = 7;
    const close = open();
    expect(sources[0]?.url).toBe("/api/sessions/s%201/stream?after_seq=7");
    sources[0]?.onopen?.();
    sources[0]?.emit("token", { run_id: "r", seq: null, type: "token", payload: { text: "x" } });
    sources[0]?.emit("token", "garbage");
    expect(actions).toEqual([{ kind: "token", runId: "r", text: "x" }]);
    close();
    expect(sources[0]?.closed).toBe(true);
    expect(conn).toEqual(["connect", "opened", "close"]);
  });

  it("moves at once when the server drains, from where it got to", () => {
    open();
    lastSeq = 12;
    sources[0]?.emit("reconnect", { after_seq: 12 });
    expect(sources[0]?.closed).toBe(true);
    vi.advanceTimersByTime(0);
    expect(sources[1]?.url).toContain("after_seq=12");
    expect(conn).toContain("drain");
  });

  it("lets the browser retry a dropped stream, and retries itself once it gives up", () => {
    open();
    const first = sources[0];
    if (!first) throw new Error("no source");
    first.onerror?.(); // CONNECTING: the browser retries with Last-Event-ID
    expect(sources).toHaveLength(1);
    first.readyState = FakeSource.CLOSED;
    first.onerror?.();
    vi.advanceTimersByTime(10_000);
    expect(sources).toHaveLength(2);
    expect(conn.filter((c) => c === "dropped")).toHaveLength(2);
  });

  it("doesn't reconnect after it is closed", () => {
    const close = open();
    sources[0]!.readyState = FakeSource.CLOSED;
    sources[0]?.onerror?.();
    close();
    vi.advanceTimersByTime(20_000);
    expect(sources).toHaveLength(1);
  });
});
