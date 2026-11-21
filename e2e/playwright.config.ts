import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against the isolated stack (e2e/stack.sh up): web 8090, api 8001, db 5433
 * (another copy: E2E_WEB_URL, E2E_API_URL, E2E_DB_CONTAINER, E2E_WEB_CONTAINER).
 * `@live` tests call real LLMs (Groq first; Claude capped by CLAUDE_MONTHLY_BUDGET_USD=0.30 in
 * the e2e stack and by helpers/db.ts spentUsd()) and only run with LIVE=1.
 */
const live = process.env.LIVE === "1";

export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // one shared database
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  grepInvert: live ? undefined : /@live/,
  globalSetup: "./global-setup.ts",
  use: {
    baseURL: process.env.E2E_WEB_URL ?? "http://127.0.0.1:8090",
    storageState: ".auth/state.json",
    locale: "tr-TR",
    timezoneId: "Europe/Istanbul",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1400, height: 900 } } }],
});
