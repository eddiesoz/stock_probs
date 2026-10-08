import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import { createRequire } from "node:module";
import { mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  APPROVED_CAPTURE_ROOT,
  APPROVED_FINALIZED_CAPTURE_ROOT,
  assertRunPreviewOutputAvailable,
  CAPTURE_IDS,
  computeServedExportEquivalence,
  CAPTURE_MANIFEST_NAME,
  CSS_PATH,
  HANDOFF_PATH,
  PDF_EXPORT_OPTIONS,
  OUTPUT_DIR,
  QA_RECEIPT_NAME,
  REPO_ROOT,
  TEMPLATE_PATH,
  normalizePdfPrintEmphasis,
  outputDirectoryForCaptureRoot,
  assertNoSecrets,
  captureMetadataSha256,
  loadVerifiedCaptures,
  parseArguments,
  renderGuideHtml,
  validateCaptureManifest,
  validateHandoff,
  validateLocalDocument,
  stageEquivalenceMatchesCurrent,
} from "../render.mjs";

const REVIEWED_REVISION = "a".repeat(40);
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const readJson = async (filePath) => JSON.parse(await readFile(filePath, "utf8"));
const STAGED_NEXT_PREFIX = "src/stock_probs/static/next/";
const AUTHORED_STATIC_ASSETS = Object.freeze([
  "src/stock_probs/static/app.css",
  "src/stock_probs/static/app.js",
  "src/stock_probs/static/theme.js",
  "src/stock_probs/static/favicon.svg",
]);
const expectedServedFileCount = (sourceHashes) => {
  assert.ok(AUTHORED_STATIC_ASSETS.every((file) => Object.hasOwn(sourceHashes, file)));
  const stagedNextCount = Object.keys(sourceHashes).filter((file) => file.startsWith(STAGED_NEXT_PREFIX)).length;
  return stagedNextCount + AUTHORED_STATIC_ASSETS.length;
};

function png(width, height, marker) {
  const bytes = Buffer.alloc(25, marker);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(bytes, 0);
  bytes.writeUInt32BE(13, 8);
  bytes.write("IHDR", 12, "ascii");
  bytes.writeUInt32BE(width, 16);
  bytes.writeUInt32BE(height, 20);
  return bytes;
}

function captureMetadata(id, bytes) {
  const mobile = id.startsWith("mobile_");
  const forecast = id === "forecast_sources";
  const dimensions = { width: mobile ? 390 : 1280, height: mobile ? 844 : 1000 };
  return {
    file: `r120-${id.replaceAll("_", "-")}.png`,
    sha256: sha256(bytes),
    revision: REVIEWED_REVISION,
    route: forecast ? "/tools/forecast" : "/tools/live-trading",
    viewport: dimensions,
    image_dimensions: dimensions,
    theme: id.endsWith("dark") ? "dark" : "light",
    data: "synthetic",
    privacy_review: "passed",
  };
}

async function withCaptureFixture(callback) {
  const root = await mkdtemp(path.join(os.tmpdir(), "assistant-help-captures-"));
  try {
    const captures = {};
    for (const [index, id] of CAPTURE_IDS.entries()) {
      const metadata = captureMetadata(id, png(
        id.startsWith("mobile_") ? 390 : 1280,
        id.startsWith("mobile_") ? 844 : 1000,
        index + 1,
      ));
      const bytes = png(metadata.image_dimensions.width, metadata.image_dimensions.height, index + 1);
      metadata.sha256 = sha256(bytes);
      captures[id] = metadata;
      await writeFile(path.join(root, metadata.file), bytes, { mode: 0o600 });
    }
    const receipt = {
      task: "R-ASTRA-120",
      status: "Pass",
      scope: "assistant-ui-captures",
      revision: REVIEWED_REVISION,
      reviewer: "LUNA MAX QA",
      capture_sha256: Object.fromEntries(CAPTURE_IDS.map((id) => [id, captures[id].sha256])),
      capture_metadata_sha256: captureMetadataSha256(captures),
    };
    const receiptBytes = Buffer.from(JSON.stringify(receipt));
    const manifest = {
      schema_version: 1,
      task: "R-ASTRA-120",
      revision: REVIEWED_REVISION,
      qa_receipt_file: QA_RECEIPT_NAME,
      qa_receipt_sha256: sha256(receiptBytes),
      captures,
    };
    await writeFile(path.join(root, QA_RECEIPT_NAME), receiptBytes, { mode: 0o600 });
    await writeFile(path.join(root, CAPTURE_MANIFEST_NAME), JSON.stringify(manifest), { mode: 0o600 });
    return await callback({
      root,
      manifest,
      receipt,
      manifestPath: path.join(root, CAPTURE_MANIFEST_NAME),
      async load(overrides = {}) {
        return loadVerifiedCaptures({
          captureRoot: root,
          manifestPath: path.join(root, CAPTURE_MANIFEST_NAME),
          expectedRevision: REVIEWED_REVISION,
          currentRevision: REVIEWED_REVISION,
          approvedRoot: os.tmpdir(),
          ...overrides,
        });
      },
    });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

test("approved handoff keeps the pre-release concept B guide scope", async () => {
  const handoff = await readJson(HANDOFF_PATH);
  assert.equal(validateHandoff(handoff), handoff);
  assert.throws(() => validateHandoff({ ...handoff, acceptance: true }), /does not authorize/);
  assert.throws(() => validateHandoff({ ...handoff, task: "other" }), /does not authorize/);
  assert.throws(() => validateHandoff({ ...handoff, arbitrary: "extra" }), /unexpected shape/);
});

test("capture manifest pins the exact eight screenshots, routes, layouts, and synthetic data", async () => {
  await withCaptureFixture(async ({ manifest }) => {
    const captures = validateCaptureManifest(manifest, REVIEWED_REVISION);
    assert.deepEqual(Object.keys(captures), [
      "desktop_light",
      "desktop_dark",
      "mobile_light",
      "mobile_dark",
      "forecast_sources",
      "action_preview",
      "action_receipt",
      "history_context",
    ]);
    assert.equal(captures.forecast_sources.route, "/tools/forecast");
    assert.equal(captures.mobile_dark.theme, "dark");
    assert.throws(
      () => validateCaptureManifest(manifest, "b".repeat(40)),
      /does not match the requested revision/,
    );
    assert.throws(
      () => validateCaptureManifest({ ...manifest, extra: true }, REVIEWED_REVISION),
      /unexpected shape/,
    );

    const wrongTheme = structuredClone(manifest);
    wrongTheme.captures.desktop_light.theme = "dark";
    assert.throws(() => validateCaptureManifest(wrongTheme, REVIEWED_REVISION), /route, theme, or data/);

    const privateData = structuredClone(manifest);
    privateData.captures.history_context.data = "owner-records";
    assert.throws(() => validateCaptureManifest(privateData, REVIEWED_REVISION), /route, theme, or data/);

    const unreviewed = structuredClone(manifest);
    unreviewed.captures.desktop_light.privacy_review = "pending";
    assert.throws(() => validateCaptureManifest(unreviewed, REVIEWED_REVISION), /private-data review/);

    const pathEscape = structuredClone(manifest);
    pathEscape.captures.desktop_light.file = "../../owner.png";
    assert.throws(() => validateCaptureManifest(pathEscape, REVIEWED_REVISION), /filename is not approved/);

    const repeatedFile = structuredClone(manifest);
    repeatedFile.captures.desktop_dark.file = repeatedFile.captures.desktop_light.file;
    assert.throws(() => validateCaptureManifest(repeatedFile, REVIEWED_REVISION), /filename is not approved/);
  });
});

test("served export validation accepts exact current and legacy records, rejecting forged subsets", async () => {
  const { hashCaptureSources } = await import("../capture.mjs");
  const sourceHashes = await hashCaptureSources();
  const current = await computeServedExportEquivalence(sourceHashes);
  const derivedServedFileCount = expectedServedFileCount(sourceHashes);
  assert.equal(current.pass, true);
  assert.equal(current.expected_served_files, derivedServedFileCount);
  assert.equal(current.staged_files, derivedServedFileCount);

  const legacy = {
    pass: true,
    expected_served_files: derivedServedFileCount - AUTHORED_STATIC_ASSETS.length,
    staged_files: derivedServedFileCount - AUTHORED_STATIC_ASSETS.length,
    missing: [],
    extra: [],
    byte_mismatches: [],
    symlink_count: 0,
  };
  assert.equal(Object.keys(legacy).length, 7);
  assert.equal(stageEquivalenceMatchesCurrent(legacy, current), true);
  assert.equal(stageEquivalenceMatchesCurrent({ ...legacy, expected_served_files: legacy.expected_served_files - 1 }, current), false);
  assert.equal(stageEquivalenceMatchesCurrent({ ...legacy, unknown: true }, current), false);
  const missingLegacyField = { ...legacy };
  delete missingLegacyField.extra;
  assert.equal(stageEquivalenceMatchesCurrent(missingLegacyField, current), false);

  const legacyWithStaticEvidence = {
    ...current,
    expected_served_files: legacy.expected_served_files,
    staged_files: legacy.staged_files,
  };
  assert.equal(stageEquivalenceMatchesCurrent(legacyWithStaticEvidence, current), true);
  const missingStaticAsset = { ...current, static_asset_matches: { ...current.static_asset_matches } };
  delete missingStaticAsset.static_asset_matches["app.css"];
  assert.equal(stageEquivalenceMatchesCurrent(missingStaticAsset, current), false);
  assert.equal(stageEquivalenceMatchesCurrent(legacy, {
    ...current,
    static_asset_matches: { ...current.static_asset_matches, "app.css": false },
  }), false);
  const missingCurrentStaticField = { ...current };
  delete missingCurrentStaticField.static_asset_matches;
  assert.equal(stageEquivalenceMatchesCurrent(legacy, missingCurrentStaticField), false);

  const missingSourceAsset = { ...sourceHashes };
  delete missingSourceAsset["src/stock_probs/static/app.css"];
  await assert.rejects(
    computeServedExportEquivalence(missingSourceAsset),
    /staged asset map is missing a fixed FastAPI static asset/,
  );

  const stagedPath = Object.keys(sourceHashes).find((file) => file.startsWith("src/stock_probs/static/next/"));
  const subset = { ...sourceHashes };
  delete subset[stagedPath];
  const mismatched = await computeServedExportEquivalence(subset);
  assert.equal(mismatched.pass, false);
  assert.ok(mismatched.missing.length > 0);
});

test("loader binds each PNG to its hash, pixels, independent QA receipt, and current revision", async () => {
  await withCaptureFixture(async ({ root, manifestPath, load }) => {
    const verified = await load();
    assert.equal(verified.revision, REVIEWED_REVISION);
    assert.equal(verified.reviewer, "LUNA MAX QA");
    assert.deepEqual(Object.keys(verified.captures), CAPTURE_IDS);
    assert.deepEqual(verified.captures.mobile_light.dimensions, { width: 390, height: 844 });
    assert.equal(verified.captures.mobile_light.bytes.length, 25);

    await assert.rejects(
      load({ currentRevision: "b".repeat(40) }),
      /does not match the current application revision/,
    );
    await assert.rejects(
      load({ manifestPath: path.join(root, "different.json") }),
      /fixed name inside the approved capture root/,
    );
    const receiptPath = path.join(root, QA_RECEIPT_NAME);
    await writeFile(receiptPath, JSON.stringify({ task: "R-ASTRA-120", status: "Fail" }));
    await assert.rejects(load(), /independent QA receipt SHA-256 does not match/);
  });
});

test("loader rejects changed screenshots and a mismatched reviewed screenshot digest", async () => {
  await withCaptureFixture(async ({ root, manifest, load }) => {
    const first = manifest.captures.desktop_light;
    await writeFile(path.join(root, first.file), png(1280, 1000, 99));
    await assert.rejects(load(), /desktop_light SHA-256 does not match/);
  });

  await withCaptureFixture(async ({ root, manifest, load }) => {
    const changed = structuredClone(manifest);
    changed.captures.desktop_light.image_dimensions.width = 1279;
    const receipt = {
      task: "R-ASTRA-120",
      status: "Pass",
      scope: "assistant-ui-captures",
      revision: REVIEWED_REVISION,
      reviewer: "LUNA MAX QA",
      capture_sha256: Object.fromEntries(CAPTURE_IDS.map((id) => [id, changed.captures[id].sha256])),
      capture_metadata_sha256: captureMetadataSha256(changed.captures),
    };
    const receiptBytes = Buffer.from(JSON.stringify(receipt));
    changed.qa_receipt_sha256 = sha256(receiptBytes);
    await writeFile(path.join(root, QA_RECEIPT_NAME), receiptBytes);
    await writeFile(path.join(root, CAPTURE_MANIFEST_NAME), JSON.stringify(changed));
    await assert.rejects(load(), /pixel dimensions do not match/);
  });
});

test("QA receipt binds the capture manifest metadata as well as screenshot bytes", async () => {
  await withCaptureFixture(async ({ root, manifest, load }) => {
    const changed = structuredClone(manifest);
    changed.captures.desktop_light.viewport.width = 1440;
    await writeFile(path.join(root, CAPTURE_MANIFEST_NAME), JSON.stringify(changed));
    await assert.rejects(load(), /independent QA receipt does not bind the capture metadata/);
  });
});

test("loader rejects arbitrary roots and symlinked screenshot files", async () => {
  await withCaptureFixture(async ({ root, load }) => {
    await assert.rejects(
      load({ approvedRoot: APPROVED_CAPTURE_ROOT }),
      /capture root must stay inside the R-ASTRA-120 independent browser QA artifact/,
    );

    const linkTarget = path.join(root, "linked-capture.png");
    const capturePath = path.join(root, "r120-desktop-light.png");
    const original = await readFile(capturePath);
    await rm(capturePath);
    await symlink(linkTarget, capturePath);
    await writeFile(linkTarget, original);
    await assert.rejects(load(), /desktop_light is not a bounded single-link regular file/);
  });
});

test("guide renders only verified local captures with usage, privacy, and recovery instructions", async () => {
  await withCaptureFixture(async ({ manifest, load }) => {
    const verified = await load();
    const template = await readFile(TEMPLATE_PATH, "utf8");
    const css = await readFile(CSS_PATH, "utf8");
    const html = renderGuideHtml(template, verified, css);
    assert.equal(validateLocalDocument(html, css), true);
    assert.equal((html.match(/<h1\b/g) ?? []).length, 1);
    assert.equal((html.match(/<img\b/g) ?? []).length, 8);
    assert.match(html, /src="data:image\/png;base64,/);
    assert.match(html, /Review the exact query and WebFetch URL/);
    assert.match(html, /complete HTTPS URL/);
    assert.match(html, /one-time confirmation phrase/);
    assert.match(html, /retrieved-at date/);
    assert.match(html, /safe-area spacing/);
    assert.match(html, /on-screen keyboard/);
    assert.match(html, /storage quota reached/i);
    assert.match(html, /not a physical phone capture/);
    assert.doesNotMatch(html, /\{\{(?:capture:|implementation_revision)/);
    assert.doesNotMatch(html, /<img\b[^>]*src="https?:/i);
    assert.doesNotMatch(css, /url\(\s*["']?https?:/i);
    assert.match(css, /min-height: 44px/);
    assert.match(css, /prefers-reduced-motion/);
    assert.match(css, /forced-colors/);
    assert.match(css, /@media print/);

    assert.throws(
      () => renderGuideHtml(template, { revision: REVIEWED_REVISION, captures: verified.captures }, css),
      /revision-bound verified captures/,
    );
  });
});

test("exported guide is self-contained with verified screenshots, trusted CSS, and labeled citation group", async () => {
  await withCaptureFixture(async ({ load }) => {
    const verified = await load();
    const template = await readFile(TEMPLATE_PATH, "utf8");
    const css = await readFile(CSS_PATH, "utf8");
    const html = renderGuideHtml(template, verified, css);

    assert.equal(validateLocalDocument(html, css), true);
    assert.ok(html.includes(`<style>${css}</style>`));
    assert.doesNotMatch(html, /<link\b/i);
    assert.doesNotMatch(html, /<script\b/i);
    assert.doesNotMatch(html, /<(?:iframe|object|embed|audio|video|source)\b/i);
    assert.doesNotMatch(css, /@import\b|url\s*\(/i);
    assert.match(
      html,
      /<div class="citation-example" role="group" aria-label="Illustrative citation labels">/,
    );

    const imageTags = [...html.matchAll(/<img\b[^>]*>/gi)].map(([tag]) => tag);
    assert.equal(imageTags.length, CAPTURE_IDS.length);
    assert.ok(imageTags.every((tag) => /\bsrc="data:image\/png;base64,[A-Za-z0-9+/]+={0,2}"/i.test(tag)));
    for (const capture of Object.values(verified.captures)) {
      const dataUri = `data:image/png;base64,${capture.bytes.toString("base64")}`;
      assert.ok(html.includes(`src="${dataUri}"`));
    }
    assert.match(html, /Example data is synthetic\./);
    assert.match(html, /not a physical phone capture/i);
    const heroMarkup = html.match(/<figure class="hero-art">([\s\S]*?)<\/figure>/)?.[1];
    assert.ok(heroMarkup, "the hero research illustration remains present");
    assert.doesNotMatch(heroMarkup, /<(?:svg|text)\b/i);
    assert.equal((heroMarkup.match(/<li>/g) ?? []).length, 4);
    for (const label of [
      "Page context",
      "Evidence",
      "Review",
      "Receipt",
      "References optional",
      "Attributed",
      "Explicit",
      "Saved",
    ]) {
      assert.match(heroMarkup, new RegExp(`>${label}<`));
    }
    assert.match(heroMarkup, /non-market illustration/i);
    assert.match(html, /<span class="draft-mark" aria-hidden="true"><\/span>/);
    assert.equal((html.match(/<span class="flow-arrow" aria-hidden="true"><\/span>/g) ?? []).length, 2);
    assert.match(html, /<span class="back-to-top-mark" aria-hidden="true"><\/span>/);
    assert.doesNotMatch(html, /[●→↑]/u);
    assert.match(css, /\.draft-mark \{[^}]*background: var\(--warn\)/);
    assert.match(css, /\.flow-arrow::after/);
    assert.match(css, /\.back-to-top-mark::before/);
    assert.doesNotMatch(html, new RegExp(REVIEWED_REVISION));
    assert.doesNotMatch(html, /\{\{(?:capture:|implementation_revision|guide_css)/);

    assert.throws(
      () => renderGuideHtml(template, verified, `${css}\n</style><script>unsafe</script>`),
      /unsafe closing-style sequence/,
    );
  });
});

test("capture copy distinguishes a handed-off action from a completed change and labels synthetic mobile examples", async () => {
  await withCaptureFixture(async ({ load }) => {
    const verified = await load();
    const template = await readFile(TEMPLATE_PATH, "utf8");
    const css = await readFile(CSS_PATH, "utf8");
    const html = renderGuideHtml(template, verified, css);

    assert.equal(validateLocalDocument(html, css), true);
    assert.match(html, /Workspace action[^<]*handed off after confirmation/i);
    assert.match(html, /browser marks the action handed off/i);
    assert.match(html, /workspace change is not shown as complete/i);
    assert.doesNotMatch(html, /workspace change (?:is|was) (?:complete|applied)/i);
    assert.doesNotMatch(html, /completed workspace-action receipt/i);

    assert.match(html, /current page route is always included/i);
    assert.match(html, /route always shared, references optional/i);
    assert.match(html, /references optional/i);
    assert.match(html, /portfolio and watchlist/i);
    assert.match(html, /change a holding quantity/i);
    assert.match(html, /confirmed new forecast request saves a new forecast/i);
    assert.match(html, /immutable saved record without calling the model again/i);
    assert.match(html, /recording an outcome appends an observation/i);
    assert.match(html, /fresh historical reconstruction saves a separate analysis/i);
    assert.match(html, /protected invitation settings/i);
    assert.match(html, /does not create or send an invitation in chat/i);
    assert.match(html, /administrator TOTP verification/i);
    assert.match(html, /secure form checks it again/i);
    assert.match(html, /never paste invitation codes in chat/i);

    assert.match(html, /running application with example accounts, conversations, forecasts, and sources/i);
    assert.match(html, /mobile views use viewport emulation/i);
    assert.match(html, /emulated[- ]mobile/i);
    assert.match(html, /example data is synthetic/i);
    assert.match(html, /not a physical-phone capture/i);
    assert.doesNotMatch(html, /full browser suite|release acceptance|release accepted|production accepted/i);
    assert.doesNotMatch(html, /independently reviewed as a scoped capture set|scoped visual review|passing independent browser QA run|QA receipt/i);
    assert.doesNotMatch(html, /capture revision:/i);
    assert.doesNotMatch(html, new RegExp(REVIEWED_REVISION));
  });
});

test("print action layout keeps paragraphs intact and allows only the second capture to force a page", async () => {
  const css = await readFile(CSS_PATH, "utf8");
  const browserRequire = createRequire(path.join(REPO_ROOT, "tools/browser/package.json"));
  const { chromium } = browserRequire("playwright");
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <style>${css}</style>
      <main>
        <section id="actions" class="guide-section">
          <div class="section-body">
            <p id="action-copy">Confirming an administrator invitation handoff requires recent TOTP verification, and the secure form checks it again when you create or send.</p>
            <div id="action-captures" class="capture-pair action-captures">
              <figure id="action-preview" class="capture"><figcaption>Preview</figcaption></figure>
              <figure id="action-receipt" class="capture"><figcaption>Receipt</figcaption></figure>
            </div>
          </div>
        </section>
      </main>
    `);

    const readPrintBreaks = () => page.evaluate(() => {
      const get = (selector, property) => getComputedStyle(document.querySelector(selector)).getPropertyValue(property);
      return {
        paragraph: get("#action-copy", "break-inside"),
        captures: get("#action-captures", "break-before"),
        firstCapture: get("#action-preview", "break-before"),
        secondCapture: get("#action-receipt", "break-before"),
      };
    });

    await page.emulateMedia({ media: "screen" });
    assert.deepEqual(await readPrintBreaks(), {
      paragraph: "auto",
      captures: "auto",
      firstCapture: "auto",
      secondCapture: "auto",
    });

    await page.emulateMedia({ media: "print" });
    assert.deepEqual(await readPrintBreaks(), {
      paragraph: "avoid",
      captures: "auto",
      firstCapture: "auto",
      secondCapture: "page",
    });
  } finally {
    await browser.close();
  }
});

test("pinned Chromium emits a tagged PDF with a document outline", async () => {
  assert.equal(PDF_EXPORT_OPTIONS.tagged, true);
  assert.equal(PDF_EXPORT_OPTIONS.outline, true);
  assert.match(PDF_EXPORT_OPTIONS.footerTemplate, /pageNumber/);
  assert.match(PDF_EXPORT_OPTIONS.footerTemplate, /totalPages/);
  const browserRequire = createRequire(path.join(REPO_ROOT, "tools/browser/package.json"));
  const { chromium } = browserRequire("playwright");
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <style>
        .callout strong { color: rgb(23, 38, 48); font-size: 19px; letter-spacing: .02em; line-height: 1.25; }
      </style>
      <main>
        <h1>Assistant help</h1><h2>Privacy</h2>
        <p class="callout"><strong id="emphasis" aria-label="Important">Readable text.</strong></p>
        <figure><img alt="A diagram description" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10'%3E%3Crect width='10' height='10' fill='teal'/%3E%3C/svg%3E"></figure>
      </main>
    `);
    await page.locator("img").evaluate((image) => image.decode());
    await page.emulateMedia({ media: "print" });
    const before = await page.locator("strong").evaluate((element) => {
      const style = getComputedStyle(element);
      return Object.fromEntries(["color", "font-size", "font-weight", "letter-spacing", "line-height"].map(
        (property) => [property, style.getPropertyValue(property)],
      ));
    });
    assert.equal(await normalizePdfPrintEmphasis(page), 1);
    const normalized = await page.locator("span#emphasis").evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        attributes: [...element.attributes].map(({ name, value }) => [name, value]),
        styles: Object.fromEntries(["color", "font-size", "font-weight", "letter-spacing", "line-height"].map(
          (property) => [property, style.getPropertyValue(property)],
        )),
        text: element.textContent,
        imageAlt: document.querySelector("figure img")?.alt,
      };
    });
    assert.deepEqual(normalized.styles, before);
    assert.deepEqual(normalized.attributes.slice(0, 2), [["id", "emphasis"], ["aria-label", "Important"]]);
    assert.equal(normalized.attributes[2]?.[0], "style");
    assert.equal(normalized.text, "Readable text.");
    assert.equal(normalized.imageAlt, "A diagram description");
    assert.equal(await page.locator("strong").count(), 0);
    const pdf = await page.pdf(PDF_EXPORT_OPTIONS);
    const source = pdf.toString("latin1");
    assert.equal(pdf.subarray(0, 5).toString("ascii"), "%PDF-");
    assert.ok(source.includes("/MarkInfo"));
    assert.ok(source.includes("/StructTreeRoot"));
    assert.ok(source.includes("/Outlines"));
    assert.ok(source.includes("/Document"));
    assert.ok(source.includes("/H1"));
    assert.ok(source.includes("/H2"));
    assert.ok(source.includes("/P"));
    assert.ok(source.includes("/Figure"));
    assert.ok(source.includes("/Alt"));
    assert.ok(source.includes("/NonStruct"));
    assert.ok(source.includes("A diagram description"));
    assert.doesNotMatch(source, /\/Strong\b/);
  } finally {
    await browser.close();
  }
});

test("capture CLI requires only explicit bounded inputs", () => {
  const browserRoot = "test-results/r-astra-120-independent-ui-qa-final/browser";
  const manifest = `${browserRoot}/assistant-help-captures.json`;
  assert.deepEqual(parseArguments([
    "--capture-root", browserRoot,
    "--manifest", manifest,
    "--revision", REVIEWED_REVISION,
  ]), {
    captureRoot: path.join(REPO_ROOT, browserRoot),
    manifestPath: path.join(REPO_ROOT, manifest),
    revision: REVIEWED_REVISION,
  });
  assert.deepEqual(parseArguments([
    "--capture-root", path.join(REPO_ROOT, browserRoot),
    "--manifest", path.join(REPO_ROOT, manifest),
    "--revision", REVIEWED_REVISION,
  ]), {
    captureRoot: path.join(REPO_ROOT, browserRoot),
    manifestPath: path.join(REPO_ROOT, manifest),
    revision: REVIEWED_REVISION,
  });
  assert.throws(() => parseArguments([]), /Usage:/);
  assert.throws(() => parseArguments(["--capture-root", "/tmp/private"]), /Usage:/);
  assert.throws(() => parseArguments([
    "--capture-root", "a", "--manifest", "b", "--revision", REVIEWED_REVISION, "--output", "c",
  ]), /Usage:/);
  assert.throws(() => parseArguments([
    "--capture-root", `${REPO_ROOT}/${browserRoot}/../browser`,
    "--manifest", manifest,
    "--revision", REVIEWED_REVISION,
  ]), /parent traversal/);
  assert.throws(() => parseArguments([
    "--capture-root", browserRoot,
    "--manifest", `${REPO_ROOT}/${browserRoot}/../browser/assistant-help-captures.json`,
    "--revision", REVIEWED_REVISION,
  ]), /parent traversal/);
});

test("renderer isolates canonical same-day run previews and rejects unsafe roots", async () => {
  const today = new Date().toISOString().slice(0, 10).replaceAll("-", "");
  const runIds = [randomBytes(6).toString("hex"), randomBytes(6).toString("hex")];
  const futureDate = new Date();
  futureDate.setUTCDate(futureDate.getUTCDate() + 1);
  const futureDateStamp = futureDate.toISOString().slice(0, 10).replaceAll("-", "");
  const taskRoots = runIds.map((runId) =>
    `test-results/assistant-r120/help-current-captures-${today}-${runId}`);
  const finalizedRoots = taskRoots.map((taskRoot) => path.join(REPO_ROOT, taskRoot, "finalized"));
  const previews = finalizedRoots.map((root) => path.join(path.dirname(root), "preview"));

  assert.notEqual(previews[0], previews[1]);
  assert.equal(outputDirectoryForCaptureRoot(APPROVED_FINALIZED_CAPTURE_ROOT), OUTPUT_DIR);
  assert.equal(outputDirectoryForCaptureRoot(APPROVED_CAPTURE_ROOT), OUTPUT_DIR);
  assert.equal(outputDirectoryForCaptureRoot(finalizedRoots[0]), previews[0]);
  assert.equal(outputDirectoryForCaptureRoot(finalizedRoots[1]), previews[1]);

  const malformedRoots = [
    `${finalizedRoots[0]}-extra`,
    path.join(REPO_ROOT, `test-results/assistant-r120/help-current-captures-${today}-ABCDEF123456/finalized`),
    path.join(REPO_ROOT, `test-results/assistant-r120/help-current-captures-20260230-${runIds[0]}/finalized`),
    path.join(REPO_ROOT, `test-results/assistant-r120/help-current-captures-${futureDateStamp}-${runIds[0]}/finalized`),
    `${finalizedRoots[0]}/../finalized`,
    path.join(REPO_ROOT, `test-results/assistant-r120/help-current-captures-${today}-abcdef12345/finalized`),
  ];
  for (const root of malformedRoots) {
    assert.throws(() => outputDirectoryForCaptureRoot(root), /parent traversal|canonical/);
  }

  const validTaskRoot = path.join(REPO_ROOT, taskRoots[0]);
  const validFinalizedRoot = finalizedRoots[0];
  await mkdir(validTaskRoot, { mode: 0o700 });
  await mkdir(validFinalizedRoot, { mode: 0o700 });
  try {
    assert.equal(await assertRunPreviewOutputAvailable(validFinalizedRoot), previews[0]);
    await mkdir(previews[0], { mode: 0o700 });
    const retainedPreviewFile = path.join(previews[0], "existing-output.txt");
    await writeFile(retainedPreviewFile, "retain existing preview", { flag: "wx", mode: 0o600 });
    await assert.rejects(
      assertRunPreviewOutputAvailable(validFinalizedRoot),
      /already exists; refusing to overwrite/,
    );
    assert.equal(await readFile(retainedPreviewFile, "utf8"), "retain existing preview");
    await assert.rejects(loadVerifiedCaptures({
      captureRoot: validFinalizedRoot,
      manifestPath: path.join(validFinalizedRoot, CAPTURE_MANIFEST_NAME),
      expectedRevision: REVIEWED_REVISION,
      currentRevision: REVIEWED_REVISION,
    }), (error) => error.code === "ENOENT");
  } finally {
    await rm(validTaskRoot, { recursive: true, force: true });
  }

  const symlinkTaskRoot = path.join(REPO_ROOT,
    `test-results/assistant-r120/help-current-captures-${today}-${randomBytes(6).toString("hex")}`);
  const symlinkTarget = await mkdtemp(path.join(os.tmpdir(), "assistant-help-run-root-"));
  await mkdir(path.join(symlinkTarget, "finalized"), { mode: 0o700 });
  await symlink(symlinkTarget, symlinkTaskRoot, "dir");
  try {
    const symlinkFinalizedRoot = path.join(symlinkTaskRoot, "finalized");
    await assert.rejects(loadVerifiedCaptures({
      captureRoot: symlinkFinalizedRoot,
      manifestPath: path.join(symlinkFinalizedRoot, CAPTURE_MANIFEST_NAME),
      expectedRevision: REVIEWED_REVISION,
      currentRevision: REVIEWED_REVISION,
    }), /real directory without symlink traversal/);
  } finally {
    await rm(symlinkTaskRoot, { recursive: true, force: true });
    await rm(symlinkTarget, { recursive: true, force: true });
  }
});

test("document policy rejects executable, remote, and secret-like content", () => {
  const protocolRelativeCss = "body { background-image: url(//example.test/image.png); }";
  assert.throws(() => validateLocalDocument(
    `<style>${protocolRelativeCss}</style><main id="main-content"><h1>Guide</h1></main>`,
    protocolRelativeCss,
  ), /executable or remote content/);
  assert.throws(() => validateLocalDocument(
    '<main id="main-content"><h1>Guide</h1><img alt="x" src="https://example.test/a.png"></main>',
    "body{}",
  ), /remote content|remote asset/);
  assert.throws(() => validateLocalDocument(
    '<main id="main-content"><h1>Guide</h1><script>fetch(1)</script></main>',
    "body{}",
  ), /executable or remote content/);
  assert.throws(() => assertNoSecrets("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123"), /secret-like/);
  assert.throws(() => assertNoSecrets("owner@example.test"), /secret-like/);
  assert.equal(assertNoSecrets("Synthetic demonstration data only."), "Synthetic demonstration data only.");
});
