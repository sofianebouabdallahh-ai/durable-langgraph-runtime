/**
 * Getting started (phase L3d): a newcomer's first agent, in five real steps.
 *
 * A checklist whose items tick themselves: progress is derived on the server from
 * what exists (a model ready, a tool, a helper…), so it never drifts. Each step says
 * why it matters and opens the real screen to do it, where a guide strip says what to
 * do there. Nothing starts by itself; it can be hidden.
 */
import { Check, ClipboardCopy, Cloud, Cpu, ExternalLink, MessageSquarePlus, RotateCcw, Sparkles } from "lucide-react";
import { type ReactNode, useState } from "react";

import { api, unwrap } from "../api/client";
import { DescribeIt } from "../agents/AgentsPage";
import { type Route } from "../app/route";
import { problemText } from "../chat/problems";
import { AddDialog } from "../settings/ModelsPage";
import { models, useDefaultModel, useModelsRefresh } from "../settings/api";
import { studio, useStudioAgents, useStudioRefresh } from "../studio/api";
import { Segmented } from "../ui/form";
import { Button, Pill, Spinner } from "../ui/primitives";
import { doneCount, guide, type Onboarding, ORDER, STEPS, type StepKey, useOnboarding, useOnboardingRefresh } from "./api";
import { useQuery } from "@tanstack/react-query";

const EXAMPLE = "It plans family trips: finds things to do, keeps to a budget, and has a helper that finds kid-friendly restaurants.";

export function GetStarted({ go }: { go: (route: Route) => void }) {
  const state = useOnboarding(true);
  const refresh = useOnboardingRefresh();
  const [open, setOpen] = useState<StepKey | "none" | null>(null); // null: the next step
  if (!state.data) return <Spinner className="m-10" label="Loading the guide…" />;
  const s = state.data;
  const shown = open === null ? s.next : open === "none" ? null : open;
  const count = doneCount(s);
  const set = (body: Parameters<typeof guide.update>[0]) => {
    void guide.update(body).then(refresh);
  };
  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="font-display text-4xl font-medium tracking-tight">Get started</h1>
      <p className="mt-2 text-stone-500 dark:text-stone-400">
        Build your first agent in five steps, in the real app. Each step ticks by itself when it's done.
      </p>
      <div className="mt-6" data-testid="guide-progress">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium">
            {count} of {ORDER.length} done
          </span>
          <span className="flex gap-1">
            <Button size="sm" variant="ghost" onClick={() => { set({ restart: true }); setOpen(null); }}>
              <RotateCcw aria-hidden className="size-3.5" /> Start over
            </Button>
            {!s.dismissed && (
              <Button size="sm" variant="ghost" onClick={() => { set({ dismissed: true }); go({ page: "home" }); }}>
                Hide this guide
              </Button>
            )}
          </span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800" role="progressbar" aria-label="Getting started" aria-valuemin={0} aria-valuemax={ORDER.length} aria-valuenow={count}>
          <div className="h-full rounded-full bg-sun-500 transition-all" style={{ width: `${String((count / ORDER.length) * 100)}%` }} />
        </div>
      </div>

      <ol className="mt-8 space-y-3">
        {ORDER.map((key, i) => {
          const step = s.steps.find((x) => x.key === key);
          return (
            <StepCard
              key={key}
              n={i + 1}
              stepKey={key}
              done={step?.done ?? false}
              skipped={step?.skipped ?? false}
              next={s.next === key}
              expanded={shown === key}
              onToggle={() => {
                setOpen(shown === key ? "none" : key);
              }}
            >
              <StepBody stepKey={key} state={s} go={go} onChange={refresh} />
            </StepCard>
          );
        })}
      </ol>

      {s.finished && s.agent && (
        <div className="mt-8 rounded-2xl bg-emerald-50 p-6 ring-1 ring-emerald-200 dark:bg-emerald-950/40 dark:ring-emerald-900" data-testid="guide-finished">
          <p className="font-display text-2xl">You built {s.agent.display_name}.</p>
          <p className="mt-1 text-sm text-stone-600 dark:text-stone-300">
            Next: give it a skill (know-how it loads when needed), or try another model. Everything you did is in Agents.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => void chatWith(s.agent?.name ?? "", go)}>
              <MessageSquarePlus aria-hidden className="size-4" /> Chat with it
            </Button>
            <Button onClick={() => { go({ page: "skills" }); }}>Skills</Button>
            <Button onClick={() => { go({ page: "models" }); }}>Models</Button>
          </div>
        </div>
      )}
    </div>
  );
}

async function chatWith(agent: string, go: (route: Route) => void) {
  const session = await unwrap(api.POST("/sessions", { body: { agent, title: "First chat" } }));
  go({ page: "chat", sessionId: session.id });
}

function StepCard({
  n,
  stepKey,
  done,
  skipped,
  next,
  expanded,
  onToggle,
  children,
}: {
  n: number;
  stepKey: StepKey;
  done: boolean;
  skipped: boolean;
  next: boolean;
  expanded: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  const step = STEPS[stepKey];
  const bodyId = `guide-step-${stepKey}`;
  return (
    <li className={`rounded-2xl border bg-white shadow-soft dark:bg-stone-900 ${next ? "border-sun-300 dark:border-sun-700/60" : "border-stone-200 dark:border-stone-800"}`} data-testid={`guide-step-${stepKey}`}>
      <button type="button" aria-expanded={expanded} aria-controls={bodyId} onClick={onToggle} className="flex w-full items-start gap-4 p-5 text-left">
        <span
          aria-hidden
          className={`flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${done ? "bg-emerald-600 text-white" : next ? "bg-sun-500 text-white" : "bg-stone-100 text-stone-500 dark:bg-stone-800"}`}
        >
          {done ? <Check className="size-4" /> : n}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-display text-lg font-medium">{step.title}</span>
            {done && <Pill tone="green">Done</Pill>}
            {skipped && <Pill>Skipped for now</Pill>}
            {next && <Pill tone="sun">Next</Pill>}
          </span>
          <span className="mt-0.5 block text-sm text-stone-600 dark:text-stone-400">{step.why}</span>
        </span>
      </button>
      {expanded && (
        <div id={bodyId} className="border-t border-stone-100 px-5 py-4 dark:border-stone-800">
          {children}
        </div>
      )}
    </li>
  );
}

function StepBody({ stepKey, state, go, onChange }: { stepKey: StepKey; state: Onboarding; go: (route: Route) => void; onChange: () => void }) {
  const agent = state.agent;
  const openStudio = agent ? (
    <Button variant="primary" onClick={() => { go({ page: "studio", agentId: agent.id }); }}>
      Open {agent.display_name} in the Studio
    </Button>
  ) : (
    <p className="text-sm text-stone-500">First create your agent (step 2).</p>
  );
  switch (stepKey) {
    case "model":
      return <ModelStep state={state} onChange={onChange} />;
    case "agent":
      return <AgentStep state={state} go={go} onChange={onChange} />;
    case "tool":
    case "helper":
      return (
        <div className="space-y-3">
          <p className="text-sm">{STEPS[stepKey].here}</p>
          {openStudio}
        </div>
      );
    case "try":
      return (
        <div className="space-y-3">
          <ul className="space-y-1.5 text-sm" data-testid="guide-tried">
            <Tick on={state.tried.tested}>Try it in a test chat (on the right of the Studio)</Tick>
            <Tick on={state.tried.published}>Publish it</Tick>
            <Tick on={state.tried.chatted}>Chat with it, for real</Tick>
          </ul>
          {state.tried.published && agent ? (
            <Button variant="primary" onClick={() => void chatWith(agent.name, go)}>
              <MessageSquarePlus aria-hidden className="size-4" /> Chat with {agent.display_name}
            </Button>
          ) : (
            openStudio
          )}
        </div>
      );
  }
}

function Tick({ on, children }: { on: boolean; children: ReactNode }) {
  return (
    <li className="flex items-center gap-2">
      <span aria-hidden className={`flex size-4 items-center justify-center rounded-full ${on ? "bg-emerald-600 text-white" : "border border-stone-300 dark:border-stone-600"}`}>
        {on && <Check className="size-3" />}
      </span>
      <span className={on ? "text-stone-500 line-through" : ""}>{children}</span>
      <span className="sr-only">{on ? "(done)" : "(to do)"}</span>
    </li>
  );
}

// ------------------------------------------------------------------ step 1

type Way = "ollama" | "key" | "demo";

function ModelStep({ state, onChange }: { state: Onboarding; onChange: () => void }) {
  const current = useDefaultModel();
  const refreshModels = useModelsRefresh();
  const [way, setWay] = useState<Way>("ollama");
  const [adding, setAdding] = useState<"ollama" | "key" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ollama = useQuery({ queryKey: ["models", "ollama"], queryFn: models.ollama, enabled: way === "ollama" });
  const done = state.steps.find((s) => s.key === "model")?.done ?? false;
  const makeDefault = (id: string, model: string) => {
    models
      .setDefault(id, model)
      .then(() => { refreshModels(); onChange(); })
      .catch((e: unknown) => { setError(problemText(e)); });
  };

  if (done) {
    const c = current.data?.connection;
    return (
      <p className="text-sm">
        Your agents use <strong>{c ? `${c.display_name} · ${current.data?.model ?? ""}` : "the model chosen in setup"}</strong>. You can add others or
        change it any time in Models.
      </p>
    );
  }
  const found = ollama.data?.[0];
  return (
    <div className="space-y-4">
      <Segmented
        label="Which model"
        value={way}
        onChange={setWay}
        options={[
          { value: "ollama", label: "Free, on this computer", hint: "Ollama" },
          { value: "key", label: "With a key", hint: "OpenAI, Azure, other" },
          { value: "demo", label: "Demo for now", hint: "Offline, simple rules" },
        ]}
      />
      {way === "ollama" &&
        (ollama.isPending ? (
          <Spinner label="Looking for Ollama on this computer…" />
        ) : found ? (
          <div className="space-y-2 text-sm" data-testid="ollama-found">
            <p>
              <Cpu aria-hidden className="mr-1 inline size-4 text-emerald-600" />
              Found Ollama{found.models.length ? ` with ${found.models.join(", ")}` : ", but no model pulled yet"}.
            </p>
            {found.models.length ? (
              <Button variant="primary" onClick={() => { setAdding("ollama"); }}>Use it</Button>
            ) : (
              <InstallOllama pullOnly onCheck={() => void ollama.refetch()} />
            )}
          </div>
        ) : (
          <InstallOllama onCheck={() => void ollama.refetch()} />
        ))}
      {way === "key" && (
        <div className="space-y-2 text-sm">
          <p>
            <Cloud aria-hidden className="mr-1 inline size-4" />
            Paste a key from OpenAI, an Azure AI Foundry deployment, or any OpenAI-compatible service. It's saved encrypted on this computer and never shown
            again.
          </p>
          <Button variant="primary" onClick={() => { setAdding("key"); }}>Add a model with a key</Button>
        </div>
      )}
      {way === "demo" && (
        <div className="space-y-2 text-sm">
          <p>
            The demo model works offline with a few simple rules (a calculator, notes, search, helpers), so you can see how everything fits. It doesn't
            really understand you; add a real model later in Models.
          </p>
          <Button onClick={() => { void guide.update({ skip_model: true }).then(onChange); }}>Use the demo model for now</Button>
        </div>
      )}
      {error && <p role="alert" className="text-sm text-rose-600">{error}</p>}
      {adding !== null && (
        <AddDialog
          open
          start={adding === "ollama" && found ? { kind: "ollama", url: found.base_url, models: found.models } : undefined}
          onClose={() => { setAdding(null); }}
          onReady={makeDefault}
        />
      )}
    </div>
  );
}

const PULL = "ollama pull qwen2.5:7b";

function platform(): "mac" | "windows" | "linux" {
  const ua = navigator.userAgent.toLowerCase();
  if (ua.includes("win")) return "windows";
  if (ua.includes("mac")) return "mac";
  return "linux";
}

function InstallOllama({ onCheck, pullOnly = false }: { onCheck: () => void; pullOnly?: boolean }) {
  const os = platform();
  const install = {
    mac: { text: "Download Ollama for macOS from ollama.com and open it, or with Homebrew:", command: "brew install ollama" },
    windows: { text: "Download Ollama for Windows from ollama.com and run the installer.", command: null },
    linux: { text: "Install it with:", command: "curl -fsSL https://ollama.com/install.sh | sh" },
  }[os];
  return (
    <div className="space-y-3 text-sm" data-testid="ollama-install">
      {!pullOnly && (
        <>
          <p>Ollama isn't running on this computer yet. It's free and keeps everything on your machine (about 6 GB of memory for a good model).</p>
          <p>
            1. {install.text}{" "}
            <a href="https://ollama.com/download" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline">
              ollama.com/download <ExternalLink aria-hidden className="size-3" />
            </a>
          </p>
          {install.command && <Command text={install.command} />}
        </>
      )}
      <p>{pullOnly ? "Pull a model that can use tools:" : "2. Then pull a model that can use tools:"}</p>
      <Command text={PULL} />
      <Button onClick={onCheck}>Check again</Button>
    </div>
  );
}

function Command({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2 rounded-xl bg-stone-900 px-3 py-2 font-mono text-[13px] text-stone-100 dark:bg-stone-950">
      <code className="min-w-0 flex-1 overflow-x-auto">{text}</code>
      <button
        type="button"
        aria-label={`Copy: ${text}`}
        className="rounded-md p-1 text-stone-400 hover:bg-stone-800 hover:text-white"
        onClick={() => {
          void navigator.clipboard.writeText(text).then(() => { setCopied(true); });
        }}
      >
        {copied ? <Check aria-hidden className="size-4" /> : <ClipboardCopy aria-hidden className="size-4" />}
      </button>
    </div>
  );
}

// ------------------------------------------------------------------ step 2

type Start = "describe" | "template" | "mine";

function AgentStep({ state, go, onChange }: { state: Onboarding; go: (route: Route) => void; onChange: () => void }) {
  const [start, setStart] = useState<Start>("describe");
  const [template, setTemplate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const templates = useQuery({ queryKey: ["agents"], queryFn: () => unwrap(api.GET("/agents")) });
  const mine = useStudioAgents();
  const refreshStudio = useStudioRefresh();
  if (state.agent) {
    const agent = state.agent;
    return (
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span>
          Your agent: <strong>{agent.display_name}</strong>
        </span>
        <Button size="sm" onClick={() => { go({ page: "studio", agentId: agent.id }); }}>Open it</Button>
      </div>
    );
  }
  const builtins = (templates.data ?? []).filter((a) => a.source === "builtin" && !a.hidden);
  const opened = (id: string) => {
    onChange();
    go({ page: "studio", agentId: id });
  };
  return (
    <div className="space-y-4">
      <Segmented
        label="How to start"
        value={start}
        onChange={setStart}
        options={[
          { value: "describe", label: "Describe it", hint: "Nuria drafts it" },
          { value: "template", label: "From a template", hint: "A built-in agent" },
          ...(mine.data?.length ? [{ value: "mine" as const, label: "One of yours", hint: "Already made" }] : []),
        ]}
      />
      {start === "describe" && <DescribeIt guide example={EXAMPLE} onCreated={opened} />}
      {start === "template" && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="min-w-0 flex-1 text-sm">
            <span className="mb-1.5 block font-medium">Template</span>
            <select
              value={template}
              onChange={(e) => { setTemplate(e.target.value); }}
              className="w-full rounded-xl border border-stone-200 bg-white px-3 py-2 text-[15px] dark:border-stone-700 dark:bg-stone-950"
            >
              <option value="">Choose one…</option>
              {builtins.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.display_name}: {t.description.slice(0, 70)}
                </option>
              ))}
            </select>
          </label>
          <Button
            variant="primary"
            disabled={!template}
            onClick={() => {
              const picked = builtins.find((t) => t.name === template);
              studio
                .create({ display_name: `My ${picked?.display_name ?? "agent"}`, description: "", copy_of: template }, true)
                .then((agent) => { refreshStudio(agent); opened(agent.id); })
                .catch((e: unknown) => { setError(problemText(e)); });
            }}
          >
            <Sparkles aria-hidden className="size-4" /> Make it mine
          </Button>
        </div>
      )}
      {start === "mine" && (
        <label className="block text-sm">
          <span className="mb-1.5 block font-medium">Your agents</span>
          <select
            defaultValue=""
            onChange={(e) => {
              const id = e.target.value;
              if (id) void guide.update({ agent_id: id }).then(() => { opened(id); });
            }}
            className="w-full rounded-xl border border-stone-200 bg-white px-3 py-2 text-[15px] dark:border-stone-700 dark:bg-stone-950"
          >
            <option value="">Choose one…</option>
            {(mine.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.display_name}
              </option>
            ))}
          </select>
        </label>
      )}
      {error && <p role="alert" className="text-sm text-rose-600">{error}</p>}
    </div>
  );
}
