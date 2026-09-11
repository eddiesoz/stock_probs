// Browser runs are serial and bounded for the target low-resource ARM64 laptop.
const { defineConfig, devices } = require("@playwright/test");

const portText = process.env.STOCK_PROBS_BROWSER_PORT || "8765";
if (!/^\d+$/.test(portText) || Number(portText) < 1 || Number(portText) > 65535) {
  throw new Error("STOCK_PROBS_BROWSER_PORT must be between 1 and 65535");
}
const baseURL = `http://127.0.0.1:${portText}`;

module.exports = defineConfig({
  testDir: "./tests",
  outputDir: "./test-results/artifacts",
  globalTimeout: 180_000,
  timeout: 30_000,
  workers: 1,
  retries: 0,
  reporter: [["line"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  metadata: { task: "M06", revision: process.env.GITHUB_SHA || "working-tree" },
  use: {
    baseURL,
    actionTimeout: 5_000,
    navigationTimeout: 10_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop-chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-chromium", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: "../../scripts/run-browser-app.sh",
    url: `${baseURL}/api/v1/readiness`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
