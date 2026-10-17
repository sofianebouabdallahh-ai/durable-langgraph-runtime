/** SC1, SC2: chat in the browser; replies stream in; tools as cards; plain words. */
import { expect, test } from "@playwright/test";

import { expectScreenMatchesTranscript, send, waitTurnOver, startChat } from "./support";

test("a question, a tool card, an answer", async ({ page, request }) => {
  const sid = await startChat(page, "What is 12 * (3 + 4)?");
  await expect(page.getByTestId("model-status")).toContainText("Demo model");
  await expect(page.getByTestId("tool-card")).toContainText("Calculator");
  await expect(page.getByTestId("assistant-message").last()).toContainText("84");
  await waitTurnOver(request, sid);
  await expectScreenMatchesTranscript(page, request, sid);
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible(); // composer free again
  // The chat is named after its first message.
  await expect(page.getByTestId("session-list")).toContainText("What is 12 * (3 + 4)?");
});

test("the reply streams in, then becomes the saved reply without a flicker or a double", async ({ page, request }) => {
  const sid = await startChat(page, "hello");
  await expect(page.getByTestId("draft")).toBeVisible(); // words arrive before the reply is complete
  await expect(page.getByTestId("assistant-message")).toContainText("Notify the team");
  await expect(page.getByTestId("draft")).toHaveCount(0);
  await expect(page.getByText("I'm running on the")).toHaveCount(1);
  await waitTurnOver(request, sid);
  await expectScreenMatchesTranscript(page, request, sid);
});

test("“What happened?” tells the turn's story in plain words", async ({ page, request }) => {
  const sid = await startChat(page, "Remember that the demo is on Friday");
  await expect(page.getByTestId("tool-card")).toContainText("Saved a note");
  await waitTurnOver(request, sid);
  await page.getByRole("button", { name: "What happened?" }).click();
  const panel = page.getByTestId("what-happened");
  await expect(panel).toContainText("A worker picked it up");
  await expect(panel).toContainText("Done");
});

test("several turns keep their context, and a reload shows the same conversation", async ({ page, request }) => {
  const sid = await startChat(page, "What is 2 + 2?");
  await expect(page.getByTestId("assistant-message").first()).toContainText("4");
  await waitTurnOver(request, sid);
  await send(page, "Search for Redis Streams");
  await expect(page.getByTestId("tool-card").nth(1)).toContainText("Search");
  await waitTurnOver(request, sid);
  await page.reload();
  await expectScreenMatchesTranscript(page, request, sid);
});
