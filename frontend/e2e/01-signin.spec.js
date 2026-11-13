// Sign-in, the one-time code, the first-login signature gate and the allow-list.
//
// These are the only specs that type an email address into the form: every other spec
// reuses a saved session, which keeps them clear of the 20-second code cooldown.
import { test, expect } from "@playwright/test";
import { shownCode, drawSignature, signOut, watchForCrashes, recordSignatureIfAsked } from "./support/ui.js";

const FRESH = "bibi.raza@presidencyuniversity.in";      // Physics: no signature on file yet
const WRONG_CODE = "nabeel@presidencyuniversity.in";
const COOLDOWN = "akhila.udupa@presidencyuniversity.in";
const SECOND = "praveenakn@presidencyuniversity.in";   // used for the reload / sign-out journey

test.describe("Sign-in", () => {
  test("an allowed account signs in with the code shown on screen and records a signature", async ({ page }) => {
    const crashes = watchForCrashes(page);
    await page.goto("/");

    await expect(page.getByRole("heading", { name: /Sign in to DAC Minutes/i })).toBeVisible();
    await page.getByPlaceholder("name@college.edu").fill(FRESH);
    await page.getByRole("button", { name: /Email me a sign-in code/i }).click();

    // The code is echoed on screen because no mail transport is configured — that is
    // the behaviour the college will rely on until Microsoft 365 is connected.
    const code = await shownCode(page);
    expect(code).toMatch(/^\d{6}$/);
    await page.getByPlaceholder("000000").fill(code);
    await page.getByRole("button", { name: /Verify and continue/i }).click();

    // First action gate: a signature must be recorded before anything else.
    const dialog = page.getByRole("dialog", { name: /digital signature/i });
    await expect(dialog).toBeVisible({ timeout: 30_000 });
    await expect(dialog).toContainText(/Add your digital signature/i);
    await expect(dialog.getByRole("button", { name: /save|sign/i }).first()).toBeVisible();

    await drawSignature(page);
    await dialog.getByRole("button", { name: /^Save signature$/i }).click();
    await expect(dialog).toBeHidden({ timeout: 30_000 });

    await expect(page.locator(".app-shell")).toBeVisible();
    await expect(page.locator(".signed-in-user")).toContainText(FRESH);
    await expect(page.getByRole("navigation", { name: /Main navigation/i })).toBeVisible();

    // The signature is now on file against the account, not just in this tab.
    const me = await page.request.get("/api/signature/me");
    expect(me.ok()).toBeTruthy();
    expect((await me.json()).required).toBe(false);

    expect(crashes, `console errors: ${crashes.join(" | ")}`).toEqual([]);
  });

  test("the session survives a reload and signs out cleanly", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /Sign in to DAC Minutes/i })).toBeVisible();

    // Its own account, so the cooldown from the first test cannot interfere.
    await page.getByPlaceholder("name@college.edu").fill(SECOND);
    await page.getByRole("button", { name: /Email me a sign-in code/i }).click();
    const code = await shownCode(page);
    await page.getByPlaceholder("000000").fill(code);
    await page.getByRole("button", { name: /Verify and continue/i }).click();

    await recordSignatureIfAsked(page);
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });

    await page.reload();
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".signed-in-user")).toContainText(SECOND);

    await signOut(page);
    await page.reload();
    await expect(page.getByRole("heading", { name: /Sign in to DAC Minutes/i })).toBeVisible();
  });

  test("an address outside the allow-list is refused and no code is shown", async ({ page }) => {
    await page.goto("/");
    await page.getByPlaceholder("name@college.edu").fill("not.a.professor@example.com");
    await page.getByRole("button", { name: /Email me a sign-in code/i }).click();

    await expect(page.locator(".login-message, .login-error").first()).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".otp-digits")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: /Sign in to DAC Minutes/i })).toBeVisible();
  });

  test("a wrong code is rejected and the person stays on the sign-in screen", async ({ page }) => {
    await page.goto("/");
    await page.getByPlaceholder("name@college.edu").fill(WRONG_CODE);
    await page.getByRole("button", { name: /Email me a sign-in code/i }).click();
    await shownCode(page);

    await page.getByPlaceholder("000000").fill("000000");
    await page.getByRole("button", { name: /Verify and continue/i }).click();

    await expect(page.locator(".login-message, .login-error").first()).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".app-shell")).toHaveCount(0);
  });

  test("a second code request inside the cooldown is rate-limited", async ({ page }) => {
    await page.goto("/");
    await page.getByPlaceholder("name@college.edu").fill(COOLDOWN);
    await page.getByRole("button", { name: /Email me a sign-in code/i }).click();
    await shownCode(page);

    // Ask again straight away — the server keeps a per-address cooldown.
    await page.getByRole("button", { name: /^Change$/ }).first().click();
    await page.getByPlaceholder("name@college.edu").fill(COOLDOWN);
    await page.getByRole("button", { name: /Email me a sign-in code/i }).click();

    await expect(page.locator(".login-message, .login-error").first()).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".login-message, .login-error").first()).toContainText(/second|wait|moment|cooldown|already/i);
  });

  test("the sign-in screen can find a professor in the directory", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /Sign in to DAC Minutes/i })).toBeVisible();

    const search = page.getByPlaceholder(/Search by name, email, department, staff ID/i);
    await expect(search).toBeVisible();
    await search.fill("Poonam");
    await expect(page.locator(".roster-item").first()).toContainText(/Poonam/i, { timeout: 15_000 });
  });
});
