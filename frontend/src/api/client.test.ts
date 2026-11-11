import { describe, expect, it } from "vitest";

import { ApiError, noContent, unwrap } from "./client";

const answer = (status: number, error?: unknown) => Promise.resolve({ error, response: new Response(null, { status }) });

describe("noContent", () => {
  it("resolves a 204, which unwrap would take for a failure (no body): a delete that worked", async () => {
    await expect(noContent(answer(204))).resolves.toBeUndefined();
    await expect(unwrap(answer(204))).rejects.toBeInstanceOf(ApiError);
  });

  it("throws like unwrap when the call failed", async () => {
    const failed = noContent(answer(404, { type: "about:blank", title: "Note not found", status: 404 }));
    await expect(failed).rejects.toMatchObject({ status: 404 });
  });
});
