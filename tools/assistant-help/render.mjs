import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import {
  constants as fsConstants,
  open,
  lstat,
  mkdir,
  readdir,
  realpath,
  readFile,
  stat,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const TOOL_DIR = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(TOOL_DIR, "../..");
export const HANDOFF_PATH = path.join(
  REPO_ROOT,
  "test-results/assistant-r120/coordination/help-artifact-handoff.json",
);
export const TEMPLATE_PATH = path.join(TOOL_DIR, "guide.template.html");
export const CSS_PATH = path.join(TOOL_DIR, "guide.css");
export const OUTPUT_DIR = path.join(REPO_ROOT, "test-results/assistant-r120/help-preview");
export const APPROVED_CAPTURE_ROOT = path.join(
  REPO_ROOT,
  "test-results/r-astra-120-independent-ui-qa-final/browser",
);
export const APPROVED_FINALIZED_CAPTURE_ROOT = path.join(
  REPO_ROOT,
  "test-results/assistant-r120/help-finalized",
);
export const CAPTURE_MANIFEST_NAME = "assistant-help-captures.json";
export const QA_RECEIPT_NAME = "assistant-help-qa-receipt.json";

export const PDF_EXPORT_OPTIONS = Object.freeze({
  format: "A4",
  printBackground: true,
  preferCSSPageSize: true,
  tagged: true,
  outline: true,
  displayHeaderFooter: true,
  headerTemplate: "<div></div>",
  footerTemplate:
    '<div style="width:100%;padding:0 14mm;text-align:right;color:#42535e;font:8px system-ui,sans-serif">Page <span class="pageNumber"></span> of <span class="totalPages"></span></div>',
});

const PDF_PRINT_TEXT_PRESERVATION_CSS = `
  @media print {
    h1, h2, h3, h4, p, figcaption {
      white-space: pre-wrap;
      font-variant-ligatures: none;
    }
  }
`;

export async function applyPdfPrintTextPreservation(page) {
  return page.addStyleTag({ content: PDF_PRINT_TEXT_PRESERVATION_CSS });
}

// Chromium emits PDF 2.0's Strong tag without a RoleMap in its PDF 1.x output.
// Normalize only the disposable print DOM to the standard inline Span tag while
// retaining computed emphasis styles; the standalone HTML keeps semantic <strong>.
export async function normalizePdfPrintEmphasis(page) {
  return page.evaluate(() => {
    const retainedStyles = ["color", "font-size", "font-weight", "letter-spacing", "line-height"];
    const strongElements = [...document.querySelectorAll("strong")];

    for (const strong of strongElements) {
      const computed = window.getComputedStyle(strong);
      const span = document.createElement("span");
      for (const attribute of strong.attributes) {
        span.setAttribute(attribute.name, attribute.value);
      }
      for (const property of retainedStyles) {
        span.style.setProperty(property, computed.getPropertyValue(property));
      }
      span.append(...strong.childNodes);
      strong.replaceWith(span);
    }

    return strongElements.length;
  });
}

const REQUIRED_SECTIONS = [
  "Open and resize the assistant; desktop panel/mobile full-screen",
  "Choose an administrator-approved model and review exact privacy terms",
  "Ask about the current page; inspect and optionally withhold page context",
  "Read tool activity, citations and retrieval dates",
  "Preview and explicitly confirm changes; secure admin forms retain authenticator checks",
  "Approve exact public search queries before external search",
  "Reopen, rename and delete conversations; provider-free saved answers",
  "Recover from cancellation, connection interruptions, unavailable providers and storage quotas",
];

const CAPTURE_COPY = Object.freeze({
  desktop_light: {
    group: "desktop",
    theme: "light",
    route: "/tools/live-trading",
    label: "Desktop · Light theme.",
    alt: "Signal Ledger workspace on desktop with the Ledger assistant open in Light theme. Synthetic demonstration data.",
    caption: "Synthetic workspace examples in Light theme.",
  },
  desktop_dark: {
    group: "desktop",
    theme: "dark",
    route: "/tools/live-trading",
    label: "Desktop · Dark theme.",
    alt: "Signal Ledger workspace on desktop with the Ledger assistant open in Dark theme. Synthetic demonstration data.",
    caption: "Synthetic workspace examples in Dark theme.",
  },
  mobile_light: {
    group: "mobile",
    theme: "light",
    route: "/tools/live-trading",
    label: "Emulated mobile · Light theme.",
    alt: "Emulated mobile view of the Ledger assistant in Light theme. Synthetic demonstration data; not a physical phone capture.",
    caption: "Viewport-emulated mobile view with synthetic records; not a physical-phone capture.",
  },
  mobile_dark: {
    group: "mobile",
    theme: "dark",
    route: "/tools/live-trading",
    label: "Emulated mobile · Dark theme.",
    alt: "Emulated mobile view of the Ledger assistant in Dark theme. Synthetic demonstration data; not a physical phone capture.",
    caption: "Viewport-emulated mobile view with synthetic records; not a physical-phone capture.",
  },
  forecast_sources: {
    group: "desktop",
    theme: "light",
    route: "/tools/forecast",
    label: "Forecast explanation and cited sources · synthetic example.",
    alt: "Forecast workspace with a sample-data explanation, separate evidence steps, and source citations. No live recommendation is shown.",
    caption: "Synthetic forecast and source examples with cited evidence.",
  },
  action_preview: {
    group: "desktop",
    theme: "light",
    route: "/tools/live-trading",
    label: "Action preview · before confirmation.",
    alt: "Assistant action preview showing the proposed workspace change and exact confirmation phrase. The proposal has not been confirmed.",
    caption: "Review the proposed change and exact phrase before deciding. This example uses synthetic workspace data.",
  },
  action_receipt: {
    group: "desktop",
    theme: "light",
    route: "/tools/live-trading",
    label: "Workspace action · handed off after confirmation.",
    alt: "Assistant transcript showing a synthetic workspace action marked handed off after explicit browser confirmation. The workspace change is not shown as complete.",
    caption: "After you enter the exact phrase, the browser marks the action handed off. The receipt does not show a completed workspace change.",
  },
  history_context: {
    group: "desktop",
    theme: "light",
    route: "/tools/live-trading",
    label: "Saved conversation and updated page context.",
    alt: "Assistant history with a selected saved conversation and a preview of its current page context. Synthetic conversation and account data.",
    caption: "Compare the saved conversation context with the current page preview. Synthetic example; reopening a saved answer does not call a model.",
  },
});

export const CAPTURE_IDS = Object.freeze(Object.keys(CAPTURE_COPY));

const SECRET_PATTERNS = [
  /\b(?:sk|gh[pousr]|xox[baprs])-[A-Za-z0-9_-]{16,}\b/i,
  /\bBearer\s+[A-Za-z0-9._~+/-]{12,}/i,
  /-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----/i,
  /(?:api[_ -]?key|access[_ -]?token|session_cookie|csrf_cookie|totp_secret)\s*[:=]\s*[A-Za-z0-9._~+/-]{12,}/i,
  /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i,
];
const VERIFIED_CAPTURE_BUNDLES = new WeakSet();

const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const REVISION_PATTERN = /^[a-f0-9]{40}$/;
const RUN_FINALIZED_ROOT_PATTERN = /^test-results\/assistant-r120\/help-current-captures-(\d{8})-([a-f0-9]{12})\/finalized$/;
const PNG_SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const MAX_CAPTURE_BYTES = 12 * 1024 * 1024;
const MAX_MANIFEST_BYTES = 256 * 1024;
const MAX_RECEIPT_BYTES = 1024 * 1024;
const MAX_STAGE_FILES = 512;
const MAX_STAGE_ENTRIES = 1024;
const MAX_STAGE_FILE_BYTES = 32 * 1024 * 1024;
const MAX_STAGE_TREE_BYTES = 512 * 1024 * 1024;
const STAGED_NEXT_PREFIX = "src/stock_probs/static/next/";
const STAGED_STATIC_PREFIX = "src/stock_probs/static/";
const SERVED_STATIC_ASSETS = Object.freeze(["app.css", "app.js", "theme.js", "favicon.svg"]);
const SERVED_EXPORT_PAGES = Object.freeze([
  "index.html",
  "api-docs.html",
  "overview.html",
  "research.html",
  "tools.html",
  "tools/forecast.html",
  "tools/live-trading.html",
  "tools/markets.html",
  "sign-in.html",
  "invite.html",
  "passkey.html",
  "authenticator.html",
  "account.html",
  "admin.html",
]);
const FINALIZED_EVIDENCE_FILES = Object.freeze({
  candidate_manifest: "evidence/candidate-manifest.json",
  candidate_run_receipt: "evidence/candidate-run-receipt.json",
  independent_receipt: "evidence/independent-capture-qa-receipt.json",
  finalization_approval: "evidence/finalization-approval.json",
  visual_review: "evidence/visual-review.json",
  artifact_integrity: "evidence/artifact-integrity.json",
  pre_source_stage_snapshot: "evidence/pre-source-stage-hashes.json",
  post_source_stage_snapshot: "evidence/post-source-stage-hashes.json",
  capture_process: "evidence/capture-process.json",
  owned_temp_cleanup: "evidence/owned-temp-cleanup.json",
});
const FINALIZED_TREE_NAMES = Object.freeze([
  "fastapi_served",
  "frontend_authored",
  "frontend_out",
]);
const FINALIZED_TREE_FIELDS = Object.freeze({
  fastapi_served: Object.freeze(["file_count", "files", "sha256"]),
  frontend_authored: Object.freeze(["excluded_sensitive_filename_count", "file_count", "files", "sha256"]),
  frontend_out: Object.freeze(["file_count", "files", "sha256"]),
});
const UPSTREAM_EVIDENCE_PATHS = Object.freeze({
  candidate_manifest: "candidate/assistant-help-captures.json",
  candidate_run_receipt: "candidate/assistant-help-capture-run.json",
  independent_receipt: "independent-capture-qa-receipt.json",
  visual_review: "visual-review.json",
  artifact_integrity: "artifact-integrity.json",
  pre_source_stage_snapshot: "pre-source-stage-hashes.json",
  post_source_stage_snapshot: "post-source-stage-hashes.json",
  capture_process: "capture-process.json",
  owned_temp_cleanup: "owned-temp-cleanup.json",
});
const REVIEW_SNAPSHOT_BINDINGS = Object.freeze({
  candidate_manifest: "candidate_manifest",
  candidate_run_receipt: "candidate_run_receipt",
  structural_artifact_audit: "artifact_integrity",
  visual_review: "visual_review",
  pre_source_stage_snapshot: "pre_source_stage_snapshot",
  post_source_stage_snapshot: "post_source_stage_snapshot",
  capture_process: "capture_process",
  owned_temp_cleanup: "owned_temp_cleanup",
});

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (isRecord(value)) {
    const entries = Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value);
}

export function captureMetadataSha256(captures) {
  return createHash("sha256").update(stableJson(captures)).digest("hex");
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value, expected, label) {
  if (!isRecord(value)) throw new Error(`${label} must be an object`);
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  if (JSON.stringify(actual) !== JSON.stringify(required)) {
    throw new Error(`${label} has an unexpected shape`);
  }
}

function isWithin(parent, candidate) {
  const relative = path.relative(parent, candidate);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}

function hasParentTraversal(candidate) {
  return typeof candidate !== "string" || candidate.split(/[\\/]/).includes("..");
}

function isValidCurrentRunDate(date) {
  if (!/^\d{8}$/.test(date)) return false;
  const parsed = new Date(`${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime())
    && parsed.toISOString().slice(0, 10).replaceAll("-", "") === date
    && date <= new Date().toISOString().slice(0, 10).replaceAll("-", "");
}

export function outputDirectoryForCaptureRoot(captureRoot) {
  if (hasParentTraversal(captureRoot)) {
    throw new Error("capture root must not contain parent traversal");
  }
  const root = path.resolve(captureRoot);
  if (isWithin(APPROVED_CAPTURE_ROOT, root) || root === APPROVED_FINALIZED_CAPTURE_ROOT) {
    return OUTPUT_DIR;
  }
  const relative = path.relative(REPO_ROOT, root).split(path.sep).join("/");
  const match = RUN_FINALIZED_ROOT_PATTERN.exec(relative);
  if (match && isValidCurrentRunDate(match[1])) {
    const taskRoot = relative.slice(0, -"/finalized".length);
    return path.join(REPO_ROOT, taskRoot, "preview");
  }
  throw new Error("capture root must be a canonical R-ASTRA-120 QA or finalized run directory");
}

export function assertNoSecrets(text, label = "content") {
  if (typeof text !== "string") throw new Error(`${label} must be text`);
  if (SECRET_PATTERNS.some((pattern) => pattern.test(text))) {
    throw new Error(`${label} contains a secret-like value`);
  }
  return text;
}

export function validateHandoff(handoff) {
  const keys = [
    "task",
    "status",
    "acceptance",
    "start_condition",
    "authored_documentation_owner",
    "proposed_asset_scope",
    "sections",
    "required_visuals",
    "privacy",
    "formats",
    "email",
  ];
  exactKeys(handoff, keys, "help handoff");
  assertNoSecrets(JSON.stringify(handoff), "help handoff");
  if (handoff.task !== "R-ASTRA-120" || handoff.acceptance !== false) {
    throw new Error("help handoff does not authorize a pre-release draft");
  }
  if (!Array.isArray(handoff.sections) || JSON.stringify(handoff.sections) !== JSON.stringify(REQUIRED_SECTIONS)) {
    throw new Error("help handoff sections do not match the approved guide scope");
  }
  return handoff;
}

function validateViewport(value, group, label) {
  exactKeys(value, ["width", "height"], `${label} viewport`);
  if (
    !Number.isInteger(value.width) || !Number.isInteger(value.height)
    || value.width < 320 || value.width > 2560
    || value.height < 480 || value.height > 2048
    || (group === "desktop" && value.width < 700)
    || (group === "mobile" && value.width >= 700)
  ) {
    throw new Error(`${label} viewport is outside its approved layout bounds`);
  }
}

export function validateCaptureManifest(manifest, expectedRevision) {
  exactKeys(
    manifest,
    ["schema_version", "task", "revision", "qa_receipt_file", "qa_receipt_sha256", "captures"],
    "capture manifest",
  );
  if (manifest.schema_version !== 1 || manifest.task !== "R-ASTRA-120") {
    throw new Error("capture manifest does not match R-ASTRA-120 schema 1");
  }
  if (typeof expectedRevision !== "string" || !REVISION_PATTERN.test(expectedRevision)) {
    throw new Error("an exact 40-character reviewed revision is required");
  }
  if (manifest.revision !== expectedRevision) {
    throw new Error("capture manifest revision does not match the requested revision");
  }
  if (manifest.qa_receipt_file !== QA_RECEIPT_NAME || !SHA256_PATTERN.test(manifest.qa_receipt_sha256)) {
    throw new Error("capture manifest needs the fixed, hash-bound independent QA receipt");
  }
  exactKeys(manifest.captures, CAPTURE_IDS, "capture list");

  const captures = {};
  const seenFiles = new Set();
  const seenHashes = new Set();
  for (const [id, spec] of Object.entries(CAPTURE_COPY)) {
    const capture = manifest.captures[id];
    exactKeys(
      capture,
      ["file", "sha256", "revision", "route", "viewport", "image_dimensions", "theme", "data", "privacy_review"],
      `capture ${id}`,
    );
    if (
      capture.file !== `r120-${id.replaceAll("_", "-")}.png`
    ) {
      throw new Error(`capture filename is not approved: ${id}`);
    }
    if (seenFiles.has(capture.file)) throw new Error(`capture filename is reused: ${id}`);
    seenFiles.add(capture.file);
    if (capture.revision !== expectedRevision || !SHA256_PATTERN.test(capture.sha256)) {
      throw new Error(`capture ${id} is not bound to the reviewed revision and SHA-256`);
    }
    if (seenHashes.has(capture.sha256)) throw new Error(`capture image is reused for another state: ${id}`);
    seenHashes.add(capture.sha256);
    if (capture.route !== spec.route || capture.theme !== spec.theme || capture.data !== "synthetic") {
      throw new Error(`capture ${id} has unapproved route, theme, or data classification`);
    }
    if (capture.privacy_review !== "passed") {
      throw new Error(`capture ${id} lacks a passed private-data review`);
    }
    validateViewport(capture.viewport, spec.group, id);
    exactKeys(capture.image_dimensions, ["width", "height"], `${id} image dimensions`);
    if (
      !Number.isInteger(capture.image_dimensions.width)
      || !Number.isInteger(capture.image_dimensions.height)
      || capture.image_dimensions.width < 1 || capture.image_dimensions.width > 8192
      || capture.image_dimensions.height < 1 || capture.image_dimensions.height > 12000
    ) {
      throw new Error(`capture ${id} image dimensions are outside their bounds`);
    }
    captures[id] = Object.freeze({
      ...spec,
      file: capture.file,
      sha256: capture.sha256,
      revision: capture.revision,
      viewport: Object.freeze({ ...capture.viewport }),
      imageDimensions: Object.freeze({ ...capture.image_dimensions }),
      outputName: `${id}.png`,
    });
  }
  return Object.freeze(captures);
}

function validateQaReceipt(receipt, manifest, expectedRevision) {
  if (receipt?.schema_version === 2) {
    exactKeys(
      receipt,
      [
        "schema_version", "task", "status", "scope", "revision", "revision_state", "reviewer",
        "reviewer_attribution", "upstream_review", "capture_sha256", "capture_metadata_sha256",
        "evidence_files", "source_stage_binding",
      ],
      "finalized QA receipt",
    );
    if (receipt.task !== "R-ASTRA-120" || receipt.status !== "Pass"
        || receipt.scope !== "assistant-ui-captures-finalized"
        || receipt.revision !== expectedRevision || !["clean", "dirty"].includes(receipt.revision_state)
        || receipt.reviewer !== "R-ASTRA-120 code-managed finalizer"
        || receipt.reviewer_attribution !== "The upstream independent capture QA receipt does not name an individual reviewer."
        || receipt.upstream_review !== "Pass for the declared capture, artifact integrity, visual, privacy, and cleanup scope only") {
      throw new Error("finalized QA receipt does not preserve its clean/dirty revision and upstream review attribution");
    }
    exactKeys(receipt.capture_sha256, CAPTURE_IDS, "finalized QA capture hashes");
    for (const id of CAPTURE_IDS) {
      if (receipt.capture_sha256[id] !== manifest.captures[id].sha256) {
        throw new Error(`finalized QA receipt does not cover ${id}`);
      }
    }
    if (receipt.capture_metadata_sha256 !== captureMetadataSha256(manifest.captures)) {
      throw new Error("finalized QA receipt does not bind the finalized capture metadata");
    }
    exactKeys(receipt.evidence_files, Object.keys(FINALIZED_EVIDENCE_FILES), "finalized evidence files");
    for (const [key, file] of Object.entries(FINALIZED_EVIDENCE_FILES)) {
      const entry = receipt.evidence_files[key];
      exactKeys(entry, ["file", "sha256"], `finalized ${key} evidence`);
      if (entry.file !== file || !SHA256_PATTERN.test(entry.sha256)) {
        throw new Error(`finalized QA receipt has an invalid ${key} evidence binding`);
      }
    }
    exactKeys(
      receipt.source_stage_binding,
      [
        "capture_source_file_count", "staged_capture_input_count", "source_sha256", "source_snapshot_sha256",
        "tree_hashes", "stage_equivalence_sha256", "current_source_stage_match", "stage_equivalence_pass",
      ],
      "finalized source/stage binding",
    );
    const sourceBinding = receipt.source_stage_binding;
    if (!Number.isInteger(sourceBinding.capture_source_file_count) || sourceBinding.capture_source_file_count < 40
        || !Number.isInteger(sourceBinding.staged_capture_input_count) || sourceBinding.current_source_stage_match !== true
        || sourceBinding.stage_equivalence_pass !== true || !SHA256_PATTERN.test(sourceBinding.stage_equivalence_sha256)) {
      throw new Error("finalized QA receipt does not prove current source/stage parity");
    }
    if (!isRecord(sourceBinding.source_sha256)) throw new Error("finalized QA receipt lacks current source hashes");
    const sourceNames = Object.keys(sourceBinding.source_sha256);
    const nextNames = sourceNames.filter((file) => file.startsWith(STAGED_NEXT_PREFIX));
    const staticNames = sourceNames.filter((file) => SERVED_STATIC_ASSETS.some(
      (asset) => file === `${STAGED_STATIC_PREFIX}${asset}`,
    ));
    if (nextNames.length < 1 || staticNames.length !== SERVED_STATIC_ASSETS.length
        || ![nextNames.length, nextNames.length + SERVED_STATIC_ASSETS.length].includes(sourceBinding.staged_capture_input_count)
        || sourceNames.length !== sourceBinding.capture_source_file_count + nextNames.length
        || sourceNames.some((file) => file.startsWith("/") || file.split(/[\\/]/).includes("..")
          || !SHA256_PATTERN.test(sourceBinding.source_sha256[file]))) {
      throw new Error("finalized QA receipt source hashes are incomplete or unsafe");
    }
    exactKeys(sourceBinding.source_snapshot_sha256, ["pre", "post"], "finalized source snapshot hashes");
    if (Object.values(sourceBinding.source_snapshot_sha256).some((value) => !SHA256_PATTERN.test(value))) {
      throw new Error("finalized QA receipt has an invalid source snapshot hash");
    }
    validateTreeHashSummary(sourceBinding.tree_hashes, "finalized source tree hashes");
    assertNoSecrets(JSON.stringify(receipt), "finalized QA receipt");
    return receipt;
  }
  exactKeys(
    receipt,
    ["task", "status", "scope", "revision", "reviewer", "capture_sha256", "capture_metadata_sha256"],
    "QA receipt",
  );
  if (
    receipt.task !== "R-ASTRA-120"
    || receipt.status !== "Pass"
    || receipt.scope !== "assistant-ui-captures"
    || receipt.revision !== expectedRevision
    || typeof receipt.reviewer !== "string"
    || receipt.reviewer.length < 1
  ) {
    throw new Error("independent QA receipt is not a passing R-ASTRA-120 UI capture review");
  }
  exactKeys(receipt.capture_sha256, CAPTURE_IDS, "QA capture hashes");
  for (const id of CAPTURE_IDS) {
    if (receipt.capture_sha256[id] !== manifest.captures[id].sha256) {
      throw new Error(`QA receipt does not cover the supplied ${id} screenshot`);
    }
  }
  if (receipt.capture_metadata_sha256 !== captureMetadataSha256(manifest.captures)) {
    throw new Error("independent QA receipt does not bind the capture metadata");
  }
  assertNoSecrets(JSON.stringify(receipt), "QA receipt");
  return receipt;
}

function imageDimensions(bytes, label) {
  if (
    bytes.length < 24
    || !bytes.subarray(0, PNG_SIGNATURE.length).equals(PNG_SIGNATURE)
    || bytes.subarray(12, 16).toString("ascii") !== "IHDR"
  ) {
    throw new Error(`${label} is not a PNG screenshot`);
  }
  const width = bytes.readUInt32BE(16);
  const height = bytes.readUInt32BE(20);
  if (width < 1 || height < 1 || width > 8192 || height > 12000) {
    throw new Error(`${label} has dimensions outside the screenshot bounds`);
  }
  return { width, height };
}

async function readBoundedRegularFile(filePath, maximumBytes, label) {
  const file = await lstat(filePath);
  if (!file.isFile() || file.isSymbolicLink() || file.nlink !== 1 || file.size < 1 || file.size > maximumBytes) {
    throw new Error(`${label} is not a bounded single-link regular file`);
  }
  const resolved = await realpath(filePath);
  if (resolved !== filePath) throw new Error(`${label} resolves through an unexpected path`);
  if (fsConstants.O_NOFOLLOW === undefined) throw new Error("capture verification requires O_NOFOLLOW support");
  const handle = await open(filePath, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW | fsConstants.O_NONBLOCK);
  try {
    const opened = await handle.stat();
    if (!opened.isFile() || opened.nlink !== 1 || opened.size < 1 || opened.size > maximumBytes) {
      throw new Error(`${label} is not a bounded single-link regular file`);
    }
    const bytes = await handle.readFile();
    if (bytes.length !== opened.size) throw new Error(`${label} changed while it was being verified`);
    return bytes;
  } finally {
    await handle.close();
  }
}

async function ensureRealDirectory(directory, label) {
  const info = await lstat(directory);
  if (!info.isDirectory() || info.isSymbolicLink() || await realpath(directory) !== directory) {
    throw new Error(`${label} must be a real directory without symlink traversal`);
  }
}

function safeRelativePath(value) {
  return typeof value === "string" && value.length > 0 && !value.includes("\\")
    && !value.startsWith("/") && value.split("/").every((part) => part && part !== "." && part !== "..");
}

function sha256Hex(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

async function readExportFile(root, relativePath, budget) {
  if (!safeRelativePath(relativePath)) throw new Error("served export contains an unsafe relative path");
  const parts = relativePath.split("/");
  let directory = root;
  for (const part of parts.slice(0, -1)) {
    directory = path.join(directory, part);
    await ensureRealDirectory(directory, "served export directory");
  }
  const filePath = path.join(root, ...parts);
  const info = await lstat(filePath);
  if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1
      || info.size < 1 || info.size > MAX_STAGE_FILE_BYTES) {
    throw new Error("served export contains an unbounded or non-regular file");
  }
  budget.bytes += info.size;
  budget.files += 1;
  if (budget.files > MAX_STAGE_FILES || budget.bytes > MAX_STAGE_TREE_BYTES) {
    throw new Error("served export exceeds the bounded file or byte limit");
  }
  const bytes = await readBoundedRegularFile(filePath, MAX_STAGE_FILE_BYTES, "served export file");
  return sha256Hex(bytes);
}

async function listNextExportFiles(root, relativeDirectory, budget, hashes) {
  if (relativeDirectory.split("/").length > 32) throw new Error("served export exceeds the bounded directory depth");
  const directory = path.join(root, ...relativeDirectory.split("/"));
  await ensureRealDirectory(directory, "served export asset directory");
  const entries = await readdir(directory, { withFileTypes: true });
  budget.entries += entries.length;
  if (budget.entries > MAX_STAGE_ENTRIES) throw new Error("served export exceeds the bounded directory entry limit");
  entries.sort((left, right) => left.name.localeCompare(right.name));
  for (const entry of entries) {
    if (!entry.name || entry.name === "." || entry.name === ".." || entry.name.includes("/")) {
      throw new Error("served export contains an invalid filename");
    }
    const relative = `${relativeDirectory}/${entry.name}`;
    const filePath = path.join(root, ...relative.split("/"));
    if (entry.isSymbolicLink()) throw new Error("served export must not contain symbolic links");
    if (entry.isDirectory()) {
      await listNextExportFiles(root, relative, budget, hashes);
    } else if (entry.isFile()) {
      hashes.set(`next/${relative}`, await readExportFile(root, relative, budget));
    } else {
      throw new Error("served export may contain only regular files and directories");
    }
  }
}

function stagedServedHashes(sourceHashes) {
  if (!isRecord(sourceHashes)) throw new Error("capture source hash map is malformed");
  const hashes = new Map();
  for (const [file, digest] of Object.entries(sourceHashes)) {
    if (!SHA256_PATTERN.test(digest || "")) throw new Error("capture source hash map contains an invalid digest");
    if (file.startsWith(STAGED_NEXT_PREFIX)) {
      const relative = file.slice(STAGED_NEXT_PREFIX.length);
      if (!safeRelativePath(relative)) throw new Error("staged asset map contains an unsafe path");
      hashes.set(`next/${relative}`, digest);
    } else if (file.startsWith(STAGED_STATIC_PREFIX)) {
      const asset = file.slice(STAGED_STATIC_PREFIX.length);
      if (!SERVED_STATIC_ASSETS.includes(asset)) throw new Error("staged asset map contains an unexpected static asset");
      hashes.set(`assets/${asset}`, digest);
    }
  }
  if (SERVED_STATIC_ASSETS.some((asset) => !hashes.has(`assets/${asset}`))) {
    throw new Error("staged asset map is missing a fixed FastAPI static asset");
  }
  return hashes;
}

/** Recompute the exact exported and staged files that FastAPI serves for this guide binding. */
export async function computeServedExportEquivalence(sourceHashes) {
  const staged = stagedServedHashes(sourceHashes);
  const exportRoot = path.join(REPO_ROOT, "frontend/out");
  await ensureRealDirectory(exportRoot, "frontend export root");
  const budget = { bytes: 0, entries: 0, files: 0 };
  const exported = new Map();
  for (const page of SERVED_EXPORT_PAGES) {
    exported.set(`next/${page}`, await readExportFile(exportRoot, page, budget));
  }

  await listNextExportFiles(exportRoot, "_next", budget, exported);

  const assetsRoot = path.join(exportRoot, "assets");
  await ensureRealDirectory(assetsRoot, "frontend export asset root");
  const assetEntries = await readdir(assetsRoot, { withFileTypes: true });
  const assetNames = assetEntries.map((entry) => entry.name).sort();
  if (JSON.stringify(assetNames) !== JSON.stringify([...SERVED_STATIC_ASSETS].sort())
      || assetEntries.some((entry) => !entry.isFile() || entry.isSymbolicLink())) {
    throw new Error("frontend export assets do not match the fixed served asset set");
  }
  for (const asset of SERVED_STATIC_ASSETS) {
    exported.set(`assets/${asset}`, await readExportFile(exportRoot, `assets/${asset}`, budget));
  }

  if (staged.size > MAX_STAGE_FILES || exported.size > MAX_STAGE_FILES) {
    throw new Error("served stage exceeds the bounded file limit");
  }
  const expected = [...exported.keys()].sort();
  const actual = [...staged.keys()].sort();
  const missing = expected.filter((file) => !staged.has(file));
  const extra = actual.filter((file) => !exported.has(file));
  const byteMismatches = expected.filter((file) => staged.has(file) && staged.get(file) !== exported.get(file));
  const staticAssetMatches = Object.fromEntries(SERVED_STATIC_ASSETS.map((asset) => [
    asset,
    staged.get(`assets/${asset}`) === exported.get(`assets/${asset}`),
  ]));
  const staticAssetByteMismatches = SERVED_STATIC_ASSETS.filter((asset) => !staticAssetMatches[asset]);
  return Object.freeze({
    pass: missing.length === 0 && extra.length === 0 && byteMismatches.length === 0
      && staticAssetByteMismatches.length === 0 && staged.size === exported.size,
    expected_served_files: exported.size,
    staged_files: staged.size,
    missing: Object.freeze(missing),
    extra: Object.freeze(extra),
    byte_mismatches: Object.freeze(byteMismatches),
    symlink_count: 0,
    static_asset_matches: Object.freeze(staticAssetMatches),
    static_asset_byte_mismatches: Object.freeze(staticAssetByteMismatches),
  });
}

export function stageEquivalenceMatchesCurrent(stored, current) {
  if (!isRecord(stored) || !isRecord(current)) return false;
  const currentKeys = [
    "pass", "expected_served_files", "staged_files", "missing", "extra", "byte_mismatches",
    "symlink_count", "static_asset_matches", "static_asset_byte_mismatches",
  ];
  const historicalNextOnlyKeys = currentKeys.filter((key) => !key.startsWith("static_asset_"));
  const hasExactKeys = (value, keys) => JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...keys].sort());
  const hasCleanStage = (value) => value.pass === true && value.symlink_count === 0
    && Number.isSafeInteger(value.expected_served_files) && value.expected_served_files >= 0
    && Number.isSafeInteger(value.staged_files) && value.staged_files >= 0
    && Array.isArray(value.missing) && value.missing.length === 0
    && Array.isArray(value.extra) && value.extra.length === 0
    && Array.isArray(value.byte_mismatches) && value.byte_mismatches.length === 0;
  const hasMatchedStaticAssets = (value) => Array.isArray(value.static_asset_byte_mismatches)
    && value.static_asset_byte_mismatches.length === 0
    && isRecord(value.static_asset_matches)
    && JSON.stringify(Object.keys(value.static_asset_matches).sort()) === JSON.stringify([...SERVED_STATIC_ASSETS].sort())
    && Object.values(value.static_asset_matches).every((matches) => matches === true);

  if (!hasExactKeys(current, currentKeys) || !hasCleanStage(current)
      || current.expected_served_files !== current.staged_files || !hasMatchedStaticAssets(current)) return false;
  if (!hasCleanStage(stored)) return false;

  if (hasExactKeys(stored, currentKeys)) {
    if (!hasMatchedStaticAssets(stored)) return false;
    if (stableJson(stored) === stableJson(current)) return true;
    // Older nine-field snapshots counted only Next files but also stored matching static-asset evidence.
    return stored.expected_served_files === current.expected_served_files - SERVED_STATIC_ASSETS.length
      && stored.staged_files === current.staged_files - SERVED_STATIC_ASSETS.length;
  }
  if (hasExactKeys(stored, historicalNextOnlyKeys)) {
    // Original seven-field snapshots predate static-asset fields; current hashes still bind those assets.
    return stored.expected_served_files === current.expected_served_files - SERVED_STATIC_ASSETS.length
      && stored.staged_files === current.staged_files - SERVED_STATIC_ASSETS.length;
  }
  return false;
}

function parseEvidenceJson(bytes, label) {
  const text = bytes.toString("utf8");
  assertNoSecrets(text, label);
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`${label} is not valid JSON`);
  }
}

function validateTreeHashSummary(trees, label) {
  exactKeys(trees, FINALIZED_TREE_NAMES, label);
  for (const name of FINALIZED_TREE_NAMES) {
    const tree = trees[name];
    exactKeys(tree, ["file_count", "sha256"], `${label} ${name}`);
    if (!Number.isInteger(tree.file_count) || tree.file_count < 1 || !SHA256_PATTERN.test(tree.sha256 || "")) {
      throw new Error(`${label} contains an invalid ${name} binding`);
    }
  }
  return trees;
}

function treeSummary(trees) {
  exactKeys(trees, FINALIZED_TREE_NAMES, "finalized source snapshot trees");
  const summary = {};
  for (const name of FINALIZED_TREE_NAMES) {
    const tree = trees[name];
    exactKeys(tree, FINALIZED_TREE_FIELDS[name], `finalized source snapshot tree ${name}`);
    if (!Number.isInteger(tree.file_count) || tree.file_count < 1 || !SHA256_PATTERN.test(tree.sha256 || "")
        || !isRecord(tree.files) || Object.keys(tree.files).length !== tree.file_count) {
      throw new Error(`finalized source snapshot has an invalid ${name} file count or tree hash`);
    }
    if (name === "frontend_authored" && tree.excluded_sensitive_filename_count !== 0) {
      throw new Error("finalized frontend source tree reports excluded sensitive filenames");
    }
    for (const [file, entry] of Object.entries(tree.files)) {
      if (!file || file.startsWith("/") || file.includes("\\")
          || file.split("/").some((part) => part === "" || part === "." || part === "..")) {
        throw new Error(`finalized ${name} tree contains an unsafe relative filename`);
      }
      exactKeys(entry, ["sha256", "size_bytes"], `finalized ${name} tree file`);
      if (!SHA256_PATTERN.test(entry.sha256 || "") || !Number.isInteger(entry.size_bytes) || entry.size_bytes < 0) {
        throw new Error(`finalized ${name} tree contains an invalid file binding`);
      }
    }
    summary[name] = { file_count: tree.file_count, sha256: tree.sha256 };
  }
  return summary;
}

function validateFinalizedEvidenceSet(receipt, bytesByKey, manifest, actualCaptureHashes, currentStageEquivalence) {
  const independent = parseEvidenceJson(bytesByKey.independent_receipt, "independent capture QA receipt");
  const expectedWorktreeState = receipt.revision_state === "dirty"
    ? "dirty; this is not a clean or final PR revision"
    : "clean; this is not a PR or release acceptance";
  if (independent.overall_status !== "Pass for the declared capture, artifact integrity, visual, privacy, and cleanup scope only"
      || independent.bound?.head !== receipt.revision
      || independent.bound?.worktree_state !== expectedWorktreeState) {
    throw new Error("finalized evidence does not preserve the exact passing clean/dirty revision review");
  }
  const candidateManifest = parseEvidenceJson(bytesByKey.candidate_manifest, "original candidate manifest");
  const candidateRun = parseEvidenceJson(bytesByKey.candidate_run_receipt, "original candidate run receipt");
  const artifact = parseEvidenceJson(bytesByKey.artifact_integrity, "structural artifact integrity record");
  if (candidateManifest.task !== "R-ASTRA-120" || candidateManifest.revision !== receipt.revision
      || candidateRun.status !== "builder-candidate" || candidateRun.revision !== receipt.revision
      || candidateRun.revision_state !== receipt.revision_state) {
    throw new Error("finalized evidence does not bind the original dirty candidate");
  }
  exactKeys(candidateManifest.captures, CAPTURE_IDS, "original candidate captures");
  exactKeys(candidateRun.capture_sha256, CAPTURE_IDS, "original candidate run hashes");
  for (const id of CAPTURE_IDS) {
    const original = candidateManifest.captures[id];
    const finalized = manifest.captures[id];
    if (original.privacy_review !== "pending" || candidateRun.capture_sha256[id] !== finalized.sha256
        || stableJson({ ...original, privacy_review: "passed" }) !== stableJson(finalized)) {
      throw new Error(`finalized ${id} metadata does not preserve the pending candidate record`);
    }
  }
  if (independent.snapshot_files === undefined) throw new Error("independent receipt lacks source evidence links");
  for (const [receiptKey, key] of Object.entries(REVIEW_SNAPSHOT_BINDINGS)) {
    const relative = UPSTREAM_EVIDENCE_PATHS[key];
    const reference = independent.snapshot_files[receiptKey];
    if (!reference || reference.path !== relative
        || createHash("sha256").update(bytesByKey[key]).digest("hex") !== reference.sha256
        || reference.sha256 !== receipt.evidence_files[key].sha256) {
      throw new Error(`finalized evidence does not preserve the upstream ${key} hash binding`);
    }
  }
  const approval = parseEvidenceJson(bytesByKey.finalization_approval, "finalization approval pin");
  exactKeys(approval, ["schema_version", "task", "status", "revision", "revision_state", "independent_receipt_sha256"], "finalization approval pin");
  if (approval.schema_version !== 1 || approval.task !== "R-ASTRA-120"
      || approval.status !== "approved-for-finalization" || approval.revision !== receipt.revision
      || approval.revision_state !== receipt.revision_state
      || approval.independent_receipt_sha256 !== createHash("sha256").update(bytesByKey.independent_receipt).digest("hex")) {
    throw new Error("finalized evidence does not preserve its fixed approval pin");
  }
  const visual = parseEvidenceJson(bytesByKey.visual_review, "independent visual/privacy review");
  if (visual.schema_version !== 1
      || visual.overall !== "Pass for per-image visual/privacy review scope"
      || visual.review_scope !== "Independent visual and privacy review of this actual eight-image capture candidate only."
      || !Array.isArray(visual.images) || visual.images.length !== CAPTURE_IDS.length) {
    throw new Error("finalized evidence lacks the passing individual image review");
  }
  const reviewed = new Map(visual.images.map((image) => [image.id, image]));
  if (reviewed.size !== CAPTURE_IDS.length) throw new Error("finalized evidence repeats a visual/privacy review capture id");
  exactKeys(artifact.captures, CAPTURE_IDS, "structural capture set");
  for (const id of CAPTURE_IDS) {
    const image = reviewed.get(id);
    if (!image) throw new Error(`finalized evidence is missing the visual/privacy review for ${id}`);
    exactKeys(image, ["id", "file", "sha256", "status", "privacy", "visual"], `visual review ${id}`);
    const candidate = candidateManifest.captures[id];
    const structural = artifact.captures[id];
    exactKeys(structural, ["bytes", "data", "dimensions", "file", "route", "sha256", "theme"], `structural capture ${id}`);
    if (image.file !== manifest.captures[id].file || image.status !== "Pass"
        || typeof image.privacy !== "string" || !image.privacy.startsWith("Pass:")
        || typeof image.visual !== "string" || image.visual.length < 1) {
      throw new Error(`finalized evidence does not retain privacy Pass for ${id}`);
    }
    if (!SHA256_PATTERN.test(image.sha256 || "")
        || image.file !== candidate.file || image.file !== structural.file
        || image.sha256 !== manifest.captures[id].sha256
        || image.sha256 !== candidate.sha256
        || image.sha256 !== candidateRun.capture_sha256[id]
        || image.sha256 !== structural.sha256
        || image.sha256 !== actualCaptureHashes[id]) {
      throw new Error(`visual/privacy review SHA-256 does not match the exact ${id} PNG bytes`);
    }
  }
  const pre = parseEvidenceJson(bytesByKey.pre_source_stage_snapshot, "pre-capture source/stage snapshot");
  const post = parseEvidenceJson(bytesByKey.post_source_stage_snapshot, "post-capture source/stage snapshot");
  const source = receipt.source_stage_binding;
  const independentTreeSummary = validateTreeHashSummary(
    independent.pre_post_tree_hashes,
    "independent pre/post source tree hashes",
  );
  const sourceTreeSummary = validateTreeHashSummary(source.tree_hashes, "finalized source tree hashes");
  for (const [phase, snapshot] of [["pre", pre], ["post", post]]) {
    if (snapshot.phase !== phase || snapshot.canonical_and_independent_hashes_match !== true
        || !stageEquivalenceMatchesCurrent(snapshot.stage_equivalence, currentStageEquivalence)
        || snapshot.capture_source_file_count !== source.capture_source_file_count
        || snapshot.staged_capture_input_count !== source.staged_capture_input_count
        || snapshot.stage_equivalence?.expected_served_files !== source.staged_capture_input_count
        || snapshot.stage_equivalence?.staged_files !== source.staged_capture_input_count
        || snapshot.stage_equivalence?.missing?.length !== 0 || snapshot.stage_equivalence?.extra?.length !== 0
        || snapshot.stage_equivalence?.byte_mismatches?.length !== 0
        || stableJson(snapshot.capture_helper_hash_map) !== stableJson(candidateRun.source_sha256)
        || stableJson(snapshot.capture_source_inputs) !== stableJson(candidateRun.source_sha256)
        || stableJson(snapshot.capture_helper_hash_map) !== stableJson(source.source_sha256)
        || stableJson(treeSummary(snapshot.trees)) !== stableJson(independentTreeSummary)
        || stableJson(treeSummary(snapshot.trees)) !== stableJson(sourceTreeSummary)) {
      throw new Error(`finalized evidence has an invalid ${phase} source/stage binding`);
    }
  }
  if (source.source_snapshot_sha256.pre !== receipt.evidence_files.pre_source_stage_snapshot.sha256
      || source.source_snapshot_sha256.post !== receipt.evidence_files.post_source_stage_snapshot.sha256
      || stableJson(pre.capture_helper_hash_map) !== stableJson(post.capture_helper_hash_map)
      || stableJson(pre.trees) !== stableJson(post.trees)
      || stableJson(pre.stage_equivalence) !== stableJson(post.stage_equivalence)
      || createHash("sha256").update(stableJson(pre.stage_equivalence)).digest("hex") !== source.stage_equivalence_sha256) {
    throw new Error("finalized pre/post source and stage evidence differs");
  }
}

async function ensureCaptureRoot(captureRoot, approvedRoot) {
  if (hasParentTraversal(captureRoot)) {
    throw new Error("capture root must not contain parent traversal");
  }
  const root = path.resolve(captureRoot);
  const relative = path.relative(REPO_ROOT, root).split(path.sep).join("/");
  const runMatch = RUN_FINALIZED_ROOT_PATTERN.exec(relative);
  const isCanonicalRunRoot = runMatch && isValidCurrentRunDate(runMatch[1]);
  const isApproved = approvedRoot
    ? isWithin(path.resolve(approvedRoot), root)
    : isWithin(APPROVED_CAPTURE_ROOT, root) || root === APPROVED_FINALIZED_CAPTURE_ROOT || isCanonicalRunRoot;
  if (!isApproved) {
    throw new Error("capture root must stay inside the R-ASTRA-120 independent browser QA artifact");
  }
  const rootInfo = await lstat(root);
  if (!rootInfo.isDirectory() || rootInfo.isSymbolicLink() || (await realpath(root)) !== root) {
    throw new Error("capture root must be a real directory without symlink traversal");
  }
  return root;
}

export async function assertRunPreviewOutputAvailable(captureRoot) {
  const root = await ensureCaptureRoot(captureRoot);
  const relative = path.relative(REPO_ROOT, root).split(path.sep).join("/");
  const match = RUN_FINALIZED_ROOT_PATTERN.exec(relative);
  if (!match || !isValidCurrentRunDate(match[1])) {
    throw new Error("preview collision checks require a canonical finalized run root");
  }
  const outputDirectory = outputDirectoryForCaptureRoot(root);
  try {
    await lstat(outputDirectory);
    throw new Error("help preview output already exists; refusing to overwrite it");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  return outputDirectory;
}

export async function loadVerifiedCaptures({
  captureRoot,
  manifestPath,
  expectedRevision,
  currentRevision,
  approvedRoot,
}) {
  if (currentRevision !== expectedRevision) {
    throw new Error("requested capture revision does not match the current application revision");
  }
  const root = await ensureCaptureRoot(captureRoot, approvedRoot);
  const expectedManifestPath = path.join(root, CAPTURE_MANIFEST_NAME);
  if (path.resolve(manifestPath) !== expectedManifestPath) {
    throw new Error("capture manifest must use the fixed name inside the approved capture root");
  }
  const manifestBytes = await readBoundedRegularFile(expectedManifestPath, MAX_MANIFEST_BYTES, "capture manifest");
  const manifest = JSON.parse(manifestBytes.toString("utf8"));
  assertNoSecrets(manifestBytes.toString("utf8"), "capture manifest");
  const captures = validateCaptureManifest(manifest, expectedRevision);

  const receiptPath = path.join(root, manifest.qa_receipt_file);
  const receiptBytes = await readBoundedRegularFile(receiptPath, MAX_RECEIPT_BYTES, "QA receipt");
  const receiptHash = createHash("sha256").update(receiptBytes).digest("hex");
  if (receiptHash !== manifest.qa_receipt_sha256) throw new Error("independent QA receipt SHA-256 does not match");
  const receipt = validateQaReceipt(JSON.parse(receiptBytes.toString("utf8")), manifest, expectedRevision);
  let finalizedEvidenceBytes;
  let currentStageEquivalence;
  if (receipt.schema_version === 2) {
    const evidenceHashes = {};
    finalizedEvidenceBytes = {};
    for (const [key, relative] of Object.entries(FINALIZED_EVIDENCE_FILES)) {
      const bytes = await readBoundedRegularFile(path.join(root, relative), MAX_RECEIPT_BYTES, `finalized ${key} evidence`);
      const digest = createHash("sha256").update(bytes).digest("hex");
      if (digest !== receipt.evidence_files[key].sha256) throw new Error(`finalized ${key} evidence SHA-256 does not match`);
      assertNoSecrets(bytes.toString("utf8"), `finalized ${key} evidence`);
      evidenceHashes[key] = digest;
      finalizedEvidenceBytes[key] = bytes;
    }
    if (evidenceHashes.pre_source_stage_snapshot !== receipt.source_stage_binding.source_snapshot_sha256.pre
        || evidenceHashes.post_source_stage_snapshot !== receipt.source_stage_binding.source_snapshot_sha256.post) {
      throw new Error("finalized source snapshot hashes do not match the evidence bundle");
    }
    const { hashCaptureSources } = await import("./capture.mjs");
    const currentHashes = await hashCaptureSources();
    if (stableJson(currentHashes) !== stableJson(receipt.source_stage_binding.source_sha256)) {
      throw new Error("current source/stage inputs differ from the finalized capture review");
    }
    currentStageEquivalence = await computeServedExportEquivalence(currentHashes);
    if (!currentStageEquivalence.pass) throw new Error("current served files do not match the frontend export");
  }

  const verified = {};
  const actualCaptureHashes = {};
  for (const [id, capture] of Object.entries(captures)) {
    const sourcePath = path.join(root, capture.file);
    const bytes = await readBoundedRegularFile(sourcePath, MAX_CAPTURE_BYTES, `capture ${id}`);
    const actualHash = createHash("sha256").update(bytes).digest("hex");
    if (actualHash !== capture.sha256) throw new Error(`capture ${id} SHA-256 does not match the QA manifest`);
    actualCaptureHashes[id] = actualHash;
    const dimensions = imageDimensions(bytes, `capture ${id}`);
    if (dimensions.width !== capture.imageDimensions.width || dimensions.height !== capture.imageDimensions.height) {
      throw new Error(`capture ${id} pixel dimensions do not match its verified manifest`);
    }
    verified[id] = Object.freeze({ ...capture, bytes, dimensions: Object.freeze(dimensions) });
  }
  if (finalizedEvidenceBytes) {
    validateFinalizedEvidenceSet(receipt, finalizedEvidenceBytes, manifest, actualCaptureHashes, currentStageEquivalence);
  }
  const bundle = Object.freeze({
    revision: expectedRevision,
    reviewer: receipt.reviewer,
    captures: Object.freeze(verified),
  });
  VERIFIED_CAPTURE_BUNDLES.add(bundle);
  return bundle;
}

function escapeHtml(value) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

export function validateLocalDocument(html, css) {
  if (typeof css !== "string") throw new Error("guide stylesheet must be text");
  if (/<\/style/i.test(css)) {
    throw new Error("guide stylesheet contains an unsafe closing-style sequence");
  }
  const combined = `${html}\n${css}`;
  assertNoSecrets(combined, "guide source");
  if (/<script\b|<iframe\b|<object\b|<embed\b|<(?:audio|video|source)\b/i.test(html)
    || /@import\b|url\s*\(/i.test(css)) {
    throw new Error("guide source contains executable or remote content");
  }
  if (/<(?:img|link)\b[^>]*(?:src|href)\s*=\s*["']https?:/i.test(html)) {
    throw new Error("guide source contains a remote asset");
  }
  if (/<link\b/i.test(html)) throw new Error("guide HTML must not depend on linked resources");
  const styleBlocks = [...html.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)];
  if (styleBlocks.length !== 1 || styleBlocks[0][1].trim() !== css.trim()) {
    throw new Error("guide HTML must embed the exact local stylesheet once");
  }
  const imageTags = [...html.matchAll(/<img\b[^>]*>/gi)].map(([tag]) => tag);
  if (imageTags.some((tag) => !/\balt="[^"]+"/i.test(tag))) {
    throw new Error("every guide image requires descriptive alternative text");
  }
  if (imageTags.some((tag) => !/\bsrc="data:image\/png;base64,[A-Za-z0-9+/]+={0,2}"/i.test(tag))) {
    throw new Error("every guide image must embed a verified PNG data URI");
  }
  const headings = [...html.matchAll(/<h1\b/g)].length;
  if (headings !== 1 || !html.includes('<main id="main-content">')) {
    throw new Error("guide document needs one primary heading and a main landmark");
  }
  return true;
}

// The emailed artifact travels without sidecars, so CSS and verified captures must be embedded.
export function renderGuideHtml(template, verifiedCaptures, css) {
  if (typeof template !== "string") throw new Error("guide template must be text");
  if (!isRecord(verifiedCaptures) || !VERIFIED_CAPTURE_BUNDLES.has(verifiedCaptures)) {
    throw new Error("guide rendering requires revision-bound verified captures");
  }
  if (typeof css !== "string") throw new Error("guide stylesheet must be text");
  if (/<\/style/i.test(css)) {
    throw new Error("guide stylesheet contains an unsafe closing-style sequence");
  }
  exactKeys(verifiedCaptures.captures, CAPTURE_IDS, "verified captures");
  const stylesheetSlots = template.match(/\{\{guide_css\}\}/g) ?? [];
  if (stylesheetSlots.length !== 1) throw new Error("guide template needs exactly one stylesheet slot");
  let html = template
    .replaceAll("{{implementation_revision}}", escapeHtml(verifiedCaptures.revision))
    .replace("{{guide_css}}", css);
  for (const [id, capture] of Object.entries(verifiedCaptures.captures)) {
    const values = {
      src: `data:image/png;base64,${capture.bytes.toString("base64")}`,
      alt: capture.alt,
      label: capture.label,
      caption: capture.caption,
    };
    for (const [field, value] of Object.entries(values)) {
      html = html.replaceAll(`{{capture:${id}:${field}}}`, escapeHtml(value));
    }
  }
  if (/\{\{(?:capture:|implementation_revision|guide_css)/.test(html)) {
    throw new Error("guide template has an unresolved verified-capture field");
  }
  return html;
}

async function ensureOutputDirectory(outputDirectory = OUTPUT_DIR) {
  const outputRoot = path.resolve(outputDirectory);
  const relative = path.relative(REPO_ROOT, outputRoot);
  if (relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
    throw new Error("fixed help output path is outside the repository");
  }
  let current = REPO_ROOT;
  const segments = relative.split(path.sep);
  for (const [index, segment] of segments.entries()) {
    current = path.join(current, segment);
    const isOutputRoot = index === segments.length - 1;
    try {
      const existing = await lstat(current);
      if (isOutputRoot) {
        throw new Error("help preview output already exists; refusing to overwrite it");
      }
      if (!existing.isDirectory() || existing.isSymbolicLink()) {
        throw new Error("fixed help output path contains a non-directory or symlink");
      }
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      await mkdir(current, { mode: 0o700 });
    }
    if ((await realpath(current)) !== current) {
      throw new Error("fixed help output path resolves outside its repository location");
    }
  }
}

async function ensureOutputFilesSafe(outputDirectory, names) {
  for (const name of names) {
    const destination = path.join(outputDirectory, name);
    if (path.dirname(destination) !== outputDirectory || name.includes(path.sep)) {
      throw new Error("help output filename is not fixed");
    }
    try {
      await lstat(destination);
      throw new Error("help preview file already exists; refusing to overwrite it");
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
}

async function makePdf(htmlPath, pdfPath) {
  const browserRequire = createRequire(path.join(REPO_ROOT, "tools/browser/package.json"));
  const { chromium } = browserRequire("playwright");
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const externalRequests = [];
  page.on("request", (request) => {
    const protocol = new URL(request.url()).protocol;
    if (protocol !== "file:" && protocol !== "about:") externalRequests.push(request.url());
  });
  try {
    await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready);
    const imageStatus = await page.evaluate(() => [...document.images].map((image) => ({
      complete: image.complete,
      width: image.naturalWidth,
    })));
    if (imageStatus.length !== CAPTURE_IDS.length || imageStatus.some((image) => !image.complete || image.width === 0)) {
      throw new Error("one or more independent-QA screenshots did not load in the guide");
    }
    const layout = await page.evaluate(() => ({
      width: document.documentElement.scrollWidth,
      viewport: document.documentElement.clientWidth,
      landmarks: {
        main: document.querySelectorAll("main").length,
        h1: document.querySelectorAll("h1").length,
        unlabeledImages: [...document.images].filter((image) => !image.alt.trim()).length,
      },
    }));
    if (
      layout.width > layout.viewport || layout.landmarks.main !== 1
      || layout.landmarks.h1 !== 1 || layout.landmarks.unlabeledImages
    ) {
      throw new Error("guide layout or semantic checks failed");
    }
    await page.setViewportSize({ width: 390, height: 844 });
    const mobileWidth = await page.evaluate(() => ({
      document: document.documentElement.scrollWidth,
      viewport: document.documentElement.clientWidth,
    }));
    if (mobileWidth.document > mobileWidth.viewport) throw new Error("guide overflows its mobile viewport");
    if (externalRequests.length) throw new Error("guide attempted a non-local network request");
    await page.emulateMedia({ media: "print" });
    await applyPdfPrintTextPreservation(page);
    await normalizePdfPrintEmphasis(page);
    await page.pdf({ path: pdfPath, ...PDF_EXPORT_OPTIONS });
  } finally {
    await browser.close();
  }
  if (externalRequests.length) throw new Error("guide attempted a non-local network request");
  const pdf = await readFile(pdfPath);
  if (pdf.subarray(0, 5).toString("ascii") !== "%PDF-" || pdf.length < 10_000) {
    throw new Error("guide PDF is missing or unexpectedly small");
  }
  return pdf.length;
}

function currentGitRevision() {
  const result = spawnSync("git", ["rev-parse", "--verify", "HEAD"], {
    cwd: REPO_ROOT,
    encoding: "utf8",
    timeout: 5000,
    stdio: ["ignore", "pipe", "ignore"],
  });
  if (result.status !== 0 || !REVISION_PATTERN.test(result.stdout.trim())) {
    throw new Error("could not verify the current full Git revision");
  }
  return result.stdout.trim();
}

export async function renderPreview({ captureRoot, manifestPath, revision }) {
  const handoff = validateHandoff(JSON.parse(await readFile(HANDOFF_PATH, "utf8")));
  const verified = await loadVerifiedCaptures({
    captureRoot,
    manifestPath,
    expectedRevision: revision,
    currentRevision: currentGitRevision(),
  });
  const outputDirectory = outputDirectoryForCaptureRoot(captureRoot);
  if (outputDirectory !== OUTPUT_DIR) {
    await assertRunPreviewOutputAvailable(captureRoot);
  }
  const outputNames = [
    ...Object.values(verified.captures).map((capture) => capture.outputName),
    "guide.css",
    "guide.html",
    "guide.pdf",
  ];
  const template = await readFile(TEMPLATE_PATH, "utf8");
  const css = await readFile(CSS_PATH, "utf8");
  const html = renderGuideHtml(template, verified, css);
  validateLocalDocument(html, css);
  await ensureOutputDirectory(outputDirectory);
  await ensureOutputFilesSafe(outputDirectory, outputNames);
  for (const capture of Object.values(verified.captures)) {
    await writeFile(path.join(outputDirectory, capture.outputName), capture.bytes, {
      flag: "wx",
      mode: 0o600,
    });
  }
  await writeFile(path.join(outputDirectory, "guide.css"), css, {
    flag: "wx",
    mode: 0o600,
  });
  const htmlPath = path.join(outputDirectory, "guide.html");
  const pdfPath = path.join(outputDirectory, "guide.pdf");
  await writeFile(htmlPath, html, { flag: "wx", mode: 0o600 });
  const pdfBytes = await makePdf(htmlPath, pdfPath);
  const htmlBytes = (await stat(htmlPath)).size;
  return {
    task: handoff.task,
    status: "draft",
    revision: verified.revision,
    qa_reviewer: verified.reviewer,
    output: path.relative(REPO_ROOT, outputDirectory).split(path.sep).join("/"),
    screenshots: CAPTURE_IDS.length,
    capture_sha256: Object.fromEntries(
      Object.entries(verified.captures).map(([id, capture]) => [id, capture.sha256]),
    ),
    html_bytes: htmlBytes,
    pdf_bytes: pdfBytes,
    external_requests: 0,
  };
}

export function parseArguments(argv) {
  const expected = ["--capture-root", "--manifest", "--revision"];
  if (argv.length !== expected.length * 2) {
    throw new Error("Usage: node render.mjs --capture-root QA_BROWSER_DIR --manifest QA_BROWSER_DIR/assistant-help-captures.json --revision FULL_SHA");
  }
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    if (!expected.includes(key) || values[key] !== undefined || !argv[index + 1]) {
      throw new Error("renderer accepts only explicit capture-root, manifest, and revision inputs");
    }
    values[key] = argv[index + 1];
  }
  if (expected.some((key) => values[key] === undefined)) {
    throw new Error("renderer requires explicit capture-root, manifest, and revision inputs");
  }
  if (hasParentTraversal(values["--capture-root"]) || hasParentTraversal(values["--manifest"])) {
    throw new Error("renderer capture-root and manifest inputs must not contain parent traversal");
  }
  return {
    captureRoot: path.resolve(REPO_ROOT, values["--capture-root"]),
    manifestPath: path.resolve(REPO_ROOT, values["--manifest"]),
    revision: values["--revision"],
  };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const inputs = parseArguments(process.argv.slice(2));
    renderPreview(inputs).then(
      (receipt) => process.stdout.write(`${JSON.stringify(receipt)}\n`),
      (error) => {
        process.stderr.write(`${error instanceof Error ? error.message : "guide render failed"}\n`);
        process.exitCode = 1;
      },
    );
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : "invalid guide inputs"}\n`);
    process.exitCode = 2;
  }
}
