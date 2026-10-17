/** The Agents section: each agent's instructions, tools, limits and helpers (sub-agents). */
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const serious = async (page: import("@playwright/test").Page) =>
  (await new AxeBuilder({ page }).analyze()).violations.filter((v) => v.impact === "serious" || v.impact === "critical");

test("agents and their helpers, then a chat with one", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Agents" }).click();
  await expect(page).toHaveURL(/#\/agents$/);
  const cards = page.getByTestId("agent-card");
  await expect(cards.filter({ hasText: "Nuria" })).toHaveCount(1);
  await expect(cards.filter({ hasText: "Delegator" })).toHaveCount(0); // test fixtures stay hidden
  await expect(page.getByText("Building your own agents is coming next")).toBeVisible();
  expect(await serious(page)).toEqual([]);

  await cards.filter({ hasText: "Nuria" }).click();
  await expect(page.getByRole("heading", { name: "Nuria", level: 1 })).toBeVisible();
  await expect(page.getByText("Instructions").first()).toBeVisible();
  await expect(page.getByText("‹today's date›")).toBeVisible(); // a placeholder, explained
  await expect(page.getByText("Sends messages to people, only with your approval")).toBeVisible();
  await expect(page.getByText("Up to 40 steps per message")).toBeVisible();
  const helpers = page.getByTestId("agent-helper");
  await expect(helpers).toHaveCount(2);
  await expect(helpers.filter({ hasText: "researcher" })).toContainText("Search");
  await helpers.filter({ hasText: "researcher" }).getByRole("button", { name: "Instructions" }).click();
  await expect(helpers.filter({ hasText: "researcher" })).toContainText("return_result");
  expect(await serious(page)).toEqual([]);

  await page.getByRole("button", { name: "Chat with Nuria" }).click();
  await expect(page).toHaveURL(/#\/s\//);
  await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();
});
