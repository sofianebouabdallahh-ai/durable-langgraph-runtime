/**
 * Phase L7c: the Activity page tells the truth. A chat turn shows up in the totals, the
 * turns list and the chats list with the API's numbers; a turn opens on its own page with
 * its model calls and its timeline; the charts have a table view (nothing is colour-only).
 */
import { expect, test } from "@playwright/test";

import { getJson, startChat, waitTurnOver } from "./support";

interface Totals { turns: number; tokens: number; tool_calls: number }
interface View { totals: Totals; agents: { agent: string; turns: number }[] }
interface TurnRow { id: string; session_id: string | null; status: string; model_calls: number }

test("a turn shows up in Activity, and opens with its model calls and timeline", async ({ page, request }) => {
  const sid = await startChat(page, "What is 12 * (3 + 4)?");
  await expect(page.getByTestId("assistant-message").last()).toContainText("84");
  await waitTurnOver(request, sid);

  await page.getByRole("link", { name: "Activity" }).click();
  await expect(page).toHaveURL(/#\/activity$/);
  const view = await getJson<View>(request, "/api/activity?range=7d");
  expect(view.totals.turns).toBeGreaterThan(0);
  const totals = page.getByTestId("activity-totals");
  await expect(totals).toContainText("Turns");
  await expect(page.getByTestId("activity-agents")).toContainText("Nuria");

  // The chats list has this chat, linked back to it.
  const chat = page.getByTestId("activity-sessions").locator(`a[href="#/s/${sid}"]`);
  await expect(chat).toBeVisible();

  // The turns list: newest first, so this chat's turn is near the top.
  const turns = await getJson<TurnRow[]>(request, `/api/activity/turns?range=7d&session_id=${sid}`);
  expect(turns).toHaveLength(1);
  const turn = turns[0]!;
  expect(turn.status).toBe("completed");
  const link = page.getByTestId("activity-turns").locator(`a[href="#/activity/turns/${turn.id}"]`);
  await expect(link).toBeVisible();

  // A chart reads as a table too.
  const chart = page.getByTestId("activity-turns-chart");
  await chart.getByRole("button", { name: "Show as a table" }).click();
  await expect(chart.getByRole("table")).toContainText("Nuria");
  await chart.getByRole("button", { name: "Show the chart" }).click();

  // The turn's own page: its model calls (they add up) and what happened.
  await link.click();
  const detail = page.getByTestId("turn-detail");
  await expect(detail).toContainText("Done");
  const models = page.getByTestId("turn-models");
  await expect(models).toBeVisible();
  await expect(models.locator("tbody tr")).not.toHaveCount(0);
  await expect(detail).toContainText(`${String(turn.model_calls)} model calls`);
  await expect(detail.getByText("What happened")).toBeVisible();
  await detail.getByRole("link", { name: "Open the chat" }).click();
  await expect(page).toHaveURL(new RegExp(`#/s/${sid}$`));
});

test("filters scope everything: the range, and test chats left out by default", async ({ page, request }) => {
  await page.goto("/#/activity");
  await expect(page.getByTestId("activity-totals")).toBeVisible();
  await page.getByTestId("activity-filters").getByRole("radio", { name: "24 hours" }).click();
  const turnsTile = page.getByTestId("stat-turns").locator("[data-value]");
  const day = await getJson<View>(request, "/api/activity?range=24h");
  const withTests = await getJson<View>(request, "/api/activity?range=24h&include_tests=true");
  expect(withTests.totals.turns).toBeGreaterThanOrEqual(day.totals.turns);
  await expect(turnsTile).toHaveText(String(day.totals.turns));

  await page.getByLabel("Include test chats").check();
  await expect(turnsTile).toHaveText(String(withTests.totals.turns));
  await expect(page.getByRole("link", { name: "Activity" })).toHaveAttribute("aria-current", "page");
});

test("an unknown turn says so", async ({ page }) => {
  await page.goto("/#/activity/turns/00000000-0000-0000-0000-000000000000");
  await expect(page.getByTestId("turn-detail")).toContainText("There's no such turn.");
});
