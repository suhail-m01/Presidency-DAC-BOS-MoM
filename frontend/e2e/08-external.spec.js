// The External Member's observation report — the Academic Office cannot approve the
// minutes until this report exists, so it is part of the workflow, not a side screen.
//
// The nominated External Member is a professor of a *different* school (the R1 rule), so
// this account keeps the faculty shell and the report lives under "My external
// observations". Order matters: the gate is proved before the report is submitted.
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { openNav, watchForCrashes } from "./support/ui.js";
import { statePath, FIXTURE_FILE } from "./support/paths.js";
import { sessionFromState } from "./support/api.js";

const fixtures = JSON.parse(fs.readFileSync(FIXTURE_FILE, "utf8")).fixtures;
const BASE_URL = process.env.DAC_BASE_URL || "http://127.0.0.1:8050";
const WORKSPACE = fixtures.externalPending.workspaceId;
const DEPARTMENT = fixtures.externalPending.department;

test.describe("External report · the Academic Office gate", () => {
  test.use({ storageState: statePath("office") });

  test("the minutes cannot be approved while the observation report is outstanding", async () => {
    const office = await sessionFromState(BASE_URL, statePath("office"));
    const result = await office.post("/api/workspace/mom/office-decision", {
      workspaceId: WORKSPACE, decision: "approved", comment: "",
    });
    expect([400, 409]).toContain(result.status);
    expect(JSON.stringify(result.body)).toMatch(/external|observation|report/i);
  });
});

test.describe("External Member · observation report", () => {
  test.use({ storageState: statePath("external-civil") });

  test("sees only the meeting they were nominated to, and answers every agenda item", async ({ page }) => {
    const crashes = watchForCrashes(page);
    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });

    await openNav(page, "My external observations");
    await expect(page.getByRole("heading", { name: /Observation report/i }).first()).toBeVisible({ timeout: 25_000 });

    // Pick the meeting this account was nominated to, from the meetings list.
    const pick = page.locator(".workspace-pick-row", { hasText: DEPARTMENT });
    if (await pick.count()) await pick.first().click();

    const table = page.locator("table.report-table");
    await expect(table).toBeVisible({ timeout: 25_000 });
    const agendaRows = table.locator("tbody tr");
    const count = await agendaRows.count();
    expect(count).toBeGreaterThan(0);

    for (let index = 0; index < count; index += 1) {
      await page.locator(`input[name="resp-${index}"]`).first().check();
    }
    await page.locator(".report-remark").first().fill("The meeting commenced on time and the records were complete.");

    await page.getByRole("button", { name: /Submit to the Academic Office/i }).click();
    await expect(page.locator(".toast")).toBeVisible({ timeout: 30_000 });

    const external = await sessionFromState(BASE_URL, statePath("external-civil"));
    await expect.poll(async () => {
      const stored = await external.get(`/api/external-report/${WORKSPACE}`);
      return stored.body.status || stored.body.report?.status || "";
    }, { timeout: 25_000 }).toBe("submitted");

    expect(crashes, `console errors: ${crashes.join(" | ")}`).toEqual([]);
  });

  test("an External Member cannot reach another school's meeting", async () => {
    const external = await sessionFromState(BASE_URL, statePath("external-civil"));
    // The observation report for a meeting they were not nominated to is not theirs.
    const other = await external.get(`/api/external-report/${fixtures.momDraft.workspaceId}`);
    expect([403, 404]).toContain(other.status);
  });

  test("the office can then approve the minutes", async () => {
    const office = await sessionFromState(BASE_URL, statePath("office"));
    const result = await office.post("/api/workspace/mom/office-decision", {
      workspaceId: WORKSPACE, decision: "approved", comment: "",
    });
    expect(result.status).toBe(200);
    expect(result.body.momReview?.status).toBe("approved");
  });
});
