/**
 * The agents: what each one is for, its instructions, tools, limits and helpers
 * (sub-agents). Read-only for now: creating and editing agents is the Agent Studio
 * (local release L3 + L4); today agents are defined in backend/agents/.
 */
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, ChevronDown, Gauge, MessageSquarePlus, Sparkles, Users, Wrench, Zap } from "lucide-react";
import { useState } from "react";

import { api, type Schemas, unwrap } from "../api/client";
import { href, type Route } from "../app/route";
import { problemText } from "../chat/problems";
import { ToolIcon } from "../ui/icons";
import { Markdown } from "../ui/Markdown";
import { Avatar, Button, Pill, Spinner } from "../ui/primitives";
import { agentLabel, limitLines, toolLabel, toolPurpose } from "../ui/words";

type Helper = Schemas["HelperView"];

export function AgentsPage() {
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => unwrap(api.GET("/agents")) });
  const list = (agents.data ?? []).filter((a) => !a.hidden); // test and example agents stay out
  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="font-display text-4xl font-medium tracking-tight">Agents</h1>
      <p className="mt-2 max-w-2xl text-stone-500 dark:text-stone-400">
        Each agent has instructions, tools it may use, and helpers it can hand work to. Nuria runs them durably: a crash or a restart never
        loses their work.
      </p>
      <StudioNotice />
      {agents.isPending && <Spinner className="mt-8" label="Loading agents…" />}
      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {list.map((a) => (
          <a
            key={a.name}
            href={href({ page: "agent", name: a.name })}
            className="group flex flex-col rounded-2xl border border-stone-200 bg-white p-5 shadow-soft transition hover:-translate-y-0.5 hover:border-stone-300 hover:shadow-lift focus-visible:outline-2 focus-visible:outline-sun-500 dark:border-stone-800 dark:bg-stone-900 dark:hover:border-stone-700"
            data-testid="agent-card"
          >
            <div className="flex items-center gap-3">
              <Avatar name={agentLabel(a.name)} size="lg" brand={a.name === "chat"} />
              <div className="min-w-0">
                <div className="font-display text-lg font-medium">{agentLabel(a.name)}</div>
                <div className="font-mono text-xs text-stone-400">{a.name}</div>
              </div>
            </div>
            <p className="mt-3 line-clamp-3 flex-1 text-sm leading-relaxed text-stone-600 dark:text-stone-400">{a.description}</p>
            <div className="mt-4 flex flex-wrap items-center gap-1.5">
              <Pill>
                <Wrench aria-hidden className="size-3" /> {a.tools.length} tools
              </Pill>
              {a.helpers.length > 0 && (
                <Pill tone="sun">
                  <Users aria-hidden className="size-3" /> {a.helpers.length} helpers
                </Pill>
              )}
              <ArrowRight aria-hidden className="ml-auto size-4 text-stone-300 transition group-hover:translate-x-0.5 group-hover:text-stone-500" />
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}

function StudioNotice() {
  return (
    <div className="mt-6 flex items-start gap-3 rounded-2xl border border-sun-200 bg-sun-50/70 p-4 text-sm dark:border-sun-700/40 dark:bg-sun-700/10">
      <Sparkles aria-hidden className="mt-0.5 size-4 shrink-0 text-sun-600 dark:text-sun-300" />
      <div className="text-stone-700 dark:text-stone-300">
        <span className="font-medium text-stone-900 dark:text-stone-100">Building your own agents is coming next.</span> The Agent Studio will let you
        create agents and helpers, write their instructions, pick their tools and model, and add skills, without code. These are the built-in
        agents.
      </div>
    </div>
  );
}

export function AgentDetail({ name, go }: { name: string; go: (route: Route) => void }) {
  const agent = useQuery({
    queryKey: ["agent", name],
    queryFn: () => unwrap(api.GET("/agents/{name}", { params: { path: { name } } })),
  });
  const [notice, setNotice] = useState<string | null>(null);
  const chat = async () => {
    try {
      const s = await unwrap(api.POST("/sessions", { body: { agent: name } }));
      go({ page: "chat", sessionId: s.id });
    } catch (e) {
      setNotice(problemText(e));
    }
  };
  if (agent.isPending) return <Spinner className="m-10" label="Loading…" />;
  if (agent.isError) return <div className="m-10 text-rose-600">This agent doesn't exist.</div>;
  const a = agent.data;
  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <a href={href({ page: "agents" })} className="inline-flex items-center gap-1.5 text-sm text-stone-500 hover:text-stone-900 dark:hover:text-stone-100">
        <ArrowLeft aria-hidden className="size-4" /> All agents
      </a>
      <div className="mt-6 flex flex-wrap items-start gap-5">
        <Avatar name={agentLabel(a.name)} size="lg" brand={a.name === "chat"} />
        <div className="min-w-0 flex-1">
          <h1 className="font-display text-3xl font-medium tracking-tight">{agentLabel(a.name)}</h1>
          <p className="mt-1.5 max-w-2xl text-stone-600 dark:text-stone-400">{a.description}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Pill>version {a.version}</Pill>
            <Pill>model role: {a.model}</Pill>
          </div>
        </div>
        <Button variant="primary" onClick={() => void chat()}>
          <MessageSquarePlus aria-hidden className="size-4" /> Chat with {agentLabel(a.name)}
        </Button>
      </div>
      {notice && <div role="alert" className="mt-4 text-sm text-rose-600">{notice}</div>}

      <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_300px]">
        <section className="rounded-2xl border border-stone-200 bg-white p-6 dark:border-stone-800 dark:bg-stone-900">
          <h2 className="text-[11px] font-semibold tracking-wider text-stone-400 uppercase">Instructions</h2>
          <div className="mt-3">
            <Markdown text={showPlaceholders(a.prompt ?? "")} />
          </div>
        </section>
        <aside className="space-y-6">
          <Panel title="Tools" icon={<Wrench aria-hidden className="size-3.5" />}>
            <ToolList tools={a.tools} />
          </Panel>
          <Panel title="Limits" icon={<Gauge aria-hidden className="size-3.5" />}>
            <ul className="space-y-1.5 text-sm text-stone-600 dark:text-stone-400">
              {limitLines(a.limits, a.max_turns).map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </Panel>
          {Object.keys(a.hooks).length > 0 && (
            <Panel title="Automations" icon={<Zap aria-hidden className="size-3.5" />}>
              <ul className="space-y-1.5 text-sm text-stone-600 dark:text-stone-400">
                {Object.entries(a.hooks).map(([when, names]) => (
                  <li key={when}>
                    <span className="text-stone-800 dark:text-stone-200">{hookMoment(when)}:</span> {names.map((n) => n.replaceAll("_", " ")).join(", ")}
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </aside>
      </div>

      {a.helpers.length > 0 && (
        <section className="mt-10">
          <h2 className="font-display text-2xl font-medium">Helpers</h2>
          <p className="mt-1 text-sm text-stone-500 dark:text-stone-400">
            {agentLabel(a.name)} can hand parts of a question to these sub-agents. They work in parallel, each with its own instructions and tools,
            and report back.
          </p>
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            {a.helpers.map((h) => (
              <HelperCard key={h.name} helper={h} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function HelperCard({ helper }: { helper: Helper }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-2xl border border-stone-200 bg-white p-5 dark:border-stone-800 dark:bg-stone-900" data-testid="agent-helper">
      <div className="flex items-center gap-3">
        <Avatar name={helper.name} />
        <div>
          <div className="font-medium">{agentLabel(helper.name)}</div>
          <div className="font-mono text-xs text-stone-400">{helper.name}</div>
        </div>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-stone-600 dark:text-stone-400">{helper.description}</p>
      <div className="mt-4">
        <ToolList tools={helper.tools} compact />
      </div>
      <div className="mt-3 text-xs text-stone-500">{limitLines(helper.limits, helper.max_turns).join(" · ")}</div>
      {helper.prompt && (
        <div className="mt-3 border-t border-stone-100 pt-3 dark:border-stone-800">
          <button
            type="button"
            aria-expanded={open}
            onClick={() => {
              setOpen(!open);
            }}
            className="inline-flex items-center gap-1 text-sm font-medium text-stone-600 hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100"
          >
            Instructions <ChevronDown aria-hidden className={`size-4 transition ${open ? "rotate-180" : ""}`} />
          </button>
          {open && (
            <div className="mt-2">
              <Markdown text={showPlaceholders(helper.prompt)} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ToolList({ tools, compact = false }: { tools: Record<string, unknown>[]; compact?: boolean }) {
  if (tools.length === 0) return <p className="text-sm text-stone-400">No tools.</p>;
  if (compact) {
    return (
      <div className="flex flex-wrap gap-1.5">
        {tools.map((t) => (
          <Pill key={String(t.name)}>
            <ToolIcon tool={String(t.name)} className="size-3" /> {toolLabel(String(t.name))}
          </Pill>
        ))}
      </div>
    );
  }
  return (
    <ul className="space-y-3">
      {tools.map((t) => {
        const name = String(t.name);
        return (
          <li key={name} className="flex items-start gap-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-300">
              <ToolIcon tool={name} />
            </span>
            <span className="min-w-0 text-sm">
              <span className="block font-medium text-stone-800 dark:text-stone-200">{toolLabel(name)}</span>
              <span className="block text-stone-500">
                {toolPurpose(name)}
                {typeof t.max_calls === "number" ? ` · at most ${String(t.max_calls)} per message` : ""}
              </span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function Panel({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-5 dark:border-stone-800 dark:bg-stone-900">
      <h2 className="mb-3 flex items-center gap-1.5 text-[11px] font-semibold tracking-wider text-stone-400 uppercase">
        {icon}
        {title}
      </h2>
      {children}
    </section>
  );
}

const PLACEHOLDER_LABELS: Record<string, string> = {
  date: "today's date",
  tools: "its tools",
  "agent.name": "its name",
  "session.title": "the chat's title",
};

/** `{{date}}` in instructions is filled in at run time: show what it becomes. */
function showPlaceholders(prompt: string): string {
  return prompt.replace(/\{\{\s*([a-zA-Z_.]+)\s*\}\}/g, (_, key: string) => `\`‹${PLACEHOLDER_LABELS[key] ?? key}›\``);
}

function hookMoment(when: string): string {
  return (
    { session_start: "When a chat starts", session_end: "When a chat ends", turn_start: "Before each reply", turn_end: "After each reply", pre_tool: "Before a tool runs", post_tool: "After a tool runs" }[when] ??
    when
  );
}
