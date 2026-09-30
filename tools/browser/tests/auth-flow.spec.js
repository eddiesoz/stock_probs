const { test, expect } = require("./fixtures");

// Keep the browser boundary explicit: GitHub mode must reach the same-origin OAuth start without falling back to local bootstrap.
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
    return route.fulfill({ status: 302, headers: { Location: "/sign-in?oauth_fixture=1" }, body: "" });
  });

  await page.goto("/sign-in");
  await expect(page.getByText("Sign in with your development account to continue.")).toHaveCount(0);
  const signIn = page.getByRole("link", { name: "Continue with GitHub" });
  await expect(signIn).toBeVisible();
  await expect(signIn).toHaveAttribute("href", "/api/v1/auth/github/start");
  await signIn.click();
  await expect(page).toHaveURL(/\/sign-in\?oauth_fixture=1$/);
  expect(starts).toBe(1);
});

test("old passkey bookmarks redirect to the authenticator flow without a ceremony", async ({ page }) => {
  await page.goto("/passkey?mode=verify&next=/authenticator%3Fmode%3Denroll%26next%3D%252Foverview");
  await expect(page).toHaveURL(/\/authenticator\?mode=enroll/);
  await expect(page.getByRole("heading", { name: "Sign in first" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open sign in" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Verify legacy passkey" })).toHaveCount(0);
});

test("authenticator loading settles deterministically on desktop and mobile", async ({ page }) => {
  let releaseSession;
  const pendingSession = new Promise((resolve) => { releaseSession = resolve; });
  await page.route("**/api/v1/auth/session", (route) => pendingSession.then(() => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      authenticated: true,
      csrf_token: "browser-test-csrf",
      requires_totp: true,
      user: { id: 1, login: "fixture-owner", role: "admin" },
    }),
  })));
  await page.route("**/api/v1/auth/totp/status", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      enrolled: false,
      enrollment_pending: false,
      recovery_codes_remaining: 0,
      requires_totp: true,
      legacy_passkey_migration: false,
      can_enroll: true,
    }),
  }));

  await page.goto("/authenticator?mode=enroll&next=/overview");
  try {
    await expect(page.getByRole("heading", { name: "Checking your authenticator" })).toBeVisible();
  } finally {
    releaseSession();
  }
  await expect(page.locator("#authenticator-heading")).toHaveText("Protect your account");
  await expect(page.getByRole("button", { name: "Generate setup key" })).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport + 1);
});

test("authenticator denies an expired session without exposing setup controls", async ({ page }) => {
  await page.route("**/api/v1/auth/session", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ authenticated: false, user: null }),
  }));

  await page.goto("/authenticator?mode=enroll&next=/overview");
  await expect(page.getByRole("heading", { name: "Sign in first" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open sign in" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate setup key" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Enable authenticator" })).toHaveCount(0);
});

test("provisional authenticator setup and verification use the local TOTP contract", async ({ page }) => {
  const session = {
    authenticated: true,
    csrf_token: "browser-test-csrf",
    requires_totp: true,
    user: { id: 1, login: "fixture-owner", role: "admin" },
  };
  await page.route("**/api/v1/auth/session", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(session),
  }));
  await page.route("**/api/v1/auth/totp/status", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      enrolled: false,
      enrollment_pending: false,
      recovery_codes_remaining: 0,
      requires_totp: true,
      legacy_passkey_migration: false,
      can_enroll: true,
    }),
  }));
  let startPayload;
  await page.route("**/api/v1/auth/totp/enroll/start", (route) => {
    startPayload = route.request().postDataJSON();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        enrollment: true,
        secret: "JBSWY3DPEHPK3PXP",
        otpauth_uri: "otpauth://totp/Signal%20Ledger:fixture-owner?secret=JBSWY3DPEHPK3PXP&issuer=Signal%20Ledger",
        expires_at: "2025-01-10T17:13:00Z",
      }),
    });
  });
  let finishPayload;
  await page.route("**/api/v1/auth/totp/enroll/finish", (route) => {
    finishPayload = route.request().postDataJSON();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        authenticated: true,
        csrf_token: "browser-test-csrf-2",
        recovery_codes: ["ABCD-EFGH", "JKLM-NPQR"],
        mfa_method: "totp",
      }),
    });
  });

  await page.goto("/authenticator?mode=enroll&next=/overview");
  await page.getByRole("button", { name: "Generate setup key" }).click();
  await expect(page.getByText("Manual setup key")).toBeVisible();
  await expect(page.getByRole("img", { name: "QR code for adding Signal Ledger to an authenticator app" })).toHaveAttribute("src", /^data:image\/png;base64,/);
  await expect(page.getByText("JBSWY3DPEHPK3PXP", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open in authenticator app" })).toHaveAttribute("href", /^otpauth:\/\//);
  await page.getByLabel("Enter the current six-digit code").fill("123456");
  await page.getByRole("button", { name: "Enable authenticator" }).click();
  await expect(page.getByText("Save these codes now")).toBeVisible();
  await expect(page.getByRole("img", { name: "QR code for adding Signal Ledger to an authenticator app" })).toHaveCount(0);
  expect(startPayload).toEqual({});
  expect(finishPayload).toEqual({ code: "123456" });
  await expect(page.getByText("ABCD-EFGH", { exact: true })).toBeVisible();

  await page.unroute("**/api/v1/auth/totp/status");
  await page.route("**/api/v1/auth/totp/status", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      enrolled: true,
      enrollment_pending: false,
      recovery_codes_remaining: 2,
      requires_totp: true,
      legacy_passkey_migration: false,
      can_enroll: false,
    }),
  }));
  let verifyPayload;
  await page.route("**/api/v1/auth/totp/verify", (route) => {
    verifyPayload = route.request().postDataJSON();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        authenticated: true,
        csrf_token: "browser-test-csrf-3",
        mfa_method: "totp",
      }),
    });
  });
  await page.route((url) => url.pathname === "/overview", (route) => route.fulfill({
    status: 200,
    contentType: "text/html",
    body: "<!doctype html><html><head><title>Overview</title></head><body></body></html>",
  }));

  await page.goto("/authenticator?mode=verify&next=/overview");
  await expect(page.locator("#authenticator-heading")).toHaveText("Enter your authenticator code");
  await page.getByLabel("Current authenticator code").fill("654321");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Authenticator verification complete.")).toBeVisible();
  await expect(page).toHaveURL(/\/overview$/);
  expect(verifyPayload).toEqual({ code: "654321" });
});
