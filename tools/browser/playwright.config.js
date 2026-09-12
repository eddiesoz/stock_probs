// Browser runs are serial and bounded on both supported Linux architectures.
const { defineConfig, devices } = require("@playwright/test");
const path = require("node:path");

const portText = process.env.STOCK_PROBS_BROWSER_PORT || "8765";
if (!/^\d+$/.test(portText) || Number(portText) < 1 || Number(portText) > 65535) {
  throw new Error("STOCK_PROBS_BROWSER_PORT must be between 1 and 65535");
}
const baseURL = `http://127.0.0.1:${portText}`;
const artifactRoot = process.env.STOCK_PROBS_BROWSER_ARTIFACT_DIR
  ? path.resolve(process.env.STOCK_PROBS_BROWSER_ARTIFACT_DIR)
  : path.resolve(__dirname, "test-results", "artifacts");

module.exports = defineConfig({
  testDir: "./tests",
  outputDir: path.join(artifactRoot, "test-artifacts"),
  globalTimeout: 180_000,
  timeout: 30_000,
  workers: 1,
  retries: 0,
  reporter: [["line"], ["html", { outputFolder: path.join(artifactRoot, "report"), open: "never" }]],
  metadata: {
    task: process.env.STOCK_PROBS_TASK_ID || "browser-development",
    revision: process.env.STOCK_PROBS_REVISION || "working-tree",
    architecture: process.arch,
    execution: `native ${process.arch}`,
  },
  use: {
    baseURL,
    actionTimeout: 5_000,
    navigationTimeout: 10_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "desktop-chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } },
    },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 7"], viewport: { width: 360, height: 800 } },
    },
  ],
  webServer: {
    command: "../../scripts/run-browser-app.sh",
    url: `${baseURL}/api/v1/readiness`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
