// The Action Taken Report, end to end through the screens: the Member Secretary fills
// every row and signs, the Chairperson signs, and the signed PDF downloads.
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { openNav, watchForCrashes } from "./support/ui.js";
import { statePath, FIXTURE_FILE } from "./support/paths.js";
import { sessionFromState } from "./support/api.js";

const fixtures = JSON.parse(fs.readFileSync(FIXTURE_FILE, "utf8")).fixtures;
const BASE_URL = process.env.DAC_BASE_URL || "http://127.0.0.1:8050";
const WORKSPACE = fixtures.atrReady.workspaceId;

test.describe("Action Taken Report · Member Secretary", () => {
  test.use({ storageState: statePath("atr-secretary") });

  test("the report is open, lists one row per action item, and is due before the next meeting", async ({ page }) => {
    const crashes = watchForCrashes(page);
    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await openNav(page, "Action Taken Report");

    await expect(page.getByRole("heading", { name: /Action Taken Report/i }).first()).toBeVisible({ timeout: 25_000 });
    // Timing rules are shown, not hidden: the latest target date drives the deadline.
    await expect(page.locator(".view-root")).toContainText(/Latest action-item target date/i);
    await expect(page.locator(".view-root")).toContainText(/Due by/i);

    const rows = page.locator(".atr-table tbody tr");
    await expect(rows).toHaveCount(3, { timeout: 20_000 });
    await expect(page.getByLabel("Status for row 1")).toBeEditable();

    expect(crashes, `console errors: ${crashes.join(" | ")}`).toEqual([]);
  });

  test("fills each row, signs with the Member Secretary's signature and submits", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await openNav(page, "Action Taken Report");
    await expect(page.locator(".atr-table tbody tr")).toHaveCount(3, { timeout: 25_000 });

    for (let index = 1; index <= 3; index += 1) {
      await page.getByLabel(`Status for row ${index}`).selectOption(index < 3 ? "Completed" : "In Progress");
      await page.getByLabel(`Action taken for row ${index}`)
        .fill(index < 3
          ? `Action ${index} carried out; evidence filed with the department.`
          : `Action ${index} is in progress — the department has been asked for a revised date.`);
    }

    await page.getByRole("button", { name: /Save draft/i }).first().click();
    await page.getByRole("button", { name: /Sign & submit to the Chairperson/i }).click();
    await expect(page.locator(".toast")).toBeVisible({ timeout: 30_000 });

    const secretary = await sessionFromState(BASE_URL, statePath("atr-secretary"));
    await expect.poll(async () => {
      const stored = await secretary.get(`/api/atr/${WORKSPACE}`);
      return stored.body.report?.status || "";
    }, { timeout: 25_000 }).toBe("submitted");

    const stored = await secretary.get(`/api/atr/${WORKSPACE}`);
    expect(stored.body.report.secretarySignature?.signatureSha256).toBeTruthy();
    // Once submitted it is locked for editing — the report is evidence.
    const afterEdit = await secretary.post(`/api/atr/${WORKSPACE}/save`, { rows: stored.body.report.rows });
    expect(afterEdit.status).toBe(409);
  });
});

test.describe("Action Taken Report · Chairperson", () => {
  test.use({ storageState: statePath("chair-soe") });

  test("signs the report and downloads the signed PDF", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await openNav(page, "Action Taken Report");

    // The Chairperson picks the report from the meetings nominated to them.
    const pick = page.locator(".workspace-pick-row", { hasText: fixtures.atrReady.department });
    if (await pick.count()) await pick.first().click();

    const sign = page.getByRole("button", { name: /Sign the report/i });
    await expect(sign).toBeVisible({ timeout: 25_000 });
    await sign.click();
    await expect(page.locator(".toast")).toBeVisible({ timeout: 30_000 });

    const download = page.getByRole("link", { name: /Download the signed report/i });
    await expect(download).toBeVisible({ timeout: 25_000 });

    const [response] = await Promise.all([page.waitForEvent("download"), download.click()]);
    expect(response.suggestedFilename()).toMatch(/\.pdf$/i);

    const chair = await sessionFromState(BASE_URL, statePath("chair-soe"));
    const pdf = await chair.raw(`/api/atr/${WORKSPACE}/document`);
    expect(pdf.status).toBe(200);
    expect(pdf.bytes.subarray(0, 4).toString()).toBe("%PDF");
    expect(pdf.bytes.length).toBeGreaterThan(5_000);
  });
});
