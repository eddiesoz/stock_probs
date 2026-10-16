// Optional tool links must wrap within the navigation and preserve reachable mobile controls.
const { test, expect } = require("./fixtures");

for (const theme of ["light", "dark"]) {
  test(`all enabled tool routes retain their viewport and keyboard links in ${theme}`, async ({ page, outOfSessionApplication }) => {
    test.setTimeout(60_000);
    await page.addInitScript(value => localStorage.setItem("stock-probs.theme", value), theme);
    const submitted = [];
    page.on("request", request => { if (request.method() === "POST") submitted.push(new URL(request.url()).pathname); });
    for (const [path, selected] of [
      ["/tools", null],
      ["/tools/forecast", "Forecast"],
      ["/tools/live-trading", "Live Trading"],
      ["/tools/markets", "Markets"],
      ["/tools/compare", "Compare"],
      ["/tools/what-if", "What-if"],
    ]) {
      await page.goto(`${outOfSessionApplication.url}${path}`);
      const nav = page.getByRole("navigation", { name: "Tools", exact: true });
      await expect(nav.getByRole("link", { name: "What-if", exact: true })).toBeVisible();
      await expect(nav.getByRole("link", { name: "Compare", exact: true })).toBeVisible();
      const width = page.viewportSize().width;
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
      if (selected) {
        await expect.poll(() => nav.evaluate(node => {
          const item = node.querySelector("[aria-current=page]");
          if (!item) return false;
          const bounds = node.getBoundingClientRect(), rect = item.getBoundingClientRect();
          return rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1;
        })).toBe(true);
      }
      const first = nav.getByRole("link", { name: "Forecast", exact: true });
      await first.focus();
      for (const label of ["Forecast", "Live Trading", "Markets", "Compare", "What-if"]) {
        const link = nav.getByRole("link", { name: label, exact: true });
        await expect(link).toBeFocused();
        await expect(link).toBeInViewport();
        const rect = await link.boundingBox();
        expect(rect.height).toBeGreaterThanOrEqual(44);
        expect(rect.width).toBeGreaterThanOrEqual(44);
        if (label !== "What-if") await page.keyboard.press("Tab");
      }
    }
    expect(submitted).not.toContain("/api/v1/forecasts");
  });
}
