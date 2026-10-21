import { describe, expect, it } from "vitest";

import { changes } from "./AuditPage";

describe("changes", () => {
  it("shows what differs, as before → after", () => {
    expect(changes({ models: ["gpt-x"], kind: "openai" }, { models: ["gpt-y"], kind: "openai" })).toEqual(['models: ["gpt-x"] → ["gpt-y"]']);
  });
  it("shows new values for a creation, and old ones for a removal", () => {
    expect(changes(null, { key: "set", version: 2 })).toEqual(["key: set", "version: 2"]);
    expect(changes({ display_name: "Old" }, null)).toEqual(["display_name was Old"]);
    expect(changes(null, null)).toEqual([]);
  });
});
