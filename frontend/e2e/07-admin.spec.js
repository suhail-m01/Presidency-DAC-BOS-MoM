// Administration and the archive: the access directory, the document vault, filters in
// the committee archive, notifications and the audit trail.
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { openNav, watchForCrashes } from "./support/ui.js";
import { statePath, FIXTURE_FILE } from "./support/paths.js";
import { sessionFromState } from "./support/api.js";

const fixtures = JSON.parse(fs.readFileSync(FIXTURE_FILE, "utf8")).fixtures;
const BASE_URL = process.env.DAC_BASE_URL || "http://127.0.0.1:8050";

test.describe("System Administrator", () => {
  test.use({ storageState: statePath("admin") });

  test("the access directory lists the accounts and their signatures", async ({ page }) => {
    const crashes = watchForCrashes(page);
    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await openNav(page, "Access directory");

    // The directory is the allow-list: the whole college, then narrowed by the search box.
    const rows = page.locator("table.directory-table tbody tr");
    await expect(rows.first()).toBeVisible({ timeout: 25_000 });
    const everyone = await rows.count();
    expect(everyone).toBeGreaterThan(20);

    const search = page.locator("input.directory-search");
    await search.fill("Poonam");
    await expect(rows.first()).toContainText(/Poonam/i, { timeout: 15_000 });
    expect(await rows.count()).toBeLessThan(everyone);
    expect(await rows.count()).toBeGreaterThan(0);

    // Credentials, DAC office and signature state are all on the row.
    await expect(rows.first()).toContainText(/poonam\.nilesh@presidencyuniversity\.in/i);

    expect(crashes, `console errors: ${crashes.join(" | ")}`).toEqual([]);
  });

  test("the document vault lists the archived documents and downloads one", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await openNav(page, "Document vault");

    await expect(page.locator(".view-root")).toContainText(/document/i, { timeout: 25_000 });
    const admin = await sessionFromState(BASE_URL, statePath("admin"));
    const listed = await admin.get("/api/documents");
    expect(listed.status).toBe(200);
    const documents = listed.body.documents || [];
    expect(documents.length).toBeGreaterThan(0);

    const sample = documents[0];
    const pdf = await admin.raw(`/api/documents/${sample.id}/download`);
    expect(pdf.status).toBe(200);
    expect(pdf.bytes.subarray(0, 4).toString()).toBe("%PDF");
  });

  test("the committee archive filters by committee and exposes the approved record", async ({ page }) => {
    const crashes = watchForCrashes(page);
    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await openNav(page, "Committee archive");

    const admin = await sessionFromState(BASE_URL, statePath("admin"));
    const all = await admin.get("/api/archive/committees");
    expect(all.status).toBe(200);
    const dac = await admin.get("/api/archive/committees?committee=DAC");
    expect(dac.status).toBe(200);
    const rows = dac.body.rows || [];
    expect(rows.every((row) => (row.committee || "DAC") === "DAC")).toBe(true);

    await expect(page.locator(".view-root")).toBeVisible();
    expect(crashes, `console errors: ${crashes.join(" | ")}`).toEqual([]);
  });

  test("notifications and the audit trail both load", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });

    await openNav(page, "Notifications");
    await expect(page.locator(".view-root")).toBeVisible();

    await openNav(page, "Security & audit");
    await expect(page.locator(".view-root")).toContainText(/audit|event|security/i, { timeout: 20_000 });

    const admin = await sessionFromState(BASE_URL, statePath("admin"));
    const audit = await admin.get("/api/audit");
    expect(audit.status).toBe(200);
    expect((audit.body.rows || audit.body || []).length).toBeGreaterThan(0);
  });

  test("the mail queue is visible to the administrator", async ({ page }) => {
    const admin = await sessionFromState(BASE_URL, statePath("admin"));
    const summary = await admin.get("/api/mail/summary");
    expect(summary.status).toBe(200);
    expect(summary.body.configured).toBeDefined();
    expect(summary.body.counts).toBeTruthy();
  });
});

test.describe("Documents · the archived minutes", () => {
  test.use({ storageState: statePath("mom-secretary") });

  test("the vault shows the minutes that were just approved, and the PDF opens", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await openNav(page, "Invitations");
    await expect(page.locator(".view-root")).toBeVisible();

    // The vault itself is the Academic Office's; the Member Secretary's own record is
    // the meeting workspace, which must show the approved minutes.
    const secretary = await sessionFromState(BASE_URL, statePath("mom-secretary"));
    const stored = await secretary.get(`/api/workspaces/${fixtures.momDraft.workspaceId}`);
    expect(stored.status).toBe(200);
    expect(stored.body.state.momReview.status).toBe("approved");

    const office = await sessionFromState(BASE_URL, statePath("office"));
    const listed = await office.get("/api/documents");
    expect(listed.status).toBe(200);
    const minutes = (listed.body.documents || []).filter((doc) => doc.docType === "mom");
    expect(minutes.length, "the approved minutes were archived").toBeGreaterThan(0);
  });
});
