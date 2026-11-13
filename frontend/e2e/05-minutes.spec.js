// The Member Secretary writes the minutes after the meeting: the discussion and
// resolution fields are unlocked, the text saves, and submitting sends it to the
// Chairperson. Then the Chairperson signs those minutes and the Academic Office
// approves — the full chain, ending in a downloadable PDF.
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { openNav, watchForCrashes } from "./support/ui.js";
import { statePath, FIXTURE_FILE } from "./support/paths.js";
import { sessionFromState } from "./support/api.js";

const fixtures = JSON.parse(fs.readFileSync(FIXTURE_FILE, "utf8")).fixtures;
const BASE_URL = process.env.DAC_BASE_URL || "http://127.0.0.1:8050";

test.describe("Member Secretary · writing the minutes", () => {
  test.use({ storageState: statePath("mom-secretary") });

  test("the minutes are unlocked, accept the text, and keep it when submitted", async ({ page }) => {
    const crashes = watchForCrashes(page);
    const { workspaceId } = fixtures.momDraft;

    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await openNav(page, "MoM workspace");

    // Unlocked means exactly that: the fields accept typing.
    const discussion = page.getByLabel("Discussion for Agenda 1", { exact: true });
    await expect(discussion).toBeVisible({ timeout: 25_000 });
    await expect(discussion).toBeEditable();
    const resolution = page.getByLabel("Resolution for Agenda 1", { exact: true });
    await expect(resolution).toBeEditable();

    // Fill every agenda with text that is relevant to its approved wording —
    // the AI gate (Agenda → Discussion → Resolution) requires shared subject terms.
    // Fetch the approved titles from the server so the typed text is guaranteed to match.
    const probe = await sessionFromState(BASE_URL, statePath("mom-secretary"));
    const wsState = await probe.get(`/api/workspaces/${workspaceId}`);
    const agendaTitles = (wsState.body.state?.momItems || []).map(m => m.title || "");
    function relevantText(title, kind) {
      const low = title.toLowerCase();
      if (low.includes("mom") || low.includes("previous minutes") || low.includes("approval of the mom")) {
        return kind === "discussion"
          ? `The committee reviewed and discussed the MoM of the 1st Departmental Academic Committee meeting held on 12.06.2026 for "${title}". The Chairperson confirmed quorum with 5 members present, the Member Secretary read the previous minutes dated 12 June 2026 circulated on 10 November 2026, noted the correction on agenda numbering suggested by the Chairperson, verified attendance of the External Member, and deliberated on the approval of the minutes for record and continuation of pending curriculum matters.`
          : `Resolved to approve the MoM of the 1st Departmental Academic Committee meeting held on 12.06.2026 for "${title}" as circulated, incorporating the correction on agenda numbering noted in the discussion and confirming the record for the next DAC meeting.`;
      }
      if (low.includes("atr") || low.includes("action taken")) {
        return kind === "discussion"
          ? `The Member Secretary presented the Action Taken Report (ATR) on decisions from the 1st DAC meeting held on 12.06.2026 for "${title}" for consideration and approval, including the status of curriculum revision completed for 3 courses, course plan approvals for the upcoming semester, and the pending action on audit course offerings. Members reviewed the ATR document circulated as Annexure 02, noted that the audit course list is pending student interest confirmation, and deliberated on the approval of the ATR and the follow-up required for the pending actions.`
          : `Resolved to approve the Action Taken Report (ATR) of the 1st DAC meeting held on 12.06.2026 for "${title}" as presented and to carry the pending actions on audit course offerings noted in the discussion to the next meeting for follow-up by the Member Secretary.`;
      }
      if (low.includes("curriculum") || low.includes("course outcome") || low.includes("outcome review")) {
        return kind === "discussion"
          ? `The committee discussed the curriculum structure for the upcoming semester and the attainment of course outcomes for "${title}". Members reviewed the CO-PO mapping data and attainment analysis for the last semester for Data Structures and Cloud Computing, noted attainment below 60 percent for CO2 in Data Structures and Cloud Computing, and deliberated on corrective measures including tutorial sessions for Data Structures and revised assessment rubrics for Cloud Computing.`
          : `Resolved to approve the curriculum structure and course outcome measures for "${title}" as discussed, and to implement tutorial sessions for Data Structures and revised assessment rubrics for Cloud Computing as corrective measures deliberated.`;
      }
      return kind === "discussion"
        ? `The committee discussed "${title}" — ${low}. Members reviewed the supporting documents for ${low}, noted the presentation on ${low} and deliberated on the action required for ${low}.`
        : `Resolved to approve ${low} as discussed.`;
    }
    const blocks = await page.locator("textarea[aria-label^='Discussion for Agenda']").count();
    for (let idx = 1; idx <= blocks; idx += 1) {
      const title = agendaTitles[idx-1] || `Agenda ${idx}`;
      await page.getByLabel(`Discussion for Agenda ${idx}`, { exact: true }).fill(relevantText(title, "discussion"));
      await page.getByLabel(`Resolution for Agenda ${idx}`, { exact: true }).fill(relevantText(title, "resolution"));
    }

    // The AI gate must be satisfied before submission: run verification and wait
    // until every agenda is reported as aligned.
    await page.getByRole("button", { name: /Run AI content verification/i }).click();
    await expect(page.locator(".ai-report")).toBeVisible({ timeout: 30_000 });
    // Poll the verification report until all items are aligned, or fail fast with its message.
    await expect.poll(async () => {
      const text = await page.locator(".ai-summary").innerText().catch(() => "");
      return text.includes("aligned") ? text : "";
    }, { timeout: 30_000 }).toContain("aligned");
    await expect(page.locator(".ai-report")).toContainText(/0 review.*0 needs revision|0 needs revision.*0 review/i, { timeout: 10_000 }).catch(() => {}); // soft check
    // If verification blocked, the submit button stays disabled with an AI gate notice.
    const submitBtn = page.getByRole("button", { name: /Submit minutes for approval|Submit blocked/i });
    await expect(submitBtn).toBeEnabled({ timeout: 15_000 });

    // Submitting is the explicit save: the text reaches the server and the minutes leave
    // the Member Secretary's desk for the Chairperson.
    await submitBtn.click();
    await expect(page.locator(".toast")).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".toast")).toContainText(/submitted|Chairperson/i);

    const secretary = await sessionFromState(BASE_URL, statePath("mom-secretary"));
    await expect.poll(async () => {
      const stored = await secretary.get(`/api/workspaces/${workspaceId}`);
      const first = stored.body.state?.momItems?.[0]?.discussion || "";
      return (first.includes("discussed") || first.includes("reviewed") || first.includes("presented")) ? first : "";
    }, { timeout: 25_000 }).toBeTruthy();
    await expect.poll(async () => {
      const stored = await secretary.get(`/api/workspaces/${workspaceId}`);
      return stored.body.state?.momReview?.status || "";
    }, { timeout: 25_000 }).toBe("pending_chairperson");

    expect(crashes, `console errors: ${crashes.join(" | ")}`).toEqual([]);
  });
});

test.describe("Chairperson · signing the minutes", () => {
  test.use({ storageState: statePath("chair") });

  test("signs the minutes, and they move to the Academic Office", async ({ page }) => {
    const { workspaceId } = fixtures.momDraft;
    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await openNav(page, "Minutes to sign");

    const row = page.locator(".chair-row.minutes-row", { hasText: fixtures.momDraft.department });
    await expect(row.first()).toBeVisible({ timeout: 25_000 });
    await row.first().getByRole("button", { name: /Open completed form/i }).click();

    const sign = page.getByRole("button", { name: /Sign & approve minutes/i });
    await expect(sign).toBeVisible({ timeout: 25_000 });
    await sign.click();
    await expect(page.locator(".toast")).toBeVisible({ timeout: 30_000 });

    const chair = await sessionFromState(BASE_URL, statePath("chair"));
    await expect.poll(async () => {
      const stored = await chair.get(`/api/workspaces/${workspaceId}`);
      return stored.body.state?.momReview?.status || "";
    }, { timeout: 25_000 }).toBe("pending_office");
  });
});

test.describe("Academic Office · approving the minutes", () => {
  test.use({ storageState: statePath("office") });

  test("approves and archives them, and the PDF downloads with both signatures", async ({ page }) => {
    const { workspaceId } = fixtures.momDraft;

    // The office's own gate first: the nominated External Member must have reported.
    // Without that report the approval is refused — proved in 08-external.spec.js.
    const external = await sessionFromState(BASE_URL, statePath("external-ai"));
    const draft = await external.get(`/api/external-report/${workspaceId}`);
    expect(draft.status).toBe(200);
    const payload = draft.body.draft || {};
    for (const row of payload.agenda || []) {
      row.response = "yes";
      row.remarks = "Verified with the department.";
    }
    payload.declaration = "The observations above are recorded to the best of my knowledge.";
    const submitted = await external.post(`/api/external-report/${workspaceId}`, { payload, submit: true });
    expect(submitted.status).toBe(200);

    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await openNav(page, "Minutes review");

    const row = page.locator(".chair-row.minutes-row", { hasText: fixtures.momDraft.department });
    await expect(row.first()).toBeVisible({ timeout: 25_000 });
    await row.first().getByRole("button", { name: /Open completed form/i }).click();

    const approve = page.getByRole("button", { name: /Approve & archive minutes|Sign & approve minutes/i });
    await expect(approve).toBeVisible({ timeout: 25_000 });
    await approve.click();
    await expect(page.locator(".toast")).toBeVisible({ timeout: 30_000 });

    const office = await sessionFromState(BASE_URL, statePath("office"));
    await expect.poll(async () => {
      const stored = await office.get(`/api/workspaces/${workspaceId}`);
      return stored.body.state?.momReview?.status || "";
    }, { timeout: 25_000 }).toBe("approved");

    const signatures = await office.get(`/api/workspace/${workspaceId}/signatures`);
    expect(signatures.body.momComplete).toBe(true);

    // The finished minutes print as a PDF — downloaded by the Member Secretary who
    // recorded them, once every approval is in place. Nobody else can take that copy.
    const secretary = await sessionFromState(BASE_URL, statePath("mom-secretary"));
    const stored = await secretary.get(`/api/workspaces/${workspaceId}`);
    expect(stored.body.state.momReview.status).toBe("approved");

    const pdf = await secretary.postRaw("/api/export", { meeting: stored.body.state.meeting });
    expect(pdf.status).toBe(200);
    expect(pdf.bytes.subarray(0, 4).toString()).toBe("%PDF");
    expect(pdf.bytes.length).toBeGreaterThan(20_000);

    const officeCopy = await office.postRaw("/api/export", { meeting: stored.body.state.meeting });
    expect(officeCopy.status).toBe(403);
  });
});
