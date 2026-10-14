import { expect, test } from "@playwright/test";
import { inquiryFields } from "../../src/lib/inquiry-fields";

const pages = [
  { path: "/weddings", kind: "wedding" },
  { path: "/contact", kind: "contact" },
  { path: "/order-flowers", kind: "bouquet" },
] as const;

test.beforeEach(async ({ page }) => {
  // Keep live banner/account polling local and deterministic as well.
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    await route.fulfill({
      json: pathname.includes("announcement")
        ? { announcement: null }
        : { authenticated: false },
    });
  });
});

for (const { path, kind } of pages) {
  for (const width of [320, 390, 520, 521, 768, 850, 851, 1440]) {
    test(`${kind} controls and navigation fit at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(path);
      await page.evaluate(() => document.fonts.ready);

      const grid = page.locator(".inquiry-form .form-grid");
      const gridBox = (await grid.boundingBox())!;
      const tracks = await grid.evaluate((element) =>
        getComputedStyle(element).gridTemplateColumns.split(" ").map(parseFloat),
      );
      expect(tracks).toHaveLength(width <= 520 ? 1 : 2);
      if (tracks.length === 2) expect(Math.abs(tracks[0] - tracks[1])).toBeLessThan(1);

      for (const field of inquiryFields[kind]) {
        const control = page.locator(`#${kind}-${field.name}`);
        // Browser-computed accessible names, not placeholders or snapshot heuristics.
        await expect(control).toHaveAccessibleName(field.label);
        if (field.required) await expect(control).toHaveAttribute("required", "");
        if (field.help) await expect(control).toHaveAccessibleDescription(field.help);
        const box = (await control.boundingBox())!;
        expect(box.x).toBeGreaterThanOrEqual(gridBox.x - 1);
        expect(box.x + box.width).toBeLessThanOrEqual(gridBox.x + gridBox.width + 1);
        if (field.type === "checkbox") {
          expect(box.width).toBeGreaterThanOrEqual(18);
          expect(box.width).toBeLessThan(20);
          expect(Math.abs(box.width - box.height)).toBeLessThan(1);
        } else {
          const expectedWidth = width <= 520 || !field.half ? gridBox.width : tracks[0];
          expect(Math.abs(box.width - expectedWidth)).toBeLessThan(1);
        }
      }

      const header = page.locator(".site-header");
      for (const selector of [".brand-mark", ".header-actions"]) {
        const box = (await header.locator(selector).boundingBox())!;
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(width);
      }
      if (width <= 850) {
        await expect(page.getByRole("navigation", { name: "Main navigation", exact: true })).toBeHidden();
        const menu = page.locator(".mobile-nav summary");
        await menu.focus();
        await page.keyboard.press("Enter");
        const navigation = page.getByRole("navigation", { name: "Mobile navigation" });
        await expect(navigation).toBeVisible();
        const box = (await navigation.boundingBox())!;
        const headerBox = (await header.boundingBox())!;
        expect(box.y).toBeGreaterThanOrEqual(headerBox.y + headerBox.height);
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(width);
        await page.keyboard.press("Tab");
        await expect(navigation.getByRole("link", { name: "About", exact: true })).toBeFocused();
        await menu.focus();
        await page.keyboard.press("Enter");
        await expect(navigation).toBeHidden();
      } else {
        await expect(page.getByRole("navigation", { name: "Main navigation", exact: true })).toBeVisible();
        await expect(page.locator(".mobile-nav")).toBeHidden();
      }
    });
  }
}

test("wedding labels focus inputs and consent works with the keyboard", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/weddings");
  await page.locator('label[for="wedding-name"]').click();
  await expect(page.getByRole("textbox", { name: "Your name", exact: true })).toBeFocused();
  const consent = page.getByRole("checkbox", { name: inquiryFields.wedding.find((field) => field.type === "checkbox")!.label });
  await consent.focus();
  await page.keyboard.press("Space");
  await expect(consent).toBeChecked();
  await page.keyboard.press("Space");
  await expect(consent).not.toBeChecked();
  await expect(page.getByRole("textbox", { name: "Company", exact: true })).toHaveCount(0);
});
