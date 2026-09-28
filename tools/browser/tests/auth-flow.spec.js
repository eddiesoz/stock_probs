const { test, expect } = require("./fixtures");

test("GitHub sign-in opens the fixed same-origin OAuth start after status loads", async ({ page }) => {
  await page.route("**/api/v1/auth/session", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ authenticated: false }),
  }));
  await page.route("**/api/v1/auth/status", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ status: "github" }),
  }));
  let starts = 0;
  await page.route("**/api/v1/auth/github/start", (route) => {
    starts += 1;
    return route.fulfill({ status: 200, contentType: "text/html", body: "<!doctype html><title>OAuth started</title>" });
  });

  await page.goto("/sign-in");
  await expect(page.getByText("Sign in with your development account to continue.")).toHaveCount(0);
  const signIn = page.getByRole("link", { name: "Continue with GitHub" });
  await expect(signIn).toBeVisible();
  await signIn.click();
  await expect(page).toHaveURL(/\/api\/v1\/auth\/github\/start$/);
  expect(starts).toBe(1);
});
