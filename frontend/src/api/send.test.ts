import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./client";
import { sendMessage, SEND_ATTEMPTS } from "./send";

const accepted = { message_id: "m", seq: 1, run_id: "r" };
const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": status >= 400 ? "application/problem+json" : "application/json" } });

describe("sendMessage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("retries a transient failure with the same key, so the server returns one turn", async () => {
    const keys: (string | null)[] = [];
    const responses = [reply(502, { status: 502 }), new TypeError("connection reset"), reply(202, accepted)];
    vi.stubGlobal("fetch", vi.fn((req: Request) => {
      keys.push(req.headers.get("idempotency-key"));
      const next = responses.shift();
      return next instanceof Error ? Promise.reject(next) : Promise.resolve(next);
    }));
    await expect(sendMessage("s1", "hi", { key: "k-1", sleep: () => Promise.resolve() })).resolves.toEqual(accepted);
    expect(keys).toEqual(["k-1", "k-1", "k-1"]);
  });

  it("doesn't retry what isn't transient, and gives up after a few attempts", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(reply(409, { type: "x/turn-active", status: 409 }))));
    await expect(sendMessage("s1", "hi", { sleep: () => Promise.resolve() })).rejects.toBeInstanceOf(ApiError);
    expect(fetch).toHaveBeenCalledTimes(1);
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(reply(503, { status: 503 }))));
    await expect(sendMessage("s1", "hi", { sleep: () => Promise.resolve() })).rejects.toMatchObject({ status: 503 });
    expect(fetch).toHaveBeenCalledTimes(SEND_ATTEMPTS);
  });

  it("doesn't retry while every agent is stopped (the kill switch): it says so at once", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(reply(503, { type: "https://x/problems/paused", status: 503 }))));
    await expect(sendMessage("s1", "hi", { sleep: () => Promise.resolve() })).rejects.toMatchObject({ status: 503 });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
