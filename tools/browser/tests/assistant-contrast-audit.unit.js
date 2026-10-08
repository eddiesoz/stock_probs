"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { evaluateAssistantContrastAudit, parseRgb } = require("./assistant-contrast-audit");

function validSnapshot() {
  const opaque = "rgb(255, 255, 255)";
  const panel = "rgb(23, 38, 48)";
  const target = (role, key, foreground, background, elementToken = `${key}-element`) => ({
    role,
    key,
    elementToken,
    element: { tag: "span", classes: [] },
    textLength: 8,
    foreground,
    semanticKind: role,
    semanticBackgroundColor: background,
    semanticBackgroundImage: "none",
    ancestors: [
      { name: "text", kind: null, style: { opacity: "1", visibility: "visible", display: "block", backgroundColor: "rgba(0, 0, 0, 0)", backgroundImage: "none", mixBlendMode: "normal", backgroundBlendMode: "normal", filter: "none", backdropFilter: "none", clipPath: "none", maskImage: "none", textShadow: "none" } },
      { name: role, kind: role, style: { opacity: "1", visibility: "visible", display: "block", backgroundColor: background, backgroundImage: "none", mixBlendMode: "normal", backgroundBlendMode: "normal", filter: "none", backdropFilter: "none", clipPath: "none", maskImage: "none", textShadow: "none" } },
      { name: "panel", testId: "assistant-panel", kind: null, style: { opacity: "1", visibility: "visible", display: "flex", backgroundColor: panel, backgroundImage: "none", mixBlendMode: "normal", backgroundBlendMode: "normal", filter: "none", backdropFilter: "none", clipPath: "none", maskImage: "none", textShadow: "none" } },
      { name: "body", kind: null, style: { opacity: "1", visibility: "visible", display: "block", backgroundColor: "rgba(0, 0, 0, 0)", backgroundImage: "none", mixBlendMode: "normal", backgroundBlendMode: "normal", filter: "none", backdropFilter: "none", clipPath: "none", maskImage: "none", textShadow: "none" } },
      { name: "html", kind: null, style: { opacity: "1", visibility: "visible", display: "block", backgroundColor: "rgba(0, 0, 0, 0)", backgroundImage: "none", mixBlendMode: "normal", backgroundBlendMode: "normal", filter: "none", backdropFilter: "none", clipPath: "none", maskImage: "none", textShadow: "none" } },
    ],
    lines: [{
      rect: { left: 8, top: 8, right: 80, bottom: 24 },
      inViewport: true,
      clippingChecks: [{ ancestor: "panel", clipped: false }],
      hitPoints: [0.25, 0.5, 0.75].map((fraction) => ({ x: 8 + (72 * fraction), y: 16, targetOrDescendant: true, hitRelation: "target" })),
    }],
  });
  return {
    rawAxe: {
      counts: { violations: 0, incomplete: 1, passes: 11, inapplicable: 0 },
      violations: [],
      incomplete: [{ id: "color-contrast", nodes: [{
        target: ["#assistant-disclaimer"],
        any: [{ id: "color-contrast", data: { contrastRatio: 0, expectedContrastRatio: "4.5:1", messageKey: "elmPartiallyObscuring" }, message: "Element's background color could not be determined because it partially overlaps other elements" }],
        all: [],
        none: [],
        html: "<p id=assistant-disclaimer>",
      }] }],
    },
    rawNodeMappings: [{
      rule: "color-contrast",
      nodeIndex: 0,
      selectorIndex: 0,
      selector: "#assistant-disclaimer",
      matchCount: 1,
      roles: ["disclaimer"],
      measuredTargetKeys: ["assistant-disclaimer"],
      directTextOnly: true,
      elementToken: "assistant-disclaimer-element",
      recognized: true,
    }],
    targets: [
      target("readiness", "readiness-line", "rgb(23, 38, 48)", opaque),
      target("answer", "answer-line", "rgb(23, 38, 48)", opaque),
      target("disclaimer", "assistant-disclaimer", "rgb(80, 97, 109)", opaque, "assistant-disclaimer-element"),
    ],
  };
}

function zeroIncompleteSnapshot() {
  const snapshot = validSnapshot();
  snapshot.rawAxe.counts.incomplete = 0;
  snapshot.rawAxe.incomplete = [];
  snapshot.rawNodeMappings = [];
  return snapshot;
}

// Keep raw axe output intact; pixel measurements supplement it instead of rewriting its findings.
test("accepts measured text while retaining the exact raw axe incomplete node", () => {
  const snapshot = validSnapshot();
  const result = evaluateAssistantContrastAudit(snapshot);
  assert.equal(result.passed, true, JSON.stringify(result.issues));
  assert.deepEqual(result.rawAxeCounts, { violations: 0, incomplete: 1, passes: 11, inapplicable: 0 });
  assert.equal(snapshot.rawAxe.incomplete[0].nodes[0].target[0], "#assistant-disclaimer");
  assert.equal(result.roleCounts.readiness, 1);
  assert.equal(result.roleCounts.answer, 1);
  assert.equal(result.roleCounts.disclaimer, 1);
});

test("accepts zero raw axe incompletes while still measuring every required text target", () => {
  const snapshot = zeroIncompleteSnapshot();
  const result = evaluateAssistantContrastAudit(snapshot);
  assert.equal(result.passed, true, JSON.stringify(result.issues));
  assert.deepEqual(result.rawAxeCounts, { violations: 0, incomplete: 0, passes: 11, inapplicable: 0 });
  assert.deepEqual(result.roleCounts, { readiness: 1, answer: 1, disclaimer: 1 });
  assert.ok(snapshot.targets.every((target) => target.measuredContrast >= 4.5));
});

test("zero raw axe incompletes do not bypass target contrast failures", () => {
  const snapshot = zeroIncompleteSnapshot();
  snapshot.targets[1].foreground = "rgb(200, 200, 200)";
  const result = evaluateAssistantContrastAudit(snapshot);
  assert.equal(result.passed, false);
  assert.ok(result.issues.some((issue) => issue.code === "contrast-below-4.5" && issue.target === "answer-line"));
});

test("rejects percentage alpha instead of interpreting its number as unit alpha", () => {
  assert.equal(parseRgb("rgb(255 255 255 / 1%)"), null);
  assert.equal(parseRgb("rgba(255, 255, 255, 100%)"), null);
});

function liveStatusSnapshot() {
  const snapshot = validSnapshot();
  const target = {
    ...snapshot.targets[2],
    key: "live-status-line",
    elementToken: "live-status-element",
    element: { tag: "p", classes: ["assistant-module__fixture__liveStatus"] },
    role: "liveStatus",
    semanticKind: "liveStatus",
  };
  target.ancestors = target.ancestors.map((ancestor, index) => ({
    ...ancestor,
    kind: index === 2 ? "liveStatus" : null,
    testId: index === 2 ? "assistant-panel" : null,
    style: {
      ...ancestor.style,
      backgroundColor: index === 2 ? "rgb(255, 255, 255)" : index === 1 ? "rgba(0, 0, 0, 0)" : ancestor.style.backgroundColor,
    },
  }));
  target.semanticBackgroundColor = "rgb(255, 255, 255)";
  snapshot.targets.push(target);
  snapshot.rawAxe.incomplete[0].nodes[0].target = [".assistant-live-status"];
  snapshot.rawNodeMappings[0] = {
    ...snapshot.rawNodeMappings[0],
    selector: ".assistant-live-status",
    roles: ["liveStatus"],
    measuredTargetKeys: ["live-status-line"],
    elementToken: "live-status-element",
  };
  return snapshot;
}

const contextMetadataSelector = ".assistant-module__fixture__userMessage > small";

function contextMetadataSnapshot() {
  const snapshot = validSnapshot();
  const background = "rgb(248, 250, 251)";
  const transparent = "rgba(0, 0, 0, 0)";
  const style = (backgroundColor) => ({
    opacity: "1",
    visibility: "visible",
    display: "block",
    backgroundColor,
    backgroundImage: "none",
    mixBlendMode: "normal",
    backgroundBlendMode: "normal",
    filter: "none",
    backdropFilter: "none",
    clipPath: "none",
    maskImage: "none",
    textShadow: "none",
  });
  const target = {
    ...snapshot.targets[2],
    role: "contextMetadata",
    key: "context-metadata-text-1",
    elementToken: "context-metadata-small",
    element: { tag: "small", id: null, classes: [] },
    textLength: "Context snapshot: Overview".length,
    contextLabelKind: "contextSnapshot",
    foreground: "rgb(80, 97, 109)",
    semanticKind: "contextMetadata",
    semanticBackgroundColor: background,
    semanticBackgroundImage: "none",
    ancestors: [
      { name: "small", tag: "small", classes: [], kind: null, style: style(transparent) },
      {
        name: "assistant-module__fixture__userMessage",
        tag: "li",
        classes: ["assistant-module__fixture__userMessage"],
        kind: "contextMetadata",
        style: style(background),
      },
      { name: "assistant-module__fixture__messageList", tag: "ol", classes: ["assistant-module__fixture__messageList"], kind: null, style: style(transparent) },
      { name: "assistant-panel", tag: "section", classes: ["assistant-module__fixture__panel"], testId: "assistant-panel", kind: null, style: style("rgb(255, 255, 255)") },
      { name: "body", tag: "body", classes: [], kind: null, style: style(transparent) },
      { name: "html", tag: "html", classes: [], kind: null, style: style(transparent) },
    ],
    lines: [{
      rect: { left: 1020.47, top: 582.17, right: 1143.31, bottom: 601.17, width: 122.84, height: 19 },
      inViewport: true,
      clippingChecks: [{ ancestor: "assistant-panel", clipped: false }],
      hitPoints: [0.25, 0.5, 0.75].map((fraction) => ({
        x: 1020.47 + (122.84 * fraction),
        y: 591.67,
        targetOrDescendant: true,
        hitRelation: "target",
      })),
    }],
  };
  const secondTarget = {
    ...target,
    key: "context-metadata-text-2",
    textLength: "Overview".length,
    lines: [{
      ...target.lines[0],
      rect: { left: 1143.31, top: 582.17, right: 1204.39, bottom: 601.17, width: 61.08, height: 19 },
      hitPoints: [0.25, 0.5, 0.75].map((fraction) => ({
        x: 1143.31 + (61.08 * fraction),
        y: 591.67,
        targetOrDescendant: true,
        hitRelation: "target",
      })),
    }],
  };
  snapshot.targets.push(target, secondTarget);
  snapshot.rawAxe.incomplete[0].nodes[0].target = [contextMetadataSelector];
  snapshot.rawAxe.incomplete[0].nodes[0].html = "<small>Context snapshot: Overview</small>";
  snapshot.rawNodeMappings[0] = {
    rule: "color-contrast",
    nodeIndex: 0,
    selectorIndex: 0,
    selector: contextMetadataSelector,
    matchCount: 1,
    roles: ["contextMetadata"],
    measuredTargetKeys: [target.key, secondTarget.key],
    directTextOnly: true,
    elementToken: target.elementToken,
    recognized: true,
    selectorError: null,
  };
  return snapshot;
}

function contextMetadataTarget(snapshot) {
  return snapshot.targets.find((target) => target.role === "contextMetadata");
}

test("measures the exact user-message context label and retains the raw axe incomplete", () => {
  const snapshot = contextMetadataSnapshot();
  const rawIncompleteBefore = JSON.stringify(snapshot.rawAxe.incomplete);
  const result = evaluateAssistantContrastAudit(snapshot, { requiredRoles: ["contextMetadata"] });
  assert.equal(result.passed, true, JSON.stringify(result.issues));
  assert.deepEqual(snapshot.targets.filter((target) => target.role === "contextMetadata").map((target) => target.measuredContrast), [6.1307, 6.1307]);
  assert.equal(snapshot.rawAxe.incomplete[0].nodes[0].target[0], contextMetadataSelector);
  assert.equal(JSON.stringify(snapshot.rawAxe.incomplete), rawIncompleteBefore);
  assert.equal(result.roleCounts.contextMetadata, 2);
});

const contextMetadataNegativeFixtures = [
  ["ambiguous context-label selector", (snapshot) => {
    snapshot.rawNodeMappings[0].matchCount = 2;
    snapshot.rawNodeMappings[0].recognized = false;
  }, "unknown-raw-incomplete-target"],
  ["nested context-label text", (snapshot) => {
    snapshot.rawNodeMappings[0].directTextOnly = false;
    snapshot.rawNodeMappings[0].recognized = false;
  }, "unknown-raw-incomplete-target"],
  ["unrelated message parent", (snapshot) => {
    const parent = contextMetadataTarget(snapshot).ancestors.find((ancestor) => ancestor.kind === "contextMetadata");
    parent.classes = ["assistant-module__fixture__answerBlocks"];
  }, "context-metadata-parent-mismatch"],
  ["wrong context-label element", (snapshot) => {
    contextMetadataTarget(snapshot).element.tag = "span";
  }, "context-metadata-element-mismatch"],
  ["lookalike message parent class", (snapshot) => {
    const parent = contextMetadataTarget(snapshot).ancestors.find((ancestor) => ancestor.kind === "contextMetadata");
    parent.classes = ["assistant-module__fixture__other_userMessage"];
  }, "context-metadata-parent-mismatch"],
  ["unverified context label kind", (snapshot) => {
    contextMetadataTarget(snapshot).contextLabelKind = "messageText";
  }, "context-metadata-label-mismatch"],
  ["translucent context bubble", (snapshot) => {
    const target = contextMetadataTarget(snapshot);
    const parent = target.ancestors.find((ancestor) => ancestor.kind === "contextMetadata");
    parent.style.backgroundColor = "rgba(248, 250, 251, 0.5)";
    target.semanticBackgroundColor = parent.style.backgroundColor;
  }, "semantic-background-not-opaque-rgb"],
  ["low-contrast context label", (snapshot) => {
    contextMetadataTarget(snapshot).foreground = "rgb(200, 200, 200)";
  }, "contrast-below-4.5"],
  ["occluded context-label line", (snapshot) => {
    contextMetadataTarget(snapshot).lines[0].hitPoints[1].targetOrDescendant = false;
  }, "line-hit-point-occluded"],
];

for (const [name, corrupt, expectedIssue] of contextMetadataNegativeFixtures) {
  test(`fails closed for ${name}`, () => {
    const snapshot = contextMetadataSnapshot();
    corrupt(snapshot);
    const result = evaluateAssistantContrastAudit(snapshot, { requiredRoles: ["contextMetadata"] });
    assert.equal(result.passed, false);
    assert.ok(result.issues.some((issue) => issue.code === expectedIssue), JSON.stringify(result.issues));
  });
}

test("measures the bounded liveStatus target against its opaque panel background", () => {
  const result = evaluateAssistantContrastAudit(liveStatusSnapshot());
  assert.equal(result.passed, true, JSON.stringify(result.issues));
});

const negativeFixtures = [
  ["contrast below 4.5", (snapshot) => { snapshot.targets[0].foreground = "rgb(170, 170, 170)"; }, "contrast-below-4.5"],
  ["panel opacity", (snapshot) => { snapshot.targets[0].ancestors[2].style.opacity = "0.9"; }, "ancestor-opacity"],
  ["ancestor filter outside panel", (snapshot) => { snapshot.targets[0].ancestors[3].style.filter = "blur(1px)"; }, "ancestor-filter"],
  ["ancestor blend mode outside panel", (snapshot) => { snapshot.targets[0].ancestors[4].style.mixBlendMode = "multiply"; }, "ancestor-blend-mode"],
  ["gradient backgrounds", (snapshot) => { snapshot.targets[1].ancestors[2].style.backgroundImage = "linear-gradient(red, blue)"; }, "ancestor-background-image"],
  ["line occlusion", (snapshot) => { snapshot.targets[1].lines[0].hitPoints[1].targetOrDescendant = false; }, "line-hit-point-occluded"],
  ["ancestor-only hit points", (snapshot) => { snapshot.targets[1].lines[0].hitPoints[1].hitRelation = "ancestor"; }, "line-hit-point-occluded"],
  ["text clipping", (snapshot) => { snapshot.targets[1].lines[0].clippingChecks[0].clipped = true; }, "line-clipped"],
  ["percentage foreground alpha", (snapshot) => { snapshot.targets[2].foreground = "rgb(255 255 255 / 1%)"; }, "foreground-not-opaque-rgb"],
  ["percentage background alpha", (snapshot) => { snapshot.targets[2].semanticBackgroundColor = "rgba(255, 255, 255, 100%)"; }, "semantic-background-not-opaque-rgb"],
  ["unknown target role", (snapshot) => { snapshot.targets.push({ ...snapshot.targets[0], key: "mystery", role: "unknown" }); }, "unknown-target-role"],
  ["semantic color mismatch", (snapshot) => { snapshot.targets[2].semanticBackgroundColor = "rgb(250, 250, 250)"; }, "semantic-background-color-mismatch"],
  ["semantic color not nearest opaque", (snapshot) => { snapshot.targets[2].ancestors[1].style.backgroundColor = "rgb(250, 250, 250)"; }, "semantic-background-not-nearest-opaque-color"],
  ["liveStatus without its semantic panel", (snapshot) => {
    snapshot = Object.assign(snapshot, liveStatusSnapshot());
    snapshot.targets[3].ancestors[2].kind = "disclaimer";
  }, "semantic-background-ancestor-missing"],
  ["liveStatus without its exact component class", (snapshot) => {
    snapshot = Object.assign(snapshot, liveStatusSnapshot());
    snapshot.targets[3].element.classes = ["assistant-module__fixture__answerBlocks"];
  }, "live-status-component-class-missing"],
  ["selector matching multiple elements", (snapshot) => { snapshot.rawNodeMappings[0].matchCount = 2; }, "unknown-raw-incomplete-target"],
  ["ancestor/group mapping", (snapshot) => { snapshot.rawNodeMappings[0].directTextOnly = false; }, "unknown-raw-incomplete-target"],
  ["unrelated same-role measurement", (snapshot) => { snapshot.rawNodeMappings[0].measuredTargetKeys = ["answer-line"]; }, "unknown-raw-incomplete-target"],
  ["extra selector mapping", (snapshot) => { snapshot.rawNodeMappings[0].selector = "#other"; }, "raw-node-selector-mapping-mismatch"],
  ["unknown raw selector target", (snapshot) => {
    snapshot.rawAxe.incomplete[0].nodes[0].target = ["#missing"];
    snapshot.rawNodeMappings[0].selector = "#missing";
    snapshot.rawNodeMappings[0].recognized = false;
    snapshot.rawNodeMappings[0].matchCount = 0;
    snapshot.rawNodeMappings[0].measuredTargetKeys = [];
    snapshot.rawNodeMappings[0].elementToken = null;
    snapshot.rawNodeMappings[0].roles = [];
    snapshot.rawNodeMappings[0].directTextOnly = false;
  }, "unknown-raw-incomplete-target"],
];

for (const [name, corrupt, expectedIssue] of negativeFixtures) {
  test(`fails closed for ${name}`, () => {
    const snapshot = validSnapshot();
    corrupt(snapshot);
    const result = evaluateAssistantContrastAudit(snapshot);
    assert.equal(result.passed, false);
    assert.ok(result.issues.some((issue) => issue.code === expectedIssue), JSON.stringify(result.issues));
  });
}

test("fails closed for unexpected raw axe rules and checks", () => {
  const extraRule = validSnapshot();
  extraRule.rawAxe.incomplete.push({ id: "landmark-unique", nodes: [] });
  extraRule.rawAxe.counts.incomplete = 2;
  let result = evaluateAssistantContrastAudit(extraRule);
  assert.ok(result.issues.some((issue) => issue.code === "unexpected-raw-incomplete-rule"));

  const extraCheck = validSnapshot();
  extraCheck.rawAxe.incomplete[0].nodes[0].any.push({ id: "other-check", data: { messageKey: "other" }, message: "Other check" });
  result = evaluateAssistantContrastAudit(extraCheck);
  assert.ok(result.issues.some((issue) => issue.code === "unexpected-raw-incomplete-check"));

  const missingNodes = validSnapshot();
  missingNodes.rawAxe.incomplete[0].nodes = [];
  missingNodes.rawNodeMappings = [];
  result = evaluateAssistantContrastAudit(missingNodes);
  assert.ok(result.issues.some((issue) => issue.code === "raw-incomplete-nodes-missing"));
});

test("fails closed for inconsistent counts and additional raw axe nodes", () => {
  const countMismatch = zeroIncompleteSnapshot();
  countMismatch.rawAxe.counts.incomplete = 1;
  let result = evaluateAssistantContrastAudit(countMismatch);
  assert.ok(result.issues.some((issue) => issue.code === "raw-axe-incomplete-count-mismatch"));

  const negativeCount = zeroIncompleteSnapshot();
  negativeCount.rawAxe.counts.incomplete = -1;
  result = evaluateAssistantContrastAudit(negativeCount);
  assert.equal(result.passed, false);
  assert.ok(result.issues.some((issue) => issue.code === "raw-axe-incomplete-count-mismatch"));
  assert.ok(result.issues.some((issue) => issue.code === "unexpected-raw-axe-incomplete-count"));

  const extraNode = validSnapshot();
  extraNode.rawAxe.incomplete[0].nodes.push({
    target: ["#unknown-extra-node"],
    any: [],
    all: [],
    none: [],
    html: "<span>unknown</span>",
  });
  result = evaluateAssistantContrastAudit(extraNode);
  assert.ok(result.issues.some((issue) => issue.code === "raw-node-mapping-count-mismatch"));
  assert.ok(result.issues.some((issue) => issue.code === "raw-node-selector-mapping-mismatch"));
});
