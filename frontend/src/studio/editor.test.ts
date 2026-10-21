import { describe, expect, it } from "vitest";

import { type AgentDocument, type Catalog, documentOf, edit, hasHook, issuesFor, newHelper, presetOf, slug, suggestTools, unplaced } from "./editor";

const doc: AgentDocument = {
  name: "trip-planner",
  display_name: "Trip planner",
  description: "",
  instructions: "Plan trips.",
  model: "chat",
  temperature: 0.2,
  max_turns: 20,
  limits: { max_tool_calls: 30, timeout_s: 300 },
  tools: [],
  hooks: {},
  helpers: [],
};
const presets: Catalog["presets"] = {
  quick: { max_turns: 8, limits: { max_tool_calls: 10, timeout_s: 120 } },
  standard: { max_turns: 20, limits: { max_tool_calls: 30, timeout_s: 300 } },
  thorough: { max_turns: 40, limits: { max_tool_calls: 50, timeout_s: 600 } },
  helper: { max_turns: 6, limits: { max_tool_calls: 8, timeout_s: 180 } },
};

describe("the form reducer", () => {
  it("edits fields and tools, idempotently, without mutating the input", () => {
    let d = edit(doc, { kind: "set", field: "description", value: "Plans trips." });
    d = edit(d, { kind: "tool", name: "search", on: true });
    d = edit(d, { kind: "tool", name: "search", on: true });
    d = edit(d, { kind: "tool-cap", name: "search", cap: 3 });
    expect(d.tools).toEqual([{ name: "search", max_calls: 3 }]);
    expect(edit(d, { kind: "tool", name: "search", on: false }).tools).toEqual([]);
    expect(doc.tools).toEqual([]); // pure
  });

  it("knows which preset the numbers are, and custom numbers", () => {
    expect(presetOf(doc, presets)).toBe("standard");
    const quick = edit(doc, { kind: "preset", preset: presets.quick! });
    expect(presetOf(quick, presets)).toBe("quick");
    const custom = edit(quick, { kind: "limit", field: "timeout_s", value: 240 });
    expect(presetOf(custom, presets)).toBe("custom");
    expect(edit(custom, { kind: "limit", field: "max_turns", value: 5 }).max_turns).toBe(5);
  });

  it("turns protections on and off, for the helpers too when they protect tool data", () => {
    let d = edit(doc, { kind: "add-helper", helper: newHelper("Scout", [], presets.helper!, {}) });
    d = edit(d, { kind: "protection", hook: "redact_secrets_in_args", point: "pre_tool", on: true, helpers: true });
    expect(hasHook(d.hooks, "pre_tool", "redact_secrets_in_args")).toBe(true);
    expect(hasHook(d.helpers?.[0]?.hooks, "pre_tool", "redact_secrets_in_args")).toBe(true);
    d = edit(d, { kind: "protection", hook: "summarize_session", point: "session_end", on: true, helpers: false });
    expect(d.helpers?.[0]?.hooks).toEqual({ pre_tool: ["redact_secrets_in_args"] });
    d = edit(d, { kind: "protection", hook: "redact_secrets_in_args", point: "pre_tool", on: false, helpers: true });
    expect(d.hooks).toEqual({ session_end: ["summarize_session"] }); // an empty point disappears
    expect(d.helpers?.[0]?.hooks).toEqual({});
  });

  it("adds, edits and removes helpers, each with a unique fixed id", () => {
    const a = newHelper("Flight finder!", [], presets.helper!, { post_tool: ["redact_secrets_in_result"] });
    expect(a).toMatchObject({ name: "flight-finder", display_name: "Flight finder!", max_turns: 6, hooks: { post_tool: ["redact_secrets_in_result"] } });
    let d = edit(doc, { kind: "add-helper", helper: a });
    d = edit(d, { kind: "add-helper", helper: newHelper("Flight finder", ["flight-finder"], presets.helper!, {}) });
    expect(d.helpers?.map((h) => h.name)).toEqual(["flight-finder", "flight-finder-2"]);
    d = edit(d, { kind: "helper", index: 1, helper: { ...d.helpers![1]!, description: "Second" } });
    expect(d.helpers?.[1]?.description).toBe("Second");
    expect(edit(d, { kind: "remove-helper", index: 0 }).helpers?.map((h) => h.name)).toEqual(["flight-finder-2"]);
    expect(edit(d, { kind: "replace", document: doc })).toBe(doc);
  });
});

describe("issues in the form", () => {
  const issues = [
    { where: "agent", field: "description", message: "Required." },
    { where: "agent", field: "limits.timeout_s", message: "Too high." },
    { where: "helpers.scout", field: "tools", message: "Needs approval." },
    { where: "agent", field: "weird", message: "Something else." },
    { where: "helpers.gone", field: "name", message: "Old helper." },
  ];
  it("go next to their field, and anything unplaced is still shown", () => {
    expect(issuesFor(issues, "agent", ["description"]).map((i) => i.message)).toEqual(["Required."]);
    expect(issuesFor(issues, "agent", ["limits"]).map((i) => i.message)).toEqual(["Too high."]);
    expect(issuesFor(issues, "helpers.scout", ["tools"])).toHaveLength(1);
    expect(unplaced(issues, ["scout"]).map((i) => i.message)).toEqual(["Something else.", "Old helper."]);
  });
});

describe("ids and documents", () => {
  it("makes kebab-case ids that start with a letter", () => {
    expect(slug("Flight Finder")).toBe("flight-finder");
    expect(slug("  ")).toBe("helper");
    expect(slug("42 things")).toBe("helper-42-things");
    expect(slug("a", ["a", "a-2"])).toBe("a-3");
  });
  it("shows the draft, else the published version, else an empty shell", () => {
    expect(documentOf({ name: "x", display_name: "X", draft: { document: doc }, published_document: null })).toBe(doc);
    expect(documentOf({ name: "x", display_name: "X", draft: null, published_document: doc })).toBe(doc);
    expect(documentOf({ name: "x", display_name: "X", draft: null, published_document: null })).toMatchObject({ name: "x", instructions: "" });
  });
});

describe("skills in the form", () => {
  it("sets the agent's skills, and a new helper starts with none", () => {
    const next = edit(doc, { kind: "skills", value: ["trip-planning"], always: [] });
    expect(next.skills).toEqual(["trip-planning"]);
    expect(doc.skills).toBeUndefined(); // the reducer is pure
    expect(newHelper("Scout", [], presets.quick ?? { max_turns: 1, limits: {} }, {}).skills).toEqual([]);
  });

  it("keeps Always use only for skills still attached", () => {
    const both = edit(doc, { kind: "skills", value: ["trip-planning", "plain-writing"], always: ["trip-planning"] });
    expect(both.always_skills).toEqual(["trip-planning"]);
    const removed = edit(both, { kind: "skills", value: ["plain-writing"], always: ["trip-planning"] });
    expect(removed.always_skills).toEqual([]);
  });

  it("places a skill issue in the Skills section, not at the top", () => {
    const issue = { where: "agent", field: "skills", message: "There's no skill called “x”" };
    expect(issuesFor([issue], "agent", ["skills"])).toEqual([issue]);
    expect(unplaced([issue], [])).toEqual([]);
  });
});

describe("tools a helper's description suggests", () => {
  const allowed = ["web_search", "read_webpage", "run_python", "workspace_files", "save_note"];
  it("finds them from plain words, searching with reading", () => {
    expect(suggestTools("Searches the web for current ferry times and prices", allowed)).toEqual(["web_search", "read_webpage", "run_python"]);
    expect(suggestTools("Works out averages from a CSV file", allowed)).toEqual(["run_python", "workspace_files"]);
  });
  it("suggests nothing it may not use, or for a writer", () => {
    expect(suggestTools("Searches the web", ["run_python"])).toEqual([]);
    expect(suggestTools("Rewrites text in a friendly tone", allowed)).toEqual([]);
  });
});
