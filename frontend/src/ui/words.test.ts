import { describe, expect, it } from "vitest";

import { eventLine, mcpTool, toolLabel } from "./words";

describe("eventLine", () => {
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
