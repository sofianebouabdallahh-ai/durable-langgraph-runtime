import { defineConfig, devices } from "@playwright/test";

// Run against the Compose stack (`./setup.sh`), from a container on its network:
// `make ui-e2e`. BASE_URL is the UI as the browser sees it.
export default defineConfig({
  testDir: "tests",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  fullyParallel: false, // the chaos tests kill shared containers: one at a time
  workers: 1,
  retries: 0, // a flaky durability test is a bug, not noise
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://ui:8080",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
