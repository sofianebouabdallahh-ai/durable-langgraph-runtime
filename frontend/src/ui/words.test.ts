import { describe, expect, it } from "vitest";

import { eventLine } from "./words";

describe("eventLine", () => {
  it("says what a tool call did, without doubling the verb", () => {
    expect(eventLine("tool.called", { tool: "calculator" })).toBe("Used Calculator");
    expect(eventLine("tool.called", { tool: "run_python" })).toBe("Ran Python");
    expect(eventLine("tool.called", { tool: "save_note" })).toBe("Saved a note");
    expect(eventLine("tool.called", {})).toBe("Used a tool");
  });
});
