/** The Studio form's sections. Presentational: they render a document and dispatch edits. */
import { Bot, ChevronDown, Cpu, Gauge, Plus, ShieldCheck, Sparkles, Trash2, Users, Wrench } from "lucide-react";
import { type Dispatch, useState } from "react";

import { ToolIcon } from "../ui/icons";
import { Avatar, Button, Pill } from "../ui/primitives";
import { Issues, Section, Segmented, Switch, TextArea, TextField } from "../ui/form";
import {
  type AgentDocument,
  type Catalog,
  type Edit,
  type HelperDocument,
  hasHook,
  type Issue,
  issuesFor,
  newHelper,
  presetOf,
  type PresetName,
} from "./editor";

interface Props {
  doc: AgentDocument;
  issues: readonly Issue[];
  dispatch: Dispatch<Edit>;
  catalog: Catalog;
  readOnly: boolean;
}

const PLACEHOLDER_LABELS: Record<string, string> = {
  date: "Today's date",
  tools: "Its tools",
  "agent.name": "Its name",
  "session.title": "The chat's title",
};

export function BasicsSection({ doc, issues, dispatch, readOnly }: Props) {
  return (
    <Section title="Basics" description="What people see when they pick this agent." icon={<Bot aria-hidden className="size-4" />} testId="section-basics">
      <div className="grid gap-4">
        <TextField
          label="Name"
          value={doc.display_name ?? ""}
          maxLength={60}
          disabled={readOnly}
          onChange={(e) => {
            dispatch({ kind: "set", field: "display_name", value: e.target.value });
          }}
          hint={
            <>
              Its id is <code className="font-mono">{doc.name}</code> (fixed, used by chats and exports).
            </>
          }
          issues={issuesFor(issues, "agent", ["display_name", "name"])}
        />
        <TextArea
          label="What is it for?"
          rows={2}
          maxLength={500}
          placeholder="Plans trips: finds flights and hotels, and builds a day-by-day plan."
          value={doc.description}
          disabled={readOnly}
          onChange={(e) => {
            dispatch({ kind: "set", field: "description", value: e.target.value });
          }}
          hint="One or two sentences. It also tells other agents when to hand work to it."
          issues={issuesFor(issues, "agent", ["description"])}
        />
      </div>
    </Section>
  );
}

export function InstructionsSection({ doc, issues, dispatch, catalog, readOnly }: Props) {
  const insert = (key: string) => {
    dispatch({ kind: "set", field: "instructions", value: `${doc.instructions}{{${key}}}` });
  };
  return (
    <Section
      title="Instructions"
      description="How it works, how it answers, and what it never does. Write as if briefing a new colleague."
      icon={<Sparkles aria-hidden className="size-4" />}
      testId="section-instructions"
    >
      <TextArea
        label="Instructions"
        rows={12}
        maxLength={20000}
        value={doc.instructions}
        disabled={readOnly}
        className="min-h-56 font-[450]"
        onChange={(e) => {
          dispatch({ kind: "set", field: "instructions", value: e.target.value });
        }}
        issues={issuesFor(issues, "agent", ["instructions"])}
        hint={`${String(doc.instructions.length)} / 20,000 characters`}
      />
      {!readOnly && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-stone-500">
          Insert:
          {(catalog.placeholders.agent ?? []).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => {
                insert(p);
              }}
              className="rounded-full border border-stone-200 px-2.5 py-1 text-stone-700 transition hover:border-sun-300 hover:bg-sun-50 dark:border-stone-700 dark:text-stone-300 dark:hover:bg-stone-800"
            >
              {PLACEHOLDER_LABELS[p] ?? p}
            </button>
          ))}
        </div>
      )}
    </Section>
  );
}

function ToolCards({
  selected,
  onToggle,
  onCap,
  catalog,
  forHelper,
  readOnly,
}: {
  selected: readonly { name: string; max_calls?: number | null }[];
  onToggle: (name: string, on: boolean) => void;
  onCap?: (name: string, cap: number | null) => void;
  catalog: Catalog;
  forHelper: boolean;
  readOnly: boolean;
}) {
  return (
    <div className="grid gap-2.5 sm:grid-cols-2">
      {catalog.tools
        .filter((t) => !forHelper || t.helpers_allowed)
        .map((t) => {
          const chosen = selected.find((s) => s.name === t.name);
          return (
            <div
              key={t.name}
              className={`rounded-xl border p-3.5 transition ${chosen ? "border-stone-900 bg-stone-50 dark:border-sun-500/60 dark:bg-sun-500/5" : "border-stone-200 dark:border-stone-700"}`}
              data-testid={`tool-option-${t.name}`}
            >
              <div className="flex items-start gap-3">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-stone-100 text-stone-700 dark:bg-stone-800 dark:text-stone-300">
                  <ToolIcon tool={t.name} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-sm font-medium">{t.label}</span>
                    {t.asks_first && <Pill tone="amber">Asks you first</Pill>}
                  </div>
                  <p className="mt-0.5 text-[13px] text-stone-500 dark:text-stone-400">{t.description}</p>
                </div>
                <Switch
                  checked={Boolean(chosen)}
                  disabled={readOnly}
                  onChange={(on) => {
                    onToggle(t.name, on);
                  }}
                  label={`Use ${t.label}`}
                />
              </div>
              {chosen && onCap && (
                <label className="mt-2.5 flex items-center gap-2 pl-11 text-xs text-stone-500">
                  At most
                  <input
                    type="number"
                    min={1}
                    max={catalog.ceilings.max_tool_calls}
                    placeholder="any"
                    value={chosen.max_calls ?? ""}
                    disabled={readOnly}
                    onChange={(e) => {
                      onCap(t.name, e.target.value ? Number(e.target.value) : null);
                    }}
                    className="w-16 rounded-lg border border-stone-200 bg-white px-2 py-1 text-stone-800 dark:border-stone-700 dark:bg-stone-950 dark:text-stone-200"
                  />
                  times per message
                </label>
              )}
            </div>
          );
        })}
    </div>
  );
}

export function ToolsSection({ doc, issues, dispatch, catalog, readOnly }: Props) {
  return (
    <Section title="Tools" description="What it can use. Tools that reach people always ask you first." icon={<Wrench aria-hidden className="size-4" />} testId="section-tools">
      <ToolCards
        selected={doc.tools ?? []}
        catalog={catalog}
        forHelper={false}
        readOnly={readOnly}
        onToggle={(name, on) => {
          dispatch({ kind: "tool", name, on });
        }}
        onCap={(name, cap) => {
          dispatch({ kind: "tool-cap", name, cap });
        }}
      />
      <Issues issues={issuesFor(issues, "agent", ["tools"])} />
    </Section>
  );
}

export function HelpersSection({ doc, issues, dispatch, catalog, readOnly }: Props) {
  const [name, setName] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const helpers = doc.helpers ?? [];
  const toolHooks: Record<string, string[]> = {};
  for (const point of ["pre_tool", "post_tool"]) {
    const hooks = doc.hooks?.[point];
    if (hooks?.length) toolHooks[point] = [...hooks];
  }
  const add = () => {
    const label = name.trim();
    if (!label) return;
    const preset = catalog.presets.helper ?? { max_turns: 6, limits: {} };
    dispatch({ kind: "add-helper", helper: newHelper(label, helpers.map((h) => h.name), preset, toolHooks) });
    setName("");
    setOpen(helpers.length);
  };
  return (
    <Section
      title="Helpers"
      description="Sub-agents it can hand parts of a question to. They work in parallel, each with its own instructions and tools, and report back."
      icon={<Users aria-hidden className="size-4" />}
      testId="section-helpers"
    >
      <div className="space-y-3">
        {helpers.map((h, i) => (
          <HelperCard
            key={h.name}
            helper={h}
            open={open === i}
            onOpen={() => {
              setOpen(open === i ? null : i);
            }}
            issues={issues.filter((x) => x.where === `helpers.${h.name}`)}
            catalog={catalog}
            readOnly={readOnly}
            onChange={(helper) => {
              dispatch({ kind: "helper", index: i, helper });
            }}
            onRemove={() => {
              dispatch({ kind: "remove-helper", index: i });
              setOpen(null);
            }}
          />
        ))}
        {helpers.length === 0 && <p className="text-sm text-stone-500">No helpers yet. Most agents don't need any; add one for a separate kind of work.</p>}
      </div>
      {!readOnly && (
        <form
          className="mt-4 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            add();
          }}
        >
          <label className="flex-1">
            <span className="sr-only">New helper's name</span>
            <input
              value={name}
              onChange={(e) => {
                setName(e.target.value);
              }}
              maxLength={60}
              placeholder="New helper's name, e.g. Flight finder"
              className="h-10 w-full rounded-xl border border-stone-200 bg-white px-3 text-sm placeholder:text-stone-400 focus:border-sun-400 focus:ring-4 focus:ring-sun-100 focus:outline-none dark:border-stone-700 dark:bg-stone-950 dark:focus:ring-sun-700/20"
            />
          </label>
          <Button type="submit" disabled={!name.trim()}>
            <Plus aria-hidden className="size-4" /> Add helper
          </Button>
        </form>
      )}
    </Section>
  );
}

function HelperCard({
  helper,
  open,
  onOpen,
  issues,
  catalog,
  readOnly,
  onChange,
  onRemove,
}: {
  helper: HelperDocument;
  open: boolean;
  onOpen: () => void;
  issues: readonly Issue[];
  catalog: Catalog;
  readOnly: boolean;
  onChange: (helper: HelperDocument) => void;
  onRemove: () => void;
}) {
  const label = helper.display_name ?? helper.name;
  return (
    <div className={`rounded-xl border ${issues.length ? "border-rose-300 dark:border-rose-800" : "border-stone-200 dark:border-stone-700"}`} data-testid="helper-editor">
      <button type="button" aria-expanded={open} onClick={onOpen} className="flex w-full items-center gap-3 px-4 py-3 text-left">
        <Avatar name={label} size="sm" />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium">{label}</span>
          <span className="block truncate text-xs text-stone-500">{helper.description || "No description yet"}</span>
        </span>
        {issues.length > 0 && <Pill tone="rose">{issues.length} to fix</Pill>}
        <Pill>{(helper.tools ?? []).length} tools</Pill>
        <ChevronDown aria-hidden className={`size-4 text-stone-400 transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="space-y-4 border-t border-stone-100 px-4 pt-4 pb-4 dark:border-stone-800">
          <TextField
            label="Helper's name"
            value={helper.display_name ?? ""}
            maxLength={60}
            disabled={readOnly}
            onChange={(e) => {
              onChange({ ...helper, display_name: e.target.value });
            }}
            hint={
              <>
                Id <code className="font-mono">{helper.name}</code>
              </>
            }
            issues={issuesFor(issues, `helpers.${helper.name}`, ["name", "display_name"])}
          />
          <TextArea
            label="What does it do?"
            rows={2}
            maxLength={500}
            value={helper.description}
            disabled={readOnly}
            placeholder="Finds flights between two cities on given dates."
            onChange={(e) => {
              onChange({ ...helper, description: e.target.value });
            }}
            hint="The main agent reads this to decide when to call it."
            issues={issuesFor(issues, `helpers.${helper.name}`, ["description"])}
          />
          <TextArea
            label="Its instructions"
            rows={6}
            maxLength={20000}
            value={helper.instructions}
            disabled={readOnly}
            onChange={(e) => {
              onChange({ ...helper, instructions: e.target.value });
            }}
            issues={issuesFor(issues, `helpers.${helper.name}`, ["instructions"])}
          />
          <div>
            <div className="mb-2 text-sm font-medium">Its tools</div>
            <ToolCards
              selected={helper.tools ?? []}
              catalog={catalog}
              forHelper
              readOnly={readOnly}
              onToggle={(name, on) => {
                const tools = on
                  ? [...(helper.tools ?? []).filter((t) => t.name !== name), { name }]
                  : (helper.tools ?? []).filter((t) => t.name !== name);
                onChange({ ...helper, tools });
              }}
            />
            <Issues issues={issuesFor(issues, `helpers.${helper.name}`, ["tools", "max_turns", "limits", "hooks"])} />
          </div>
          {!readOnly && (
            <Button variant="danger" size="sm" onClick={onRemove}>
              <Trash2 aria-hidden className="size-4" /> Remove this helper
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

const PRESET_LABELS: Record<Exclude<PresetName, "custom">, { label: string; hint: string }> = {
  quick: { label: "Quick", hint: "Short answers" },
  standard: { label: "Standard", hint: "Most tasks" },
  thorough: { label: "Thorough", hint: "Long, careful work" },
};

export function LimitsSection({ doc, issues, dispatch, catalog, readOnly }: Props) {
  const current = presetOf(doc, catalog.presets);
  const [custom, setCustom] = useState(current === "custom");
  const value: PresetName = custom ? "custom" : current;
  const limits = doc.limits ?? {};
  const options = [
    ...(Object.keys(PRESET_LABELS) as Exclude<PresetName, "custom">[]).map((k) => ({ value: k, ...PRESET_LABELS[k] })),
    { value: "custom" as PresetName, label: "Custom", hint: "Set the numbers" },
  ];
  return (
    <Section title="Effort" description="How much it may do for one message. It wraps up gracefully when it gets close." icon={<Gauge aria-hidden className="size-4" />} testId="section-limits">
      <Segmented
        label="Effort"
        value={value}
        options={options}
        onChange={(v) => {
          if (readOnly) return;
          setCustom(v === "custom");
          const preset = v === "custom" ? undefined : catalog.presets[v];
          if (preset) dispatch({ kind: "preset", preset });
        }}
      />
      {value === "custom" && (
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          {(
            [
              ["max_turns", "Steps per message", doc.max_turns, catalog.ceilings.max_turns, 1],
              ["max_tool_calls", "Tool uses per message", Number(limits.max_tool_calls ?? 0), catalog.ceilings.max_tool_calls, 1],
              ["timeout_s", "Time limit (minutes)", Math.round(Number(limits.timeout_s ?? 60) / 60), Math.floor((catalog.ceilings.timeout_s ?? 600) / 60), 60],
            ] as const
          ).map(([field, label, val, max, unit]) => (
            <label key={field} className="text-sm">
              <span className="mb-1 block font-medium">{label}</span>
              <input
                type="number"
                min={1}
                max={max}
                value={val}
                disabled={readOnly}
                onChange={(e) => {
                  dispatch({ kind: "limit", field, value: Math.max(1, Number(e.target.value)) * unit });
                }}
                className="h-10 w-full rounded-xl border border-stone-200 bg-white px-3 dark:border-stone-700 dark:bg-stone-950"
              />
              <span className="mt-1 block text-xs text-stone-500">Up to {String(max)}</span>
            </label>
          ))}
        </div>
      )}
      <Issues issues={issuesFor(issues, "agent", ["max_turns", "limits"])} />
    </Section>
  );
}

export function ProtectionsSection({ doc, dispatch, catalog, readOnly, issues }: Props) {
  return (
    <Section title="Protections" description="Safety and housekeeping, built in. You choose which are on." icon={<ShieldCheck aria-hidden className="size-4" />} testId="section-protections">
      <div className="grid gap-4 sm:grid-cols-2">
        {catalog.protections.map((p) => (
          <Switch
            key={p.hook}
            checked={hasHook(doc.hooks, p.point, p.hook)}
            disabled={readOnly}
            label={p.label}
            description={p.description}
            onChange={(on) => {
              dispatch({ kind: "protection", hook: p.hook, point: p.point, on, helpers: p.helpers });
            }}
          />
        ))}
      </div>
      <Issues issues={issuesFor(issues, "agent", ["hooks"])} />
    </Section>
  );
}

export function ModelSection() {
  return (
    <Section title="Model" description="Which AI model answers." icon={<Cpu aria-hidden className="size-4" />} testId="section-model">
      <p className="text-sm text-stone-600 dark:text-stone-400">
        Uses Nuria's model (the one chosen in setup). Choosing a model for each agent and helper comes next.
      </p>
    </Section>
  );
}
