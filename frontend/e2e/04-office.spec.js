// The Academic Office approves an agenda and roster, and the approval is what unlocks
// the rest of the workflow. Also covers the minutes-review queue and the calendar.
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { openNav, watchForCrashes } from "./support/ui.js";
import { statePath, FIXTURE_FILE } from "./support/paths.js";
import { sessionFromState } from "./support/api.js";

const fixtures = JSON.parse(fs.readFileSync(FIXTURE_FILE, "utf8")).fixtures;
const BASE_URL = process.env.DAC_BASE_URL || "http://127.0.0.1:8050";

test.describe("Academic Office · approval queue", () => {
  test.use({ storageState: statePath("office") });

  test("approves a request that both signatories have signed", async ({ page }) => {
    const crashes = watchForCrashes(page);
    const { workspaceId } = fixtures.officeQueue;

    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await openNav(page, "Approval queue");

    // A single pending request opens on its own; a longer queue is a list to pick from.
    const queueRow = page.locator(".admin-queue-row", { hasText: fixtures.officeQueue.department });
    if (await queueRow.count()) await queueRow.first().click();

    const comment = page.locator("#office-comment");
    if (await comment.isVisible().catch(() => false)) {
      await comment.fill("Agenda wording and roster checked against the department list.");
    }
    const approve = page.getByRole("button", { name: /Approve agenda & members/i });
    await expect(approve).toBeVisible({ timeout: 25_000 });
    await approve.click();
    await expect(page.locator(".toast")).toContainText(/approved/i, { timeout: 30_000 });

    const office = await sessionFromState(BASE_URL, statePath("office"));
    const stored = await office.get(`/api/workspaces/${workspaceId}`);
    expect(stored.body.state.status).toBe("approved");

    // Approval produced the signed request form in the document vault.
    const vault = await office.get("/api/documents");
    const titles = (vault.body.documents || []).map((doc) => `${doc.docType}:${doc.workspaceId || ""}`);
    expect(titles.some((entry) => entry.startsWith("request"))).toBeTruthy();

    expect(crashes, `console errors: ${crashes.join(" | ")}`).toEqual([]);
  });

  test("cannot approve the same request twice", async () => {
    const office = await sessionFromState(BASE_URL, statePath("office"));
    // Approving is a one-way signature step; a second approval is refused rather than
    // silently re-stamping the document.
    const result = await office.post("/api/workspace/decision", {
      workspaceId: fixtures.momDraft.workspaceId, decision: "approved", comment: "",
    });
    expect(result.status).toBe(409);
    expect(JSON.stringify(result.body)).toMatch(/no longer pending/i);
  });

  test("the minutes review queue and the meeting calendar both open", async ({ page }) => {
    const crashes = watchForCrashes(page);
    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });

    await openNav(page, "Minutes review");
    await expect(page.locator(".view-root")).toBeVisible();

    await openNav(page, "Meeting calendar");
    await expect(page.locator(".view-root")).toContainText(/calendar|meeting|semester/i, { timeout: 20_000 });

    await openNav(page, "Agenda library");
    await expect(page.locator(".view-root")).toContainText(/agenda/i, { timeout: 20_000 });

    expect(crashes, `console errors: ${crashes.join(" | ")}`).toEqual([]);
  });
});
