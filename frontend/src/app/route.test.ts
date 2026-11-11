import { describe, expect, it } from "vitest";

import { href, parse } from "./route";

describe("routes", () => {
  it("an agent's memory has its own address (H8), and the agent page keeps its own", () => {
    expect(parse("#/agents/chat/memory")).toEqual({ page: "agent", name: "chat", section: "memory" });
    expect(parse("#/agents/chat")).toEqual({ page: "agent", name: "chat" });
    expect(parse("#/agents")).toEqual({ page: "agents" });
    expect(href({ page: "agent", name: "chat", section: "memory" })).toBe("#/agents/chat/memory");
    expect(href({ page: "agent", name: "trip-planner" })).toBe("#/agents/trip-planner");
  });
});
