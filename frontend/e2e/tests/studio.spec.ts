/**
 * The Agent Studio in the browser (phase L3a). SC1: a person builds an agent with a
 * helper through the form only, tests it, publishes it and chats with it. No
 * Markdown on screen at any point.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { getJson, newBlankAgent, waitTurnOver } from "./support";

const serious = async (page: Page) =>
  (await new AxeBuilder({ page }).analyze()).violations.filter((v) => v.impact === "serious" || v.impact === "critical");

const newAgent = newBlankAgent;

async function saved(page: Page) {
  await expect(page.getByTestId("save-state")).toHaveText(/Saved/, { timeout: 15_000 });
}

test("build an agent with a helper, test it, publish it, chat with it", async ({ page, request }) => {
  const stamp = Date.now().toString(36);
  const name = `Trip planner ${stamp}`;
  const id = await newAgent(page, name);
  await expect(page.getByText("Required.")).toBeVisible(); // what it's for: shown by the field
  await expect(page.getByRole("button", { name: "Start a test chat" })).toBeDisabled();

  await page.getByLabel("What is it for?").fill("Plans trips: finds places and builds a day-by-day plan.");
  await page.getByLabel("Instructions", { exact: true }).fill("You plan trips. Ask your helper to find places. Today is ");
  await page.getByRole("button", { name: "Today's date" }).click();
  await page.getByRole("switch", { name: "Use Search" }).first().click();
  await page.getByRole("switch", { name: "Use Read web pages" }).first().click();

  await page.getByPlaceholder(/New helper's name/).fill("Place finder");
  await page.getByRole("button", { name: "Add helper" }).click();
  const helper = page.getByTestId("helper-editor");
  await helper.getByLabel("What does it do?").fill("Finds places worth visiting in a city.");
  await helper.getByLabel("Its instructions").fill("Find places for the task you are given, then return_result.");
  await helper.getByRole("switch", { name: "Use Search" }).click();
  await expect(helper.getByRole("switch", { name: "Use Notifications" })).toHaveCount(0); // asks first: not for helpers

  await page.getByRole("radio", { name: /Quick/ }).click();
  await saved(page);
  await expect(page.getByTestId("field-issues")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("---"); // no frontmatter, ever

  // Not tested yet: publishing says what's missing.
  await page.getByRole("button", { name: "Publish" }).first().click();
  await expect(page.getByTestId("publish-blockers")).toContainText("test chat");
  await page.getByRole("button", { name: "OK" }).click();

  // The test chat uses the helper (the demo model hands "plan" tasks to it).
  await page.getByRole("button", { name: "Start a test chat" }).click();
  const chat = page.getByTestId("test-chat");
  await chat.getByRole("textbox", { name: "Message" }).fill("Plan a weekend in Lisbon");
  await chat.getByRole("textbox", { name: "Message" }).press("Enter");
  await expect(chat.getByTestId("helper-card")).toContainText("Helper: Place finder", { timeout: 30_000 });
  await expect(chat.getByTestId("assistant-message").last()).toContainText("Place finder", { timeout: 30_000 });
  await expect(chat.getByText("Tested", { exact: true })).toBeVisible({ timeout: 15_000 });

  await page.getByRole("button", { name: "Publish" }).first().click();
  await page.getByRole("dialog").getByLabel(/What changed/).fill("First version");
  await page.getByRole("dialog").getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("Published v1")).toBeVisible();
  expect(await serious(page)).toEqual([]);

  // Everyone can chat with it now: from its page, and from Home's agent picker.
  await page.getByRole("button", { name: "Chat with it" }).click();
  await expect(page).toHaveURL(/#\/s\//);
  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("Plan three days in Porto");
  await box.press("Enter");
  await expect(page.getByTestId("helper-card")).toBeVisible({ timeout: 30_000 });
  const sid = decodeURIComponent(new URL(page.url()).hash.slice(4));
  await waitTurnOver(request, sid);
  const agents = await getJson<{ name: string; display_name: string; source: string }[]>(request, "/api/agents");
  expect(agents.find((a) => a.display_name === name)?.source).toBe("user");
  const turn = await getJson<{ messages: { type: string }[] }>(request, `/api/sessions/${sid}/messages`);
  expect(turn.messages.filter((m) => m.type === "tool_call").length).toBeGreaterThan(0);
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: "Agent" }).locator("option", { hasText: name })).toHaveCount(1);
  expect(id).toBeTruthy();
});

test("issues show next to their field, and editing after a test needs a new test", async ({ page }) => {
  await newAgent(page, `Sloppy ${Date.now().toString(36)}`);
  await page.getByLabel("What is it for?").fill("Tries things.");
  await page.getByLabel("Instructions", { exact: true }).fill("Hi {{secret}}");
  await saved(page);
  const instructions = page.getByTestId("section-instructions");
  await expect(instructions.getByTestId("field-issues")).toContainText("{{secret}} isn't something it can fill in");
  await page.getByLabel("Instructions", { exact: true }).fill("Hi. Today is {{date}}.");
  await saved(page);
  await expect(page.getByTestId("field-issues")).toHaveCount(0);

  await page.getByRole("button", { name: "Start a test chat" }).click();
  const chat = page.getByTestId("test-chat");
  await chat.getByRole("textbox", { name: "Message" }).fill("hello");
  await chat.getByRole("textbox", { name: "Message" }).press("Enter");
  await expect(chat.getByText("Tested", { exact: true })).toBeVisible({ timeout: 30_000 });
  await page.getByLabel("What is it for?").fill("Tries things, carefully."); // a change → a new test
  await saved(page);
  await expect(chat.getByText("Not tested yet")).toBeVisible({ timeout: 15_000 });
});

test("copy a built-in agent, publish twice, restore the first version", async ({ page }) => {
  await page.goto("/#/agents");
  const nuria = page.getByTestId("agent-card").filter({ hasText: "Nuria" });
  await nuria.getByRole("button", { name: "Copy" }).click();
  const name = `My Nuria ${Date.now().toString(36)}`;
  await page.getByRole("dialog").getByLabel("Name").fill(name);
  await page.getByRole("dialog").getByRole("button", { name: "Copy", exact: true }).click();
  await expect(page).toHaveURL(/#\/studio\//);
  await expect(page.getByTestId("helper-editor")).toHaveCount(2); // the helpers came along
  await saved(page).catch(() => undefined);

  const publish = async (note: string) => {
    await page.getByRole("button", { name: "Start a test chat" }).or(page.getByRole("button", { name: "New test" })).first().click();
    const chat = page.getByTestId("test-chat");
    await expect(chat.getByText("Start the conversation")).toBeVisible(); // the new, empty test chat
    await chat.getByRole("textbox", { name: "Message" }).fill("hello");
    await chat.getByRole("textbox", { name: "Message" }).press("Enter");
    await expect(chat.getByText("Tested", { exact: true })).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Publish" }).first().click();
    await page.getByRole("dialog").getByLabel(/What changed/).fill(note);
    await page.getByRole("dialog").getByRole("button", { name: "Publish" }).click();
  };
  await publish("Copied");
  await expect(page.getByText("Published v1")).toBeVisible();
  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("What is it for?").fill("Changed in v2.");
  await saved(page);
  await publish("Changed the description");
  await expect(page.getByText("Published v2")).toBeVisible();

  await page.getByRole("button", { name: "History" }).click();
  const history = page.getByTestId("history");
  await expect(history).toContainText("Changed the description");
  await history.locator("li", { hasText: "Version 1" }).getByRole("button", { name: "Restore" }).click();
  await expect(page.getByLabel("What is it for?")).not.toHaveValue("Changed in v2.");
  await expect(page.getByText(/unpublished changes/)).toBeVisible();
  expect(await serious(page)).toEqual([]);
});
