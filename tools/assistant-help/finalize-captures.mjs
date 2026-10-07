import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import {
  constants as fsConstants,
  lstat,
  mkdir,
  open,
  realpath,
  rm,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  CAPTURE_SOURCE_FILES,
  hashCaptureSources,
} from "./capture.mjs";
import {
  assertNoSecrets,
  captureMetadataSha256,
  CAPTURE_IDS,
  computeServedExportEquivalence,
  REPO_ROOT,
  stageEquivalenceMatchesCurrent,
} from "./render.mjs";

const TASK_ROOT_PREFIX = "test-results/assistant-r120/help-current-captures-";
const TASK_ROOT_PATTERN = /^test-results\/assistant-r120\/help-current-captures-(\d{8})(?:-([a-f0-9]{12}))?$/;
const SERVED_STATIC_ASSETS = Object.freeze(["app.css", "app.js", "theme.js", "favicon.svg"]);

function utcDateStamp(now) {
  if (!(now instanceof Date) || Number.isNaN(now.getTime())) throw new Error("finalization requires a valid current date");
  return now.toISOString().slice(0, 10).replaceAll("-", "");
}

function taskPaths(taskDate, runId) {
  if (!/^\d{8}$/.test(taskDate)) throw new Error("capture task root date is invalid");
  if (runId !== undefined && !/^[a-f0-9]{12}$/.test(runId)) throw new Error("capture run suffix is invalid");
  const parsed = new Date(`${taskDate.slice(0, 4)}-${taskDate.slice(4, 6)}-${taskDate.slice(6, 8)}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime()) || utcDateStamp(parsed) !== taskDate) throw new Error("capture task root date is invalid");
  const taskRootRelative = `${TASK_ROOT_PREFIX}${taskDate}${runId ? `-${runId}` : ""}`;
  const evidenceRoot = path.resolve(REPO_ROOT, taskRootRelative);
  if (path.relative(REPO_ROOT, evidenceRoot).split(path.sep).join("/") !== taskRootRelative) {
    throw new Error("capture task root must stay within the R-ASTRA-120 evidence directory");
  }
  const candidateRelativePath = `${taskRootRelative}/candidate`;
  return Object.freeze({
    taskDate,
    taskRootRelative,
    evidenceRoot,
    candidateRoot: path.join(evidenceRoot, "candidate"),
    candidateRelativePath,
    outputRoot: runId
      ? path.join(evidenceRoot, "finalized")
      : path.join(REPO_ROOT, "test-results/assistant-r120/help-finalized"),
  });
}

export const CAPTURE_TASK_DATE = utcDateStamp(new Date());
const DEFAULT_TASK_PATHS = taskPaths(CAPTURE_TASK_DATE);
export const CAPTURE_EVIDENCE_ROOT = DEFAULT_TASK_PATHS.evidenceRoot;
export const CANDIDATE_ROOT = DEFAULT_TASK_PATHS.candidateRoot;
export const CANDIDATE_RELATIVE_PATH = DEFAULT_TASK_PATHS.candidateRelativePath;
export const FINALIZED_CAPTURE_ROOT = DEFAULT_TASK_PATHS.outputRoot;
export const FINALIZATION_APPROVAL_FILE = "finalization-approval.json";

export const FINAL_MANIFEST_NAME = "assistant-help-captures.json";
export const FINAL_QA_RECEIPT_NAME = "assistant-help-qa-receipt.json";
export const CANDIDATE_MANIFEST_NAME = "assistant-help-captures.json";
export const CANDIDATE_RUN_RECEIPT_NAME = "assistant-help-capture-run.json";

const MAX_JSON_BYTES = 1024 * 1024;
const MAX_CAPTURE_BYTES = 12 * 1024 * 1024;
const ZERO_SHA256 = "0".repeat(64);
const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const REVISION_PATTERN = /^[a-f0-9]{40}$/;
const PNG_SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const STAGED_PREFIX = "src/stock_probs/static/next/";
const UPSTREAM_EVIDENCE = Object.freeze({
  candidate_manifest: Object.freeze({ source: "candidate/assistant-help-captures.json", output: "evidence/candidate-manifest.json" }),
  candidate_run_receipt: Object.freeze({ source: "candidate/assistant-help-capture-run.json", output: "evidence/candidate-run-receipt.json" }),
  independent_receipt: Object.freeze({ source: "independent-capture-qa-receipt.json", output: "evidence/independent-capture-qa-receipt.json" }),
  finalization_approval: Object.freeze({ source: FINALIZATION_APPROVAL_FILE, output: "evidence/finalization-approval.json" }),
  visual_review: Object.freeze({ source: "visual-review.json", output: "evidence/visual-review.json" }),
  artifact_integrity: Object.freeze({ source: "artifact-integrity.json", output: "evidence/artifact-integrity.json" }),
  pre_source_stage_snapshot: Object.freeze({ source: "pre-source-stage-hashes.json", output: "evidence/pre-source-stage-hashes.json" }),
  post_source_stage_snapshot: Object.freeze({ source: "post-source-stage-hashes.json", output: "evidence/post-source-stage-hashes.json" }),
  capture_process: Object.freeze({ source: "capture-process.json", output: "evidence/capture-process.json" }),
  owned_temp_cleanup: Object.freeze({ source: "owned-temp-cleanup.json", output: "evidence/owned-temp-cleanup.json" }),
});

const CAPTURE_SPECS = Object.freeze({
  desktop_light: Object.freeze({ file: "r120-desktop-light.png", route: "/tools/live-trading", theme: "light", viewport: { width: 1440, height: 1000 } }),
  desktop_dark: Object.freeze({ file: "r120-desktop-dark.png", route: "/tools/live-trading", theme: "dark", viewport: { width: 1440, height: 1000 } }),
  mobile_light: Object.freeze({ file: "r120-mobile-light.png", route: "/tools/live-trading", theme: "light", viewport: { width: 390, height: 844 } }),
  mobile_dark: Object.freeze({ file: "r120-mobile-dark.png", route: "/tools/live-trading", theme: "dark", viewport: { width: 390, height: 844 } }),
  forecast_sources: Object.freeze({ file: "r120-forecast-sources.png", route: "/tools/forecast", theme: "light", viewport: { width: 1440, height: 1000 } }),
  action_preview: Object.freeze({ file: "r120-action-preview.png", route: "/tools/live-trading", theme: "light", viewport: { width: 1440, height: 1000 } }),
  action_receipt: Object.freeze({ file: "r120-action-receipt.png", route: "/tools/live-trading", theme: "light", viewport: { width: 1440, height: 1000 } }),
  history_context: Object.freeze({ file: "r120-history-context.png", route: "/tools/live-trading", theme: "light", viewport: { width: 1440, height: 1000 } }),
});

const REQUIRED_CHECKS = Object.freeze([
  "one actual capture invocation with approved identifiers",
  "source and stage bindings",
  "PNG bytes, hashes, dimensions and synthetic labels",
  "capture diagnostics",
  "fixture process, port, and temporary cleanup",
  "individual image visual/privacy review",
  "candidate privacy/QA metadata preserved",
]);

const OUTPUT_EVIDENCE_NAMES = Object.freeze(Object.fromEntries(
  Object.entries(UPSTREAM_EVIDENCE).map(([key, spec]) => [key, spec.output]),
));
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
const SNAPSHOT_EVIDENCE_KEYS = Object.freeze(Object.keys(REVIEW_SNAPSHOT_BINDINGS));
const EXPANDED_CAPTURE_IDS = Object.freeze(["action_preview", "action_receipt", "history_context"]);

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

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function currentGitMetadata() {
  // A matching HEAD does not make uncommitted guide inputs reviewable; bind dirtiness separately.
  const revision = spawnSync("git", ["rev-parse", "--verify", "HEAD"], {
    cwd: REPO_ROOT,
    encoding: "utf8",
    timeout: 5000,
    stdio: ["ignore", "pipe", "ignore"],
  });
  const status = spawnSync("git", ["status", "--porcelain", "--untracked-files=all"], {
    cwd: REPO_ROOT,
    encoding: "utf8",
    timeout: 5000,
    stdio: ["ignore", "pipe", "ignore"],
  });
  const fullRevision = revision.stdout?.trim();
  if (revision.status !== 0 || status.status !== 0 || !REVISION_PATTERN.test(fullRevision || "")) {
    throw new Error("could not verify the current full Git revision and worktree state");
  }
  return Object.freeze({ revision: fullRevision, dirty: status.stdout.length > 0 });
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (isRecord(value)) {
    const entries = Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value);
}

function isWithin(parent, candidate) {
  const relative = path.relative(parent, candidate);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}

async function ensureRealDirectory(directory, label) {
  const resolved = path.resolve(directory);
  const info = await lstat(resolved);
  if (!info.isDirectory() || info.isSymbolicLink() || await realpath(resolved) !== resolved) {
    throw new Error(`${label} must be a real directory without symlink traversal`);
  }
  return resolved;
}

async function readBoundedRegularFile(filePath, maxBytes, label) {
  const info = await lstat(filePath);
  if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1 || info.size < 1 || info.size > maxBytes) {
    throw new Error(`${label} is not a bounded single-link regular file`);
  }
  if (await realpath(filePath) !== filePath) throw new Error(`${label} resolves through an unexpected path`);
  if (fsConstants.O_NOFOLLOW === undefined) throw new Error("capture finalization requires O_NOFOLLOW support");
  const handle = await open(filePath, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW | fsConstants.O_NONBLOCK);
  try {
    const opened = await handle.stat();
    if (!opened.isFile() || opened.nlink !== 1 || opened.size < 1 || opened.size > maxBytes) {
      throw new Error(`${label} is not a bounded single-link regular file`);
    }
    const bytes = await handle.readFile();
    if (bytes.length !== opened.size) throw new Error(`${label} changed while it was being verified`);
    return bytes;
  } finally {
    await handle.close();
  }
}

async function readJson(root, relativePath, label) {
  const bytes = await readBoundedRegularFile(path.join(root, relativePath), MAX_JSON_BYTES, label);
  const text = bytes.toString("utf8");
  assertNoSecrets(text, label);
  try {
    return { bytes, value: JSON.parse(text) };
  } catch {
    throw new Error(`${label} is not valid JSON`);
  }
}

function validateCandidateManifest(manifest, revision) {
  exactKeys(manifest, ["schema_version", "task", "revision", "qa_receipt_file", "qa_receipt_sha256", "captures"], "candidate manifest");
  if (manifest.schema_version !== 1 || manifest.task !== "R-ASTRA-120" || manifest.revision !== revision) {
    throw new Error("candidate manifest is not the expected R-ASTRA-120 revision");
  }
  if (manifest.qa_receipt_file !== FINAL_QA_RECEIPT_NAME || manifest.qa_receipt_sha256 !== ZERO_SHA256) {
    throw new Error("candidate manifest must retain its pending QA receipt marker");
  }
  exactKeys(manifest.captures, CAPTURE_IDS, "candidate captures");
  for (const id of CAPTURE_IDS) {
    const capture = manifest.captures[id];
    exactKeys(capture, ["file", "sha256", "revision", "route", "viewport", "image_dimensions", "theme", "data", "privacy_review"], `candidate capture ${id}`);
    const spec = CAPTURE_SPECS[id];
    if (capture.file !== spec.file || capture.revision !== revision || capture.route !== spec.route
        || capture.theme !== spec.theme || capture.data !== "synthetic"
        || capture.privacy_review !== "pending" || !SHA256_PATTERN.test(capture.sha256 || "")) {
      throw new Error(`candidate ${id} metadata is not the approved pending capture state`);
    }
    exactKeys(capture.viewport, ["width", "height"], `${id} viewport`);
    exactKeys(capture.image_dimensions, ["width", "height"], `${id} image dimensions`);
    if (JSON.stringify(capture.viewport) !== JSON.stringify(spec.viewport)
        || JSON.stringify(capture.image_dimensions) !== JSON.stringify(spec.viewport)) {
      throw new Error(`candidate ${id} viewport or image dimensions differ from the approved state`);
    }
  }
  return manifest;
}

function validateCapturePresentation(presentation) {
  exactKeys(presentation, EXPANDED_CAPTURE_IDS, "expanded assistant capture presentation");
  for (const id of EXPANDED_CAPTURE_IDS) {
    const item = presentation[id];
    exactKeys(item, ["assistant_size", "viewport", "panel_bounds"], `${id} presentation`);
    exactKeys(item.viewport, ["width", "height"], `${id} presentation viewport`);
    exactKeys(item.panel_bounds, ["x", "y", "width", "height"], `${id} panel bounds`);
    const viewport = CAPTURE_SPECS[id].viewport;
    const { x, y, width, height } = item.panel_bounds;
    if (item.assistant_size !== "expanded"
        || item.viewport.width !== viewport.width || item.viewport.height !== viewport.height
        || ![x, y, width, height].every(Number.isFinite)
        || x < 0 || y < 0 || x + width > viewport.width + 1 || y + height > viewport.height + 1
        || width < 800 || height < 900) {
      throw new Error(`candidate ${id} lacks approved expanded assistant geometry`);
    }
  }
}

function validateRunReceipt(runReceipt, revision, revisionState, manifest) {
  exactKeys(runReceipt, ["task", "status", "revision", "revision_state", "source_sha256", "capture_sha256", "capture_presentation", "fixture_lifecycle"], "candidate run receipt");
  if (runReceipt.task !== "R-ASTRA-120" || runReceipt.status !== "builder-candidate"
      || runReceipt.revision !== revision || runReceipt.revision_state !== revisionState) {
    throw new Error("candidate run receipt does not identify the exact pinned capture revision state");
  }
  exactKeys(runReceipt.capture_sha256, CAPTURE_IDS, "candidate run capture hashes");
  const hashes = {};
  for (const id of CAPTURE_IDS) {
    const value = runReceipt.capture_sha256[id];
    if (value !== manifest.captures[id].sha256) throw new Error(`candidate run receipt has a mismatched ${id} hash`);
    hashes[id] = value;
  }
  if (!isRecord(runReceipt.source_sha256)) throw new Error("candidate run receipt lacks its source and staged-input map");
  const stagedFiles = Object.keys(runReceipt.source_sha256).filter((file) => file.startsWith(STAGED_PREFIX));
  const authoredFiles = Object.keys(runReceipt.source_sha256).filter((file) => !file.startsWith(STAGED_PREFIX));
  if (stagedFiles.length < 1 || authoredFiles.length !== CAPTURE_SOURCE_FILES.length) {
    throw new Error("candidate run receipt lacks the complete approved source and staged-input map");
  }
  for (const [file, digest] of Object.entries(runReceipt.source_sha256)) {
    if ((!CAPTURE_SOURCE_FILES.includes(file) && !file.startsWith(STAGED_PREFIX)) || !SHA256_PATTERN.test(digest || "")) {
      throw new Error("candidate run receipt contains an unexpected source or staged input");
    }
  }
  validateCapturePresentation(runReceipt.capture_presentation);
  exactKeys(runReceipt.fixture_lifecycle, ["child_pid", "loopback_port", "termination_signals", "child_exit_code", "child_exit_signal", "process_exit_verified", "loopback_port_released", "runtime_directory_removed"], "fixture lifecycle");
  if (!Number.isInteger(runReceipt.fixture_lifecycle.child_pid) || runReceipt.fixture_lifecycle.child_pid < 1
      || !Number.isInteger(runReceipt.fixture_lifecycle.loopback_port)
      || runReceipt.fixture_lifecycle.loopback_port < 1024 || runReceipt.fixture_lifecycle.loopback_port > 65535
      || !Array.isArray(runReceipt.fixture_lifecycle.termination_signals)
      || runReceipt.fixture_lifecycle.process_exit_verified !== true
      || runReceipt.fixture_lifecycle.loopback_port_released !== true
      || runReceipt.fixture_lifecycle.runtime_directory_removed !== true) {
    throw new Error("candidate run receipt lacks verified fixture and temporary cleanup");
  }
  return Object.freeze({ ...runReceipt, capture_sha256: Object.freeze(hashes) });
}

function worktreeStateDescription(revisionState) {
  if (revisionState === "dirty") return "dirty; this is not a clean or final PR revision";
  if (revisionState === "clean") return "clean; this is not a PR or release acceptance";
  throw new Error("finalization revision state must be clean or dirty");
}

function validateIndependentReceipt(receipt, revision, revisionState) {
  exactKeys(receipt, ["schema_version", "task", "overall_status", "recorded_at_utc", "capture_window_utc", "capture_command", "capture_invocation_count", "capture_exit_code", "bound", "environment", "checks", "pre_post_tree_hashes", "snapshot_files", "limitations"], "independent capture QA receipt");
  if (receipt.schema_version !== 1 || receipt.task !== "R-ASTRA-120 actual eight-capture independent QA"
      || receipt.overall_status !== "Pass for the declared capture, artifact integrity, visual, privacy, and cleanup scope only"
      || receipt.capture_invocation_count !== 1 || receipt.capture_exit_code !== 0
      || receipt.bound?.head !== revision
      || receipt.bound?.worktree_state !== worktreeStateDescription(revisionState)) {
    throw new Error("independent capture QA receipt is not a passing receipt for this pinned revision state");
  }
  exactKeys(receipt.bound, ["branch", "head", "worktree_state"], "independent receipt revision binding");
  if (receipt.bound.branch !== "codex/signal-ledger-assistant-r120") throw new Error("independent receipt is bound to an unexpected branch");
  if (!Array.isArray(receipt.checks) || receipt.checks.length !== REQUIRED_CHECKS.length) {
    throw new Error("independent capture QA receipt lacks the full required check set");
  }
  exactKeys(receipt.snapshot_files, SNAPSHOT_EVIDENCE_KEYS, "independent evidence file bindings");
  for (const [index, check] of receipt.checks.entries()) {
    exactKeys(check, ["name", "status", "evidence"], `independent check ${index}`);
    if (check.name !== REQUIRED_CHECKS[index] || check.status !== "Pass"
        || typeof check.evidence !== "string" || check.evidence.length < 1) {
      throw new Error(`independent check did not Pass: ${REQUIRED_CHECKS[index]}`);
    }
  }
  if (!isRecord(receipt.snapshot_files) || !isRecord(receipt.pre_post_tree_hashes)) {
    throw new Error("independent receipt lacks bound source/stage and capture evidence");
  }
  return receipt;
}

function validateFinalizationApproval(approval, revision, receiptSha256) {
  exactKeys(approval, ["schema_version", "task", "status", "revision", "revision_state", "independent_receipt_sha256"], "finalization approval pin");
  if (approval.schema_version !== 1 || approval.task !== "R-ASTRA-120"
      || approval.status !== "approved-for-finalization"
      || !["clean", "dirty"].includes(approval.revision_state)
      || approval.revision !== revision
      || approval.independent_receipt_sha256 !== receiptSha256
      || !SHA256_PATTERN.test(approval.independent_receipt_sha256 || "")) {
    throw new Error("fixed finalization approval does not select this revision state and independent receipt");
  }
  return approval;
}

function validateVisualReview(review, manifest, runReceipt, artifact) {
  if (review.schema_version !== 1 || review.overall !== "Pass for per-image visual/privacy review scope"
      || review.review_scope !== "Independent visual and privacy review of this actual eight-image capture candidate only.") {
    throw new Error("independent visual/privacy review is not a passing eight-image review");
  }
  if (!Array.isArray(review.images) || review.images.length !== CAPTURE_IDS.length) {
    throw new Error("independent visual/privacy review does not cover all eight captures");
  }
  const reviewed = new Map(review.images.map((image) => [image.id, image]));
  if (reviewed.size !== CAPTURE_IDS.length) throw new Error("independent visual/privacy review repeats a capture id");
  for (const id of CAPTURE_IDS) {
    const image = reviewed.get(id);
    if (!image) throw new Error(`independent visual/privacy review is missing ${id}`);
    exactKeys(image, ["id", "file", "sha256", "status", "privacy", "visual"], `visual review ${id}`);
    if (image.file !== CAPTURE_SPECS[id].file || image.status !== "Pass"
        || typeof image.privacy !== "string" || !image.privacy.startsWith("Pass:")
        || typeof image.visual !== "string" || image.visual.length < 1) {
      throw new Error(`independent visual/privacy review did not Pass for ${id}`);
    }
    const expectedSha256 = manifest.captures[id].sha256;
    if (!SHA256_PATTERN.test(image.sha256 || "")
        || image.sha256 !== expectedSha256
        || image.sha256 !== runReceipt.capture_sha256[id]
        || image.sha256 !== artifact.captures[id].sha256) {
      throw new Error(`visual/privacy review SHA-256 does not match the exact ${id} candidate PNG bytes`);
    }
  }
  return review;
}

function validateArtifactIntegrity(artifact, revision, revisionState, manifest, imageSizes) {
  if (artifact.status !== "Pass for structural/artifact/process integrity"
      || artifact.candidate_status !== "builder-candidate"
      || artifact.candidate_manifest_status_preserved !== "builder-candidate"
      || artifact.revision !== revision || artifact.revision_state !== revisionState
      || artifact.capture_command_exit_code !== 0 || artifact.capture_helper_invocation_count !== 1
      || artifact.capture_count !== CAPTURE_IDS.length || artifact.output_file_count !== 10
      || artifact.prepost_canonical_capture_hashes_match !== true
      || artifact.prepost_complete_source_stage_tree_hashes_match !== true
      || artifact.prepost_stage_equivalence_pass !== true
      || artifact.qa_receipt_sha256_is_pending !== true
      || JSON.stringify(artifact.approved_ids) !== JSON.stringify(CAPTURE_IDS)
      || artifact.fixture_child_pid_absent_after_exit !== true
      || artifact.fixture_port_bind_free_after_exit !== true
      || artifact.helper_receipt_says_port_released !== true
      || artifact.outer_process_group_gone !== true
      || artifact.runtime_directory_removed !== true
      || artifact.TMPDIR_empty_after_capture !== true
      || JSON.stringify(artifact.privacy_review_statuses) !== JSON.stringify(["pending"])) {
    throw new Error("structural artifact record does not preserve the builder-candidate state");
  }
  exactKeys(artifact.captures, CAPTURE_IDS, "structural capture set");
  for (const id of CAPTURE_IDS) {
    const image = artifact.captures[id];
    exactKeys(image, ["bytes", "data", "dimensions", "file", "route", "sha256", "theme"], `structural capture ${id}`);
    if (image.sha256 !== manifest.captures[id].sha256 || image.file !== manifest.captures[id].file
        || image.bytes !== imageSizes[id] || image.data !== "synthetic"
        || image.route !== manifest.captures[id].route || image.theme !== manifest.captures[id].theme
        || image.dimensions?.width !== manifest.captures[id].image_dimensions.width
        || image.dimensions?.height !== manifest.captures[id].image_dimensions.height) {
      throw new Error(`structural artifact record does not match ${id}`);
    }
  }
}

function validateSourceSnapshots(pre, post, receipt, runReceipt, currentSourceHashes, currentStageEquivalence) {
  // Join the producer's fixed tree names, file maps, and pre/post state to both candidate and independent QA.
  const authoredInputCount = CAPTURE_SOURCE_FILES.length;
  const stagedNextCount = Object.keys(runReceipt.source_sha256).filter((file) => file.startsWith(STAGED_PREFIX)).length;
  const servedInputCount = stagedNextCount + SERVED_STATIC_ASSETS.length;
  for (const [phase, snapshot] of [["pre", pre], ["post", post]]) {
    if (snapshot.phase !== phase || snapshot.canonical_and_independent_hashes_match !== true
        || snapshot.capture_source_file_count !== authoredInputCount
        || ![stagedNextCount, servedInputCount].includes(snapshot.staged_capture_input_count)
        || !isRecord(snapshot.capture_helper_hash_map)
        || !isRecord(snapshot.capture_source_inputs)
        || !stageEquivalenceMatchesCurrent(snapshot.stage_equivalence, currentStageEquivalence)) {
      throw new Error(`independent ${phase} source/stage snapshot does not pass its exact binding checks`);
    }
    if (stableJson(snapshot.capture_helper_hash_map) !== stableJson(runReceipt.source_sha256)
        || stableJson(snapshot.capture_source_inputs) !== stableJson(runReceipt.source_sha256)) {
      throw new Error(`independent ${phase} source/stage snapshot does not bind the candidate run inputs`);
    }
    const treeSummary = Object.fromEntries(Object.entries(snapshot.trees).map(([key, value]) => [key, {
      file_count: value.file_count,
      sha256: value.sha256,
    }]));
    if (stableJson(treeSummary) !== stableJson(receipt.pre_post_tree_hashes)) {
      throw new Error(`independent ${phase} source/stage tree summary differs from its QA receipt`);
    }
    if (stableJson(snapshot.capture_helper_hash_map) !== stableJson(currentSourceHashes)) {
      const captured = snapshot.capture_helper_hash_map;
      const current = currentSourceHashes;
      const different = Object.keys(captured).filter((file) => current[file] !== captured[file]);
      const missing = Object.keys(captured).filter((file) => current[file] === undefined);
      const extra = Object.keys(current).filter((file) => captured[file] === undefined);
      const details = [...different, ...missing.map((file) => `${file} (missing)`), ...extra.map((file) => `${file} (new)`)].slice(0, 8);
      throw new Error(`current capture source/stage inputs have drifted since the independent review (${details.join(", ")})`);
    }
  }
  if (stableJson(pre.capture_helper_hash_map) !== stableJson(post.capture_helper_hash_map)
      || stableJson(pre.capture_source_inputs) !== stableJson(post.capture_source_inputs)
      || stableJson(pre.trees) !== stableJson(post.trees)
      || stableJson(pre.stage_equivalence) !== stableJson(post.stage_equivalence)) {
    throw new Error("pre/post source and stage evidence differs");
  }
  return {
    capture_source_file_count: authoredInputCount,
    staged_capture_input_count: pre.staged_capture_input_count,
    source_sha256: Object.freeze({ ...currentSourceHashes }),
    source_snapshot_sha256: Object.freeze({}),
    tree_hashes: Object.freeze(Object.fromEntries(
      Object.entries(pre.trees).map(([key, value]) => [key, Object.freeze({ file_count: value.file_count, sha256: value.sha256 })]),
    )),
    stage_equivalence_sha256: sha256(Buffer.from(stableJson(pre.stage_equivalence))),
    current_source_stage_match: true,
    stage_equivalence_pass: true,
  };
}

function validateProcessCleanup(processReceipt, cleanupReceipt, independentReceipt, candidateRelativePath) {
  const expectedArgvSuffix = [
    "tools/assistant-help/capture.mjs",
    "--output-dir",
    candidateRelativePath,
  ];
  const argv = processReceipt.argv;
  const argvMatches = Array.isArray(argv) && argv.length >= expectedArgvSuffix.length
    && JSON.stringify(argv.slice(-expectedArgvSuffix.length)) === JSON.stringify(expectedArgvSuffix);
  if (processReceipt.invocation_count !== 1 || processReceipt.exit_code !== 0
      || processReceipt.owned_process_group_remaining_after_exit !== false
      || processReceipt.output_directory !== candidateRelativePath || !argvMatches
      || typeof independentReceipt.capture_command !== "string"
      || !independentReceipt.capture_command.endsWith(expectedArgvSuffix.join(" "))
      || cleanupReceipt.status !== "Pass" || cleanupReceipt.unexpected_entries_absent !== true
      || cleanupReceipt.root_removed !== true || cleanupReceipt.process_group_gone !== true
      || cleanupReceipt.fixture_pid_absent !== true || cleanupReceipt.port_rebind_check?.includes("bind succeeded") !== true) {
    throw new Error("independent process and owned temporary cleanup evidence did not Pass");
  }
}

async function verifyEvidenceChain({ evidenceRoot, candidateRoot, candidateRelativePath, revision, revisionState, expectedReceiptSha256, currentSourceHashes }) {
  if (!REVISION_PATTERN.test(revision)) throw new Error("finalization requires an exact 40-character revision");
  const evidenceDir = await ensureRealDirectory(evidenceRoot, "independent capture QA root");
  const candidateDir = await ensureRealDirectory(candidateRoot, "capture candidate root");
  if (candidateDir !== path.join(evidenceDir, "candidate")) {
    throw new Error("candidate directory must be the fixed candidate child of the independent QA artifact");
  }
  if (!SHA256_PATTERN.test(expectedReceiptSha256 || "")) throw new Error("finalization requires an exact independent receipt SHA-256");

  const loaded = {};
  for (const [key, spec] of Object.entries(UPSTREAM_EVIDENCE)) {
    const item = await readJson(evidenceDir, spec.source, key.replaceAll("_", " "));
    loaded[key] = { bytes: item.bytes, value: item.value };
  }
  // Approval pins the exact independent-receipt bytes and revision state; it never substitutes for the joins below.
  validateFinalizationApproval(loaded.finalization_approval.value, revision, expectedReceiptSha256);
  const independentHash = sha256(loaded.independent_receipt.bytes);
  if (independentHash !== expectedReceiptSha256) throw new Error("independent capture QA receipt SHA-256 does not match the reviewed receipt");

  const candidateManifest = validateCandidateManifest(loaded.candidate_manifest.value, revision);
  const runReceipt = validateRunReceipt(loaded.candidate_run_receipt.value, revision, revisionState, candidateManifest);
  const independentReceipt = validateIndependentReceipt(loaded.independent_receipt.value, revision, revisionState);
  validateProcessCleanup(loaded.capture_process.value, loaded.owned_temp_cleanup.value, independentReceipt, candidateRelativePath);

  const snapshotRefs = independentReceipt.snapshot_files;
  for (const [receiptKey, evidenceKey] of Object.entries(REVIEW_SNAPSHOT_BINDINGS)) {
    const spec = UPSTREAM_EVIDENCE[evidenceKey];
    const ref = snapshotRefs[receiptKey];
    if (!ref || ref.path !== spec.source || !SHA256_PATTERN.test(ref.sha256 || "")) {
      throw new Error(`independent receipt does not bind the exact ${receiptKey} evidence file`);
    }
  }
  if (sha256(loaded.candidate_manifest.bytes) !== snapshotRefs.candidate_manifest.sha256
      || sha256(loaded.candidate_run_receipt.bytes) !== snapshotRefs.candidate_run_receipt.sha256) {
    throw new Error("independent receipt does not hash-bind the original candidate metadata");
  }
  for (const [receiptKey, evidenceKey] of Object.entries(REVIEW_SNAPSHOT_BINDINGS)) {
    if (evidenceKey === "candidate_manifest" || evidenceKey === "candidate_run_receipt") continue;
    if (sha256(loaded[evidenceKey].bytes) !== snapshotRefs[receiptKey].sha256) {
      throw new Error(`independent receipt does not hash-bind ${receiptKey}`);
    }
  }

  const currentStageEquivalence = await computeServedExportEquivalence(currentSourceHashes);
  if (!currentStageEquivalence.pass) throw new Error("current served files do not match the frontend export");
  const sourceBinding = validateSourceSnapshots(
    loaded.pre_source_stage_snapshot.value,
    loaded.post_source_stage_snapshot.value,
    independentReceipt,
    runReceipt,
    currentSourceHashes,
    currentStageEquivalence,
  );
  const imageBytes = {};
  const imageSizes = {};
  for (const id of CAPTURE_IDS) {
    const capture = candidateManifest.captures[id];
    const bytes = await readBoundedRegularFile(path.join(candidateDir, capture.file), MAX_CAPTURE_BYTES, `capture ${id}`);
    const digest = sha256(bytes);
    if (digest !== capture.sha256 || runReceipt.capture_sha256[id] !== digest) {
      throw new Error(`candidate ${id} image SHA-256 differs from the exact candidate and run receipt`);
    }
    if (bytes.length < 24 || !bytes.subarray(0, 8).equals(PNG_SIGNATURE) || bytes.toString("ascii", 12, 16) !== "IHDR"
        || bytes.readUInt32BE(16) !== capture.image_dimensions.width
        || bytes.readUInt32BE(20) !== capture.image_dimensions.height) {
      throw new Error(`candidate ${id} image bytes do not match the PNG metadata`);
    }
    imageBytes[id] = bytes;
    imageSizes[id] = bytes.length;
  }
  validateArtifactIntegrity(loaded.artifact_integrity.value, revision, revisionState, candidateManifest, imageSizes);
  const visualReview = validateVisualReview(
    loaded.visual_review.value,
    candidateManifest,
    runReceipt,
    loaded.artifact_integrity.value,
  );

  const finalCaptures = Object.fromEntries(CAPTURE_IDS.map((id) => [id, {
    ...candidateManifest.captures[id],
    privacy_review: "passed",
  }]));
  const outputManifest = {
    schema_version: 1,
    task: "R-ASTRA-120",
    revision,
    qa_receipt_file: FINAL_QA_RECEIPT_NAME,
    qa_receipt_sha256: ZERO_SHA256,
    captures: finalCaptures,
  };
  const evidenceFiles = Object.fromEntries(Object.entries(loaded).map(([key, item]) => [key, {
    file: OUTPUT_EVIDENCE_NAMES[key],
    sha256: sha256(item.bytes),
  }]));
  sourceBinding.source_snapshot_sha256 = Object.freeze({
    pre: evidenceFiles.pre_source_stage_snapshot.sha256,
    post: evidenceFiles.post_source_stage_snapshot.sha256,
  });
  const qaReceipt = Object.freeze({
    schema_version: 2,
    task: "R-ASTRA-120",
    status: "Pass",
    scope: "assistant-ui-captures-finalized",
    revision,
    revision_state: revisionState,
    reviewer: "R-ASTRA-120 code-managed finalizer",
    reviewer_attribution: "The upstream independent capture QA receipt does not name an individual reviewer.",
    upstream_review: "Pass for the declared capture, artifact integrity, visual, privacy, and cleanup scope only",
    capture_sha256: Object.freeze(Object.fromEntries(CAPTURE_IDS.map((id) => [id, finalCaptures[id].sha256]))),
    capture_metadata_sha256: captureMetadataSha256(finalCaptures),
    evidence_files: Object.freeze(evidenceFiles),
    source_stage_binding: Object.freeze(sourceBinding),
  });
  const qaBytes = Buffer.from(JSON.stringify(qaReceipt, null, 2) + "\n");
  outputManifest.qa_receipt_sha256 = sha256(qaBytes);
  return Object.freeze({
    candidateManifestBytes: loaded.candidate_manifest.bytes,
    candidateRunReceiptBytes: loaded.candidate_run_receipt.bytes,
    imageBytes: Object.freeze(imageBytes),
    evidenceBytes: Object.freeze(Object.fromEntries(Object.entries(loaded).map(([key, item]) => [key, item.bytes]))),
    qaReceiptBytes: qaBytes,
    manifestBytes: Buffer.from(JSON.stringify(outputManifest, null, 2) + "\n"),
    revision,
    capture_sha256: Object.freeze(Object.fromEntries(CAPTURE_IDS.map((id) => [id, finalCaptures[id].sha256]))),
    qaReceipt,
  });
}

export async function finalizeCaptureBundle({
  evidenceRoot = CAPTURE_EVIDENCE_ROOT,
  candidateRoot = CANDIDATE_ROOT,
  candidateRelativePath = CANDIDATE_RELATIVE_PATH,
  outputRoot = FINALIZED_CAPTURE_ROOT,
  currentRevision,
  currentDirty,
  currentSourceHashes,
} = {}) {
  const output = path.resolve(outputRoot);
  const git = currentRevision === undefined || currentDirty === undefined ? currentGitMetadata() : { revision: currentRevision, dirty: currentDirty };
  const approvalFile = await readJson(path.resolve(evidenceRoot), FINALIZATION_APPROVAL_FILE, "finalization approval pin");
  const approval = approvalFile.value;
  const revision = approval?.revision;
  const expectedReceiptSha256 = approval?.independent_receipt_sha256;
  validateFinalizationApproval(approval, revision, expectedReceiptSha256);
  const revisionState = approval.revision_state;
  // Refuse a stale or differently dirty checkout before creating any finalized output.
  if (git.revision !== revision || git.dirty !== (revisionState === "dirty")) {
    throw new Error("finalization approval revision and clean/dirty state must match the current Git worktree");
  }
  const actualSourceHashes = currentSourceHashes || await hashCaptureSources();
  const evidence = await verifyEvidenceChain({
    evidenceRoot,
    candidateRoot,
    candidateRelativePath,
    revision,
    revisionState,
    expectedReceiptSha256,
    currentSourceHashes: actualSourceHashes,
  });

  const parent = path.dirname(output);
  await mkdir(parent, { recursive: true, mode: 0o700 });
  if (await realpath(parent) !== parent) throw new Error("finalized capture output parent resolves unexpectedly");
  try {
    await lstat(output);
    throw new Error("finalized capture output already exists; refusing to overwrite it");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  await mkdir(output, { mode: 0o700 });
  let published = false;
  try {
    for (const id of CAPTURE_IDS) {
      await writeFile(path.join(output, CAPTURE_SPECS[id].file), evidence.imageBytes[id], { flag: "wx", mode: 0o600 });
    }
    const evidenceDirectory = path.join(output, "evidence");
    await mkdir(evidenceDirectory, { mode: 0o700 });
    for (const [key, bytes] of Object.entries(evidence.evidenceBytes)) {
      const destination = path.join(output, OUTPUT_EVIDENCE_NAMES[key]);
      await writeFile(destination, bytes, { flag: "wx", mode: 0o600 });
    }
    await writeFile(path.join(output, FINAL_QA_RECEIPT_NAME), evidence.qaReceiptBytes, { flag: "wx", mode: 0o600 });
    await writeFile(path.join(output, FINAL_MANIFEST_NAME), evidence.manifestBytes, { flag: "wx", mode: 0o600 });
    published = true;
  } finally {
    if (!published) await rm(output, { recursive: true, force: true });
  }
  return Object.freeze({
    task: "R-ASTRA-120",
    status: "draft",
    revision: evidence.revision,
    revision_state: evidence.qaReceipt.revision_state,
    output: path.relative(REPO_ROOT, output),
    screenshots: CAPTURE_IDS.length,
    capture_sha256: evidence.capture_sha256,
    upstream_review_attribution: "unattributed in source receipt",
    current_source_stage_match: true,
  });
}

export function parseArguments(argv, { now = new Date() } = {}) {
  const today = utcDateStamp(now);
  let selected = taskPaths(today);
  if (argv.length === 2 && argv[0] === "--task-root" && typeof argv[1] === "string") {
    const match = TASK_ROOT_PATTERN.exec(argv[1]);
    if (!match || match[1] > today) {
      throw new Error("capture task root must be a fixed, valid R-ASTRA-120 UTC-date directory with an optional 12-character lowercase hex run suffix, no later than today");
    }
    selected = taskPaths(match[1], match[2]);
  } else if (argv.length !== 0) {
    throw new Error("Usage: node tools/assistant-help/finalize-captures.mjs [--task-root test-results/assistant-r120/help-current-captures-YYYYMMDD[-<12-lowercase-hex>]]");
  }
  return Object.freeze({
    evidenceRoot: selected.evidenceRoot,
    candidateRoot: selected.candidateRoot,
    candidateRelativePath: selected.candidateRelativePath,
    outputRoot: selected.outputRoot,
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const options = parseArguments(process.argv.slice(2));
    finalizeCaptureBundle(options).then(
      (receipt) => process.stdout.write(`${JSON.stringify(receipt)}\n`),
      (error) => {
        process.stderr.write(`${error instanceof Error ? error.message : "capture finalization failed"}\n`);
        process.exitCode = 1;
      },
    );
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : "invalid capture finalization arguments"}\n`);
    process.exitCode = 2;
  }
}
