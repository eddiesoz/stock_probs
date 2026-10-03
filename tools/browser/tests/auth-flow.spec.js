const fs = require("node:fs/promises");
const path = require("node:path");
const { test, expect } = require("./fixtures");

const frontendExport = path.resolve(__dirname, "../../../frontend/out");

async function installFreshAdminExport(page) {
  await page.route("**/admin", async (route) => route.fulfill({
    status: 200,
    contentType: "text/html",
    body: await fs.readFile(path.join(frontendExport, "admin.html")),
  }));
  await page.route("**/_next/**", async (route) => {
    const requestPath = new URL(route.request().url()).pathname;
    const assetPath = path.resolve(frontendExport, `.${requestPath}`);
    if (!assetPath.startsWith(`${frontendExport}${path.sep}`)) return route.abort();
    const extension = path.extname(assetPath);
    const contentType = extension === ".js" ? "application/javascript"
      : extension === ".css" ? "text/css"
        : extension === ".woff2" ? "font/woff2"
          : "application/octet-stream";
    return route.fulfill({ status: 200, contentType, body: await fs.readFile(assetPath) });
  });
}

async function installAdminSession(page, emailInvitesEnabled) {
  await page.route("**/api/v1/auth/session", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      authenticated: true,
      csrf_token: "browser-test-csrf",
      user: { id: 1, login: "fixture-owner", role: "admin" },
    }),
  }));
  await page.route("**/api/v1/auth/invites", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ invitations: [], email_invites_enabled: emailInvitesEnabled }),
  }));
  await page.route("**/api/v1/auth/totp/status", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      enrolled: true,
      enrollment_pending: false,
      recovery_codes_remaining: 8,
      requires_totp: true,
      can_enroll: false,
    }),
  }));
}

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
        expires_at: "2099-01-10T17:13:00Z",
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
  const appChoice = page.getByLabel("Which authenticator do you want to use?");
  const generateKey = page.getByRole("button", { name: "Generate setup key" });
  await expect(appChoice).toBeFocused();
  await expect(generateKey).toBeDisabled();
  await appChoice.selectOption("microsoft-authenticator");
  await expect(generateKey).toBeEnabled();
  await generateKey.click();
  await expect(page.getByText("Manual setup key")).toBeVisible();
  await expect(page.getByTestId("totp-enrollment-expiry")).toContainText("Setup key expires in");
  await expect(page.getByRole("img", { name: "Signal Ledger QR code to scan inside Microsoft Authenticator" })).toHaveCount(0);
  await expect(page.getByText("JBSWY3DPEHPK3PXP", { exact: true })).toBeVisible();
  await expect(appChoice).toBeFocused();
  await expect(page.getByLabel("Enter the current six-digit code")).not.toBeFocused();
  await appChoice.selectOption("apple-passwords");
  await expect(page.getByText(/Passwords and select the Signal Ledger login/)).toBeVisible();
  await expect(page.getByRole("img", { name: "QR code for adding Signal Ledger to an authenticator app" })).toHaveAttribute("src", /^data:image\/png;base64,/);
  await appChoice.selectOption("google-authenticator");
  await expect(page.getByText(/Google Authenticator, tap \+, then Enter a setup key/)).toBeVisible();
  await appChoice.selectOption("microsoft-authenticator");
  await expect(page.getByText(/iPhone Camera and Photos can send a setup QR code to Apple Passwords/)).toBeVisible();
  await expect(page.getByRole("img", { name: "Signal Ledger QR code to scan inside Microsoft Authenticator" })).toHaveCount(0);
  await expect(page.getByRole("radio", { name: "On this phone: copy the setup key" })).toBeChecked();
  await expect(page.getByText(/then Enter code manually if offered/)).toBeVisible();
  await page.getByRole("radio", { name: "Another screen: scan from inside Microsoft Authenticator" }).check();
  await expect(page.getByText(/Do not use iPhone Camera or Photos; those open Apple Passwords/)).toBeVisible();
  await expect(page.getByRole("img", { name: "Signal Ledger QR code to scan inside Microsoft Authenticator" })).toHaveAttribute("src", /^data:image\/png;base64,/);
  await page.getByRole("radio", { name: "On this phone: copy the setup key" }).check();
  await expect(page.getByRole("img", { name: "Signal Ledger QR code to scan inside Microsoft Authenticator" })).toHaveCount(0);
  await appChoice.selectOption("1password");
  await expect(page.getByText(/One-Time Password\. On this iPhone, paste the copied setup key/)).toBeVisible();
  await appChoice.selectOption("other");
  await expect(page.getByText(/choose time-based \(TOTP\)/)).toBeVisible();
  await appChoice.selectOption("");
  await expect(page.getByRole("button", { name: "Start over with new key" })).toBeDisabled();
  await appChoice.selectOption("other");
  await expect(page.getByRole("link", { name: "Try device’s default otpauth handler" })).toHaveCount(0);
  await expect(page.getByText(/A generic setup link can open a different app on iOS/)).toBeVisible();
  await expect(page.getByText(/use its in-app QR scanner/)).toBeVisible();
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByRole("button", { name: "Copy setup key" }).click();
  await expect(page.getByRole("button", { name: "Copied setup key" })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("JBSWY3DPEHPK3PXP");
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

test("authenticator rotation clears stale setup data and explains rejected stale QR codes", async ({ page, browserDiagnostics }) => {
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
      can_enroll: true,
    }),
  }));
  const startPayloads = [];
  let startCount = 0;
  let releaseReplacement;
  const replacement = new Promise((resolve) => { releaseReplacement = resolve; });
  await page.route("**/api/v1/auth/totp/enroll/start", (route) => {
    startPayloads.push(route.request().postDataJSON());
    startCount += 1;
    const setup = startCount === 1
      ? {
        secret: "OLDOSECRETVALUE",
        otpauth_uri: "otpauth://totp/Signal%20Ledger:fixture-owner?secret=OLDOSECRETVALUE&issuer=Signal%20Ledger",
      }
      : {
        secret: "NEWSECRETREPLACEMENT",
        otpauth_uri: "otpauth://totp/Signal%20Ledger:fixture-owner?secret=NEWSECRETREPLACEMENT&issuer=Signal%20Ledger",
      };
    const response = {
      enrollment: true,
      ...setup,
      expires_at: "2099-01-10T17:13:00Z",
    };
    if (startCount === 1) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(response) });
    return replacement.then(() => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(response) }));
  });
  browserDiagnostics.expectHttpFailures({ method: "POST", path: "/api/v1/auth/totp/enroll/finish", status: 403 });
  await page.route("**/api/v1/auth/totp/enroll/finish", (route) => route.fulfill({
    status: 403,
    contentType: "application/json",
    body: JSON.stringify({ error: { code: "totp_rejected", message: "Rejected setup secret NEWSECRETREPLACEMENT" } }),
  }));

  await page.goto("/authenticator?mode=enroll&next=/overview");
  await page.getByLabel("Which authenticator do you want to use?").selectOption("other");
  await page.getByRole("button", { name: "Generate setup key" }).click();
  await expect(page.getByTestId("totp-setup-key")).toHaveText("OLDOSECRETVALUE");
  await expect(page.getByRole("img", { name: "QR code for adding Signal Ledger to an authenticator app" })).toBeVisible();

  await page.getByRole("button", { name: "Start over with new key" }).click();
  await expect(page.getByTestId("totp-setup-key")).toHaveCount(0);
  await expect(page.getByRole("img", { name: "QR code for adding Signal Ledger to an authenticator app" })).toHaveCount(0);
  await expect(page.getByLabel("Enter the current six-digit code")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Starting over…" })).toBeDisabled();
  expect(startPayloads).toEqual([{}, { replace: true }]);

  releaseReplacement();
  await expect(page.getByTestId("totp-setup-key")).toHaveText("NEWSECRETREPLACEMENT");
  await expect(page.getByText(/Replace the old Signal Ledger entry/)).toBeVisible();
  await page.getByLabel("Enter the current six-digit code").fill("123456");
  await page.getByRole("button", { name: "Enable authenticator" }).click();
  const errorMessage = page.locator('[data-tone="error"]');
  await expect(errorMessage).toContainText("previously scanned QR code may be stale");
  await expect(errorMessage).toContainText("Start over with new key");
  await expect(errorMessage).not.toContainText("NEWSECRETREPLACEMENT");
});

test("authenticator start conflict offers an explicit replacement action", async ({ page, browserDiagnostics }) => {
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
    body: JSON.stringify({ enrolled: false, enrollment_pending: false, recovery_codes_remaining: 0, requires_totp: true, can_enroll: true }),
  }));
  browserDiagnostics.expectHttpFailures({ method: "POST", path: "/api/v1/auth/totp/enroll/start", status: 403 });
  const startPayloads = [];
  await page.route("**/api/v1/auth/totp/enroll/start", (route) => {
    startPayloads.push(route.request().postDataJSON());
    if (startPayloads.length === 1) {
      return route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "totp_rejected", message: "A pending setup belongs to another session." } }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        enrollment: true,
        secret: "REPLACEMENTSECRET",
        otpauth_uri: "otpauth://totp/Signal%20Ledger:fixture-owner?secret=REPLACEMENTSECRET&issuer=Signal%20Ledger",
        expires_at: "2099-01-10T17:13:00Z",
      }),
    });
  });

  await page.goto("/authenticator?mode=enroll&next=/overview");
  await page.getByLabel("Which authenticator do you want to use?").selectOption("other");
  await page.getByRole("button", { name: "Generate setup key" }).click();
  await expect(page.locator('[data-tone="error"]')).toContainText("A pending setup already exists in another session");
  await expect(page.getByText(/invalidates the other session’s pending QR and setup key/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Start over with new key" })).toBeEnabled();

  await page.getByRole("button", { name: "Start over with new key" }).click();
  await expect(page.getByTestId("totp-setup-key")).toHaveText("REPLACEMENTSECRET");
  expect(startPayloads).toEqual([{}, { replace: true }]);
});

test("expired authenticator setup disables QR and code submission", async ({ page }) => {
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
    body: JSON.stringify({ enrolled: false, enrollment_pending: false, recovery_codes_remaining: 0, requires_totp: true, can_enroll: true }),
  }));
  await page.route("**/api/v1/auth/totp/enroll/start", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      enrollment: true,
      secret: "EXPIREDSECRET",
      otpauth_uri: "otpauth://totp/Signal%20Ledger:fixture-owner?secret=EXPIREDSECRET&issuer=Signal%20Ledger",
      expires_at: "2020-01-10T17:13:00Z",
    }),
  }));

  await page.goto("/authenticator?mode=enroll&next=/overview");
  await page.getByLabel("Which authenticator do you want to use?").selectOption("other");
  await page.getByRole("button", { name: "Generate setup key" }).click();
  await expect(page.getByTestId("totp-enrollment-expiry")).toHaveAttribute("data-state", "expired");
  await expect(page.getByText("It cannot be scanned or used.")).toBeVisible();
  await expect(page.getByTestId("totp-setup-key")).toHaveCount(0);
  await expect(page.getByRole("img", { name: "QR code for adding Signal Ledger to an authenticator app" })).toHaveCount(0);
  await expect(page.getByLabel("Enter the current six-digit code")).toHaveCount(0);
  await expect(page.getByLabel("Which authenticator do you want to use?")).toBeVisible();
  await expect(page.getByRole("button", { name: "Start over with new key" })).toBeVisible();
});

test("admin keeps manual invitations available when mail is unconfigured", async ({ page }) => {
  await installAdminSession(page, false);
  let manualPayload;
  await page.route("**/api/v1/auth/invites", async (route) => {
    if (route.request().method() === "POST") {
      manualPayload = route.request().postDataJSON();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ code: "manual-code-fixture", github_id: 24680, expires_at: "2026-10-01T00:00:00Z" }),
      });
    }
    return route.fallback();
  });

  await page.goto("/admin");
  await page.getByLabel("GitHub account ID", { exact: true }).fill("24680");
  await expect(page.getByRole("button", { name: "Send invitation email" })).toBeDisabled();
  await expect(page.getByText("Mail sending is not configured on this server.")).toBeVisible();
  await page.getByRole("button", { name: "Create invitation" }).click();
  await expect(page.getByText("Invitation created. Copy the single-use code through a private channel.")).toBeVisible();
  expect(manualPayload).toEqual({ github_id: 24680 });
  await expect(page.getByText("Code manual-code-fixture")).toBeVisible();
});

test("configured admin sends an email-only invitation by keyboard on mobile and shows pending identity", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await installAdminSession(page, true);
  await installFreshAdminExport(page);
  let emailPayload;
  let csrfHeader;
  let inviteReads = 0;
  let releaseEmail;
  const emailResponse = new Promise((resolve) => { releaseEmail = resolve; });
  await page.route("**/api/v1/auth/invites", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    inviteReads += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        email_invites_enabled: true,
        invitations: inviteReads === 1 ? [] : [
          {
            id: "mail-invite-1",
            github_id: null,
            github_login: null,
            email_bound: true,
            expires_at: "2026-10-01T00:00:00Z",
          },
          {
            id: "used-mail-invite-1",
            github_id: null,
            github_login: null,
            email_bound: true,
            consumed_at: "2026-09-30T11:00:00Z",
            used_at: "2026-09-30T11:00:00Z",
            expires_at: "2026-10-01T00:00:00Z",
          },
        ],
      }),
    });
  });
  await page.route("**/api/v1/auth/invites/email", async (route) => {
    emailPayload = route.request().postDataJSON();
    csrfHeader = route.request().headers()["x-csrf-token"];
    return emailResponse.then(() => route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        submission_status: "smtp_accepted",
        submission_id: "mail-invite-1",
        submitted_at: "2026-09-30T12:00:00Z",
        github_id: null,
        github_login: null,
        expires_at: "2026-10-01T00:00:00Z",
        invite_url: "https://ledger.example.test/invite?code=fixture-bearer-code",
      }),
    }));
  });

  await page.goto("/admin");
  await page.getByLabel("Recipient email address").fill("person@example.com");
  const send = page.getByRole("button", { name: /Send invitation email|Submitting invitation email/ });
  await expect(send).toBeEnabled();
  await send.focus();
  await expect(send).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(send).toHaveText("Submitting invitation email…");
  await expect(page.getByRole("button", { name: "Create invitation" })).toBeDisabled();
  releaseEmail();

  await expect(page.getByRole("status")).toHaveText("Mail server accepted the invitation. The recipient must use a GitHub account with the invitation email marked verified. Delivery is not confirmed.");
  expect(emailPayload).toEqual({ email: "person@example.com" });
  expect(csrfHeader).toBe("browser-test-csrf");
  expect(inviteReads).toBe(2);
  const emailInvitationRows = page.locator("li").filter({ hasText: "Email invitation · pending GitHub verification" });
  await expect(emailInvitationRows).toHaveCount(2);
  await expect(emailInvitationRows.filter({ hasText: "Used" })).toHaveCount(1);
  await expect(page.getByText("Open", { exact: true })).toBeVisible();
  await expect(page.getByText("person@example.com", { exact: true })).toHaveCount(0);
  expect(page.url()).not.toContain("fixture-bearer-code");
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain("mail-invite-1");
  const layout = await page.evaluate(() => ({
    viewportWidth: document.documentElement.clientWidth,
    contentWidth: document.documentElement.scrollWidth,
    button: document.querySelector('button[aria-describedby="email-invites-help invitation-email-verification"]')?.getBoundingClientRect().toJSON(),
  }));
  expect(layout.contentWidth).toBeLessThanOrEqual(layout.viewportWidth + 1);
  expect(layout.button.width).toBeGreaterThan(0);
  expect(layout.button.height).toBeGreaterThanOrEqual(44);
  expect(layout.button.right).toBeLessThanOrEqual(layout.viewportWidth + 1);
});

test("email invitation can optionally restrict a resolved account without making username required", async ({ page }) => {
  await installAdminSession(page, true);
  await installFreshAdminExport(page);
  let emailPayload;
  await page.route("**/api/v1/auth/invites/email", async (route) => {
    emailPayload = route.request().postDataJSON();
    return route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        submission_status: "smtp_accepted",
        submission_id: "restricted-mail-invite",
        submitted_at: "2026-09-30T12:00:00Z",
        github_id: 24680,
        github_login: null,
        expires_at: "2026-10-01T00:00:00Z",
        invite_url: "https://ledger.example.test/invite?code=fixture-restricted-code",
      }),
    });
  });

  await page.goto("/admin");
  await page.getByLabel("Recipient email address").fill("person@example.com");
  await page.getByText("Optional resolved GitHub account restriction").click();
  await page.getByLabel("GitHub account ID (optional)", { exact: true }).fill("24680");
  await expect(page.getByRole("button", { name: "Send invitation email" })).toBeEnabled();
  await page.getByRole("button", { name: "Send invitation email" }).click();

  await expect(page.getByRole("status")).toContainText("Mail server accepted the invitation.");
  await expect(page.getByRole("status")).toContainText("The recipient must use GitHub account 24680.");
  expect(emailPayload).toEqual({ email: "person@example.com", github_id: 24680 });
});

test("admin email submission shows a safe failure without SMTP details", async ({ page, browserDiagnostics }) => {
  await installAdminSession(page, true);
  browserDiagnostics.expectHttpFailures({ method: "POST", path: "/api/v1/auth/invites/email", status: 502 });
  await page.route("**/api/v1/auth/invites/email", (route) => route.fulfill({
    status: 502,
    contentType: "application/json",
    body: JSON.stringify({ error: { code: "mail_submission_failed", message: "SMTP credential smtp-private-value rejected" } }),
  }));

  await page.goto("/admin");
  await page.getByLabel("Recipient email address").fill("person@example.com");
  await page.getByRole("button", { name: "Send invitation email" }).click();
  const errorMessage = page.locator('[data-tone="error"]');
  await expect(errorMessage).toHaveText("Invitation email could not be submitted. Check the recipient address and mail configuration, then try again.");
  await expect(errorMessage).not.toContainText("smtp-private-value");
});
