import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { reportError } from "./errors";

describe("reportError", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the error once, with the failed call's request id, and never throws", () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 202 }));
    vi.stubGlobal("fetch", fetch);
    window.location.hash = "#/activity";
    const error = new ApiError(500, { detail: "boom" }, "req-123");
    reportError("unhandledrejection", error);
    reportError("unhandledrejection", error); // the same one: once
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/client-errors");
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body).toMatchObject({ kind: "unhandledrejection", message: "ApiError: boom", route: "#/activity", failed_request_id: "req-123" });

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    expect(() => {
      reportError("error", new Error("another"));
    }).not.toThrow();
  });
});
