// The Chairperson signs a meeting request from the screen they actually use, and the
// request leaves their inbox for the Academic Office.
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { openNav, watchForCrashes } from "./support/ui.js";
import { statePath, FIXTURE_FILE } from "./support/paths.js";
import { sessionFromState } from "./support/api.js";

const fixtures = JSON.parse(fs.readFileSync(FIXTURE_FILE, "utf8")).fixtures;
const BASE_URL = process.env.DAC_BASE_URL || "http://127.0.0.1:8050";

test.describe("Chairperson · request signature", () => {
  test.use({ storageState: statePath("chair") });

  test("reviews the whole request, signs it, and it moves to the Academic Office", async ({ page }) => {
    const crashes = watchForCrashes(page);
    const { workspaceId } = fixtures.chairQueue;
    const department = fixtures.chairQueue.department;

    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });

    // The queue of requests awaiting this Chairperson's signature sits on the Overview.
    const panel = page.locator("section.panel", { hasText: "Requests waiting for your signature" });
    await expect(panel).toBeVisible({ timeout: 20_000 });
    // A row shows the department and the date — that is what a Chairperson reads.
    const row = panel.locator(".chair-row", { hasText: fixtures.chairQueue.department });
    await expect(row).toBeVisible({ timeout: 20_000 });

    await row.getByRole("button", { name: /Review request/i }).click();

    // The review shows the document itself, not a summary line.
    const review = page.locator(".chair-review-body");
    await expect(review).toBeVisible({ timeout: 20_000 });
    await expect(review).toContainText(/Agenda No/i);
    await expect(review).toContainText(/Proposed invitees/i);

    const approve = page.locator(".chair-review-foot").getByRole("button", { name: /Sign & approve/i });
    await expect(approve).toBeVisible({ timeout: 20_000 });
    await approve.click();

    await expect(page.locator(".toast")).toContainText(/Approved|signed/i, { timeout: 30_000 });

    // The server agrees: it is no longer awaiting the Chairperson.
    const office = await sessionFromState(BASE_URL, statePath("office"));
    const inbox = await office.get("/api/workspaces/inbox");
    const queue = (inbox.body.workspaces || []).map((item) => item.workspaceId);
    expect(queue).toContain(workspaceId);

    const stored = await office.get(`/api/workspaces/${workspaceId}`);
    expect(stored.status).toBe(200);
    expect(stored.body.state.status).toBe("pending");

    const signatures = await office.get(`/api/workspace/${workspaceId}/signatures`);
    const rows = Object.fromEntries((signatures.body.signatures || []).map((item) => [item.role, item]));
    expect(rows.Chairperson?.image, "the Chairperson's signature is on the request").toBeTruthy();
    expect(rows["Member Secretary"]?.image, "the Member Secretary's signature is on the request").toBeTruthy();

    expect(crashes, `console errors: ${crashes.join(" | ")}`).toEqual([]);
  });

  test("the Chairperson's inbox is now empty of that request", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await openNav(page, "Overview");
    const panel = page.locator("section.panel", { hasText: "Requests waiting for your signature" });
    if (await panel.isVisible().catch(() => false)) {
      await expect(panel.locator(".chair-row", { hasText: fixtures.chairQueue.department })).toHaveCount(0);
    }
  });
});
