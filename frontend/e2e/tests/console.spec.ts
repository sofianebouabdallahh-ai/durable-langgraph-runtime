/**
 * Every page loads without an error in the browser's console: a blocked resource (the
 * CSP refused an inlined font on every page, unseen by any other test) or a crash.
 */
import { expect, test } from "@playwright/test";

const ROUTES = ["", "start", "agents", "skills", "settings/models", "settings/tools", "settings/privacy", "activity", "activity/audit"];

// The test browser reaches the UI as http://ui, which isn't a trustworthy origin, so it
// ignores the Cross-Origin-Opener-Policy header and says so. On localhost it doesn't.
const ONLY_HERE = /Cross-Origin-Opener-Policy header has been ignored/;

test("every page loads with nothing blocked and no errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" && !ONLY_HERE.test(m.text())) errors.push(`${page.url()}: ${m.text().slice(0, 200)}`);
  });
  page.on("pageerror", (e) => errors.push(`${page.url()}: ${e.message}`));
  for (const route of ROUTES) {
    await page.goto(`/#/${route}`);
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  }
  expect(errors).toEqual([]);
});
