// Exercise the configured MCP transport and a real headless Chromium context with bounded I/O.
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const task = process.env.STOCK_PROBS_TASK_ID || "M06";
const config = JSON.parse(fs.readFileSync(path.join(root, "opencode.json"), "utf8"));
const [command, ...args] = config.mcp.playwright.command;
const child = spawn(command, args, { cwd: root, stdio: ["pipe", "pipe", "pipe"] });
let stdout = "";
let stderr = "";
let finished = false;

function send(message) {
  child.stdin.write(`${JSON.stringify(message)}\n`);
}

function fail(message) {
  if (finished) return;
  finished = true;
  child.kill("SIGTERM");
  console.error(`${message}${stderr ? `\n${stderr}` : ""}`);
  process.exitCode = 1;
}

const timer = setTimeout(() => fail("MCP smoke timed out after 20 seconds."), 20_000);
child.stderr.on("data", (chunk) => {
  stderr += chunk.toString();
  if (stderr.length > 65_536) fail("MCP stderr exceeded its smoke-test limit.");
});
child.stdout.on("data", (chunk) => {
  stdout += chunk.toString();
  if (stdout.length > 1_048_576) return fail("MCP stdout exceeded its smoke-test limit.");
  let newline;
  while ((newline = stdout.indexOf("\n")) >= 0) {
    const line = stdout.slice(0, newline).trim();
    stdout = stdout.slice(newline + 1);
    if (!line) continue;
    let message;
    try {
      message = JSON.parse(line);
    } catch (error) {
      return fail(`MCP returned invalid JSON: ${error.message}`);
    }
    if (message.id === 1) {
      send({ jsonrpc: "2.0", method: "notifications/initialized" });
      send({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });
    } else if (message.id === 2) {
      const names = (message.result?.tools || []).map((tool) => tool.name);
      if (!names.includes("browser_tabs")) return fail("Official browser tools were not listed.");
      send({
        jsonrpc: "2.0",
        id: 3,
        method: "tools/call",
        params: { name: "browser_tabs", arguments: { action: "list" } },
      });
    } else if (message.id === 3) {
      if (message.error || message.result?.isError) return fail("Chromium context initialization failed.");
      finished = true;
      clearTimeout(timer);
      child.kill("SIGTERM");
      console.log(`${task} MCP smoke passed: official tools and isolated Chromium responded.`);
    }
  }
});
child.on("error", (error) => fail(`MCP process could not start: ${error.message}`));
child.on("exit", (code) => {
  if (!finished) fail(`MCP process exited before completing the smoke test (${code}).`);
});

send({
  jsonrpc: "2.0",
  id: 1,
  method: "initialize",
  params: {
    protocolVersion: "2025-06-18",
    capabilities: {},
    clientInfo: { name: `stock-probs-${task.toLowerCase()}-smoke`, version: "1.0.0" },
  },
});
