/**
 * Phase L7a in containers: one id finds every line. A chat turn's lines, in the API's and
 * the workers' logs, carry its session; the API names the request it served; an error in
 * the page lands in the API's log as `component=ui`. Read with `docker logs`, as an
 * operator would.
 */
import { spawnSync } from "node:child_process";

import { expect, test } from "@playwright/test";

import { containers, startChat, transcript, waitTurnOver } from "./support";

type Line = Record<string, unknown>;

/** Every JSON line a service's containers wrote. */
function lines(service: string): Line[] {
  return containers(service).flatMap((id) => {
    const r = spawnSync("docker", ["logs", id], { encoding: "utf8", maxBuffer: 256 * 1024 * 1024 });
    return `${r.stdout}\n${r.stderr}`
      .split("\n")
      .filter((l) => l.startsWith("{"))
      .map((l) => JSON.parse(l) as Line);
  });
}

test("a turn's lines carry its ids, in the API and in the workers", async ({ page, request }) => {
  const sid = await startChat(page, "What is 12 * (3 + 4)?");
  await expect(page.getByTestId("assistant-message").last()).toContainText("84");
  await waitTurnOver(request, sid);
  const runId = (await transcript(request, sid)).find((m) => m.run_id)?.run_id;
  expect(runId).toBeTruthy();

  await expect.poll(() => lines("worker").filter((l) => l.run_id === runId).length).toBeGreaterThan(2);
  const worker = lines("worker").filter((l) => l.run_id === runId);
  for (const l of worker) expect(l, JSON.stringify(l)).toMatchObject({ session_id: sid, component: "worker" });
  const msgs = worker.map((l) => String(l.msg));
  expect(msgs.some((m) => m.startsWith("model call:"))).toBe(true);
  const tool = worker.find((l) => String(l.msg).startsWith("tool call: "));
  expect(tool).toMatchObject({ tool: expect.stringMatching(/^(calculator|run_python)$/) as unknown, tool_call_id: expect.any(String) as unknown });
  expect(msgs.some((m) => m.endsWith(": completed"))).toBe(true);

  const api = lines("api").filter((l) => l.logger === "api.access" && l.session_id === sid);
  const sent = api.find((l) => l.route === "/sessions/{session_id}/messages" && l.method === "POST");
  expect(sent).toMatchObject({ method: "POST", status: 202, component: "api" });
  expect(String(sent?.request_id)).toMatch(/^[0-9a-f]{32}$/);
  expect(String(sent?.msg)).not.toContain(sid); // the route's template, not its ids
  expect(lines("api").some((l) => l.logger === "api.access" && String(l.route).includes("healthz"))).toBe(false);
});

test("an error in the page is written to the API's log", async ({ page }) => {
  await page.goto("/#/activity");
  await expect(page.getByTestId("activity-totals")).toBeVisible();
  const marker = `planted-${String(Date.now())}`;
  await page.evaluate((m) => {
    setTimeout(() => {
      throw new Error(m);
    });
  }, marker);
  await expect
    .poll(() => lines("api").find((l) => l.component === "ui" && String(l.msg).includes(marker)))
    .toMatchObject({ level: "WARNING", kind: "error", route: "#/activity" });
});
