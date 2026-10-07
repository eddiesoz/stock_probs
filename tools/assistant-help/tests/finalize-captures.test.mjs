import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  CAPTURE_SOURCE_FILES,
  hashCaptureSources,
} from "../capture.mjs";
import {
  CAPTURE_EVIDENCE_ROOT,
  CAPTURE_TASK_DATE,
  CANDIDATE_ROOT,
  CANDIDATE_RELATIVE_PATH,
  FINALIZED_CAPTURE_ROOT,
  FINAL_MANIFEST_NAME,
  FINAL_QA_RECEIPT_NAME,
  finalizeCaptureBundle,
  parseArguments,
} from "../finalize-captures.mjs";
import {
  CAPTURE_IDS,
  REPO_ROOT,
  computeServedExportEquivalence,
  loadVerifiedCaptures,
  stageEquivalenceMatchesCurrent,
  captureMetadataSha256,
} from "../render.mjs";

const REVISION = "a".repeat(40);
const HASH = (bytes) => createHash("sha256").update(bytes).digest("hex");
const STAGED_PREFIX = "src/stock_probs/static/next/";
const AUTHORED_STATIC_ASSETS = Object.freeze([
  "src/stock_probs/static/app.css",
  "src/stock_probs/static/app.js",
  "src/stock_probs/static/theme.js",
  "src/stock_probs/static/favicon.svg",
]);
const expectedServedFileCount = (sourceHashes) => {
  assert.ok(AUTHORED_STATIC_ASSETS.every((file) => Object.hasOwn(sourceHashes, file)));
  const stagedNextCount = Object.keys(sourceHashes).filter((file) => file.startsWith(STAGED_PREFIX)).length;
  return stagedNextCount + AUTHORED_STATIC_ASSETS.length;
};
const SPECS = Object.freeze({
  desktop_light: { file: "r120-desktop-light.png", route: "/tools/live-trading", theme: "light", dimensions: { width: 1440, height: 1000 } },
  desktop_dark: { file: "r120-desktop-dark.png", route: "/tools/live-trading", theme: "dark", dimensions: { width: 1440, height: 1000 } },
  mobile_light: { file: "r120-mobile-light.png", route: "/tools/live-trading", theme: "light", dimensions: { width: 390, height: 844 } },
  mobile_dark: { file: "r120-mobile-dark.png", route: "/tools/live-trading", theme: "dark", dimensions: { width: 390, height: 844 } },
  forecast_sources: { file: "r120-forecast-sources.png", route: "/tools/forecast", theme: "light", dimensions: { width: 1440, height: 1000 } },
  action_preview: { file: "r120-action-preview.png", route: "/tools/live-trading", theme: "light", dimensions: { width: 1440, height: 1000 } },
  action_receipt: { file: "r120-action-receipt.png", route: "/tools/live-trading", theme: "light", dimensions: { width: 1440, height: 1000 } },
  history_context: { file: "r120-history-context.png", route: "/tools/live-trading", theme: "light", dimensions: { width: 1440, height: 1000 } },
});
const UPSTREAM_FILES = Object.freeze({
  candidate_manifest: "candidate/assistant-help-captures.json",
  candidate_run_receipt: "candidate/assistant-help-capture-run.json",
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
const TREE_NAMES = Object.freeze([
  "fastapi_served",
  "frontend_authored",
  "frontend_out",
]);
const CHECK_NAMES = Object.freeze([
  "one actual capture invocation with approved identifiers",
  "source and stage bindings",
  "PNG bytes, hashes, dimensions and synthetic labels",
  "capture diagnostics",
  "fixture process, port, and temporary cleanup",
  "individual image visual/privacy review",
  "candidate privacy/QA metadata preserved",
]);

test("finalizer CLI binds canonical current or prior UTC roots and defaults across midnight", () => {
  const now = new Date("2026-10-07T18:00:00Z");
  const expectedFor = (date, runId) => {
    const taskRoot = `test-results/assistant-r120/help-current-captures-${date}${runId ? `-${runId}` : ""}`;
    return {
      evidenceRoot: path.join(REPO_ROOT, taskRoot),
      candidateRoot: path.join(REPO_ROOT, taskRoot, "candidate"),
      candidateRelativePath: `${taskRoot}/candidate`,
      outputRoot: runId
        ? path.join(REPO_ROOT, taskRoot, "finalized")
        : FINALIZED_CAPTURE_ROOT,
    };
  };
  const currentRoot = "test-results/assistant-r120/help-current-captures-20261007";
  const priorRoot = "test-results/assistant-r120/help-current-captures-20261006";
  assert.deepEqual(parseArguments([], { now }), expectedFor("20261007"));
  assert.deepEqual(parseArguments(["--task-root", currentRoot], { now }), expectedFor("20261007"));
  assert.deepEqual(parseArguments(["--task-root", priorRoot], { now }), expectedFor("20261006"));
  const firstRunId = "012345abcdef";
  const secondRunId = "fedcba987654";
  const firstRunRoot = `${currentRoot}-${firstRunId}`;
  const secondRunRoot = `${currentRoot}-${secondRunId}`;
  assert.deepEqual(parseArguments(["--task-root", firstRunRoot], { now }), expectedFor("20261007", firstRunId));
  assert.deepEqual(parseArguments(["--task-root", secondRunRoot], { now }), expectedFor("20261007", secondRunId));
  assert.notEqual(
    parseArguments(["--task-root", firstRunRoot], { now }).outputRoot,
    parseArguments(["--task-root", secondRunRoot], { now }).outputRoot,
  );
  assert.deepEqual(parseArguments([], { now: new Date("2026-10-06T23:59:59.999Z") }), expectedFor("20261006"));
  assert.deepEqual(parseArguments([], { now: new Date("2026-10-07T00:00:00.000Z") }), expectedFor("20261007"));
  assert.equal(CAPTURE_TASK_DATE, new Date().toISOString().slice(0, 10).replaceAll("-", ""));
  assert.equal(CANDIDATE_RELATIVE_PATH, `test-results/assistant-r120/help-current-captures-${CAPTURE_TASK_DATE}/candidate`);
  assert.equal(CAPTURE_EVIDENCE_ROOT, path.join(REPO_ROOT, `test-results/assistant-r120/help-current-captures-${CAPTURE_TASK_DATE}`));
  assert.equal(CANDIDATE_ROOT, path.join(CAPTURE_EVIDENCE_ROOT, "candidate"));
  for (const forged of [
    ["--task-root", "test-results/assistant-r120/help-current-captures-20261008"],
    ["--task-root", "test-results/assistant-r120/../assistant-r120/help-current-captures-20261007"],
    ["--task-root", "/tmp/help-current-captures-20261007"],
    ["--task-root", "test-results/assistant-r120/help-current-captures-20260230"],
    ["--task-root", "test-results/assistant-r120/help-current-captures-2026107"],
    ["--task-root", `${currentRoot}-ABCDEF123456`],
    ["--task-root", `${currentRoot}-abcdef12345`],
    ["--task-root", `${currentRoot}-abcdef1234567`],
    ["--task-root", `${currentRoot}-abcdef12345g`],
    ["--task-root", `test-results/assistant-r120/help-current-captures-20261008-${firstRunId}`],
    ["--capture-root", "/tmp/arbitrary"],
  ]) assert.throws(() => parseArguments(forged, { now }), /Usage:|UTC-date|within|invalid/);
});

test("same-day run finalization refuses an existing run output without changing it", async () => {
  await fixture(async (state) => {
    const runOutputRoot = path.join(state.evidenceRoot, "finalized");
    await mkdir(runOutputRoot, { mode: 0o700 });
    const retainedFile = path.join(runOutputRoot, "reserved-output.txt");
    await writeFile(retainedFile, "preserve existing run output", { flag: "wx", mode: 0o600 });
    await assert.rejects(
      state.finalize({ outputRoot: runOutputRoot }),
      /already exists; refusing to overwrite/,
    );
    assert.equal(await readFile(retainedFile, "utf8"), "preserve existing run output");
  });
});

function png(width, height, marker) {
  const bytes = Buffer.alloc(25, marker);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(bytes, 0);
  bytes.writeUInt32BE(13, 8);
  bytes.write("IHDR", 12, "ascii");
  bytes.writeUInt32BE(width, 16);
  bytes.writeUInt32BE(height, 20);
  return bytes;
}

function jsonBytes(value) {
  return Buffer.from(JSON.stringify(value, null, 2) + "\n");
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

async function writeJson(filePath, value) {
  const bytes = jsonBytes(value);
  await writeFile(filePath, bytes, { mode: 0o600 });
  return bytes;
}

async function rewriteFinalizedVisualReview(state, update) {
  const manifestPath = path.join(state.outputRoot, FINAL_MANIFEST_NAME);
  const receiptPath = path.join(state.outputRoot, FINAL_QA_RECEIPT_NAME);
  const visualPath = path.join(state.outputRoot, "evidence/visual-review.json");
  const independentPath = path.join(state.outputRoot, "evidence/independent-capture-qa-receipt.json");
  const approvalPath = path.join(state.outputRoot, "evidence/finalization-approval.json");
  const visual = JSON.parse(await readFile(visualPath, "utf8"));
  update(visual);
  const visualBytes = await writeJson(visualPath, visual);
  const independent = JSON.parse(await readFile(independentPath, "utf8"));
  independent.snapshot_files.visual_review.sha256 = HASH(visualBytes);
  const independentBytes = await writeJson(independentPath, independent);
  const approval = JSON.parse(await readFile(approvalPath, "utf8"));
  approval.independent_receipt_sha256 = HASH(independentBytes);
  const approvalBytes = await writeJson(approvalPath, approval);
  const receipt = JSON.parse(await readFile(receiptPath, "utf8"));
  receipt.evidence_files.visual_review.sha256 = HASH(visualBytes);
  receipt.evidence_files.independent_receipt.sha256 = HASH(independentBytes);
  receipt.evidence_files.finalization_approval.sha256 = HASH(approvalBytes);
  const receiptBytes = await writeJson(receiptPath, receipt);
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  manifest.qa_receipt_sha256 = HASH(receiptBytes);
  await writeJson(manifestPath, manifest);
  return manifestPath;
}

async function rewriteFinalizedQaReceipt(state, update) {
  const manifestPath = path.join(state.outputRoot, FINAL_MANIFEST_NAME);
  const receiptPath = path.join(state.outputRoot, FINAL_QA_RECEIPT_NAME);
  const receipt = JSON.parse(await readFile(receiptPath, "utf8"));
  update(receipt);
  const receiptBytes = await writeJson(receiptPath, receipt);
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  manifest.qa_receipt_sha256 = HASH(receiptBytes);
  await writeJson(manifestPath, manifest);
  return manifestPath;
}

async function resealFinalizedSnapshots(state, update) {
  // Rebind every dependent digest after tampering so the loader must reject broken joins/counts, not stale checksums.
  const snapshotPaths = {
    pre_source_stage_snapshot: path.join(state.outputRoot, "evidence/pre-source-stage-hashes.json"),
    post_source_stage_snapshot: path.join(state.outputRoot, "evidence/post-source-stage-hashes.json"),
  };
  const snapshotHashes = {};
  for (const [key, filePath] of Object.entries(snapshotPaths)) {
    const snapshot = JSON.parse(await readFile(filePath, "utf8"));
    update(snapshot, key);
    snapshotHashes[key] = HASH(await writeJson(filePath, snapshot));
  }

  const evidenceRoot = path.join(state.outputRoot, "evidence");
  const independentPath = path.join(evidenceRoot, "independent-capture-qa-receipt.json");
  const independent = JSON.parse(await readFile(independentPath, "utf8"));
  independent.snapshot_files.pre_source_stage_snapshot.sha256 = snapshotHashes.pre_source_stage_snapshot;
  independent.snapshot_files.post_source_stage_snapshot.sha256 = snapshotHashes.post_source_stage_snapshot;
  const independentHash = HASH(await writeJson(independentPath, independent));

  const approvalPath = path.join(evidenceRoot, "finalization-approval.json");
  const approval = JSON.parse(await readFile(approvalPath, "utf8"));
  approval.independent_receipt_sha256 = independentHash;
  const approvalHash = HASH(await writeJson(approvalPath, approval));

  const manifestPath = await rewriteFinalizedQaReceipt(state, (receipt) => {
    receipt.evidence_files.pre_source_stage_snapshot.sha256 = snapshotHashes.pre_source_stage_snapshot;
    receipt.evidence_files.post_source_stage_snapshot.sha256 = snapshotHashes.post_source_stage_snapshot;
    receipt.evidence_files.independent_receipt.sha256 = independentHash;
    receipt.evidence_files.finalization_approval.sha256 = approvalHash;
    receipt.source_stage_binding.source_snapshot_sha256.pre = snapshotHashes.pre_source_stage_snapshot;
    receipt.source_stage_binding.source_snapshot_sha256.post = snapshotHashes.post_source_stage_snapshot;
  });
  return manifestPath;
}

async function fixture(callback, revisionState = "dirty") {
  const dirty = revisionState === "dirty";
  const worktreeDescription = dirty
    ? "dirty; this is not a clean or final PR revision"
    : "clean; this is not a PR or release acceptance";
  const tempRoot = await mkdtemp(path.join(os.tmpdir(), "assistant-help-finalize-"));
  const evidenceRoot = path.join(tempRoot, "qa");
  const candidateRoot = path.join(evidenceRoot, "candidate");
  const outputRoot = path.join(tempRoot, "finalized");
  await mkdir(candidateRoot, { recursive: true, mode: 0o700 });
  try {
    const sourceHashes = await hashCaptureSources();
    const stageEquivalence = await computeServedExportEquivalence(sourceHashes);
    assert.equal(stageEquivalence.pass, true);
    const captures = {};
    const imageBytes = {};
    const imageAudit = {};
    const visualImages = [];
    for (const [index, id] of CAPTURE_IDS.entries()) {
      const spec = SPECS[id];
      const bytes = png(spec.dimensions.width, spec.dimensions.height, index + 1);
      const digest = HASH(bytes);
      const metadata = {
        file: spec.file,
        sha256: digest,
        revision: REVISION,
        route: spec.route,
        viewport: { ...spec.dimensions },
        image_dimensions: { ...spec.dimensions },
        theme: spec.theme,
        data: "synthetic",
        privacy_review: "pending",
      };
      captures[id] = metadata;
      imageBytes[id] = bytes;
      imageAudit[id] = {
        bytes: bytes.length,
        data: "synthetic",
        dimensions: { ...spec.dimensions },
        file: spec.file,
        route: spec.route,
        sha256: digest,
        theme: spec.theme,
      };
      visualImages.push({
        id,
        file: spec.file,
        sha256: digest,
        status: "Pass",
        privacy: "Pass: synthetic fixture content only; no private data visible.",
        visual: "Pass: target content is visible in the approved synthetic capture.",
      });
      await writeFile(path.join(candidateRoot, spec.file), bytes, { mode: 0o600 });
    }
    const manifest = {
      schema_version: 1,
      task: "R-ASTRA-120",
      revision: REVISION,
      qa_receipt_file: "assistant-help-qa-receipt.json",
      qa_receipt_sha256: "0".repeat(64),
      captures,
    };
    const runReceipt = {
      task: "R-ASTRA-120",
      status: "builder-candidate",
      revision: REVISION,
      revision_state: revisionState,
      source_sha256: sourceHashes,
      capture_sha256: Object.fromEntries(CAPTURE_IDS.map((id) => [id, captures[id].sha256])),
      capture_presentation: Object.fromEntries(
        ["action_preview", "action_receipt", "history_context"].map((id) => [id, {
          assistant_size: "expanded",
          viewport: { width: 1440, height: 1000 },
          panel_bounds: { x: 604, y: 64, width: 820, height: 920 },
        }]),
      ),
      fixture_lifecycle: {
        child_pid: 42,
        loopback_port: 41773,
        termination_signals: ["SIGTERM"],
        child_exit_code: null,
        child_exit_signal: "SIGTERM",
        process_exit_verified: true,
        loopback_port_released: true,
        runtime_directory_removed: true,
      },
    };
    const manifestBytes = await writeJson(path.join(candidateRoot, "assistant-help-captures.json"), manifest);
    const runReceiptBytes = await writeJson(path.join(candidateRoot, "assistant-help-capture-run.json"), runReceipt);

    const summaryTrees = Object.fromEntries(TREE_NAMES.map((name) => [name, {
      file_count: 1,
      sha256: HASH(Buffer.from(`tree:${name}`)),
    }]));
    const detailedTrees = Object.fromEntries(TREE_NAMES.map((name) => [name, {
      ...(name === "frontend_authored" ? { excluded_sensitive_filename_count: 0 } : {}),
      ...summaryTrees[name],
      files: {
        [`${name}/fixture.txt`]: {
          sha256: HASH(Buffer.from(`tree-file:${name}`)),
          size_bytes: Buffer.byteLength(`tree-file:${name}`),
        },
      },
    }]));
    const snapshots = {};
    for (const phase of ["pre", "post"]) {
      snapshots[phase] = {
        phase,
        recorded_utc: new Date().toISOString(),
        capture_source_file_count: CAPTURE_SOURCE_FILES.length,
        staged_capture_input_count: stageEquivalence.expected_served_files,
        capture_source_inputs: sourceHashes,
        capture_helper_hash_map: sourceHashes,
        canonical_and_independent_hashes_match: true,
        stage_equivalence: stageEquivalence,
        trees: detailedTrees,
        other_input_hashes: {},
      };
    }
    const visualReview = {
      schema_version: 1,
      review_scope: "Independent visual and privacy review of this actual eight-image capture candidate only.",
      overall: "Pass for per-image visual/privacy review scope",
      images: visualImages,
      privacy_boundary: "Only synthetic fixture data appears in these captures.",
      limitations: ["Synthetic test receipt fixture."],
    };
    const artifactIntegrity = {
      status: "Pass for structural/artifact/process integrity",
      candidate_status: "builder-candidate",
      candidate_manifest_status_preserved: "builder-candidate",
      approved_ids: CAPTURE_IDS,
      revision: REVISION,
      revision_state: revisionState,
      capture_command_exit_code: 0,
      capture_helper_invocation_count: 1,
      capture_count: 8,
      output_file_count: 10,
      prepost_canonical_capture_hashes_match: true,
      prepost_complete_source_stage_tree_hashes_match: true,
      prepost_stage_equivalence_pass: true,
      qa_receipt_sha256_is_pending: true,
      privacy_review_statuses: ["pending"],
      fixture_child_pid_absent_after_exit: true,
      fixture_port_bind_free_after_exit: true,
      helper_receipt_says_port_released: true,
      outer_process_group_gone: true,
      runtime_directory_removed: true,
      TMPDIR_empty_after_capture: true,
      captures: imageAudit,
    };
    const captureProcess = {
      argv: ["/usr/bin/timeout", "--signal=TERM", "--kill-after=15s", "180s", "/runtime/node/bin/node", "tools/assistant-help/capture.mjs", "--output-dir", CANDIDATE_RELATIVE_PATH],
      output_directory: CANDIDATE_RELATIVE_PATH,
      invocation_count: 1,
      exit_code: 0,
      owned_process_group_remaining_after_exit: false,
    };
    const cleanup = {
      status: "Pass",
      unexpected_entries_absent: true,
      root_removed: true,
      process_group_gone: true,
      fixture_pid_absent: true,
      port_rebind_check: "127.0.0.1:41773 bind succeeded after capture; socket closed",
    };
    const data = {
      "visual-review.json": visualReview,
      "artifact-integrity.json": artifactIntegrity,
      "pre-source-stage-hashes.json": snapshots.pre,
      "post-source-stage-hashes.json": snapshots.post,
      "capture-process.json": captureProcess,
      "owned-temp-cleanup.json": cleanup,
    };
    for (const [name, value] of Object.entries(data)) await writeJson(path.join(evidenceRoot, name), value);

    const snapshotPaths = Object.fromEntries(Object.entries(REVIEW_SNAPSHOT_BINDINGS)
      .map(([receiptKey, internalKey]) => [receiptKey, UPSTREAM_FILES[internalKey]]));
    const snapshotFiles = {};
    for (const [key, relative] of Object.entries(snapshotPaths)) {
      const internalKey = REVIEW_SNAPSHOT_BINDINGS[key];
      const bytes = internalKey === "candidate_manifest" ? manifestBytes
        : internalKey === "candidate_run_receipt" ? runReceiptBytes
          : await readFile(path.join(evidenceRoot, relative));
      snapshotFiles[key] = { path: relative, sha256: HASH(bytes) };
    }
    const qaReceipt = {
      schema_version: 1,
      task: "R-ASTRA-120 actual eight-capture independent QA",
      overall_status: "Pass for the declared capture, artifact integrity, visual, privacy, and cleanup scope only",
      recorded_at_utc: new Date().toISOString(),
      capture_window_utc: { start: new Date().toISOString(), end: new Date().toISOString() },
      capture_command: `TMPDIR=/tmp/assistant-help-fixture /usr/bin/timeout --signal=TERM --kill-after=15s 180s /runtime/node/bin/node tools/assistant-help/capture.mjs --output-dir ${CANDIDATE_RELATIVE_PATH}`,
      capture_invocation_count: 1,
      capture_exit_code: 0,
      bound: { branch: "codex/signal-ledger-assistant-r120", head: REVISION, worktree_state: worktreeDescription },
      environment: { architecture: "synthetic fixture" },
      checks: CHECK_NAMES.map((name) => ({ name, status: "Pass", evidence: "synthetic test fixture" })),
      pre_post_tree_hashes: summaryTrees,
      snapshot_files: snapshotFiles,
      limitations: ["Synthetic test fixture; no real independent review is claimed."],
    };
    const qaBytes = await writeJson(path.join(evidenceRoot, "independent-capture-qa-receipt.json"), qaReceipt);
    const approval = {
      schema_version: 1,
      task: "R-ASTRA-120",
      status: "approved-for-finalization",
      revision: REVISION,
      revision_state: revisionState,
      independent_receipt_sha256: HASH(qaBytes),
    };
    await writeJson(path.join(evidenceRoot, "finalization-approval.json"), approval);

    const originalFiles = await Promise.all([
      ...Object.values(SPECS).map((spec) => readFile(path.join(candidateRoot, spec.file))),
      readFile(path.join(candidateRoot, "assistant-help-captures.json")),
      readFile(path.join(candidateRoot, "assistant-help-capture-run.json")),
      readFile(path.join(evidenceRoot, "independent-capture-qa-receipt.json")),
      readFile(path.join(evidenceRoot, "visual-review.json")),
    ]);
    await callback({
      tempRoot,
      evidenceRoot,
      candidateRoot,
      outputRoot,
      sourceHashes,
      stageEquivalence,
      revision: REVISION,
      approval,
      qaBytes,
      manifest,
      imageBytes,
      async finalize(overrides = {}) {
        return finalizeCaptureBundle({
          evidenceRoot,
          candidateRoot,
          outputRoot,
          currentRevision: REVISION,
          currentDirty: dirty,
          currentSourceHashes: sourceHashes,
          ...overrides,
        });
      },
      async replaceEvidence(key, value) {
        const relative = UPSTREAM_FILES[key];
        if (!relative) throw new Error("test fixture evidence key is unsupported");
        await writeJson(path.join(evidenceRoot, relative), value);
        const updatedBytes = await readFile(path.join(evidenceRoot, relative));
        const receipt = JSON.parse(await readFile(path.join(evidenceRoot, "independent-capture-qa-receipt.json"), "utf8"));
        const receiptKey = Object.entries(REVIEW_SNAPSHOT_BINDINGS).find(([, internalKey]) => internalKey === key)?.[0];
        receipt.snapshot_files[receiptKey].sha256 = HASH(updatedBytes);
        const newQaBytes = await writeJson(path.join(evidenceRoot, "independent-capture-qa-receipt.json"), receipt);
        const nextApproval = { ...approval, independent_receipt_sha256: HASH(newQaBytes) };
        await writeJson(path.join(evidenceRoot, "finalization-approval.json"), nextApproval);
      },
      async assertOriginalsUnchanged() {
        const after = await Promise.all([
          ...Object.values(SPECS).map((spec) => readFile(path.join(candidateRoot, spec.file))),
          readFile(path.join(candidateRoot, "assistant-help-captures.json")),
          readFile(path.join(candidateRoot, "assistant-help-capture-run.json")),
          readFile(path.join(evidenceRoot, "independent-capture-qa-receipt.json")),
          readFile(path.join(evidenceRoot, "visual-review.json")),
        ]);
        assert.deepEqual(after.slice(0, originalFiles.length), originalFiles);
      },
    });
  } finally {
    await rm(tempRoot, { recursive: true, force: true });
  }
}

test("finalizer creates a new strict draft bundle and renderer verifies it", async () => {
  await fixture(async (state) => {
    await state.finalize();
    const manifestPath = path.join(state.outputRoot, FINAL_MANIFEST_NAME);
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    const qaReceipt = JSON.parse(await readFile(path.join(state.outputRoot, FINAL_QA_RECEIPT_NAME), "utf8"));
    assert.equal(manifest.revision, REVISION);
    assert.equal(manifest.qa_receipt_sha256, HASH(await readFile(path.join(state.outputRoot, FINAL_QA_RECEIPT_NAME))));
    assert.equal(qaReceipt.status, "Pass");
    assert.equal(qaReceipt.reviewer, "R-ASTRA-120 code-managed finalizer");
    assert.match(qaReceipt.reviewer_attribution, /does not name an individual reviewer/);
    assert.equal(qaReceipt.source_stage_binding.current_source_stage_match, true);
    assert.equal(qaReceipt.source_stage_binding.staged_capture_input_count, state.stageEquivalence.expected_served_files);
    assert.deepEqual(Object.keys(qaReceipt.source_stage_binding.tree_hashes), [
      "fastapi_served",
      "frontend_authored",
      "frontend_out",
    ]);
    assert.deepEqual(Object.keys(qaReceipt.source_stage_binding.tree_hashes.frontend_out), ["file_count", "sha256"]);
    assert.ok(Object.values(manifest.captures).every((capture) => capture.privacy_review === "passed"));
    const verified = await loadVerifiedCaptures({
      captureRoot: state.outputRoot,
      manifestPath,
      expectedRevision: REVISION,
      currentRevision: REVISION,
      approvedRoot: state.tempRoot,
    });
    assert.equal(verified.reviewer, "R-ASTRA-120 code-managed finalizer");
    assert.deepEqual(Object.keys(verified.captures), CAPTURE_IDS);
    await state.assertOriginalsUnchanged();
    await assert.rejects(state.finalize(), /already exists; refusing to overwrite/);
  });
});

test("served export comparison binds the exact current set and rejects omissions or byte drift", async () => {
  const sourceHashes = await hashCaptureSources();
  const current = await computeServedExportEquivalence(sourceHashes);
  const derivedServedFileCount = expectedServedFileCount(sourceHashes);
  assert.equal(current.pass, true);
  assert.equal(current.expected_served_files, derivedServedFileCount);
  assert.equal(current.staged_files, derivedServedFileCount);
  assert.deepEqual(current.missing, []);
  assert.deepEqual(current.extra, []);
  assert.deepEqual(current.byte_mismatches, []);
  assert.equal(stageEquivalenceMatchesCurrent(current, current), true);

  const stagedPath = Object.keys(sourceHashes).find((file) => file.startsWith(STAGED_PREFIX));
  const omitted = { ...sourceHashes };
  delete omitted[stagedPath];
  const missing = await computeServedExportEquivalence(omitted);
  assert.equal(missing.pass, false);
  assert.ok(missing.missing.length > 0);
  assert.equal(stageEquivalenceMatchesCurrent({ ...current, expected_served_files: derivedServedFileCount - 1 }, current), false);

  const drifted = { ...sourceHashes, [stagedPath]: HASH(Buffer.from("different staged bytes")) };
  const mismatch = await computeServedExportEquivalence(drifted);
  assert.equal(mismatch.pass, false);
  assert.ok(mismatch.byte_mismatches.includes(stagedPath.slice(STAGED_PREFIX.length).replace(/^/, "next/")));
});

test("finalizer rejects hash-resealed stage snapshots with missing or forged served paths", async () => {
  for (const mutation of [
    (snapshot) => {
      snapshot.stage_equivalence = {
        ...snapshot.stage_equivalence,
        pass: false,
        missing: ["next/tools/forged.html"],
      };
    },
    (snapshot) => {
      snapshot.stage_equivalence = {
        ...snapshot.stage_equivalence,
        pass: false,
        extra: ["next/unreviewed.js"],
      };
    },
  ]) {
    await fixture(async (state) => {
      const pre = JSON.parse(await readFile(path.join(state.evidenceRoot, UPSTREAM_FILES.pre_source_stage_snapshot), "utf8"));
      mutation(pre);
      await state.replaceEvidence("pre_source_stage_snapshot", pre);
      await assert.rejects(state.finalize(), /independent pre source\/stage snapshot/);
    });
  }
});

test("finalizer and loader accept the historical seven-field Next-only stage record", async () => {
  await fixture(async (state) => {
    const legacyStage = {
      pass: true,
      expected_served_files: state.stageEquivalence.expected_served_files - AUTHORED_STATIC_ASSETS.length,
      staged_files: state.stageEquivalence.staged_files - AUTHORED_STATIC_ASSETS.length,
      missing: [],
      extra: [],
      byte_mismatches: [],
      symlink_count: 0,
    };
    assert.equal(Object.keys(legacyStage).length, 7);
    for (const key of ["pre_source_stage_snapshot", "post_source_stage_snapshot"]) {
      const snapshot = JSON.parse(await readFile(path.join(state.evidenceRoot, UPSTREAM_FILES[key]), "utf8"));
      snapshot.staged_capture_input_count = legacyStage.expected_served_files;
      snapshot.stage_equivalence = legacyStage;
      await state.replaceEvidence(key, snapshot);
    }
    await state.finalize();
    const receiptPath = path.join(state.outputRoot, FINAL_QA_RECEIPT_NAME);
    const resealedManifest = await resealFinalizedSnapshots(state, (snapshot) => {
      snapshot.staged_capture_input_count = legacyStage.expected_served_files;
      snapshot.stage_equivalence = legacyStage;
    });
    const receipt = JSON.parse(await readFile(receiptPath, "utf8"));
    receipt.source_stage_binding.staged_capture_input_count = legacyStage.expected_served_files;
    receipt.source_stage_binding.stage_equivalence_sha256 = HASH(Buffer.from(stableJson(legacyStage)));
    await rewriteFinalizedQaReceipt(state, (current) => Object.assign(current, receipt));
    const verified = await loadVerifiedCaptures({
      captureRoot: state.outputRoot,
      manifestPath: resealedManifest,
      expectedRevision: REVISION,
      currentRevision: REVISION,
      approvedRoot: state.tempRoot,
    });
    assert.equal(verified.reviewer, "R-ASTRA-120 code-managed finalizer");
  });
});

test("strict finalized loader rejects unknown, missing, or changed producer tree bindings", async () => {
  const cases = [
    {
      name: "unknown tree",
      update(trees) { trees.retired_tree = { file_count: 1, sha256: HASH(Buffer.from("retired")) }; },
    },
    {
      name: "missing tree",
      update(trees) { delete trees.frontend_authored; },
    },
  ];
  for (const scenario of cases) {
    await fixture(async (state) => {
      await state.finalize();
      const manifestPath = await rewriteFinalizedQaReceipt(state, (receipt) => {
        scenario.update(receipt.source_stage_binding.tree_hashes);
      });
      await assert.rejects(loadVerifiedCaptures({
        captureRoot: state.outputRoot,
        manifestPath,
        expectedRevision: REVISION,
        currentRevision: REVISION,
        approvedRoot: state.tempRoot,
      }), /finalized source tree hashes has an unexpected shape/, scenario.name);
    });
  }

  await fixture(async (state) => {
    await state.finalize();
    const manifestPath = await rewriteFinalizedQaReceipt(state, (receipt) => {
      receipt.source_stage_binding.tree_hashes.frontend_out.sha256 = HASH(Buffer.from("changed tree digest"));
    });
    await assert.rejects(loadVerifiedCaptures({
      captureRoot: state.outputRoot,
      manifestPath,
      expectedRevision: REVISION,
      currentRevision: REVISION,
      approvedRoot: state.tempRoot,
    }), /invalid pre source\/stage binding/);
  });
});

test("strict finalized loader rejects inconsistent snapshot joins and source counts", async () => {
  await fixture(async (state) => {
    await state.finalize();
    const manifestPath = await resealFinalizedSnapshots(state, (snapshot, key) => {
      if (key === "pre_source_stage_snapshot") snapshot.capture_source_file_count += 1;
    });
    await assert.rejects(loadVerifiedCaptures({
      captureRoot: state.outputRoot,
      manifestPath,
      expectedRevision: REVISION,
      currentRevision: REVISION,
      approvedRoot: state.tempRoot,
    }), /invalid pre source\/stage binding/);
  });

  await fixture(async (state) => {
    await state.finalize();
    const manifestPath = await resealFinalizedSnapshots(state, (snapshot, key) => {
      if (key === "pre_source_stage_snapshot") {
        snapshot.trees.frontend_out.sha256 = HASH(Buffer.from("different joined snapshot tree"));
      }
    });
    await assert.rejects(loadVerifiedCaptures({
      captureRoot: state.outputRoot,
      manifestPath,
      expectedRevision: REVISION,
      currentRevision: REVISION,
      approvedRoot: state.tempRoot,
    }), /invalid pre source\/stage binding/);
  });
});

test("strict finalized loader rejects evidence changed outside its digest chain", async () => {
  await fixture(async (state) => {
    await state.finalize();
    const visualPath = path.join(state.outputRoot, "evidence/visual-review.json");
    await writeFile(visualPath, `${await readFile(visualPath, "utf8")} `);
    await assert.rejects(loadVerifiedCaptures({
      captureRoot: state.outputRoot,
      manifestPath: path.join(state.outputRoot, FINAL_MANIFEST_NAME),
      expectedRevision: REVISION,
      currentRevision: REVISION,
      approvedRoot: state.tempRoot,
    }), /finalized visual_review evidence SHA-256 does not match/);
  });
});

test("strict finalized loader rejects missing, stale, and different-image review digests", async () => {
  const cases = [
    {
      name: "missing",
      update(review) { delete review.images[0].sha256; },
      message: /unexpected shape/,
    },
    {
      name: "stale",
      update(review) { review.images[0].sha256 = HASH(Buffer.from("stale previously reviewed image")); },
      message: /SHA-256 does not match the exact desktop_light PNG bytes/,
    },
    {
      name: "different image",
      update(review, state) { review.images[0].sha256 = state.manifest.captures.desktop_dark.sha256; },
      message: /SHA-256 does not match the exact desktop_light PNG bytes/,
    },
  ];
  for (const scenario of cases) {
    await fixture(async (state) => {
      await state.finalize();
      const manifestPath = await rewriteFinalizedVisualReview(state, (review) => scenario.update(review, state));
      await assert.rejects(loadVerifiedCaptures({
        captureRoot: state.outputRoot,
        manifestPath,
        expectedRevision: REVISION,
        currentRevision: REVISION,
        approvedRoot: state.tempRoot,
      }), scenario.message, scenario.name);
    });
  }
});

test("finalizer accepts a clean exact capture revision while keeping its output a draft", async () => {
  await fixture(async (state) => {
    const result = await state.finalize();
    const manifest = JSON.parse(await readFile(path.join(state.outputRoot, FINAL_MANIFEST_NAME), "utf8"));
    const qaReceipt = JSON.parse(await readFile(path.join(state.outputRoot, FINAL_QA_RECEIPT_NAME), "utf8"));
    assert.equal(result.status, "draft");
    assert.equal(result.revision_state, "clean");
    assert.equal(manifest.revision, REVISION);
    assert.equal(qaReceipt.revision_state, "clean");
    assert.equal(qaReceipt.reviewer, "R-ASTRA-120 code-managed finalizer");
    assert.match(qaReceipt.reviewer_attribution, /does not name an individual reviewer/);
    const verified = await loadVerifiedCaptures({
      captureRoot: state.outputRoot,
      manifestPath: path.join(state.outputRoot, FINAL_MANIFEST_NAME),
      expectedRevision: REVISION,
      currentRevision: REVISION,
      approvedRoot: state.tempRoot,
    });
    assert.equal(verified.reviewer, "R-ASTRA-120 code-managed finalizer");
  }, "clean");
});

test("strict finalized loader rejects a changed source/stage equivalence digest", async () => {
  await fixture(async (state) => {
    await state.finalize();
    const receiptPath = path.join(state.outputRoot, FINAL_QA_RECEIPT_NAME);
    const manifestPath = path.join(state.outputRoot, FINAL_MANIFEST_NAME);
    const receipt = JSON.parse(await readFile(receiptPath, "utf8"));
    receipt.source_stage_binding.stage_equivalence_sha256 = "f".repeat(64);
    const receiptBytes = await writeJson(receiptPath, receipt);
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    manifest.qa_receipt_sha256 = HASH(receiptBytes);
    await writeJson(manifestPath, manifest);
    await assert.rejects(loadVerifiedCaptures({
      captureRoot: state.outputRoot,
      manifestPath,
      expectedRevision: REVISION,
      currentRevision: REVISION,
      approvedRoot: state.tempRoot,
    }), /pre\/post source and stage evidence differs/);
  });
});

test("finalizer refuses a mismatched receipt hash and revision", async () => {
  await fixture(async (state) => {
    await writeJson(path.join(state.evidenceRoot, "finalization-approval.json"), {
      ...state.approval,
      independent_receipt_sha256: "0".repeat(64),
    });
    await assert.rejects(
      state.finalize(),
      /independent capture QA receipt SHA-256 does not match/,
    );
    await assert.rejects(
      state.finalize({ currentRevision: "b".repeat(40) }),
      /must match the current Git worktree/,
    );
  });
});

test("finalizer refuses altered expanded capture geometry", async () => {
  await fixture(async (state) => {
    const runReceipt = JSON.parse(await readFile(
      path.join(state.candidateRoot, "assistant-help-capture-run.json"),
      "utf8",
    ));
    runReceipt.capture_presentation.action_receipt.panel_bounds.width = 799;
    await state.replaceEvidence("candidate_run_receipt", runReceipt);
    await assert.rejects(state.finalize(), /lacks approved expanded assistant geometry/);
  });
});

test("finalizer refuses a pending privacy decision and a missing independent receipt", async () => {
  await fixture(async (state) => {
    const review = JSON.parse(await readFile(path.join(state.evidenceRoot, "visual-review.json"), "utf8"));
    review.images[0].privacy = "Pending independent privacy review.";
    await state.replaceEvidence("visual_review", review);
    await assert.rejects(state.finalize(), /did not Pass for desktop_light/);
  });

  await fixture(async (state) => {
    await rm(path.join(state.evidenceRoot, "independent-capture-qa-receipt.json"));
    await assert.rejects(state.finalize(), /independent receipt SHA-256|ENOENT/);
  });
});

test("finalizer rejects missing, stale, and different-image visual review digests", async () => {
  await fixture(async (state) => {
    const review = JSON.parse(await readFile(path.join(state.evidenceRoot, "visual-review.json"), "utf8"));
    delete review.images[0].sha256;
    await state.replaceEvidence("visual_review", review);
    await assert.rejects(state.finalize(), /unexpected shape/);
  });

  await fixture(async (state) => {
    const review = JSON.parse(await readFile(path.join(state.evidenceRoot, "visual-review.json"), "utf8"));
    review.images[0].sha256 = HASH(png(1440, 1000, 99));
    await state.replaceEvidence("visual_review", review);
    await assert.rejects(state.finalize(), /SHA-256 does not match the exact desktop_light candidate PNG bytes/);
  });

  await fixture(async (state) => {
    const review = JSON.parse(await readFile(path.join(state.evidenceRoot, "visual-review.json"), "utf8"));
    review.images[0].sha256 = state.manifest.captures.desktop_dark.sha256;
    await state.replaceEvidence("visual_review", review);
    await assert.rejects(state.finalize(), /SHA-256 does not match the exact desktop_light candidate PNG bytes/);
  });
});

test("finalizer refuses modified or symlinked source images", async () => {
  await fixture(async (state) => {
    const capture = SPECS.desktop_light;
    await writeFile(path.join(state.candidateRoot, capture.file), png(1440, 1000, 99));
    await assert.rejects(state.finalize(), /SHA-256 differs from the exact candidate/);
  });

  await fixture(async (state) => {
    const capture = SPECS.desktop_light;
    const capturePath = path.join(state.candidateRoot, capture.file);
    const targetPath = path.join(state.candidateRoot, "linked-target.png");
    await writeFile(targetPath, state.imageBytes.desktop_light);
    await rm(capturePath);
    await symlink(targetPath, capturePath);
    await assert.rejects(state.finalize(), /bounded single-link regular file/);
  });
});

test("finalizer refuses current source/stage drift before creating output", async () => {
  await fixture(async (state) => {
    const drifted = { ...state.sourceHashes };
    const target = Object.keys(drifted).find((file) => file.startsWith(STAGED_PREFIX));
    drifted[target] = "f".repeat(64);
    await assert.rejects(
      state.finalize({ currentSourceHashes: drifted }),
      /current served files do not match the frontend export|current capture source\/stage inputs have drifted/,
    );
    await assert.rejects(
      readFile(path.join(state.outputRoot, FINAL_MANIFEST_NAME)),
      { code: "ENOENT" },
    );
  });
});
