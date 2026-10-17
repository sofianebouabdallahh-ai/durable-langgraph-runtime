/**
 * SC3 (AC20: resume the conversation) and SC4: whatever happens mid-reply (a
 * reload, the API replica serving the stream killed or stopped, the worker killed),
 * the conversation on screen ends identical to the saved one: every message once,
 * in order.
 */
import { expect, test } from "@playwright/test";

import { containers, docker, expectScreenMatchesTranscript, getJson, newChat, restoreStack, send, servingReplica, waitTurnOver } from "./support";

const API_REPLICAS = Number(process.env.API_REPLICAS ?? 2);
const WORKERS = Number(process.env.WORKERS ?? 2);

// Chaos tests put back what they broke: the next test starts from a full stack.
test.afterEach(() => restoreStack(API_REPLICAS, WORKERS));

test("reload in the middle of a reply", async ({ page, request }) => {
  const sid = await newChat(page);
  await send(page, "hello");
  await expect(page.getByTestId("draft")).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("assistant-message")).toContainText("Notify the team");
  await waitTurnOver(request, sid);
  await expectScreenMatchesTranscript(page, request, sid);
});

for (const how of ["kill", "stop"] as const) {
  test(`the API replica serving the stream is ${how === "kill" ? "killed" : "stopped (it drains)"} mid-reply`, async ({ page, request }) => {
    const sid = await newChat(page);
    await send(page, "hello");
    await expect(page.getByTestId("draft")).toBeVisible();
    const replica = servingReplica(sid);
    docker(how, replica);
    // The browser reconnects through the proxy to the other replica and catches up.
    await expect(page.getByTestId("assistant-message")).toContainText("Notify the team", { timeout: 60_000 });
    await waitTurnOver(request, sid);
    await expect(page.getByTestId("connection-banner")).toHaveCount(0);
    await expectScreenMatchesTranscript(page, request, sid);
  });
}

test("the worker running the turn is killed in the middle of a tool call", async ({ page, request }) => {
  const sid = await newChat(page);
  // A slow side effect, sent through the API: the browser just watches the chat.
  const sent = await request.post(`/api/sessions/${sid}/messages`, {
    data: { content: "keep this", script: [
      { tool_calls: [{ name: "save_note", args: { text: "kept once", linger_s: 6 } }] },
      { content: "Kept it." },
    ] },
  });
  expect(sent.status()).toBe(202);
  const runId = ((await sent.json()) as { run_id: string }).run_id;
  await expect(page.getByTestId("tool-card")).toContainText("Saved a note");
  let owner = "";
  await expect.poll(async () => {
    const run = await getJson<{ status: string; owner: string | null }>(request, `/api/runs/${runId}`);
    owner = run.status === "running" && run.owner ? run.owner : "";
    return owner;
  }).not.toBe("");
  const host = owner.split(":")[0] ?? ""; // a container's hostname is its id's first 12 characters
  const victim = containers("worker").find((id) => id.startsWith(host));
  expect(victim).toBeTruthy();
  docker("kill", victim!);
  await expect(page.getByTestId("assistant-message")).toContainText("Kept it.", { timeout: 90_000 });
  await waitTurnOver(request, sid);
  await expectScreenMatchesTranscript(page, request, sid);
  await expect(page.getByTestId("tool-card")).toHaveCount(1); // the tool ran once, shown once
  const events = await getJson<{ events: { type: string }[] }>(request, `/api/runs/${runId}/events?limit=500`);
  expect(events.events.filter((e) => e.type === "run.reclaimed")).toHaveLength(1);
  await page.getByRole("button", { name: "What happened?" }).click();
  await expect(page.getByTestId("what-happened")).toContainText("another one took over");
});
