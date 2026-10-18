/**
 * Your own models in the browser (phase L3b), against the fake OpenAI-compatible
 * server (Compose profile `test`, http://fake-model:9999). SC1 add and test a model
 * without a terminal; SC2 / AC44 an agent and its helper on two connections in one
 * conversation; SC3 / AC45 the key appears nowhere: page, API, containers' logs.
 */
import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

import { containers, docker, getJson, startChat, waitTurnOver } from "./support";

const FAKE = "http://fake-model:9999";

async function addModel(page: Page, name: string, key: string, model: string) {
  await page.goto("/#/settings/models");
  await page.getByRole("button", { name: "Add a model" }).click();
  await page.getByRole("button", { name: /Other service/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByLabel("Address").fill(`${FAKE}/v1`);
  await dialog.getByLabel(/^Key/).fill(key);
  await dialog.getByLabel("Model").fill(model);
  await dialog.getByRole("button", { name: "Save and test" }).click();
  await expect(dialog).toBeHidden({ timeout: 30_000 }); // saved, and the test passed
  const card = page.getByTestId("connection-card").filter({ hasText: name });
  await expect(card.getByText("Ready", { exact: true })).toBeVisible();
  return card;
}

async function resetDefault(request: APIRequestContext) {
  await request.put("/api/models/default", { data: { connection_id: null } });
}

test.afterEach(async ({ request }) => {
  await resetDefault(request); // the other suites use the demo model
});

test("add a model, make it the default, chat with it; the key appears nowhere", async ({ page, request }) => {
  const stamp = Date.now().toString(36);
  const key = `e2e-key-${stamp}-${Math.random().toString(36).slice(2)}`;
  const name = `Fake A ${stamp}`;
  const card = await addModel(page, name, key, "fake-a");
  await expect(card.getByTestId("test-result")).toContainText("it answers and uses tools");
  await expect(card).toContainText("A key is saved");
  expect(await serious(page)).toEqual([]);

  await page.getByRole("combobox", { name: "Default model" }).selectOption({ label: `${name} · fake-a` });
  await expect(page.getByTestId("model-status")).toContainText(`${name} · fake-a`);

  const sid = await startChat(page, "Plan a day in Lisbon");
  await expect(page.getByTestId("assistant-message").last()).toContainText("Answered by fake-a", { timeout: 60_000 });
  await expect(page.getByTestId("answered-by")).toContainText("fake-a");
  await waitTurnOver(request, sid);

  // AC45: not on any page, in any API response we can reach, nor in the containers' logs.
  for (const path of ["/#/settings/models", `/#/s/${sid}`]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    expect(await page.content()).not.toContain(key);
  }
  for (const api of ["/api/models/connections", "/api/models/default", `/api/sessions/${sid}/messages`, "/api/studio/agents", "/api/agents"]) {
    expect(await (await request.get(api)).text()).not.toContain(key);
  }
  for (const service of ["api", "worker", "ui"]) {
    for (const id of containers(service)) expect(docker("logs", id)).not.toContain(key);
  }
});

test("AC44: an agent and its helper answer through two different connections", async ({ page, request }) => {
  const stamp = Date.now().toString(36);
  await addModel(page, `Main ${stamp}`, `main-${stamp}-key`, "fake-a");
  await addModel(page, `Helper ${stamp}`, `helper-${stamp}-key`, "fake-b");
  const connections = await getJson<{ name: string; display_name: string }[]>(request, "/api/models/connections");
  const main = connections.find((c) => c.display_name === `Main ${stamp}`)!.name;
  const helper = connections.find((c) => c.display_name === `Helper ${stamp}`)!.name;

  // An agent built in the Studio: its own model, and a helper on another.
  await page.goto("/#/agents");
  await page.getByRole("button", { name: "New agent" }).click();
  await page.getByRole("dialog").getByLabel("Name").fill(`Split ${stamp}`);
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page).toHaveURL(/#\/studio\//);
  await page.getByLabel("What is it for?").fill("Splits work between two models.");
  await page.getByPlaceholder(/New helper's name/).fill("Scout");
  await page.getByRole("button", { name: "Add helper" }).click();
  await page.getByTestId("helper-editor").getByLabel("What does it do?").fill("Scouts.");
  await page.getByTestId("helper-editor").getByLabel("Its model").selectOption(`${helper}:fake-b`);
  await page.getByTestId("section-model").getByLabel("Its model").selectOption(`${main}:fake-a`);
  await expect(page.getByTestId("save-state")).toHaveText(/Saved/, { timeout: 15_000 });

  await request.delete(`${FAKE}/calls`);
  await page.getByRole("button", { name: "Start a test chat" }).click();
  const chat = page.getByTestId("test-chat");
  await expect(chat.getByText("Start the conversation")).toBeVisible();
  await chat.getByRole("textbox", { name: "Message" }).fill("split this");
  await chat.getByRole("textbox", { name: "Message" }).press("Enter");
  await expect(chat.getByTestId("assistant-message").last()).toContainText("Answered by fake-a", { timeout: 60_000 });
  await expect(chat.getByTestId("helper-card")).toContainText("Helper work by fake-b");

  const calls = (await (await request.get(`${FAKE}/calls`)).json()) as { model: string; key: string; tools: string[] }[];
  const keys = new Map(calls.map((c) => [c.model, c.key]));
  expect([...keys.keys()].sort()).toEqual(["fake-a", "fake-b"]);
  expect(keys.get("fake-a")).not.toBe(keys.get("fake-b")); // two connections, two keys
  await expect(chat.getByText("Tested", { exact: true })).toBeVisible({ timeout: 15_000 });
});

test("a model that can't use tools is caught by the test", async ({ page }) => {
  await page.goto("/#/settings/models");
  await page.getByRole("button", { name: "Add a model" }).click();
  await page.getByRole("button", { name: /Other service/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill(`Chatty ${Date.now().toString(36)}`);
  await dialog.getByLabel("Address").fill(`${FAKE}/v1`);
  await dialog.getByLabel("Model").fill("fake-notools");
  await dialog.getByRole("button", { name: "Save and test" }).click();
  await expect(dialog.getByRole("alert")).toContainText("doesn't use tools");
});

async function serious(page: Page) {
  return (await new AxeBuilder({ page }).analyze()).violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}
