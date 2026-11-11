/**
 * H8: what an agent remembers, from a chat's note card to the agent's page, where you
 * can see it, bring back what it forgot, delete one note, or forget everything.
 */
import { type APIRequestContext, expect, test } from "@playwright/test";

import { getJson, waitTurnOver } from "./support";

type Memory = { notes: { id: string; text: string; forgotten_at: string | null }[] };

async function scripted(request: APIRequestContext, content: string, script: unknown[]): Promise<string> {
  const sid = ((await (await request.post("/api/sessions", { data: { agent: "chat", title: content } })).json()) as { id: string }).id;
  const sent = await request.post(`/api/sessions/${sid}/messages`, { data: { content, script } });
  expect(sent.status()).toBe(202);
  await waitTurnOver(request, sid);
  return sid;
}

async function idOf(request: APIRequestContext, text: string): Promise<string> {
  const memory = await getJson<Memory>(request, "/api/agents/chat/memory");
  const note = memory.notes.find((n) => n.text === text);
  expect(note).toBeDefined();
  return note?.id ?? "";
}

test("H8: a saved note's card leads to what it remembers; forgotten notes come back; you can delete", async ({ page, request }) => {
  const keep = `locker ${String(Date.now())}`;
  const drop = `old fact ${String(Date.now())}`;
  const sid = await scripted(request, "remember my locker", [{ tool_calls: [{ name: "save_note", args: { text: keep } }] }, { content: "Saved." }]);
  await scripted(request, "remember", [{ tool_calls: [{ name: "save_note", args: { text: drop } }] }, { content: "Saved." }]);
  const dropId = await idOf(request, drop);
  await scripted(request, "forget it", [{ tool_calls: [{ name: "forget_note", args: { note_id: dropId } }] }, { content: "Forgotten." }]);

  // From the chat: the note's card, opened, links to the agent's memory.
  await page.goto(`/#/s/${sid}`);
  await page.getByTestId("tool-card").getByRole("button", { name: /Saved a note/ }).click();
  await page.getByRole("link", { name: "See what it remembers" }).click();
  await page.waitForFunction(() => location.hash === "#/agents/chat/memory");
  const memory = page.getByTestId("memory");
  const remembered = memory.getByRole("list", { name: "Remembered" });
  await expect(remembered).toContainText(keep);
  await expect(remembered).not.toContainText(drop);

  // What it was asked to forget: listed apart, and restored at once.
  await memory.getByText(/^Forgotten \(/).click();
  const forgotten = memory.getByRole("list", { name: "Forgotten" });
  await expect(forgotten).toContainText(drop);
  await forgotten.getByRole("button", { name: `Restore “${drop}”` }).click();
  await expect(remembered).toContainText(drop);

  // Delete one, for good.
  await remembered.getByRole("button", { name: `Delete “${keep}”` }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete", exact: true }).click();
  await expect(remembered).not.toContainText(keep);
  const after = await getJson<Memory>(request, "/api/agents/chat/memory");
  expect(after.notes.map((n) => n.text)).not.toContain(keep);
  expect(after.notes.find((n) => n.text === drop)?.forgotten_at).toBeNull();

  // Forget everything, after saying yes.
  await memory.getByRole("button", { name: "Forget everything" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Forget everything" }).click();
  await expect(memory).toContainText("Nothing yet");
  expect((await getJson<Memory>(request, "/api/agents/chat/memory")).notes).toEqual([]);
});
