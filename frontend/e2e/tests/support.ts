/** Shared helpers: the stack's containers (via the Docker CLI) and the API's truth. */
import { execFileSync, spawnSync } from "node:child_process";

import { expect, type APIRequestContext, type Page } from "@playwright/test";

const PROJECT = process.env.COMPOSE_PROJECT ?? "agent-runtime";

export function docker(...args: string[]): string {
  return execFileSync("docker", args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
}

/** The containers of a Compose service (full ids): running ones, or all with `all`. */
export function containers(service: string, all = false): string[] {
  const out = docker("ps", ...(all ? ["-a"] : []), "-q", "--no-trunc", "--filter", `label=com.docker.compose.project=${PROJECT}`,
    "--filter", `label=com.docker.compose.service=${service}`);
  return out ? out.split("\n") : [];
}

/** Start again whatever a chaos step stopped (the one-shot migration excepted). */
export async function restoreStack(apiReplicas: number, workers: number): Promise<void> {
  for (const service of ["api", "worker", "ui"]) {
    const running = new Set(containers(service));
    for (const id of containers(service, true)) if (!running.has(id)) docker("start", id);
  }
  await waitForReplicas("api", apiReplicas);
  await waitForReplicas("worker", workers);
}

/** A container's log, stdout and stderr (uvicorn's access log is on stderr). */
function logs(id: string): string {
  const r = spawnSync("docker", ["logs", "--timestamps", id], { encoding: "utf8" });
  return `${r.stdout}\n${r.stderr}`;
}

/** The API replica serving this session's stream: the last one to log its request. */
export function servingReplica(sessionId: string): string {
  let best: { id: string; at: string } | null = null;
  for (const id of containers("api")) {
    const hits = logs(id).split("\n").filter((l) => l.includes(`/sessions/${sessionId}/stream`));
    const last = hits.map((l) => l.split(" ")[0] ?? "").sort().at(-1);
    if (last && (!best || last > best.at)) best = { id, at: last };
  }
  if (!best) throw new Error(`no API replica has served the stream of ${sessionId}`);
  return best.id;
}

/** Wait until the stack is healthy again after a chaos step (restart policy). */
export async function waitForReplicas(service: string, count: number): Promise<void> {
  await expect.poll(() => containers(service).length, { timeout: 60_000 }).toBe(count);
}

export async function newChat(page: Page): Promise<string> {
  await page.goto("/");
  await page.getByRole("button", { name: "+ New chat" }).click();
  await expect(page).toHaveURL(/#\/s\//);
  const id = decodeURIComponent(new URL(page.url()).hash.slice("#/s/".length));
  await expect(page.getByTestId("connection-banner")).toHaveCount(0); // stream open
  return id;
}

export async function send(page: Page, text: string): Promise<void> {
  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill(text);
  await box.press("Enter");
  await expect(box).toHaveValue("");
}

interface Msg { seq: number; message_id: string; type: string; content: Record<string, unknown> }

export async function transcript(request: APIRequestContext, sessionId: string): Promise<Msg[]> {
  const resp = await request.get(`/api/sessions/${sessionId}/messages?limit=500`);
  expect(resp.ok()).toBe(true);
  return ((await resp.json()) as { messages: Msg[] }).messages;
}

export async function waitTurnOver(request: APIRequestContext, sessionId: string): Promise<void> {
  await expect.poll(async () => {
    const s = (await (await request.get(`/api/sessions/${sessionId}`)).json()) as { active_run_id: string | null };
    return s.active_run_id;
  }, { timeout: 90_000 }).toBeNull();
}

/**
 * What the screen shows equals the persisted transcript: every reply and tool call
 * once, in order, nothing missing and nothing doubled (AC20's "identical").
 */
export async function expectScreenMatchesTranscript(page: Page, request: APIRequestContext, sessionId: string): Promise<Msg[]> {
  const messages = await transcript(request, sessionId);
  const ids = messages.map((m) => m.message_id);
  expect(new Set(ids).size).toBe(ids.length);
  expect(messages.map((m) => m.seq)).toEqual(messages.map((_, i) => i + 1));
  const replies = messages.filter((m) => m.type === "assistant" && String(m.content.text ?? "").trim());
  await expect(page.getByTestId("assistant-message")).toHaveCount(replies.length);
  const tools = messages.filter((m) => m.type === "tool_call" && !String(m.content.tool).includes("subagent"));
  await expect(page.getByTestId("tool-card")).toHaveCount(tools.length);
  await expect(page.getByTestId("user-message")).toHaveCount(messages.filter((m) => m.type === "user").length);
  await expect(page.getByTestId("draft")).toHaveCount(0);
  return messages;
}
