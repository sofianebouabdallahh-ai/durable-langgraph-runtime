/** "Open the trace": a run's trace in Jaeger, when the installation exports traces (L4a). */
export function traceLink(
  about: { tracing?: boolean; trace_ui_url?: string | null } | undefined,
  traceId: string | null | undefined,
): string | null {
  if (!about?.tracing || !about.trace_ui_url || !traceId || !/^[0-9a-f]{32}$/.test(traceId)) return null;
  return `${about.trace_ui_url.replace(/\/+$/, "")}/trace/${traceId}`;
}
