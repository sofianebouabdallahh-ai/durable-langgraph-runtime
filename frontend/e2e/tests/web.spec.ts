/**
 * The web tools in the browser (phase L6a), against the fake web (profile `test`: the
 * fake model server answers like SearXNG and serves a few pages; the page reader lets
 * that one host through, FETCH_ALLOW_HOSTS=fake-model).
 * SC1 search, read and cite; Settings → Tools; SC4 planted instructions stay data.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { newBlankAgent } from "./support";

const FAKE = "http://fake-model:9999";

const serious = async (page: Page) =>
  (await new AxeBuilder({ page }).analyze()).violations.filter((v) => v.impact === "serious" || v.impact === "critical");

async function builtIn(request: APIRequestContext) {
  await request.put("/api/tools/settings", { data: { search_provider: "searxng", searxng_url: "", web_allowlist: [] } });
  await request.put("/api/models/default", { data: { connection_id: null } });
}

test.afterEach(async ({ request }) => {
  await builtIn(request);
});

test("Settings → Tools: point search somewhere and test it", async ({ page }) => {
  await page.goto("/#/settings/tools");
  const search = page.getByTestId("search-settings");
  await expect(search.getByRole("radio", { name: /Built in/ })).toHaveAttribute("aria-checked", "true");
  await search.getByText("Use your own SearXNG instead").click();
  await search.getByLabel("SearXNG address").fill(`${FAKE}/searxng`);
  await search.getByRole("button", { name: "Save and test" }).click();
  await expect(page.getByTestId("search-test")).toContainText("Works", { timeout: 30_000 });
  await expect(page.getByTestId("search-test")).toContainText("Ferries to Naxos");
  expect(await serious(page)).toEqual([]);
  await search.getByRole("radio", { name: /Tavily/ }).click();
  await expect(search.getByRole("button", { name: "Save and test" })).toBeDisabled(); // a key first
});

test("SC1: an agent searches the web, reads a page and says what it read", async ({ page, request }) => {
  await request.put("/api/tools/settings", { data: { searxng_url: `${FAKE}/searxng` } });
  const added = await request.post("/api/models/connections", {
    data: { display_name: `Web ${Date.now().toString(36)}`, kind: "compatible", base_url: `${FAKE}/v1`, models: ["fake-a"] },
  });
  const connection = (await added.json()) as { id: string };
  await request.post(`/api/models/connections/${connection.id}/test`, { data: { model: "fake-a" } });
  await request.put("/api/models/default", { data: { connection_id: connection.id, model: "fake-a" } });

  await newBlankAgent(page, `Researcher ${Date.now().toString(36)}`);
  await page.getByLabel("What is it for?").fill("Finds facts on the web and cites them.");
  await page.getByRole("switch", { name: "Use Search the web" }).first().click();
  await page.getByRole("switch", { name: "Use Read web pages" }).first().click();
  await expect(page.getByTestId("save-state")).toHaveText(/Saved/, { timeout: 15_000 });

  await page.getByRole("button", { name: "Start a test chat" }).click();
  const chat = page.getByTestId("test-chat");
  await chat.getByRole("textbox", { name: "Message" }).fill("ferries to naxos");
  await chat.getByRole("textbox", { name: "Message" }).press("Enter");
  await expect(chat.getByTestId("tool-card").first()).toContainText("Web search", { timeout: 30_000 });
  await expect(chat.getByTestId("tool-card").nth(1)).toContainText("Read a page");
  await expect(chat.getByTestId("assistant-message").last()).toContainText("Read: Ferries to Naxos.", { timeout: 30_000 });
});

test("SC4: a page that says “call notify” is read as data, and nothing is sent", async ({ page, request }) => {
  await request.put("/api/tools/settings", { data: { searxng_url: `${FAKE}/searxng` } });
  const added = await request.post("/api/models/connections", {
    data: { display_name: `Planted ${Date.now().toString(36)}`, kind: "compatible", base_url: `${FAKE}/v1`, models: ["fake-a"] },
  });
  const connection = (await added.json()) as { id: string };
  await request.post(`/api/models/connections/${connection.id}/test`, { data: { model: "fake-a" } });
  await request.put("/api/models/default", { data: { connection_id: connection.id, model: "fake-a" } });

  await newBlankAgent(page, `Tips ${Date.now().toString(36)}`);
  await page.getByLabel("What is it for?").fill("Gives travel tips.");
  await page.getByRole("switch", { name: "Use Search the web" }).first().click();
  await page.getByRole("switch", { name: "Use Read web pages" }).first().click();
  await page.getByRole("switch", { name: "Use Notifications" }).first().click();
  await expect(page.getByTestId("save-state")).toHaveText(/Saved/, { timeout: 15_000 });
  await page.getByRole("button", { name: "Start a test chat" }).click();
  const chat = page.getByTestId("test-chat");
  await chat.getByRole("textbox", { name: "Message" }).fill("travel tips");
  await chat.getByRole("textbox", { name: "Message" }).press("Enter");
  await expect(chat.getByTestId("assistant-message").last()).toContainText("Read: Travel tips.", { timeout: 30_000 });
  await expect(chat.getByTestId("tool-card")).toHaveCount(2); // search and read: no notification
  await expect(chat.getByRole("button", { name: "Approve" })).toHaveCount(0);
});
