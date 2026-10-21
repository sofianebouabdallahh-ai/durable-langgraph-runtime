/**
 * Activity (phase L7): what all agents have been doing. From the database, so it works
 * without the observability stack. Filters (range, agent, test chats) sit in one row
 * above everything and scope every number, chart and list below.
 */
import { useInfiniteQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CircleDollarSign, Clock, History, Hourglass, MessageSquare, Power, ThumbsDown, ThumbsUp, Wrench } from "lucide-react";
import { type ReactNode, useState } from "react";

import { href } from "../app/route";
import { useKillSwitch } from "../safety/KillSwitch";
import { Segmented } from "../ui/form";
import { Pill, Spinner } from "../ui/primitives";
import { agentLabel, failureReason, toolName } from "../ui/words";
import { type Activity, type Filters, type Range, type Turn, turnsPage, useActivity, useSessions } from "./api";
import { type Column, Columns, compact, Meter, type Series } from "./charts";

const RANGES: readonly { value: Range; label: string }[] = [
  { value: "24h", label: "24 hours" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
];
const SLOTS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)"];

export const money = (n: number) => (n === 0 ? "$0" : n < 0.01 ? "<$0.01" : `$${n.toFixed(2)}`);
export const seconds = (s: number | null | undefined) =>
  s == null ? "—" : s < 60 ? `${s.toFixed(1)} s` : `${String(Math.floor(s / 60))} min ${String(Math.round(s % 60))} s`;
const when = (iso: string) => new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
// Days are UTC days (as the API counts them), so a turn's day is the same for everyone.
const day = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString([], { month: "short", day: "numeric", timeZone: "UTC" });

export function ActivityPage() {
  const [filters, setFilters] = useState<Filters>({ range: "7d", agent: null, tests: false });
  const activity = useActivity(filters);
  const data = activity.data;
  return (
    <div className="mx-auto max-w-6xl px-6 py-10" data-testid="activity">
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="font-display text-4xl font-medium tracking-tight">Activity</h1>
        <a href={href({ page: "audit" })} className="mb-1 ml-auto inline-flex items-center gap-1.5 text-sm font-medium text-stone-600 underline-offset-2 hover:underline dark:text-stone-300" data-testid="audit-link">
          <History aria-hidden className="size-4" /> Who changed what
        </a>
      </div>
      <p className="mt-2 max-w-2xl text-stone-500 dark:text-stone-400">What your agents have been doing: every chat and turn, what they used, what it cost, and what went wrong.</p>

      <div className="mt-6 flex flex-wrap items-end gap-4" data-testid="activity-filters">
        <div className="w-full sm:w-80">
          <Segmented compact label="Range" value={filters.range} options={RANGES} onChange={(range) => { setFilters({ ...filters, range }); }} />
        </div>
        <label className="text-sm">
          <span className="mb-1.5 block font-medium">Agent</span>
          <select
            value={filters.agent ?? ""}
            onChange={(e) => { setFilters({ ...filters, agent: e.target.value || null }); }}
            className="h-10 rounded-xl border border-stone-200 bg-white px-3 dark:border-stone-700 dark:bg-stone-950"
          >
            <option value="">All agents</option>
            {(data?.agents ?? []).map((a) => (
              <option key={a.agent} value={a.agent}>{agentLabel(a.agent)}</option>
            ))}
            {filters.agent && !data?.agents.some((a) => a.agent === filters.agent) && <option value={filters.agent}>{agentLabel(filters.agent)}</option>}
          </select>
        </label>
        <label className="flex h-10 items-center gap-2 text-sm">
          <input type="checkbox" checked={filters.tests} onChange={(e) => { setFilters({ ...filters, tests: e.target.checked }); }} />
          Include test chats
        </label>
      </div>

      {!data ? (
        <Spinner className="mt-10" label="Loading activity…" />
      ) : (
        <div className={`mt-8 space-y-8 transition-opacity ${activity.isPlaceholderData ? "opacity-60" : ""}`}>
          <Now data={data} />
          <Totals data={data} />
          <Over data={data} />
          <Breakdowns data={data} onAgent={(agent) => { setFilters({ ...filters, agent }); }} />
          <Errors data={data} />
          <Sessions filters={filters} />
          <Turns filters={filters} />
        </div>
      )}
    </div>
  );
}

function Card({ title, children, testId, aside }: { title: string; children: ReactNode; testId?: string; aside?: ReactNode }) {
  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-soft dark:border-stone-800 dark:bg-stone-900" data-testid={testId}>
      <div className="mb-3 flex items-center gap-2">
        <h2 className="font-display text-lg font-medium">{title}</h2>
        {aside && <div className="ml-auto">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

function Stat({ label, value, sub, icon, testId }: { label: string; value: string; sub?: string | undefined; icon?: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId} className="rounded-xl border border-stone-200 bg-white px-4 py-3 dark:border-stone-800 dark:bg-stone-900">
      <div className="flex items-center gap-1.5 text-xs text-stone-500">{icon}{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums" data-value>{value}</div>
      {sub && <div className="text-xs text-stone-500">{sub}</div>}
    </div>
  );
}

function Now({ data }: { data: Activity }) {
  const switches = useKillSwitch();
  const off = switches.data?.agents ?? [];
  const n = data.now;
  return (
    <Card title="Right now" testId="activity-now">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Running" value={String(n.running)} icon={<Clock aria-hidden className="size-3.5" />} />
        <Stat label="Waiting for you" value={String(n.waiting_approval)} icon={<Hourglass aria-hidden className="size-3.5" />} />
        <Stat label="Queued" value={String(n.queued)} />
        <Stat label="Spend today" value={money(n.spend_today)} icon={<CircleDollarSign aria-hidden className="size-3.5" />} />
        <Stat
          label="Switched off"
          value={switches.data?.all_off ? "Every agent" : String(off.length)}
          sub={off.map((s) => agentLabel(s.agent)).join(", ") || undefined}
          icon={<Power aria-hidden className="size-3.5" />}
        />
      </div>
      {n.waiting.length > 0 && (
        <ul className="mt-4 space-y-1.5 text-sm" data-testid="activity-waiting">
          {n.waiting.map((w) => (
            <li key={w.run_id} className="flex items-center gap-2">
              <Hourglass aria-hidden className="size-4 text-amber-500" />
              <span>
                {agentLabel(w.agent)} wants to use <strong>{w.tool ? toolName(w.tool) : "a tool"}</strong>
              </span>
              {w.session_id && (
                <a href={href({ page: "chat", sessionId: w.session_id })} className="ml-auto inline-flex items-center gap-1 text-sm font-medium underline-offset-2 hover:underline">
                  Open the chat <ArrowRight aria-hidden className="size-3.5" />
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Totals({ data }: { data: Activity }) {
  const t = data.totals;
  const rate = t.turns ? `${String(Math.round((t.failed / t.turns) * 100))}% failed` : undefined;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6" data-testid="activity-totals">
      <Stat testId="stat-turns" label="Turns" value={compact(t.turns)} sub={rate} icon={<MessageSquare aria-hidden className="size-3.5" />} />
      <Stat label="Chats" value={compact(t.chats)} />
      <Stat label="Tokens" value={compact(t.tokens)} sub={`${compact(t.model_calls)} model calls`} />
      <Stat label="Cost" value={money(t.cost)} />
      <Stat label="Tool calls" value={compact(t.tool_calls)} sub={t.helpers ? `${compact(t.helpers)} helper runs` : undefined} icon={<Wrench aria-hidden className="size-3.5" />} />
      <Stat label="Approvals" value={compact(t.approvals.asked)} sub={`${String(t.approvals.approved)} approved · ${String(t.approvals.rejected)} rejected`} />
    </div>
  );
}

/** The top five agents keep their colour (by name, in a stable order); the rest are "Other". */
function agentSeries(data: Activity): Series[] {
  const named = [...data.agents].sort((a, b) => a.agent.localeCompare(b.agent));
  const top = [...data.agents].sort((a, b) => b.turns - a.turns).slice(0, SLOTS.length).map((a) => a.agent);
  const kept = named.filter((a) => top.includes(a.agent));
  const series: Series[] = kept.map((a, i) => ({ key: a.agent, label: agentLabel(a.agent), color: SLOTS[i] ?? "var(--series-other)" }));
  if (data.agents.length > kept.length) series.push({ key: "__other", label: "Other", color: "var(--series-other)" });
  return series;
}

function Over({ data }: { data: Activity }) {
  const series = agentSeries(data);
  const kept = new Set(series.map((s) => s.key));
  const turns: Column[] = data.days.map((d) => {
    const values: Record<string, number> = {};
    for (const [agent, n] of Object.entries(d.by_agent)) {
      const key = kept.has(agent) ? agent : "__other";
      values[key] = (values[key] ?? 0) + n;
    }
    return { key: d.day, label: day(d.day), values };
  });
  const cost: Column[] = data.days.map((d) => ({ key: d.day, label: day(d.day), values: { cost: d.cost } }));
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card title="Over time" testId="activity-turns-chart">
        <Columns title="Turns per day, by agent" columns={turns} series={series} />
      </Card>
      <Card title="Spend" testId="activity-cost-chart">
        <Columns title="Cost per day" columns={cost} series={[{ key: "cost", label: "Cost", color: "var(--series-1)" }]} format={money} />
      </Card>
    </div>
  );
}

const th = "py-2 pr-4 text-left text-xs font-medium text-stone-500";
const td = "py-2 pr-4 tabular-nums";

function Breakdowns({ data, onAgent }: { data: Activity; onAgent: (agent: string) => void }) {
  const maxTurns = Math.max(0, ...data.agents.map((a) => a.turns));
  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Card title="Agents" testId="activity-agents">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr><th className={th}>Agent</th><th className={th}>Turns</th><th className={th}>Failed</th><th className={th}>Median · p95</th><th className={th}>Tokens</th><th className={th}>Cost</th><th className={th}>Rated</th></tr></thead>
            <tbody>
              {data.agents.map((a) => (
                <tr key={a.agent} className="border-t border-stone-100 dark:border-stone-800">
                  <td className="py-2 pr-4">
                    <button type="button" className="text-left font-medium underline-offset-2 hover:underline" onClick={() => { onAgent(a.agent); }} title="Show only this agent">
                      {agentLabel(a.agent)}
                    </button>
                  </td>
                  <td className={td}><span className="mr-2">{a.turns}</span><Meter value={a.turns} max={maxTurns} label={`${String(a.turns)} turns`} /></td>
                  <td className={td}>{a.failed ? <Pill tone="rose">{a.failed}</Pill> : "0"}</td>
                  <td className={td}>{seconds(a.p50_s)} · {seconds(a.p95_s)}</td>
                  <td className={td}>{compact(a.tokens)}</td>
                  <td className={td}>{money(a.cost)}</td>
                  <td className={td} data-testid="agent-rated">
                    {a.liked + a.disliked === 0 ? (
                      "—"
                    ) : (
                      <span className="inline-flex items-center gap-2">
                        <span className="inline-flex items-center gap-0.5" title="Good replies"><ThumbsUp aria-label="Good replies" className="size-3.5" /> {a.liked}</span>
                        <span className="inline-flex items-center gap-0.5" title="Bad replies"><ThumbsDown aria-label="Bad replies" className="size-3.5" /> {a.disliked}</span>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
              {data.agents.length === 0 && <tr><td colSpan={7} className="py-4 text-stone-500">No turns in this range.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="space-y-5">
        <Card title="Models" testId="activity-models">
          <table className="w-full text-sm">
            <thead><tr><th className={th}>Model</th><th className={th}>Calls</th><th className={th}>Tokens in · out</th><th className={th}>Avg time</th><th className={th}>Cost</th></tr></thead>
            <tbody>
              {data.models.map((m) => (
                <tr key={m.model} className="border-t border-stone-100 dark:border-stone-800">
                  <td className="py-2 pr-4 font-mono text-[13px]">{m.model}</td>
                  <td className={td}>{compact(m.calls)}</td>
                  <td className={td}>{compact(m.tokens_in)} · {compact(m.tokens_out)}</td>
                  <td className={td}>{m.avg_ms == null ? "—" : seconds(m.avg_ms / 1000)}</td>
                  <td className={td}>{money(m.cost)}</td>
                </tr>
              ))}
              {data.models.length === 0 && <tr><td colSpan={5} className="py-4 text-stone-500">No model calls in this range.</td></tr>}
            </tbody>
          </table>
        </Card>
        <Card title="Tools" testId="activity-tools">
          <table className="w-full text-sm">
            <thead><tr><th className={th}>Tool</th><th className={th}>Calls</th><th className={th}>Failed</th><th className={th}>Reused</th><th className={th}>p95</th></tr></thead>
            <tbody>
              {data.tools.map((t) => (
                <tr key={t.tool ?? "?"} className="border-t border-stone-100 dark:border-stone-800">
                  <td className="py-2 pr-4">{t.tool ? toolName(t.tool) : "?"}</td>
                  <td className={td}>{compact(t.calls)}</td>
                  <td className={td}>{t.failed ? <Pill tone="rose">{t.failed}</Pill> : "0"}</td>
                  <td className={td}>{t.cached}</td>
                  <td className={td}>{t.p95_ms == null ? "—" : seconds(t.p95_ms / 1000)}</td>
                </tr>
              ))}
              {data.tools.length === 0 && <tr><td colSpan={5} className="py-4 text-stone-500">No tool calls in this range.</td></tr>}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}

function Errors({ data }: { data: Activity }) {
  if (data.errors.length === 0) return null;
  return (
    <Card title="What went wrong" testId="activity-errors">
      <ul className="divide-y divide-stone-100 text-sm dark:divide-stone-800">
        {data.errors.map((e) => (
          <li key={`${e.reason ?? ""}:${e.agent}`} className="flex flex-wrap items-center gap-3 py-2">
            <AlertTriangle aria-hidden className="size-4 text-rose-500" />
            <span className="font-medium">{failureReason(e.reason)}</span>
            <span className="text-stone-500">{agentLabel(e.agent)} · {e.count} {e.count === 1 ? "time" : "times"}</span>
            <a href={href({ page: "turn", runId: e.run_id })} className="ml-auto inline-flex items-center gap-1 font-medium underline-offset-2 hover:underline">
              The latest <ArrowRight aria-hidden className="size-3.5" />
            </a>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Sessions({ filters }: { filters: Filters }) {
  const sessions = useSessions(filters);
  return (
    <Card title="Chats" testId="activity-sessions">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr><th className={th}>Chat</th><th className={th}>Agent</th><th className={th}>Turns</th><th className={th}>Messages</th><th className={th}>Tokens</th><th className={th}>Cost</th><th className={th}>Last activity</th></tr></thead>
          <tbody>
            {(sessions.data ?? []).map((s) => (
              <tr key={s.id} className="border-t border-stone-100 dark:border-stone-800">
                <td className="py-2 pr-4">
                  <a href={href({ page: "chat", sessionId: s.id })} className="font-medium underline-offset-2 hover:underline">{s.title ?? "New chat"}</a>
                  {s.test && <Pill className="ml-2">test</Pill>}
                </td>
                <td className="py-2 pr-4">{agentLabel(s.agent)}</td>
                <td className={td}>{s.turns}{s.failed > 0 && <span className="ml-1 text-rose-600">({s.failed} failed)</span>}</td>
                <td className={td}>{s.messages}</td>
                <td className={td}>{compact(s.tokens)}</td>
                <td className={td}>{money(s.cost)}</td>
                <td className="py-2 pr-4 text-stone-500">{when(s.last_activity_at)}</td>
              </tr>
            ))}
            {sessions.data?.length === 0 && <tr><td colSpan={7} className="py-4 text-stone-500">No chats in this range.</td></tr>}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function statusPill(t: Turn) {
  if (t.status === "completed") return <Pill tone="green">Done</Pill>;
  if (t.status === "failed") return <Pill tone="rose">{failureReason(t.reason)}</Pill>;
  if (t.status === "cancelled") return <Pill>Stopped</Pill>;
  if (t.status === "waiting_approval") return <Pill tone="amber">Waiting for you</Pill>;
  return <Pill tone="sun">{t.status === "running" ? "Running" : "Queued"}</Pill>;
}

function Turns({ filters }: { filters: Filters }) {
  const turns = useInfiniteQuery({
    queryKey: ["activity", "turns", filters],
    queryFn: ({ pageParam }) => turnsPage(filters, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => (last.length === 25 ? last[last.length - 1]?.created_at : undefined),
  });
  const rows = turns.data?.pages.flat() ?? [];
  return (
    <Card title="Turns" testId="activity-turns">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr><th className={th}>When</th><th className={th}>Agent</th><th className={th}>Outcome</th><th className={th}>Model</th><th className={th}>Steps · tools</th><th className={th}>Tokens</th><th className={th}>Cost</th><th className={th}>Time</th></tr></thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id} className="border-t border-stone-100 dark:border-stone-800" data-testid="activity-turn">
                <td className="py-2 pr-4"><a href={href({ page: "turn", runId: t.id })} className="font-medium underline-offset-2 hover:underline">{when(t.created_at)}</a></td>
                <td className="py-2 pr-4">{agentLabel(t.agent)}{t.agent_version ? <span className="text-stone-500"> v{t.agent_version}</span> : null}</td>
                <td className="py-2 pr-4">{statusPill(t)}{t.reclaims > 0 && <span className="ml-1 text-xs text-amber-600">taken over ×{t.reclaims}</span>}</td>
                <td className="py-2 pr-4 font-mono text-[12px]">{t.models.join(", ") || "—"}</td>
                <td className={td}>{t.steps} · {t.tool_calls}</td>
                <td className={td}>{compact(t.tokens)}</td>
                <td className={td}>{money(t.cost)}</td>
                <td className={td}>{seconds(t.duration_s)}</td>
              </tr>
            ))}
            {turns.isSuccess && rows.length === 0 && <tr><td colSpan={8} className="py-4 text-stone-500">No turns in this range.</td></tr>}
          </tbody>
        </table>
      </div>
      {turns.hasNextPage && (
        <button type="button" className="mt-3 text-sm font-medium underline-offset-2 hover:underline" onClick={() => void turns.fetchNextPage()} disabled={turns.isFetchingNextPage}>
          {turns.isFetchingNextPage ? "Loading…" : "Show more"}
        </button>
      )}
    </Card>
  );
}
