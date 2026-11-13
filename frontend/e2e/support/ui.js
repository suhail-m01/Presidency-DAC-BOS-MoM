// Helpers for driving the interface the way a person does.
//
// Locators are by role and by visible text, exactly as Playwright recommends: if a
// control is renamed the test fails loudly instead of silently clicking the wrong thing.
import { expect } from "@playwright/test";

export const NAV = 'nav[aria-label="Main navigation"]';

/** The six-digit code the server echoes on screen while no mail transport is set. */
export async function shownCode(page) {
  const box = page.locator(".otp-box .otp-digits");
  await expect(box).toBeVisible({ timeout: 20_000 });
  const digits = (await box.innerText()).replace(/\s+/g, "");
  if (!/^\d{6}$/.test(digits)) throw new Error(`unexpected code on screen: ${digits}`);
  return digits;
}

/** Sign in with an email address and the one-time code shown on screen. */
export async function signInThroughUi(page, email, { expectFailure = false } = {}) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Sign in to DAC Minutes/i })).toBeVisible();
  await page.getByPlaceholder("name@college.edu").fill(email);
  await page.getByRole("button", { name: /Email me a sign-in code/i }).click();

  if (expectFailure) return null;

  const code = await shownCode(page);
  await page.getByPlaceholder("000000").fill(code);
  await page.getByRole("button", { name: /Verify and continue/i }).click();
  await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
  return code;
}

/** A sidebar button. The accessible name is "<glyph> <label>", so it is anchored at the end. */
export function escapeForRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Record a signature if the first-login gate is showing. Returns true when it drew one. */
export async function recordSignatureIfAsked(page) {
  const dialog = page.getByRole("dialog", { name: /digital signature/i });
  // The gate opens only after /api/signature/me answers, so poll rather than guess.
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (await dialog.isVisible().catch(() => false)) {
      await drawSignature(page);
      await dialog.getByRole("button", { name: /^Save signature$/i }).click();
      await expect(dialog).toBeHidden({ timeout: 30_000 });
      return true;
    }
    await page.waitForTimeout(250);
  }
  return false;
}

/** Draw a stroke on the signature canvas — the same gesture a person makes. */
export async function drawSignature(page) {
  const dialog = page.getByRole("dialog", { name: /digital signature/i });
  await expect(dialog).toBeVisible();
  const canvas = dialog.locator("canvas");
  const box = await canvas.boundingBox();
  if (!box) throw new Error("the signature canvas has no box");
  const startX = box.x + box.width * 0.16;
  const startY = box.y + box.height * 0.7;
  await page.mouse.move(startX, startY);
  await page.mouse.down();
  for (let step = 1; step <= 14; step += 1) {
    await page.mouse.move(
      startX + (box.width * 0.62 * step) / 14,
      startY - Math.sin((step / 14) * Math.PI * 2) * box.height * 0.22,
    );
    await page.waitForTimeout(12);
  }
  await page.mouse.up();
  return dialog;
}

/** Open a screen from the sidebar. */
/** The accessible name of a sidebar button: "<glyph> <label>" plus an optional count. */
export function navName(label) {
  return new RegExp(`${escapeForRegExp(label)}(\\s+\\d+)?$`);
}

export async function openNav(page, label) {
  const item = page.locator(NAV).getByRole("button", { name: navName(label) });
  await expect(item).toBeVisible();
  await item.click();
  await expect(item).toHaveClass(/active/);
}

/** Sign out from the top bar. */
export async function signOut(page) {
  await page.getByRole("button", { name: /^Sign out$/ }).click();
  await expect(page.getByRole("heading", { name: /Sign in to DAC Minutes/i })).toBeVisible({ timeout: 20_000 });
}

/** Collect console errors and page errors, so a spec can assert the screen stayed clean. */
export function watchForCrashes(page) {
  const problems = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    // "Failed to load resource: 404/401/428" is the browser narrating an HTTP answer the
    // app handles deliberately (a locked action answers 428, /api/auth/me answers 401
    // before sign-in). A JavaScript fault is what this watcher is for.
    if (/Failed to load resource/i.test(text)) return;
    if (/fonts\.googleapis|fonts\.gstatic|ERR_INTERNET_DISCONNECTED/.test(text)) return;
    problems.push(text);
  });
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  return problems;
}

export const EXPECTED_TITLES = {
  overview: /Overview|Manage who can enter|Document-first/i,
  directory: /Access directory/i,
  request: /Meeting request|Complete the minutes|Approved request/i,
  mom: /MoM workspace|Complete the minutes/i,
  atr: /Action Taken Report/i,
  review: /Approval queue/i,
  archive: /Committee archive/i,
  vault: /Document vault/i,
  alerts: /Notifications/i,
  security: /Security/i,
  calendar: /Meeting calendar/i,
  library: /Agenda library/i,
  minutes: /Minutes/i,
  member: /Observation report/i,
  outbox: /Invitation/i,
};
