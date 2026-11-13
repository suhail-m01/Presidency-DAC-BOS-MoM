// Playwright end-to-end configuration.
//
// The suite drives the real interface in a real Chromium against a running server:
//
//     bash tests/run_e2e.sh                     (recommended — starts its own server)
//     DAC_BASE_URL=http://127.0.0.1:8050 npx playwright test
//
// Deliberate choices:
//   * one worker — the app is session- and database-backed, and two journeys advancing
//     the same meeting clock in parallel would race;
//   * traces, screenshots and video only on failure — a green run stays small;
//   * the HTML report is the artefact to open when something fails.
import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.DAC_BASE_URL || "http://127.0.0.1:8050";
const CI = Boolean(process.env.CI);

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e/.artifacts",
  globalSetup: "./e2e/global-setup.js",
  fullyParallel: false,
  workers: 1,
  retries: CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [
    ["list"],
    ["html", { outputFolder: "./e2e/report", open: "never" }],
    ["json", { outputFile: "./e2e/report/results.json" }],
  ],
  use: {
    baseURL: BASE_URL,
    headless: true,
    viewport: { width: 1440, height: 900 },
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
