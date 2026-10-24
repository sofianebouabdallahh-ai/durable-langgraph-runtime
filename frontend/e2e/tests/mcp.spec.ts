/**
 * MCP servers in the browser (phase L8), against the fake MCP server (profile `test`: the
 * fake model serves it at /mcp, behind a token, and calls MCP tools it's offered).
 * SC1: add a server, switch a tool on, give it to an agent, the agent uses it.
 * SC3: the server changes the tool; Settings shows it, and agents wait for a new approval.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { newBlankAgent } from "./support";

const FAKE = "http://fake-model:9999";
const TOKEN = "fake-mcp-token";
const FACT = "Ferries to Naxos leave Piraeus at 07:30 and 17:00";

interface Server { id: string; name: string }

async function cleanUp(request: APIRequestContext) {
  await request.post(`${FAKE}/mcp-admin/reset`);
  const servers = (await (await request.get("/api/mcp/servers")).json()) as Server[];
  for (const s of servers) await request.delete(`/api/mcp/servers/${s.id}`);
  await request.put("/api/models/default", { data: { connection_id: null } });
}

test.beforeEach(async ({ request }) => {
  await cleanUp(request);
});
test.afterEach(async ({ request }) => {
  await cleanUp(request);
});

async function fakeModel(request: APIRequestContext) {
  const added = await request.post("/api/models/connections", {
    data: { display_name: `Mcp ${Date.now().toString(36)}`, kind: "compatible", base_url: `${FAKE}/v1`, models: ["fake-a"] },
  });
  const connection = (await added.json()) as { id: string };
  await request.post(`/api/models/connections/${connection.id}/test`, { data: { model: "fake-a" } });
  await request.put("/api/models/default", { data: { connection_id: connection.id, model: "fake-a" } });
}

/** The add form: open already when there's no server yet, else behind "Add a server". */
async function addForm(page: Page) {
  await page.goto("/#/settings/tools");
  const section = page.getByTestId("mcp-servers");
  const form = section.getByTestId("mcp-add");
  const open = section.getByTestId("mcp-add-open");
  await expect(form.or(open)).toBeVisible();
  if (await open.isVisible()) await open.click();
  return form;
}

async function addServer(page: Page, name: string, token = TOKEN): Promise<void> {
  const form = await addForm(page);
  await form.getByLabel("Name").fill(name);
  await form.getByLabel("Address").fill(`${FAKE}/mcp/`);
  await form.getByLabel("Token (optional)").fill(token);
  await form.getByRole("button", { name: "Add and test" }).click();
}

test("SC1: add a server, switch a tool on, and an agent uses it", async ({ page, request }) => {
  await fakeModel(request);
  await addServer(page, "Travel");
  const server = page.getByTestId("mcp-server").filter({ hasText: "Travel" });
  await expect(server).toContainText("Ready");
  await expect(server.getByTestId("mcp-status")).toHaveText("3 tools");
  await expect(server).toContainText("Token set");
  await expect(page.locator("body")).not.toContainText(TOKEN); // never shown again

  const lookup = server.getByTestId("mcp-tool").filter({ hasText: "lookup" });
  await lookup.getByRole("switch", { name: "Use it" }).click();
  await lookup.getByRole("switch", { name: "Runs without asking" }).click();
  await expect(lookup.getByRole("switch", { name: "Runs without asking" })).toHaveAttribute("aria-checked", "true");
  const send = server.getByTestId("mcp-tool").filter({ hasText: "send_message" });
  await expect(send).toContainText("asks you first");
  await expect(send.getByRole("switch", { name: "Runs without asking" })).toHaveCount(0); // never for a tool with effects
  const serious = (await new AxeBuilder({ page }).include('[data-testid="mcp-servers"]').analyze()).violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(serious).toEqual([]);

  // The Studio offers it, under its server; a test chat uses it. (Names are never reused,
  // even after a server is removed: read this one's.)
  const name = await server.getAttribute("data-name");
  await newBlankAgent(page, `Ferry planner ${Date.now().toString(36)}`);
  await page.getByLabel("What is it for?").fill("Plans ferry trips with up-to-date facts.");
  const option = page.getByTestId(`tool-option-mcp__${name ?? ""}__lookup`);
  await expect(option).toContainText("Travel · MCP");
  await option.getByRole("switch").click();
  await expect(page.getByTestId("save-state")).toHaveText(/Saved/, { timeout: 15_000 });
  await page.getByRole("button", { name: "Start a test chat" }).click();
  const chat = page.getByTestId("test-chat");
  await chat.getByRole("textbox", { name: "Message" }).fill("ferries to naxos");
  await chat.getByRole("textbox", { name: "Message" }).press("Enter");
  await expect(chat.getByTestId("tool-card").first()).toContainText("Lookup (travel", { timeout: 30_000 });
  await expect(chat.getByTestId("assistant-message").last()).toContainText(FACT, { timeout: 30_000 });

  // Who changed what: the server and the tool.
  await page.goto("/#/activity/audit");
  await expect(page.getByTestId("audit-row").filter({ hasText: "Added an MCP server" }).first()).toBeVisible();
  await expect(page.getByTestId("audit-row").filter({ hasText: "Switched on an MCP tool" }).first()).toContainText(`mcp__${name ?? ""}__lookup`);
});

test("SC3: the server changes a tool; it waits for you to look", async ({ page, request }) => {
  await addServer(page, "Travel");
  const server = page.getByTestId("mcp-server").filter({ hasText: "Travel" });
  const lookup = server.getByTestId("mcp-tool").filter({ hasText: "lookup" });
  await lookup.getByRole("switch", { name: "Use it" }).click();
  await expect(lookup.getByRole("switch", { name: "Use it" })).toHaveAttribute("aria-checked", "true");

  await request.post(`${FAKE}/mcp-admin/change`); // the "rug pull"
  await server.getByTestId("mcp-test").click();
  await expect(server).toContainText("1 changed: look again");
  const notice = lookup.getByTestId("mcp-changed");
  await expect(notice).toContainText("Agents can't use it until you look");
  await expect(notice).toContainText("Was: Looks up a travel fact about a topic.");
  await expect(lookup.getByTestId("mcp-findings")).toContainText("steer"); // the new description hides an instruction

  const name = await server.getAttribute("data-name");
  const catalog = (await (await request.get("/api/studio/catalog")).json()) as { tools: { name: string }[] };
  expect(catalog.tools.map((t) => t.name)).not.toContain(`mcp__${name ?? ""}__lookup`); // not offered meanwhile

  await notice.getByRole("button", { name: "It's fine: use the new version" }).click();
  await expect(lookup.getByTestId("mcp-changed")).toHaveCount(0);
  await expect(server).not.toContainText("changed: look again");
});

test("a wrong token is said plainly", async ({ page }) => {
  await addServer(page, "Locked", "not-the-token");
  const server = page.getByTestId("mcp-server").filter({ hasText: "Locked" });
  await expect(server).toContainText("Not working");
  await expect(server.getByTestId("mcp-status")).toContainText("refused the token");
});
