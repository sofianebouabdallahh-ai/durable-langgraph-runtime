/**
 * The Studio form as a pure reducer over the agent document (Pattern: Reducer).
 * Components dispatch edits; autosave sends the document; the server's validator
 * answers with issues, which `issuesFor` places next to the right field.
 */
import type { Schemas } from "../api/client";

export type AgentDocument = Schemas["AgentDocument"];
export type HelperDocument = Schemas["HelperDocument"];
export type Issue = Schemas["IssueView"];
export type Catalog = Schemas["StudioCatalog"];
export type PresetName = "quick" | "standard" | "thorough" | "custom";

type Limits = Record<string, unknown>;

export type Edit =
  | { kind: "set"; field: "display_name" | "description" | "instructions"; value: string }
  | { kind: "tool"; name: string; on: boolean }
  | { kind: "tool-cap"; name: string; cap: number | null }
  | { kind: "preset"; preset: { max_turns: number; limits: Limits } }
  | { kind: "limit"; field: "max_turns" | "max_tool_calls" | "timeout_s"; value: number }
  | { kind: "protection"; hook: string; point: string; on: boolean; helpers: boolean }
  | { kind: "add-helper"; helper: HelperDocument }
  | { kind: "helper"; index: number; helper: HelperDocument }
  | { kind: "remove-helper"; index: number }
  | { kind: "replace"; document: AgentDocument };

export function edit(doc: AgentDocument, e: Edit): AgentDocument {
  switch (e.kind) {
    case "set":
      return { ...doc, [e.field]: e.value };
    case "tool":
      return { ...doc, tools: toggleTool(doc.tools ?? [], e.name, e.on) };
    case "tool-cap":
      return {
        ...doc,
        tools: (doc.tools ?? []).map((t) => (t.name === e.name ? { name: t.name, max_calls: e.cap } : t)),
      };
    case "preset":
      return { ...doc, max_turns: e.preset.max_turns, limits: { ...(doc.limits ?? {}), ...e.preset.limits } };
    case "limit":
      return e.field === "max_turns"
        ? { ...doc, max_turns: e.value }
        : { ...doc, limits: { ...(doc.limits ?? {}), [e.field]: e.value } };
    case "protection": {
      const hooks = setHook(doc.hooks ?? {}, e.point, e.hook, e.on);
      // Tool protections cover the helpers too: their tool calls carry the same data.
      const helpers = e.helpers
        ? (doc.helpers ?? []).map((h) => ({ ...h, hooks: setHook(h.hooks ?? {}, e.point, e.hook, e.on) }))
        : doc.helpers;
      return { ...doc, hooks, helpers: helpers ?? [] };
    }
    case "add-helper":
      return { ...doc, helpers: [...(doc.helpers ?? []), e.helper] };
    case "helper":
      return { ...doc, helpers: (doc.helpers ?? []).map((h, i) => (i === e.index ? e.helper : h)) };
    case "remove-helper":
      return { ...doc, helpers: (doc.helpers ?? []).filter((_, i) => i !== e.index) };
    case "replace":
      return e.document;
  }
}

export function toggleTool<T extends { name: string; max_calls?: number | null }>(tools: T[], name: string, on: boolean): T[] {
  const has = tools.some((t) => t.name === name);
  if (on && !has) return [...tools, { name } as T];
  if (!on && has) return tools.filter((t) => t.name !== name);
  return tools;
}

function setHook(hooks: Record<string, string[]>, point: string, hook: string, on: boolean): Record<string, string[]> {
  const list = hooks[point] ?? [];
  const next = on ? (list.includes(hook) ? list : [...list, hook]) : list.filter((h) => h !== hook);
  const others = Object.entries(hooks).filter(([p]) => p !== point);
  return Object.fromEntries(next.length ? [...others, [point, next]] : others);
}

export function hasHook(hooks: Record<string, string[]> | undefined, point: string, hook: string): boolean {
  return hooks?.[point]?.includes(hook) ?? false;
}

/** Which preset the current limits are, or "custom". */
export function presetOf(doc: Pick<AgentDocument, "max_turns" | "limits">, presets: Catalog["presets"]): PresetName {
  for (const name of ["quick", "standard", "thorough"] as const) {
    const p = presets[name];
    if (!p) continue;
    const lim = doc.limits ?? {};
    if (doc.max_turns === p.max_turns && lim.max_tool_calls === p.limits.max_tool_calls && lim.timeout_s === p.limits.timeout_s) {
      return name;
    }
  }
  return "custom";
}

/** A form section's issues. `where`: "agent" or "helpers.<name>"; `fields`: prefixes. */
export function issuesFor(issues: readonly Issue[], where: string, fields: readonly string[]): Issue[] {
  return issues.filter((i) => i.where === where && fields.some((f) => (i.field ?? "") === f || (i.field ?? "").startsWith(`${f}.`)));
}

const SECTION_FIELDS = ["name", "display_name", "description", "instructions", "tools", "max_turns", "limits", "hooks", "temperature", "model"];

/** Issues no section claims: shown at the top so nothing is ever hidden. */
export function unplaced(issues: readonly Issue[], helperNames: readonly string[]): Issue[] {
  return issues.filter((i) => {
    if (i.where.startsWith("helpers.")) return !helperNames.includes(i.where.slice("helpers.".length));
    if (i.where !== "agent") return true;
    const f = i.field ?? "";
    return !SECTION_FIELDS.some((s) => f === s || f.startsWith(`${s}.`)) && !f.startsWith("helpers");
  });
}

/** "Flight Finder!" → "flight-finder", unique among `taken` (a helper's fixed id). */
export function slug(text: string, taken: readonly string[] = []): string {
  let s = text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40).replace(/-+$/g, "");
  if (!s || !/^[a-z]/.test(s)) s = s ? `helper-${s}` : "helper";
  let out = s;
  for (let n = 2; taken.includes(out); n++) out = `${s}-${String(n)}`;
  return out;
}

export function newHelper(displayName: string, taken: readonly string[], preset: { max_turns: number; limits: Limits }, toolHooks: Record<string, string[]>): HelperDocument {
  return {
    name: slug(displayName, taken),
    display_name: displayName,
    description: "",
    instructions: "You handle one focused task, given to you as your task. When you're done, call return_result with your answer.",
    model: "chat",
    temperature: 0.2,
    max_turns: preset.max_turns,
    limits: preset.limits,
    tools: [],
    hooks: toolHooks,
  };
}

/** The document to show: the draft, else the published version, else an empty shell. */
export function documentOf(agent: { name: string; display_name: string; draft: { document: AgentDocument } | null; published_document: AgentDocument | null }): AgentDocument {
  return (
    agent.draft?.document ??
    agent.published_document ?? {
      name: agent.name,
      display_name: agent.display_name,
      description: "",
      instructions: "",
      model: "chat",
      temperature: 0.2,
      max_turns: 20,
    }
  );
}
