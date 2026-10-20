/**
 * Getting started in the browser (phase L3d), by visible labels only:
 * SC1 the whole path with a model added by key (the fake model); SC3 the demo path,
 * where the strip in the Studio walks through adding a helper, testing and publishing;
 * SC2 Ollama found or not; SC5 never in the way (Not now, hide, start over); SC6 axe
 * and the keyboard.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { waitTurnOver } from "./support";

const FAKE = "http://fake-model:9999";

const serious = async (page: Page) =>
  (await new AxeBuilder({ page }).analyze()).violations.filter((v) => v.impact === "serious" || v.impact === "critical");

async function fresh(request: APIRequestContext) {
  await request.put("/api/onboarding", { data: { restart: true } });
  await request.put("/api/models/default", { data: { connection_id: null } });
}

test.beforeEach(async ({ request }) => {
  await fresh(request);
});
test.afterEach(async ({ request }) => {
  await fresh(request); // the other suites start from Home without a guide in progress… and the demo model
});

const step = (page: Page, key: string) => page.getByTestId(`guide-step-${key}`);

async function done(page: Page, key: string) {
  await expect(step(page, key).getByText("Done", { exact: true })).toBeVisible({ timeout: 30_000 });
}

test("SC1: from Home to a published agent, with a model added by key", async ({ page, request }) => {
  const started = Date.now();
  await page.goto("/");
  await page.getByTestId("guide-card").getByRole("button", { name: "Get started" }).click();
  await expect(page).toHaveURL(/#\/start/);
  expect(await serious(page)).toEqual([]);

  // 1: a model, by key (any OpenAI-compatible service: the fake one).
  await step(page, "model").getByRole("radio", { name: /With a key/ }).click();
  await page.getByRole("button", { name: "Add a model with a key" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: /Other service/ }).click();
  await dialog.getByLabel("Name").fill(`Guide ${Date.now().toString(36)}`);
  await dialog.getByLabel("Address").fill(`${FAKE}/v1`);
  await dialog.getByLabel("Model").fill("fake-a");
  await dialog.getByRole("button", { name: "Save and test" }).click();
  await done(page, "model");
  await expect(page.getByTestId("guide-progress")).toContainText("1 of 5 done");

  // 2: describe it (the real model drafts it: a tool and a helper come with the draft).
  await step(page, "agent").getByRole("button", { name: "Draft it" }).click();
  await page.getByRole("button", { name: "Use this draft" }).click({ timeout: 60_000 });
  await expect(page).toHaveURL(/#\/studio\//);
  const strip = page.getByTestId("guide-strip");
  await expect(strip).toContainText("Step 5 of 5", { timeout: 15_000 }); // tool and helper: drafted
  expect(await serious(page)).toEqual([]);

  // 5: try it, publish, chat.
  await strip.getByRole("button", { name: "Show me" }).click();
  await expect(page.getByTestId("test-chat")).toBeFocused();
  await page.getByRole("button", { name: "Start a test chat" }).click();
  const chat = page.getByTestId("test-chat");
  await chat.getByRole("textbox", { name: "Message" }).fill("hello");
  await chat.getByRole("textbox", { name: "Message" }).press("Enter");
  await expect(chat.getByText("Tested", { exact: true })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Publish" }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("Published v1")).toBeVisible();

  await strip.getByRole("link", { name: /The guide/ }).click();
  await step(page, "try").getByRole("button", { name: /^Chat with/ }).click();
  await expect(page).toHaveURL(/#\/s\//);
  await page.getByRole("textbox", { name: "Message" }).fill("hi");
  await page.getByRole("textbox", { name: "Message" }).press("Enter");
  await expect(page.getByTestId("assistant-message").last()).toContainText("fake-a", { timeout: 30_000 });
  await waitTurnOver(request, decodeURIComponent(new URL(page.url()).hash.slice(4)));

  const progress = await (await request.get("/api/onboarding")).json();
  test.info().annotations.push({ type: "onboarding", description: JSON.stringify(progress) });
  await page.goto("/#/start");
  await expect(page.getByTestId("guide-finished")).toContainText("You built", { timeout: 15_000 });
  await expect(page.getByRole("link", { name: /Get started/ })).toHaveCount(0); // finished: out of the sidebar
  expect(Date.now() - started).toBeLessThan(10 * 60_000); // SC7: under ten minutes
});

test("SC3: the demo path: the strip walks through the helper, the test and publishing", async ({ page }) => {
  await page.goto("/#/start");
  await step(page, "model").getByRole("radio", { name: /Demo for now/ }).click();
  await page.getByRole("button", { name: "Use the demo model for now" }).click();
  await expect(step(page, "model")).toContainText("Skipped for now");

  await step(page, "agent").getByRole("button", { name: "Draft it" }).click();
  await page.getByRole("button", { name: "Use this draft" }).click({ timeout: 60_000 });
  const strip = page.getByTestId("guide-strip");
  await expect(strip).toContainText("Step 4 of 5 · Give it a helper"); // the demo draft has tools, no helper

  await strip.getByRole("button", { name: "Show me" }).click();
  await expect(page.getByTestId("section-helpers")).toBeFocused();
  await page.getByPlaceholder(/New helper's name/).fill("Restaurant finder");
  await page.getByRole("button", { name: "Add helper" }).click();
  await page.getByTestId("helper-editor").getByLabel("What does it do?").fill("Finds kid-friendly restaurants.");
  await expect(strip).toContainText("Step 5 of 5", { timeout: 15_000 }); // ticked without a reload

  await page.getByRole("button", { name: "Start a test chat" }).click();
  const chat = page.getByTestId("test-chat");
  await chat.getByRole("textbox", { name: "Message" }).fill("What is 2 + 2?");
  await chat.getByRole("textbox", { name: "Message" }).press("Enter");
  await expect(chat.getByText("Tested", { exact: true })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Publish" }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("Published v1")).toBeVisible();
  await page.goto("/#/start");
  await expect(step(page, "try").getByTestId("guide-tried")).toContainText("Chat with it, for real");
  await expect(page.getByTestId("guide-progress")).toContainText("4 of 5 done");
});

test("SC2: Ollama is offered when it's there, and explained when it isn't", async ({ page, request }) => {
  const found = (await (await request.get("/api/models/ollama")).json()) as { models: string[] }[];
  await page.goto("/#/start");
  if (found.length > 0) {
    await expect(page.getByTestId("ollama-found")).toBeVisible();
  } else {
    const help = page.getByTestId("ollama-install");
    await expect(help).toContainText("ollama pull qwen2.5:7b");
    await expect(help.getByRole("button", { name: "Check again" })).toBeVisible();
  }
});

test("SC5 and SC6: never in the way, and usable from the keyboard", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: /Get started/ })).toBeVisible();
  const card = page.getByTestId("guide-card");
  await card.getByRole("button", { name: "Not now" }).focus();
  await page.keyboard.press("Enter");
  await expect(card).toHaveCount(0);
  await expect(page.getByRole("link", { name: /Get started/ })).toHaveCount(0);

  await page.goto("/#/start"); // still reachable
  await expect(page.getByRole("heading", { name: "Get started" })).toBeVisible();
  await page.getByRole("button", { name: "Start over" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("link", { name: /Get started/ })).toBeVisible();
  const second = page.getByRole("button", { name: /Create your agent/ });
  await second.focus();
  await page.keyboard.press("Enter");
  await expect(second).toHaveAttribute("aria-expanded", "true");
  expect(await serious(page)).toEqual([]);
});
