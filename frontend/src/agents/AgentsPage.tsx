/**
 * The agents: yours (built in the Agent Studio, editable) and the built-in ones
 * (files in the repository, read-only, copyable). Each shows what it is for, its
 * instructions, tools, limits and helpers (sub-agents).
 */
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronDown, Copy, Gauge, MessageSquarePlus, Plus, Sparkles, Upload, Users, Wrench, Zap } from "lucide-react";
import { useRef, useState } from "react";

import { api, type Schemas, unwrap } from "../api/client";
import { href, type Route } from "../app/route";
import { problemText } from "../chat/problems";
import { type DraftProposal, studio, useAssist, useCreateAgent, useStudioAgents, useStudioRefresh } from "../studio/api";
import { Dialog, Segmented, TextArea, TextField } from "../ui/form";
import { ToolIcon } from "../ui/icons";
import { Markdown } from "../ui/Markdown";
import { Avatar, Button, Pill, Spinner } from "../ui/primitives";
import { AgentPowerButton, OffPill } from "../safety/KillSwitch";
import { agentLabel, limitLines, toolName, toolPurpose } from "../ui/words";

type Helper = Schemas["HelperView"];
type Agent = Schemas["AgentView"];

const card =
  "group flex flex-col rounded-2xl border border-stone-200 bg-white p-5 shadow-soft transition hover:-translate-y-0.5 hover:border-stone-300 hover:shadow-lift focus-visible:outline-2 focus-visible:outline-sun-500 dark:border-stone-800 dark:bg-stone-900 dark:hover:border-stone-700";

export function AgentsPage({ go }: { go: (route: Route) => void }) {
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => unwrap(api.GET("/agents")) });
  const mine = useStudioAgents();
  const builtins = (agents.data ?? []).filter((a) => a.source === "builtin" && !a.hidden);
  const [creating, setCreating] = useState<{ copyOf: Agent | null } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const refresh = useStudioRefresh();
  const file = useRef<HTMLInputElement>(null);

  const importFile = async (f: File) => {
    setNotice(null);
    try {
      const agent = await studio.importFile(f);
      refresh(agent);
      go({ page: "studio", agentId: agent.id });
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Import failed.");
    }
  };

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <div className="flex flex-wrap items-end gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="font-display text-4xl font-medium tracking-tight">Agents</h1>
          <p className="mt-2 max-w-2xl text-stone-500 dark:text-stone-400">
            Each agent has instructions, tools it may use, and helpers it can hand work to. Nuria runs them durably: a crash or a restart never
            loses their work.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => file.current?.click()}>
            <Upload aria-hidden className="size-4" /> Import
          </Button>
          <input
            ref={file}
            type="file"
            accept=".md,.zip"
            className="hidden"
            aria-label="Import an agent file"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void importFile(f);
              e.target.value = "";
            }}
          />
          <Button
            variant="primary"
            onClick={() => {
              setCreating({ copyOf: null });
            }}
          >
            <Plus aria-hidden className="size-4" /> New agent
          </Button>
        </div>
      </div>
      {notice && (
        <div role="alert" className="mt-4 rounded-xl bg-rose-50 px-4 py-2 text-sm text-rose-800 ring-1 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900">
          {notice}
        </div>
      )}

      <h2 className="mt-10 text-[11px] font-semibold tracking-wider text-stone-500 uppercase">Your agents</h2>
      {mine.data?.length === 0 && (
        <div className="mt-3 rounded-2xl border border-dashed border-stone-300 p-8 text-center dark:border-stone-700">
          <p className="font-display text-xl">Build your first agent</p>
          <p className="mt-1 text-sm text-stone-500">Describe the assistant you want and Nuria drafts it, or copy a built-in agent below.</p>
        </div>
      )}
      <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {mine.data?.map((a) => (
          <a key={a.id} href={href({ page: "studio", agentId: a.id })} className={card} data-testid="my-agent-card">
            <div className="flex items-center gap-3">
              <Avatar name={a.display_name} size="lg" />
              <div className="min-w-0">
                <div className="truncate font-display text-lg font-medium">{a.display_name}</div>
                <div className="font-mono text-xs text-stone-500">{a.name}</div>
              </div>
            </div>
            <p className="mt-3 line-clamp-3 flex-1 text-sm leading-relaxed text-stone-600 dark:text-stone-400">{a.description || "No description yet."}</p>
            <div className="mt-4 flex items-center gap-1.5">
              {a.status === "draft" && <Pill tone="sun">Draft</Pill>}
              {a.status === "published" && <Pill tone="green">Published v{a.published?.number}</Pill>}
              {a.status === "changes" && <Pill tone="amber">v{a.published?.number} · unpublished changes</Pill>}
              <OffPill agent={a.name} />
              <span className="ml-auto text-xs font-medium text-stone-500 group-hover:text-stone-900 dark:group-hover:text-stone-100">Edit →</span>
            </div>
          </a>
        ))}
      </div>

      <h2 className="mt-10 text-[11px] font-semibold tracking-wider text-stone-500 uppercase">Built in</h2>
      {agents.isPending && <Spinner className="mt-4" label="Loading agents…" />}
      <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {builtins.map((a) => (
          <div key={a.name} className={`${card} relative`} data-testid="agent-card">
            <a href={href({ page: "agent", name: a.name })} className="absolute inset-0 rounded-2xl" aria-label={`About ${a.display_name}`} />
            <div className="flex items-center gap-3">
              <Avatar name={a.display_name} size="lg" brand={a.name === "chat"} />
              <div className="min-w-0">
                <div className="font-display text-lg font-medium">{a.display_name}</div>
                <div className="font-mono text-xs text-stone-500">{a.name}</div>
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
              <AgentPowerButton agent={a.name} label={a.display_name} className="relative z-10 ml-auto" />
              <button
                type="button"
                onClick={() => {
                  setCreating({ copyOf: a });
                }}
                className="relative z-10 inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-stone-600 hover:bg-stone-100 hover:text-stone-900 dark:text-stone-300 dark:hover:bg-stone-800"
              >
                <Copy aria-hidden className="size-3.5" /> Copy
              </button>
            </div>
          </div>
        ))}
      </div>
      <NewAgentDialog
        open={creating !== null}
        copyOf={creating?.copyOf ?? null}
        templates={builtins}
        onClose={() => {
          setCreating(null);
        }}
        onCreated={(id) => {
          setCreating(null);
          go({ page: "studio", agentId: id });
        }}
      />
    </div>
  );
}

type Start = "describe" | "template" | "blank";
const STARTS: readonly { value: Start; label: string; hint: string }[] = [
  { value: "describe", label: "Describe it", hint: "We draft it for you" },
  { value: "template", label: "From a template", hint: "Start from a built-in" },
  { value: "blank", label: "Start blank", hint: "Fill it in yourself" },
];

function NewAgentDialog({
  open,
  copyOf,
  templates,
  onClose,
  onCreated,
}: {
  open: boolean;
  copyOf: Agent | null;
  templates: readonly Agent[];
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const [start, setStart] = useState<Start>("describe");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [template, setTemplate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useCreateAgent((a) => {
    setName("");
    setDescription("");
    onCreated(a.id);
  });
  const source = copyOf ?? templates.find((t) => t.name === template) ?? null;
  const copying = copyOf !== null || start === "template";
  const title = copyOf ? `Copy ${copyOf.display_name}` : "New agent";
  return (
    <Dialog open={open} onClose={onClose} title={title}>
      {!copyOf && (
        <div className="mb-4">
          <Segmented label="How to start" value={start} options={STARTS} onChange={setStart} />
        </div>
      )}
      {!copyOf && start === "describe" ? (
        <DescribeIt onCreated={onCreated} onClose={onClose} />
      ) : (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            create.mutate(
              { display_name: name.trim(), description: description.trim(), copy_of: copying ? (source?.name ?? null) : null },
              { onError: (err) => { setError(problemText(err)); } },
            );
          }}
        >
          {!copyOf && start === "template" && (
            <label className="block text-sm">
              <span className="mb-1.5 block font-medium">Template</span>
              <select
                value={template}
                required
                onChange={(e) => {
                  setTemplate(e.target.value);
                  const picked = templates.find((t) => t.name === e.target.value);
                  if (picked && !name) setName(`My ${picked.display_name}`);
                }}
                className="w-full rounded-xl border border-stone-200 bg-white px-3 py-2 text-[15px] dark:border-stone-700 dark:bg-stone-950"
              >
                <option value="">Choose one…</option>
                {templates.map((t) => (
                  <option key={t.name} value={t.name}>
                    {t.display_name}: {t.description.slice(0, 70)}
                  </option>
                ))}
              </select>
            </label>
          )}
          <p className="text-sm text-stone-600 dark:text-stone-400">
            {copying
              ? `You'll get your own editable agent, starting from ${source?.display_name ?? "the template"}'s instructions, tools and helpers. The original stays as it is.`
              : "Give it a name; you'll fill in the rest next, and try it before anyone else sees it."}
          </p>
          <TextField
            label="Name"
            value={name}
            maxLength={60}
            required
            autoFocus
            placeholder={source ? `My ${source.display_name}` : "Trip planner"}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
          {!copying && (
            <TextArea
              label="What is it for? (optional)"
              rows={2}
              maxLength={500}
              value={description}
              onChange={(e) => {
                setDescription(e.target.value);
              }}
            />
          )}
          {error && <div role="alert" className="text-sm text-rose-600">{error}</div>}
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" type="submit" disabled={!name.trim() || create.isPending || (copying && !source)}>
              {copying ? "Copy" : "Create"}
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}

/** "Describe it" (R17.3): the builder agent drafts the form; nothing is saved until you accept. */
export function DescribeIt({
  onCreated,
  onClose,
  guide = false,
  example = "",
}: {
  onCreated: (id: string) => void;
  onClose?: () => void;
  guide?: boolean; // made in Getting started: it becomes the guide's agent
  example?: string;
}) {
  const [text, setText] = useState(example);
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);
  const refresh = useStudioRefresh();
  const answer = useAssist(runId);
  const result = answer.data;
  const draft = result?.status === "done" ? (result.proposal as unknown as DraftProposal) : null;
  const working = runId !== null && (!result || result.status === "working");

  if (draft) {
    return (
      <div className="space-y-4" data-testid="draft-preview">
        <div className="rounded-xl border border-stone-200 p-4 dark:border-stone-700">
          <div className="font-display text-lg font-medium">{draft.display_name}</div>
          <p className="mt-0.5 text-sm text-stone-600 dark:text-stone-400">{draft.description}</p>
          <dl className="mt-3 space-y-1.5 text-sm">
            <Row label="Tools" value={(draft.tools ?? []).map(toolName).join(", ") || "none"} />
            <Row label="Helpers" value={(draft.helpers ?? []).map((h) => h.display_name).join(", ") || "none"} />
            <Row label="Skills" value={(draft.skills ?? []).join(", ") || "none"} />
            <Row label="Effort" value={draft.effort} />
          </dl>
        </div>
        <p className="text-sm text-stone-500">Next you can change anything, then try it in a test chat.</p>
        {error && <div role="alert" className="text-sm text-rose-600">{error}</div>}
        <div className="flex justify-end gap-2">
          <Button
            onClick={() => {
              setRunId(null);
            }}
          >
            Try again
          </Button>
          <Button
            variant="primary"
            disabled={accepting}
            onClick={() => {
              setAccepting(true);
              studio
                .fromProposal(draft, guide)
                .then((agent) => {
                  refresh(agent);
                  onCreated(agent.id);
                })
                .catch((e: unknown) => {
                  setError(problemText(e));
                })
                .finally(() => {
                  setAccepting(false);
                });
            }}
          >
            Use this draft
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        studio
          .describe(text.trim())
          .then((r) => {
            setRunId(r.run_id);
          })
          .catch((err: unknown) => {
            setError(problemText(err));
          });
      }}
    >
      <TextArea
        label="Describe the assistant you want"
        rows={5}
        minLength={10}
        maxLength={4000}
        required
        autoFocus={onClose !== undefined} // in a dialog, not on a page
        value={text}
        disabled={working}
        placeholder="It plans family trips: finds things to do, keeps to a budget, and has a helper that finds kid-friendly restaurants."
        hint="What it's for, what it should do, and anything it must never do. You'll check and change the draft before anyone uses it."
        onChange={(e) => {
          setText(e.target.value);
        }}
      />
      {working && <Spinner label="Drafting your agent…" />}
      {result?.status === "failed" && (
        <div role="alert" className="text-sm text-rose-700 dark:text-rose-400">
          {result.problem}
        </div>
      )}
      {error && <div role="alert" className="text-sm text-rose-600">{error}</div>}
      <div className="flex justify-end gap-2">
        {onClose && <Button onClick={onClose}>Cancel</Button>}
        <Button variant="primary" type="submit" disabled={text.trim().length < 10 || working}>
          <Sparkles aria-hidden className="size-4" /> Draft it
        </Button>
      </div>
    </form>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <dt className="w-16 shrink-0 text-stone-500">{label}</dt>
      <dd className="min-w-0">{value}</dd>
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
        <Avatar name={a.display_name} size="lg" brand={a.name === "chat"} />
        <div className="min-w-0 flex-1">
          <h1 className="font-display text-3xl font-medium tracking-tight">{a.display_name}</h1>
          <p className="mt-1.5 max-w-2xl text-stone-600 dark:text-stone-400">{a.description}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Pill>version {a.version}</Pill>
            <Pill>model role: {a.model}</Pill>
          </div>
        </div>
        <Button variant="primary" onClick={() => void chat()}>
          <MessageSquarePlus aria-hidden className="size-4" /> Chat with {a.display_name}
        </Button>
      </div>
      {notice && <div role="alert" className="mt-4 text-sm text-rose-600">{notice}</div>}

      <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_300px]">
        <section className="rounded-2xl border border-stone-200 bg-white p-6 dark:border-stone-800 dark:bg-stone-900">
          <h2 className="text-[11px] font-semibold tracking-wider text-stone-500 uppercase">Instructions</h2>
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
            {a.display_name} can hand parts of a question to these sub-agents. They work in parallel, each with its own instructions and tools,
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
          <div className="font-mono text-xs text-stone-500">{helper.name}</div>
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
  if (tools.length === 0) return <p className="text-sm text-stone-500">No tools.</p>;
  if (compact) {
    return (
      <div className="flex flex-wrap gap-1.5">
        {tools.map((t) => (
          <Pill key={String(t.name)}>
            <ToolIcon tool={String(t.name)} className="size-3" /> {toolName(String(t.name))}
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
              <span className="block font-medium text-stone-800 dark:text-stone-200">{toolName(name)}</span>
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
      <h2 className="mb-3 flex items-center gap-1.5 text-[11px] font-semibold tracking-wider text-stone-500 uppercase">
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
