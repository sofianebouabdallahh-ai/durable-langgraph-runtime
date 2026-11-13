/**
 * Who changed what (phase L7d): the audit trail, newest first. Every change to agents,
 * skills, models, settings, the kill switch and approvals, with what it was before and
 * after. Read-only: nothing can change or delete it. Download gives the same as CSV.
 */
import { useInfiniteQuery } from "@tanstack/react-query";
import { ArrowLeft, Download } from "lucide-react";
import { useState } from "react";

import { API_BASE, api, type Schemas, unwrap } from "../api/client";
import { href } from "../app/route";
import { Spinner } from "../ui/primitives";

type Row = Schemas["AuditRow"];

/** Each action, in plain words (and the filter's options, in this order). */
export const ACTIONS: Record<string, string> = {
  "approval.decided": "Approved or rejected a tool call",
  "kill_switch.on": "Switched an agent off",
  "kill_switch.off": "Switched an agent back on",
  "agent.created": "Created an agent",
  "agent.imported": "Imported an agent",
  "agent.published": "Published an agent",
  "agent.restored": "Restored an earlier version",
  "agent.archived": "Archived an agent",
  "skill.created": "Added a skill",
  "skill.updated": "Changed a skill",
  "skill.archived": "Archived a skill",
  "skill.approved": "Marked a skill as read",
  "model_connection.added": "Added a model",
  "model_connection.changed": "Changed a model",
  "model_connection.removed": "Removed a model",
  "default_model.changed": "Changed the default model",
  "tool_settings.changed": "Changed tool settings",
  "usage_sharing.changed": "Changed usage sharing",
  "mcp_server.added": "Added an MCP server",
  "mcp_server.changed": "Changed an MCP server",
  "mcp_server.removed": "Removed an MCP server",
  "mcp_tool.enabled": "Switched on an MCP tool",
  "mcp_tool.disabled": "Switched off an MCP tool",
  "mcp_tool.approved_change": "Approved a changed MCP tool",
};

const PAGE = 50;

function target(r: Row): string {
  if (r.target_id === "*") return "every agent";
  return r.target_id ?? r.target_type;
}

const shown = (v: unknown): string => (v === null || v === undefined ? "—" : typeof v === "string" ? v : JSON.stringify(v));

/** What changed: "key: before → after" for the keys that differ, or the new values. */
export function changes(before: Row["before"], after: Row["after"]): string[] {
  const keys = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])];
  return keys.flatMap((k) => {
    const was = before?.[k];
    const now = after?.[k];
    if (JSON.stringify(was) === JSON.stringify(now)) return [];
    if (before == null) return [`${k}: ${shown(now)}`];
    if (after == null) return [`${k} was ${shown(was)}`];
    return [`${k}: ${shown(was)} → ${shown(now)}`];
  });
}

export function AuditPage() {
  const [action, setAction] = useState("");
  const rows = useInfiniteQuery({
    queryKey: ["audit", action],
    queryFn: ({ pageParam }) =>
      unwrap(api.GET("/audit", { params: { query: { action: action || null, before: pageParam ?? null, limit: PAGE } } })),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => (last.length === PAGE ? last[last.length - 1]?.at : undefined),
  });
  const all = rows.data?.pages.flat() ?? [];
  const csv = `${API_BASE}/audit.csv${action ? `?action=${encodeURIComponent(action)}` : ""}`;

  return (
    <div className="mx-auto max-w-5xl px-6 py-10" data-testid="audit">
      <a href={href({ page: "activity" })} className="inline-flex items-center gap-1 text-sm text-stone-500 hover:text-stone-900 dark:hover:text-stone-100">
        <ArrowLeft aria-hidden className="size-4" /> Activity
      </a>
      <h1 className="mt-3 font-display text-4xl font-medium tracking-tight">Who changed what</h1>
      <p className="mt-2 max-w-2xl text-stone-500 dark:text-stone-400">
        Every change to agents, skills, models, settings and the kill switch, and every approval, with what it was before. Nothing here can be edited or deleted. Keys never
        appear: only that one was set.
      </p>

      <div className="mt-6 flex flex-wrap items-end gap-4">
        <label className="text-sm">
          <span className="mb-1.5 block font-medium">What</span>
          <select
            value={action}
            onChange={(e) => { setAction(e.target.value); }}
            className="h-10 rounded-xl border border-stone-200 bg-white px-3 dark:border-stone-700 dark:bg-stone-950"
          >
            <option value="">Every change</option>
            {Object.entries(ACTIONS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <a href={csv} download className="ml-auto inline-flex h-10 items-center gap-1.5 rounded-xl border border-stone-200 px-3 text-sm font-medium hover:bg-stone-50 dark:border-stone-700 dark:hover:bg-stone-900" data-testid="audit-download">
          <Download aria-hidden className="size-4" /> Download (CSV)
        </a>
      </div>

      {rows.isPending ? (
        <Spinner className="mt-10" label="Loading…" />
      ) : (
        <div className="mt-6 overflow-x-auto rounded-2xl border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-stone-500">
                <th className="px-4 py-2.5 font-medium">When</th>
                <th className="px-4 py-2.5 font-medium">What</th>
                <th className="px-4 py-2.5 font-medium">Of</th>
                <th className="px-4 py-2.5 font-medium">Change</th>
              </tr>
            </thead>
            <tbody>
              {all.map((r) => (
                <tr key={r.id} className="border-t border-stone-100 align-top dark:border-stone-800" data-testid="audit-row" data-action={r.action}>
                  <td className="whitespace-nowrap px-4 py-2.5 text-stone-500" title={r.request_id ? `request ${r.request_id}` : undefined}>
                    {new Date(r.at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 font-medium">{ACTIONS[r.action] ?? r.action}</td>
                  <td className="px-4 py-2.5 font-mono text-[12px]">{target(r)}</td>
                  <td className="px-4 py-2.5 text-stone-600 dark:text-stone-300">
                    <ul className="space-y-0.5">
                      {changes(r.before, r.after).map((c) => (
                        <li key={c} className="break-all">{c}</li>
                      ))}
                    </ul>
                  </td>
                </tr>
              ))}
              {all.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-stone-500">Nothing yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {rows.hasNextPage && (
        <button type="button" className="mt-3 text-sm font-medium underline-offset-2 hover:underline" onClick={() => void rows.fetchNextPage()} disabled={rows.isFetchingNextPage}>
          {rows.isFetchingNextPage ? "Loading…" : "Show more"}
        </button>
      )}
    </div>
  );
}
