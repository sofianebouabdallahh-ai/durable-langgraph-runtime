/**
 * Phases L4a and L7b with the observability profile up (`./setup.sh --observability`);
 * skipped otherwise. In containers: a chat turn's trace reaches Tempo with the API's and
 * the worker's spans (AC8), its log lines reach Loki under the same trace id, Grafana
 * links the two both ways (SC2), "Open the trace" and "Its log lines" open them, and
 * Prometheus scrapes every replica.
 */
import { expect, test, type APIRequestContext } from "@playwright/test";

import { getJson, startChat, transcript, waitTurnOver } from "./support";

// Inside the Compose network, as the e2e container sees the services.
const TEMPO = process.env.TEMPO_URL ?? "http://tempo:3200";
const LOKI = process.env.LOKI_URL ?? "http://loki:3100";
const GRAFANA = process.env.GRAFANA_URL ?? "http://grafana:3000";
const PROMETHEUS = process.env.PROMETHEUS_URL ?? "http://prometheus:9090";

interface About { tracing: boolean; trace_ui_url: string | null; dashboard_url: string | null }

async function about(request: APIRequestContext): Promise<About> {
  return getJson<About>(request, "/api/about");
}

test.beforeEach(async ({ request }) => {
  test.skip(!(await about(request)).tracing, "needs the observability profile (./setup.sh --observability)");
});

type Attr = { key: string; value: { stringValue?: string } };
interface ResourceSpans { resource: { attributes: Attr[] }; scopeSpans: { spans: { name: string }[] }[] }

/** The trace's spans, as Tempo has them: (service, span name). */
async function traceSpans(request: APIRequestContext, traceId: string): Promise<{ service: string; name: string }[]> {
  const resp = await request.get(`${TEMPO}/api/v2/traces/${traceId}`, { headers: { Accept: "application/json" } });
  if (!resp.ok()) return [];
  const body = (await resp.json()) as { trace?: { resourceSpans?: ResourceSpans[] } };
  return (body.trace?.resourceSpans ?? []).flatMap((rs) => {
    const service = rs.resource.attributes.find((a) => a.key === "service.name")?.value.stringValue ?? "";
    return rs.scopeSpans.flatMap((ss) => ss.spans.map((s) => ({ service, name: s.name })));
  });
}

/** Log lines in Loki for a LogQL query over the last hour: their labels and text. */
async function logLines(request: APIRequestContext, query: string): Promise<{ labels: Record<string, string>; line: string }[]> {
  const start = String((Date.now() - 3_600_000) * 1_000_000);
  const resp = await request.get(`${LOKI}/loki/api/v1/query_range`, { params: { query, start, limit: "500" } });
  if (!resp.ok()) return [];
  const body = (await resp.json()) as { data: { result: { stream: Record<string, string>; values: [string, string][] }[] } };
  return body.data.result.flatMap((r) => r.values.map(([, line]) => ({ labels: r.stream, line })));
}

/** A link built for the browser's Grafana (localhost), opened at the e2e network's. */
function inNetwork(link: string | null, about_: About): string {
  return (link ?? "").replace((about_.trace_ui_url ?? "").replace(/\/+$/, ""), GRAFANA);
}

test("a turn's trace in Tempo, its log lines in Loki, linked both ways and opened from “What happened?”", async ({ page, request }) => {
  const sid = await startChat(page, "What is 12 * (3 + 4)?");
  await expect(page.getByTestId("assistant-message").last()).toContainText("84");
  await waitTurnOver(request, sid);
  const runId = (await transcript(request, sid)).find((m) => m.run_id)?.run_id;
  expect(runId).toBeTruthy();
  const run = await getJson<{ trace_id: string | null }>(request, `/api/runs/${runId}`);
  const traceId = run.trace_id ?? "";
  expect(traceId).toMatch(/^[0-9a-f]{32}$/);

  // AC8: the request (api) and the turn's execution (worker), with its model and tool calls.
  await expect.poll(async () => {
    const spans = await traceSpans(request, traceId);
    return {
      services: [...new Set(spans.map((s) => s.service))].sort(),
      run: spans.some((s) => s.name === "run"),
      llm: spans.some((s) => s.name === "llm.call"),
      tool: spans.some((s) => s.name.startsWith("tool:")),
    };
  }, { timeout: 60_000 }).toEqual({ services: ["api", "worker"], run: true, llm: true, tool: true });

  // SC2: the same trace id finds the turn's log lines, from the API and the worker.
  await expect.poll(async () => {
    const lines = await logLines(request, `{service_name=~".+"} | trace_id="${traceId}"`);
    return [...new Set(lines.map((l) => l.labels.service_name))].sort();
  }, { timeout: 60_000 }).toEqual(["api", "worker"]);
  const turn = await logLines(request, `{service_name="worker"} | run_id="${runId}"`);
  expect(turn.some((l) => l.line.startsWith("model call:") && l.labels.session_id === sid)).toBe(true);

  // Grafana links them both ways (provisioned): trace → its lines, line → its trace.
  const settings = await getJson<{ datasources: Record<string, { uid: string; jsonData: Record<string, unknown> }> }>(
    request, `${GRAFANA}/api/frontend/settings`,
  );
  const byUid = Object.fromEntries(Object.values(settings.datasources).map((d) => [d.uid, d.jsonData]));
  expect(byUid.tempo?.tracesToLogsV2).toMatchObject({ datasourceUid: "loki", customQuery: true });
  expect(byUid.loki?.derivedFields).toEqual(
    expect.arrayContaining([expect.objectContaining({ datasourceUid: "tempo", matcherType: "label", matcherRegex: "trace_id" })]),
  );

  // "What happened?": both links, and they open in Grafana.
  await page.getByRole("button", { name: "What happened?" }).click();
  const a = await about(request);
  const traceHref = await page.getByTestId("open-trace").getAttribute("href");
  const logsHref = await page.getByTestId("open-logs").getAttribute("href");
  expect(traceHref).toContain(encodeURIComponent(traceId));
  expect(logsHref).toContain(encodeURIComponent(runId ?? ""));
  await expect(page.getByTestId("open-trace")).toHaveAttribute("target", "_blank");
  await expect(page.getByTestId("what-happened")).toContainText(`trace ${traceId.slice(0, 8)}`);

  const grafana = await page.context().newPage();
  await grafana.goto(inNetwork(traceHref, a));
  await expect(grafana.getByText("llm.call").first()).toBeVisible({ timeout: 60_000 });
  await grafana.goto(inNetwork(logsHref, a));
  await expect(grafana.getByText(/model call:/).first()).toBeVisible({ timeout: 60_000 });
});

test("the sidebar opens the dashboard; Prometheus scrapes every API replica and worker", async ({ page, request }) => {
  await page.goto("/");
  const { dashboard_url } = await about(request);
  await expect(page.getByTestId("dashboard-link")).toHaveAttribute("href", dashboard_url ?? "");

  interface Targets { data: { activeTargets: { labels: { job: string }; health: string }[] } }
  await expect.poll(async () => {
    const body = (await (await request.get(`${PROMETHEUS}/api/v1/targets`)).json()) as Targets;
    const up = (job: string) => body.data.activeTargets.filter((t) => t.labels.job === job && t.health === "up").length;
    return { api: up("api") >= 1, worker: up("worker") >= 1 };
  }, { timeout: 30_000 }).toEqual({ api: true, worker: true });
});
