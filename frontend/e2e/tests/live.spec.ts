/**
 * SC2 with a real model: replies stream word by word and the model uses a tool.
 * Needs a model behind the stack (`./setup.sh --model ollama`, or a key):
 *   make ui-e2e LIVE_MODEL=1 ARGS="tests/live.spec.ts"
 */
import { expect, test } from "@playwright/test";

import { expectScreenMatchesTranscript, send, waitTurnOver, startChat } from "./support";

test.skip(!process.env.LIVE_MODEL, "needs a real model: LIVE_MODEL=1");
test.setTimeout(300_000);

test("a real model streams its reply and uses the calculator", async ({ page, request }) => {
  const sid = await startChat(page, "In two sentences: what is a fencing token in distributed systems?");
  await expect(page.getByTestId("draft")).toBeVisible({ timeout: 120_000 }); // words before the end
  await expect(page.getByTestId("assistant-message")).toHaveCount(1, { timeout: 180_000 });
  await waitTurnOver(request, sid);
  await send(page, "What is 23 * 19? Use the calculator.");
  await expect(page.getByTestId("tool-card")).toContainText("Calculator", { timeout: 180_000 });
  await expect(page.getByTestId("assistant-message").last()).toContainText("437", { timeout: 180_000 });
  await waitTurnOver(request, sid);
  await expectScreenMatchesTranscript(page, request, sid);
});
