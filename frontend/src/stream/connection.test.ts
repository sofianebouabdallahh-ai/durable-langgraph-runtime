import { describe, expect, it } from "vitest";

import { backoffMs, connection, type ConnectionEvent, initialConnection, OFFLINE_AFTER } from "./connection";

const run = (events: ConnectionEvent["type"][]) =>
  events.reduce((s, type) => connection(s, { type }), initialConnection);

describe("the connection state machine", () => {
  it("connects, drops, reconnects, and goes offline after repeated failures", () => {
    expect(run(["connect"])).toEqual({ status: "connecting" });
    expect(run(["connect", "opened"])).toEqual({ status: "open" });
    expect(run(["connect", "opened", "dropped"])).toEqual({ status: "reconnecting", attempts: 1 });
    expect(run(["connect", "opened", "dropped", "dropped"])).toEqual({ status: "reconnecting", attempts: 2 });
    const offline = run(["connect", ...Array<"dropped">(OFFLINE_AFTER).fill("dropped")]);
    expect(offline.status).toBe("offline");
    expect(connection(offline, { type: "dropped" })).toMatchObject({ status: "offline", attempts: OFFLINE_AFTER + 1 });
    expect(connection(offline, { type: "opened" })).toEqual({ status: "open" });
  });

  it("a drain moves an open stream back to connecting; idle ignores everything but connect", () => {
    expect(run(["connect", "opened", "drain"])).toEqual({ status: "connecting" });
    for (const type of ["opened", "dropped", "drain"] as const) expect(run([type])).toEqual(initialConnection);
    expect(run(["connect", "close"])).toEqual(initialConnection);
    expect(run(["connect", "connect"])).toEqual({ status: "connecting" });
  });

  it("backs off exponentially with full jitter, capped at 10 s", () => {
    expect(backoffMs(1, () => 1)).toBe(500);
    expect(backoffMs(3, () => 1)).toBe(2000);
    expect(backoffMs(20, () => 1)).toBe(10_000);
    expect(backoffMs(0, () => 0.5)).toBe(250);
  });
});
