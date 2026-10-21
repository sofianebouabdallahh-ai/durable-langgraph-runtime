/**
 * Links into Grafana Explore, when the installation exports traces and logs (L4a, L7b):
 * "Open the trace" (Tempo) and "Its log lines" (Loki). `trace_ui_url` is that Grafana.
 * Only ids we've checked go into a link.
 */
type About = { tracing?: boolean; trace_ui_url?: string | null } | undefined;

const TRACE_ID = /^[0-9a-f]{32}$/;
const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function explore(base: string, type: string, query: Record<string, string>): string {
  const panes = {
    a: { datasource: type, queries: [{ refId: "A", datasource: { type, uid: type }, ...query }], range: { from: "now-7d", to: "now" } },
  };
  return `${base.replace(/\/+$/, "")}/explore?schemaVersion=1&orgId=1&panes=${encodeURIComponent(JSON.stringify(panes))}`;
}

/** "Open the trace": the run's trace in Tempo. */
export function traceLink(about: About, traceId: string | null | undefined): string | null {
  if (!about?.tracing || !about.trace_ui_url || !traceId || !TRACE_ID.test(traceId)) return null;
  return explore(about.trace_ui_url, "tempo", { queryType: "traceql", query: traceId });
}

/** "Its log lines": every line the run wrote (worker, helpers, tools), in Loki. */
export function logsLink(about: About, runId: string | null | undefined): string | null {
  if (!about?.tracing || !about.trace_ui_url || !runId || !RUN_ID.test(runId)) return null;
  return explore(about.trace_ui_url, "loki", { expr: `{service_name=~".+"} | run_id="${runId}"` });
}
