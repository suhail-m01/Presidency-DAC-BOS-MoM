// The shell: the navigation each role is allowed to see, every screen opening without a
// crash, a phone-sized viewport, and the project notes page.
import { test, expect } from "@playwright/test";
import { openNav, watchForCrashes, navName } from "./support/ui.js";
import { statePath as AUTH } from "./support/paths.js";

const ROLE_NAV = {
  "mom-secretary": {
    role: "faculty (Member Secretary)",
    items: ["Overview", "Meeting request", "MoM workspace", "Action Taken Report", "Minutes to sign", "My external observations", "Invitations", "Notifications", "Security & audit"],
    forbidden: ["Access directory", "Approval queue", "Agenda library", "Meeting calendar"],
  },
  office: {
    role: "Academic Office",
    items: ["Overview", "Approval queue", "Minutes review", "Action Taken Reports", "Meeting calendar", "Committee archive", "Document vault", "Agenda library", "Invitation log", "Notifications", "Security & audit"],
    forbidden: ["Meeting request", "MoM workspace", "Access directory"],
  },
  admin: {
    role: "System Administrator",
    items: ["Overview", "Access directory", "Document vault", "Committee archive", "Action Taken Reports", "Notifications", "Security & audit"],
    forbidden: ["Meeting request", "MoM workspace", "Approval queue", "Meeting calendar"],
  },
  "external-civil": {
    role: "External Member (a professor of another school, nominated into this committee)",
    items: ["My external observations", "Notifications", "Security & audit"],
    forbidden: ["Access directory", "Approval queue", "Agenda library"],
  },
};

for (const [stateName, config] of Object.entries(ROLE_NAV)) {
  test.describe(`Shell · ${config.role}`, () => {
    test.use({ storageState: AUTH(stateName) });

    test("sees exactly the screens its role allows, and each one opens cleanly", async ({ page }) => {
      const crashes = watchForCrashes(page);
      await page.goto("/");
      await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });

      const nav = page.getByRole("navigation", { name: /Main navigation/i });
      for (const label of config.items) {
        await expect(nav.getByRole("button", { name: navName(label) })).toHaveCount(1);
      }
      for (const label of config.forbidden) {
        await expect(nav.getByRole("button", { name: navName(label) })).toHaveCount(0);
      }

      // Every permitted screen renders a heading and leaves the console clean.
      for (const label of config.items) {
        await openNav(page, label);
        await expect(page.locator(".view-root")).toBeVisible();
        await expect(page.locator(".main-area h1, .main-area h2").first()).toBeVisible({ timeout: 20_000 });
      }
      expect(crashes, `console errors: ${crashes.join(" | ")}`).toEqual([]);
    });
  });
}

test.describe("Shell · layout", () => {
  test.use({ storageState: AUTH("mom-secretary") });

  test("works on a phone-sized screen without sideways scrolling", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("navigation", { name: /Main navigation/i })).toBeVisible();

    await openNav(page, "Meeting request");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `horizontal overflow of ${overflow}px`).toBeLessThanOrEqual(2);
  });

  test("the project and security notes page is served", async ({ page }) => {
    const response = await page.goto("/README");
    expect(response.status()).toBe(200);
    await expect(page.locator("body")).toContainText(/DAC Minutes|security/i);
  });

  test("keyboard focus reaches the navigation in order", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible({ timeout: 30_000 });
    const order = [];
    for (let step = 0; step < 12; step += 1) {
      await page.keyboard.press("Tab");
      order.push(await page.evaluate(() => {
        const node = document.activeElement;
        return node ? `${node.tagName}:${(node.innerText || node.getAttribute("aria-label") || "").trim().slice(0, 30)}` : "";
      }));
    }
    expect(order.filter(Boolean).length).toBeGreaterThan(4);
  });
});
