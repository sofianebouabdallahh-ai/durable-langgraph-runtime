/**
 * Phase L4a with the observability profile up (`./setup.sh --observability`); skipped
 * otherwise. AC8 in containers: a chat turn's trace reaches Jaeger with the API's and
 * the worker's spans, "Open the trace" links to it, and Prometheus scrapes every replica.
 */
import { expect, test, type APIRequestContext } from "@playwright/test";

import { getJson, startChat, transcript, waitTurnOver } from "./support";

// Inside the Compose network, as the e2e container sees the services.
const JAEGER = process.env.JAEGER_URL ?? "http://jaeger:16686";
const PROMETHEUS = process.env.PROMETHEUS_URL ?? "http://prometheus:9090";

interface About { tracing: boolean; trace_ui_url: string | null; dashboard_url: string | null }

async function about(request: APIRequestContext): Promise<About> {
  return getJson<About>(request, "/api/about");
}

test.beforeEach(async ({ request }) => {
  test.skip(!(await about(request)).tracing, "needs the observability profile (./setup.sh --observability)");
});

interface OtlpSpan { name: string; spanId: string; parentSpanId?: string }
interface Otlp { result: { resourceSpans: { resource: { attributes: { key: string; value: { stringValue?: string } }[] }; scopeSpans: { spans: OtlpSpan[] }[] }[] } }

async function traceSpans(request: APIRequestContext, traceId: string): Promise<{ service: string; name: string }[]> {
  const resp = await request.get(`${JAEGER}/api/v3/traces/${traceId}`);
  if (!resp.ok()) return [];
  const body = (await resp.json()) as Otlp;
  return body.result.resourceSpans.flatMap((rs) => {
    const service = rs.resource.attributes.find((a) => a.key === "service.name")?.value.stringValue ?? "";
    return rs.scopeSpans.flatMap((ss) => ss.spans.map((s) => ({ service, name: s.name })));
  });
}

test("a turn's trace: API and worker spans in Jaeger, opened from “What happened?”", async ({ page, request }) => {
  const sid = await startChat(page, "What is 12 * (3 + 4)?");
  await expect(page.getByTestId("assistant-message").last()).toContainText("84");
  await waitTurnOver(request, sid);
  const runId = (await transcript(request, sid)).find((m) => m.run_id)?.run_id;
  expect(runId).toBeTruthy();
  const run = await getJson<{ trace_id: string | null }>(request, `/api/runs/${runId}`);
  expect(run.trace_id).toMatch(/^[0-9a-f]{32}$/);

  // AC8: the request (api) and the turn's execution (worker), with its model and tool calls.
  await expect.poll(async () => {
    const spans = await traceSpans(request, run.trace_id!);
    return {
      services: [...new Set(spans.map((s) => s.service))].sort(),
      run: spans.some((s) => s.name === "run"),
      llm: spans.some((s) => s.name === "llm.call"),
      tool: spans.some((s) => s.name === "tool:calculator"),
    };
  }, { timeout: 30_000 }).toEqual({ services: ["api", "worker"], run: true, llm: true, tool: true });

  await page.getByRole("button", { name: "What happened?" }).click();
  const link = page.getByTestId("open-trace");
  await expect(link).toBeVisible();
  const { trace_ui_url } = await about(request);
  await expect(link).toHaveAttribute("href", `${trace_ui_url}/trace/${run.trace_id}`);
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(page.getByTestId("what-happened")).toContainText(`trace ${run.trace_id!.slice(0, 8)}`);
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
