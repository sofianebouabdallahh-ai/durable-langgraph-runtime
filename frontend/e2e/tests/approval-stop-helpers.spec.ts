/** SC5 approvals, SC6 stop, SC7 helpers: the controls a person uses mid-reply. */
import { expect, test } from "@playwright/test";

import { expectScreenMatchesTranscript, send, transcript, waitTurnOver, startChat } from "./support";

test("approve a notification, after a reload", async ({ page, request }) => {
  const sid = await startChat(page, "Notify the team that the build is green");
  const card = page.getByTestId("approval-card");
  await expect(card).toContainText("Nuria wants to use: Notification");
  await expect(page.getByText("Waiting for your approval")).toHaveCount(0); // the card says it
  await page.reload(); // a decision can wait: nothing is held meanwhile
  await expect(card).toContainText("the build is green");
  await card.getByRole("button", { name: "Approve" }).click();
  await expect(card).toContainText("You approved this");
  await expect(page.getByTestId("assistant-message").last()).toContainText("Done.");
  await waitTurnOver(request, sid);
  const messages = await expectScreenMatchesTranscript(page, request, sid);
  expect(messages.filter((m) => m.type === "tool_result")).toHaveLength(1); // ran once
});

test("reject one, with a reason", async ({ page, request }) => {
  const sid = await startChat(page, "Notify ops that we are down");
  const card = page.getByTestId("approval-card");
  await card.getByPlaceholder("Reason (optional)").fill("not today");
  await card.getByRole("button", { name: "Reject" }).click();
  await expect(card).toContainText("You rejected this");
  await waitTurnOver(request, sid);
  const decision = (await transcript(request, sid)).find((m) => m.type === "approval");
  expect(decision?.content).toMatchObject({ decision: "reject", reason: "not today" });
});

test("stop a reply: the partial reply stays, and the chat goes on", async ({ page, request }) => {
  const sid = await startChat(page, "hello");
  await expect(page.getByTestId("draft")).toBeVisible();
  const stopped = Date.now();
  await page.getByRole("button", { name: "Stop the reply" }).click();
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible({ timeout: 5_000 });
  expect(Date.now() - stopped).toBeLessThan(2_000 + 1_000); // SC6: < 2 s (+ the poll's slack)
  await expect(page.getByText("Stopped.")).toBeVisible();
  await expect(page.getByText("(stopped before the end)")).toBeVisible();
  await waitTurnOver(request, sid);
  await send(page, "What is 1 + 1?");
  await expect(page.getByTestId("assistant-message").last()).toContainText("2");
  await waitTurnOver(request, sid);
  await expectScreenMatchesTranscript(page, request, sid);
});

test("two helpers work in parallel, with live progress, then the combined answer", async ({ page, request }) => {
  const sid = await startChat(page, "Research Redis Streams and compute 12 * 4");
  const cards = page.getByTestId("helper-card");
  await expect(cards).toHaveCount(2);
  await expect(page.getByText("Helper: researcher")).toBeVisible();
  await expect(page.getByText("Helper: data-analyst")).toBeVisible();
  await expect(page.getByTestId("assistant-message").last()).toContainText("48");
  await expect(cards.filter({ hasText: "Done" })).toHaveCount(2);
  await waitTurnOver(request, sid);
  await page.reload(); // helpers' results come back from the saved run
  await expect(cards).toHaveCount(2);
  await expect(cards.filter({ hasText: "12 * 4 = 48" })).toHaveCount(1); // the analyst's result
});
