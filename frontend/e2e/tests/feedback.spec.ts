/**
 * Phase L5: feedback in two clicks, nothing sent without one (SC4); "Report this
 * reply" and "Download this chat" (SC5); usage counts only when turned on (SC6).
 */
import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { startChat, waitTurnOver } from "./support";

test.afterEach(async ({ request }) => {
  await request.put("/api/telemetry", { data: { sharing: false } }); // leave it as it was: off
});

test("send feedback: the issue is pre-filled, and nothing goes to GitHub before the click", async ({ page }) => {
  const outside: string[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).hostname.endsWith("github.com")) outside.push(r.url());
  });
  await page.goto("/");
  await expect(page.getByTestId("nuria-version")).toHaveText(/^Nuria \d+\.\d+\.\d+$/);
  await page.getByTestId("send-feedback").click();
  const dialog = page.getByTestId("feedback-dialog");
  await expect(page.getByTestId("feedback-github")).toHaveAttribute("aria-disabled", "true"); // empty: nothing to send
  await dialog.getByLabel("What were you doing?").fill("Trying the demo");
  await dialog.getByLabel("What happened?").fill("It answered quickly");
  await dialog.getByRole("button", { name: "Delightful" }).click();
  await expect(page.getByTestId("feedback-details")).toContainText("Nuria");
  await expect(page.getByTestId("feedback-details")).not.toContainText("Usage counts"); // off by default

  const href = await page.getByTestId("feedback-github").getAttribute("href");
  const url = new URL(href ?? "");
  expect(url.pathname).toBe("/sofianebouabdallahh-ai/durable-langgraph-runtime/issues/new");
  expect(url.searchParams.get("template")).toBe("feedback.yml");
  expect(url.searchParams.get("happened")).toBe("It answered quickly");
  expect(url.searchParams.get("feeling")).toBe("5 – Delightful");
  await expect(page.getByTestId("feedback-github")).toHaveAttribute("target", "_blank");

  const saved = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download" }).click();
  const file = readFileSync(await (await saved).path(), "utf8");
  expect(file).toContain("## What happened?\nIt answered quickly");
  expect(outside).toEqual([]); // the page never talked to GitHub on its own
});

test("usage counts: off by default, shown exactly, added to feedback only when on", async ({ page }) => {
  await page.goto("/#/settings/privacy");
  const toggle = page.getByRole("switch", { name: "Share anonymous usage counts with my feedback" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId("usage-table")).toContainText("chat turns, all time");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("send-feedback").click();
  await expect(page.getByTestId("feedback-details")).toContainText("Usage counts");
  await page.getByLabel("Include the anonymous usage counts (Settings → Privacy)").uncheck();
  await expect(page.getByTestId("feedback-details")).not.toContainText("Usage counts");
});

test("report this reply, and download this chat", async ({ page, request }) => {
  const sid = await startChat(page, "Remember that the demo is on Friday");
  await expect(page.getByTestId("tool-card")).toContainText("Saved a note");
  await waitTurnOver(request, sid);

  const chat = page.waitForEvent("download");
  await page.getByTestId("download-chat").click();
  const md = readFileSync(await (await chat).path(), "utf8");
  expect(md).toContain("Remember that the demo is on Friday");
  expect(md).toContain("*Used save_note*");

  await page.getByRole("button", { name: "What happened?" }).click();
  await page.getByTestId("report-reply").click();
  await expect(page.getByTestId("report-dialog")).toContainText("Nothing is uploaded");
  const plain = await page.getByTestId("report-download").getAttribute("href");
  expect(plain).toMatch(/^\/api\/runs\/[0-9a-f-]+\/report$/);
  await page.getByLabel("Also include this conversation's text (what you wrote and what it answered)").check();
  await expect(page.getByTestId("report-download")).toHaveAttribute("href", `${plain ?? ""}?include_chat=true`);
  const zip = page.waitForEvent("download");
  await page.getByTestId("report-download").click();
  const got = await zip;
  expect(got.suggestedFilename()).toMatch(/^nuria-report-[0-9a-f]{8}\.zip$/);
  expect(readFileSync(await got.path()).subarray(0, 2).toString()).toBe("PK"); // a zip
  const issue = new URL((await page.getByTestId("report-github").getAttribute("href")) ?? "");
  expect(issue.searchParams.get("template")).toBe("agent-behaviour.yml");
});
