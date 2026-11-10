import { describe, expect, it } from "vitest";

import { eventLine, mcpTool, toolLabel } from "./words";

describe("eventLine", () => {
  it("says when a long chat was summarised or a step shortened (H5), and a retry (H4)", () => {
    expect(eventLine("context.compacted", { turns: 12 })).toBe("Earlier messages were summarised to make room (12 turns)");
    expect(eventLine("context.trimmed", { cleared: 3 })).toBe("Old tool results were left out of this step to make room");
    expect(eventLine("context.trimmed", { refused: true })).toContain("too long");
    expect(eventLine("run.released", { reason: "infrastructure" })).toContain("continues from the last saved step");
  });

  it("says what a tool call did, without doubling the verb", () => {
    expect(eventLine("tool.called", { tool: "calculator" })).toBe("Used Calculator");
    expect(eventLine("tool.called", { tool: "run_python" })).toBe("Ran Python");
    expect(eventLine("tool.called", { tool: "save_note" })).toBe("Saved a note");
    expect(eventLine("tool.called", {})).toBe("Used a tool");
  });
});

describe("MCP tools", () => {
  it("are named by their tool and server, not their full name", () => {
    expect(mcpTool("mcp__travel_facts__lookup")).toEqual({ server: "travel_facts", tool: "lookup" });
    expect(toolLabel("mcp__travel_facts__send_message")).toBe("Send message (travel facts)");
    expect(mcpTool("web_search")).toBeNull();
  });
});
