"use strict";

const REQUIRED_ROLES = ["readiness", "answer", "disclaimer"];
const AUDITABLE_ROLES = [...REQUIRED_ROLES, "liveStatus"];

function parseRgb(value) {
  if (typeof value !== "string") return null;
  if (value.trim().toLowerCase() === "transparent") return { red: 0, green: 0, blue: 0, alpha: 0 };
  const match = value.match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+)(%)?)?\s*\)$/i);
  if (!match) return null;
  if (match[5] === "%") return null;
  const channels = match.slice(1, 4).map(Number);
  const alpha = match[4] === undefined ? 1 : Number(match[4]);
  if (channels.some((channel) => !Number.isFinite(channel) || channel < 0 || channel > 255)
      || !Number.isFinite(alpha) || alpha < 0 || alpha > 1) return null;
  return { red: channels[0], green: channels[1], blue: channels[2], alpha };
}

function luminance(color) {
  const linear = [color.red, color.green, color.blue].map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return (0.2126 * linear[0]) + (0.7152 * linear[1]) + (0.0722 * linear[2]);
}

function calculateContrast(foreground, background) {
  const left = luminance(foreground);
  const right = luminance(background);
  return (Math.max(left, right) + 0.05) / (Math.min(left, right) + 0.05);
}

function evaluateAssistantContrastAudit(snapshot, { requiredRoles = snapshot?.requiredRoles ?? REQUIRED_ROLES } = {}) {
  const issues = [];
  const add = (code, target = null, details = null) => issues.push({ code, target, details });
  if (!Array.isArray(requiredRoles) || requiredRoles.some((role) => !AUDITABLE_ROLES.includes(role))) {
    add("unknown-required-role", null, { requiredRoles });
    requiredRoles = [];
  }
  const rawAxe = snapshot?.rawAxe;
  const counts = rawAxe?.counts;
  if (!counts || !Number.isSafeInteger(counts.violations) || !Number.isSafeInteger(counts.incomplete)) {
    add("raw-axe-counts-missing");
  } else {
    if (counts.violations !== (rawAxe.violations || []).length) add("raw-axe-violation-count-mismatch");
    if (counts.incomplete !== (rawAxe.incomplete || []).length) add("raw-axe-incomplete-count-mismatch");
    if (counts.violations !== 0) add("axe-violations-present", null, { count: counts.violations });
    if (![0, 1].includes(counts.incomplete)) add("unexpected-raw-axe-incomplete-count", null, { expected: [0, 1], actual: counts.incomplete });
  }

  const targets = Array.isArray(snapshot?.targets) ? snapshot.targets : [];
  const roleCounts = Object.fromEntries(requiredRoles.map((role) => [role, 0]));
  for (const target of targets) {
    if (!target || !AUDITABLE_ROLES.includes(target.role)) {
      add("unknown-target-role", target?.key ?? null, { role: target?.role ?? null });
      continue;
    }
    roleCounts[target.role] += 1;
    auditTarget(target, add);
  }
  for (const role of requiredRoles) {
    if (roleCounts[role] === 0) add("required-target-missing", role);
  }

  const mappings = Array.isArray(snapshot?.rawNodeMappings) ? snapshot.rawNodeMappings : [];
  const expectedMappings = [];
  for (const rule of rawAxe?.incomplete || []) {
    if (rule.id !== "color-contrast") add("unexpected-raw-incomplete-rule", rule.id, { expected: "color-contrast" });
    if (!Array.isArray(rule.nodes) || rule.nodes.length === 0) add("raw-incomplete-nodes-missing", rule.id);
    for (const [nodeIndex, node] of (rule.nodes || []).entries()) {
      const selectors = Array.isArray(node.target) ? node.target : [];
      if (selectors.length === 0) expectedMappings.push({ rule: rule.id, nodeIndex, selectorIndex: null, selector: null });
      selectors.forEach((selector, selectorIndex) => expectedMappings.push({
        rule: rule.id,
        nodeIndex,
        selectorIndex,
        selector,
      }));
      const exactCheck = node.any?.length === 1
        && node.any[0]?.id === "color-contrast"
        && node.any[0]?.data?.messageKey === "elmPartiallyObscuring"
        && node.any[0]?.data?.contrastRatio === 0
        && node.any[0]?.data?.expectedContrastRatio === "4.5:1"
        && node.any[0]?.message === "Element's background color could not be determined because it partially overlaps other elements"
        && node.all?.length === 0
        && node.none?.length === 0;
      if (!exactCheck) add("unexpected-raw-incomplete-check", `${rule.id}:${nodeIndex}`, {
        any: node.any,
        all: node.all,
        none: node.none,
      });
    }
  }
  if (mappings.length !== expectedMappings.length) add("raw-node-mapping-count-mismatch", null, {
    mapped: mappings.length,
    rawSelectors: expectedMappings.length,
  });
  const measuredByKey = new Map(targets.map((target) => [target.key, target]));
  const mappingKeys = mappings.map((mapping) => `${mapping?.rule}:${mapping?.nodeIndex}:${mapping?.selectorIndex}`);
  if (new Set(mappingKeys).size !== mappingKeys.length) add("duplicate-raw-node-mapping", null, { mappingKeys });
  for (const expected of expectedMappings) {
    const mapping = mappings.find((candidate) => candidate?.rule === expected.rule
      && candidate?.nodeIndex === expected.nodeIndex
      && candidate?.selectorIndex === expected.selectorIndex);
    if (!mapping || mapping.selector !== expected.selector) {
      add("raw-node-selector-mapping-mismatch", expected.selector, { expected, actual: mapping ?? null });
      continue;
    }
    const roles = Array.isArray(mapping?.roles) ? mapping.roles : [];
    const measuredKeys = Array.isArray(mapping?.measuredTargetKeys) ? mapping.measuredTargetKeys : [];
    const measuredTargets = measuredKeys.map((key) => measuredByKey.get(key));
    if (!mapping || mapping.recognized !== true || mapping.matchCount !== 1 || mapping.directTextOnly !== true
        || roles.length !== 1 || !AUDITABLE_ROLES.includes(roles[0]) || measuredTargets.length === 0
        || !mapping.elementToken
        || new Set(measuredKeys).size !== measuredKeys.length
        || measuredTargets.some((target) => !target || target.role !== roles[0] || target.elementToken !== mapping.elementToken)) {
      add("unknown-raw-incomplete-target", mapping?.selector ?? null, mapping ?? null);
    }
  }
  return { passed: issues.length === 0, issues, roleCounts, rawAxeCounts: counts ?? null };
}

function auditTarget(target, add) {
  const key = target.key;
  const foreground = parseRgb(target.foreground);
  const background = parseRgb(target.semanticBackgroundColor);
  if (!foreground || foreground.alpha !== 1) add("foreground-not-opaque-rgb", key, { value: target.foreground });
  if (!background || background.alpha !== 1) add("semantic-background-not-opaque-rgb", key, { value: target.semanticBackgroundColor });
  if (target.semanticBackgroundImage !== "none") add("semantic-background-image", key, { value: target.semanticBackgroundImage });
  if (target.semanticKind !== target.role) add("unexpected-semantic-background", key, {
    expected: target.role,
    actual: target.semanticKind,
  });

  const ancestors = Array.isArray(target.ancestors) ? target.ancestors : [];
  const semanticAncestor = ancestors.find((ancestor) => ancestor.kind === target.role);
  if (!semanticAncestor) add("semantic-background-ancestor-missing", key, { expected: target.role });
  if (target.role === "liveStatus") {
    const classes = Array.isArray(target.element?.classes) ? target.element.classes : [];
    if (!classes.some((className) => typeof className === "string" && /(?:^|_)liveStatus(?:_|$)/.test(className))) {
      add("live-status-component-class-missing", key, { classes });
    }
    if (semanticAncestor?.testId !== "assistant-panel") {
      add("live-status-panel-missing", key, { testId: semanticAncestor?.testId ?? null });
    }
  }
  const semanticStyleColor = semanticAncestor ? parseRgb(semanticAncestor.style?.backgroundColor) : null;
  if (!background || !semanticStyleColor || !sameRgb(background, semanticStyleColor)) {
    add("semantic-background-color-mismatch", key, {
      declared: target.semanticBackgroundColor,
      measured: semanticAncestor?.style?.backgroundColor ?? null,
    });
  }
  let nearestOpaque = null;
  for (const ancestor of ancestors) {
    const style = ancestor.style || {};
    const opacity = Number(style.opacity);
    if (!Number.isFinite(opacity) || opacity !== 1) add("ancestor-opacity", key, { ancestor: ancestor.name, value: style.opacity });
    if (style.visibility !== "visible" || style.display === "none") add("ancestor-not-visible", key, {
      ancestor: ancestor.name,
      visibility: style.visibility,
      display: style.display,
    });
    if (style.backgroundImage !== "none") add("ancestor-background-image", key, {
      ancestor: ancestor.name,
      value: style.backgroundImage,
    });
    if (style.mixBlendMode !== "normal") add("ancestor-blend-mode", key, { ancestor: ancestor.name, value: style.mixBlendMode });
    if (style.backgroundBlendMode !== "normal") add("ancestor-background-blend-mode", key, {
      ancestor: ancestor.name,
      value: style.backgroundBlendMode,
    });
    if (style.filter !== "none") add("ancestor-filter", key, { ancestor: ancestor.name, value: style.filter });
    if (style.backdropFilter !== "none") add("ancestor-backdrop-filter", key, { ancestor: ancestor.name, value: style.backdropFilter });
    if (style.clipPath !== "none") add("ancestor-clip-path", key, { ancestor: ancestor.name, value: style.clipPath });
    if (style.maskImage !== "none") add("ancestor-mask-image", key, { ancestor: ancestor.name, value: style.maskImage });
    if (style.textShadow !== "none") add("ancestor-text-shadow", key, { ancestor: ancestor.name, value: style.textShadow });
    const color = parseRgb(style.backgroundColor);
    if (!color) {
      add("ancestor-background-unparseable", key, { ancestor: ancestor.name, value: style.backgroundColor });
    } else if (color.alpha > 0 && color.alpha < 1) {
      add("ancestor-background-translucent", key, { ancestor: ancestor.name, value: style.backgroundColor });
    } else if (color.alpha === 1 && nearestOpaque === null) {
      nearestOpaque = { ancestor, color };
    }
  }
  if (!nearestOpaque || nearestOpaque.ancestor.kind !== target.role) {
    add("nearest-opaque-background-mismatch", key, {
      expected: target.role,
      actual: nearestOpaque?.ancestor.kind ?? null,
      name: nearestOpaque?.ancestor.name ?? null,
    });
  }
  if (!nearestOpaque || !background || !sameRgb(nearestOpaque.color, background)) {
    add("semantic-background-not-nearest-opaque-color", key, {
      declared: target.semanticBackgroundColor,
      nearestOpaque: nearestOpaque?.ancestor.style.backgroundColor ?? null,
    });
  }
  if (foreground && foreground.alpha === 1 && background && background.alpha === 1) {
    const ratio = calculateContrast(foreground, background);
    if (ratio < 4.5) add("contrast-below-4.5", key, { ratio: Number(ratio.toFixed(4)), minimum: 4.5 });
    target.measuredContrast = Number(ratio.toFixed(4));
  }

  const lines = Array.isArray(target.lines) ? target.lines : [];
  if (lines.length === 0) add("text-line-missing", key);
  lines.forEach((line, index) => {
    if (line.inViewport !== true) add("line-outside-viewport", key, { line: index, rect: line.rect });
    if (!Array.isArray(line.clippingChecks) || line.clippingChecks.length === 0) {
      add("line-clipping-checks-missing", key, { line: index });
    } else {
      for (const clipping of line.clippingChecks) {
        if (clipping.clipped !== false) add("line-clipped", key, { line: index, clipping });
      }
    }
    if (!Array.isArray(line.hitPoints) || line.hitPoints.length < 3) add("line-hit-points-missing", key, { line: index });
    for (const hit of line.hitPoints || []) {
      if (hit.targetOrDescendant !== true || !["target", "descendant"].includes(hit.hitRelation)) {
        add("line-hit-point-occluded", key, { line: index, hit });
      }
    }
  });
}

function sameRgb(left, right) {
  return left.red === right.red && left.green === right.green && left.blue === right.blue && left.alpha === right.alpha;
}

async function captureAssistantContrastSnapshot(page, axeResults) {
  const dom = await page.evaluate((incompleteRules) => {
    const panel = document.querySelector('[data-testid="assistant-panel"]');
    if (!panel) return { error: "assistant-panel-missing", targets: [], rawNodeMappings: [] };
    const containsClass = (element, name) => Array.from(element.classList).some((value) => value.includes(name));
    const hasComponentClass = (element, name) => Array.from(element.classList).some((value) => (
      new RegExp(`(?:^|_)${name}(?:_|$)`).test(value)
    ));
    const describe = (element) => ({
      tag: element.tagName.toLowerCase(),
      id: element.id || null,
      classes: Array.from(element.classList),
    });
    const roots = [];
    const readinessStatus = Array.from(panel.querySelectorAll('[role="status"]')).filter((candidate) => (
      candidate.tagName === "DIV"
      && candidate.parentElement
      && containsClass(candidate.parentElement, "body")
      && Array.from(candidate.children).some((child) => child.getAttribute("aria-hidden") === "true")
      && Array.from(candidate.children).some((child) => child.tagName === "SPAN" && child.textContent.trim())
    ));
    if (readinessStatus.length === 1) {
      const spans = Array.from(readinessStatus[0].children).filter((child) => child.tagName === "SPAN" && child.textContent.trim());
      if (spans.length === 1) roots.push({ role: "readiness", root: readinessStatus[0], textRoot: spans[0], key: "readiness-text" });
    }
    const answerRoots = Array.from(panel.querySelectorAll('[class*="answerBlocks"]'));
    answerRoots.forEach((answerRoot, answerIndex) => roots.push({
      role: "answer",
      root: answerRoot,
      textRoot: answerRoot,
      key: `answer-${answerIndex + 1}`,
    }));
    const disclaimers = Array.from(panel.querySelectorAll("#assistant-disclaimer"));
    if (disclaimers.length === 1) roots.push({ role: "disclaimer", root: disclaimers[0], textRoot: disclaimers[0], key: "assistant-disclaimer" });

    const liveStatusRoots = new Set();
    for (const rule of incompleteRules || []) {
      for (const node of rule.nodes || []) {
        for (const selector of Array.isArray(node.target) ? node.target : []) {
          try {
            const matches = document.querySelectorAll(selector);
            if (matches.length !== 1) continue;
            const candidate = matches[0];
            if (!panel.contains(candidate) || !hasComponentClass(candidate, "liveStatus") || liveStatusRoots.has(candidate)) continue;
            liveStatusRoots.add(candidate);
            roots.push({ role: "liveStatus", root: candidate, textRoot: candidate, key: `raw-live-status-${roots.length + 1}` });
          } catch {
            // Invalid raw selectors remain unmapped below and fail closed.
          }
        }
      }
    }

    const computedRecord = (element) => {
      const style = getComputedStyle(element);
      return {
        opacity: style.opacity,
        visibility: style.visibility,
        display: style.display,
        color: style.color,
        textFillColor: style.webkitTextFillColor,
        backgroundColor: style.backgroundColor,
        backgroundImage: style.backgroundImage,
        mixBlendMode: style.mixBlendMode,
        backgroundBlendMode: style.backgroundBlendMode,
        filter: style.filter,
        backdropFilter: style.backdropFilter || style.webkitBackdropFilter || "none",
        clipPath: style.clipPath,
        maskImage: style.maskImage || style.webkitMaskImage || "none",
        textShadow: style.textShadow,
        overflowX: style.overflowX,
        overflowY: style.overflowY,
      };
    };
    const classKind = (element, role) => {
      if (role === "readiness" && element.getAttribute("role") === "status") return "readiness";
      if (role === "answer" && containsClass(element, "assistantMessage")) return "answer";
      if (role === "disclaimer" && hasComponentClass(element, "composer")) return "disclaimer";
      if (role === "liveStatus" && element === panel) return "liveStatus";
      return null;
    };
    const ancestorsFor = (element, role) => {
      const ancestors = [];
      for (let current = element; current; current = current.parentElement) {
        const record = {
          name: current.id ? `#${current.id}` : describe(current).classes.join("."),
          testId: current.getAttribute("data-testid"),
          kind: classKind(current, role),
          style: computedRecord(current),
          rect: (() => {
            const rect = current.getBoundingClientRect();
            return { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom };
          })(),
          client: {
            left: current.clientLeft,
            top: current.clientTop,
            width: current.clientWidth,
            height: current.clientHeight,
          },
        };
        ancestors.push(record);
        if (current === document.documentElement) break;
      }
      return ancestors;
    };
    const isVisibleText = (node) => {
      const parent = node.parentElement;
      if (!parent || !node.nodeValue.trim()) return false;
      const style = getComputedStyle(parent);
      if (style.display === "none" || style.visibility !== "visible" || Number(style.opacity) === 0) return false;
      const range = document.createRange();
      range.selectNodeContents(node);
      return range.getClientRects().length > 0;
    };
    const textNodes = (element) => {
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      const nodes = [];
      while (walker.nextNode()) if (isVisibleText(walker.currentNode)) nodes.push(walker.currentNode);
      return nodes;
    };
    const targets = [];
    const elementTokens = new WeakMap();
    let nextElementToken = 1;
    const tokenForElement = (element) => {
      if (!elementTokens.has(element)) elementTokens.set(element, `element-${nextElementToken++}`);
      return elementTokens.get(element);
    };
    for (const group of roots) {
      const nodes = textNodes(group.textRoot);
      nodes.forEach((textNode, textIndex) => {
        const element = textNode.parentElement;
        const style = computedRecord(element);
        const ancestors = ancestorsFor(element, group.role);
        const semanticAncestor = ancestors.find((ancestor) => ancestor.kind === group.role);
        const foreground = style.textFillColor && style.textFillColor !== "currentcolor" ? style.textFillColor : style.color;
        const range = document.createRange();
        range.selectNodeContents(textNode);
        const clientRects = Array.from(range.getClientRects());
        const lines = clientRects.map((clientRect) => {
          const rect = { left: clientRect.left, top: clientRect.top, right: clientRect.right, bottom: clientRect.bottom, width: clientRect.width, height: clientRect.height };
          const clippingChecks = ancestors
            .filter((ancestor) => ancestor.style.overflowX !== "visible" || ancestor.style.overflowY !== "visible")
            .map((ancestor) => {
              const clip = {
                left: ancestor.rect.left + ancestor.client.left,
                top: ancestor.rect.top + ancestor.client.top,
                right: ancestor.rect.left + ancestor.client.left + ancestor.client.width,
                bottom: ancestor.rect.top + ancestor.client.top + ancestor.client.height,
              };
              const clipX = ancestor.style.overflowX !== "visible";
              const clipY = ancestor.style.overflowY !== "visible";
              const clipped = (clipX && (rect.left < clip.left - 0.5 || rect.right > clip.right + 0.5))
                || (clipY && (rect.top < clip.top - 0.5 || rect.bottom > clip.bottom + 0.5));
              return { ancestor: ancestor.name, overflowX: ancestor.style.overflowX, overflowY: ancestor.style.overflowY, clipped };
            });
          const hitPoints = [0.25, 0.5, 0.75].map((fraction) => {
            const x = rect.left + rect.width * fraction;
            const y = rect.top + rect.height / 2;
            const hit = document.elementFromPoint(x, y);
            const hitRelation = hit === element ? "target" : hit && element.contains(hit) ? "descendant"
              : hit && hit.contains(element) ? "ancestor" : hit ? "other" : "none";
            return {
              x,
              y,
              targetOrDescendant: hitRelation === "target" || hitRelation === "descendant",
              hitRelation,
              hit: hit ? describe(hit) : null,
            };
          });
          return {
            rect,
            inViewport: rect.left >= -0.5 && rect.top >= -0.5 && rect.right <= innerWidth + 0.5 && rect.bottom <= innerHeight + 0.5,
            clippingChecks,
            hitPoints,
          };
        });
        targets.push({
          key: `${group.key}-text-${textIndex + 1}`,
          elementToken: tokenForElement(element),
          element: describe(element),
          role: group.role,
          textLength: textNode.nodeValue.length,
          foreground,
          semanticKind: semanticAncestor?.kind ?? null,
          semanticBackgroundColor: semanticAncestor?.style.backgroundColor ?? null,
          semanticBackgroundImage: semanticAncestor?.style.backgroundImage ?? null,
          ancestors,
          lines,
        });
      });
    }

    const rawNodeMappings = [];
    for (const rule of incompleteRules || []) {
      for (const [nodeIndex, node] of (rule.nodes || []).entries()) {
        const selectors = Array.isArray(node.target) ? node.target : [];
        for (const [selectorIndex, selector] of selectors.entries()) {
          let matched = [];
          let selectorError = null;
          try { matched = Array.from(document.querySelectorAll(selector)); }
          catch (error) { selectorError = String(error); }
          const candidate = matched.length === 1 ? matched[0] : null;
          const measuredTargetKeys = candidate
            ? targets.filter((target) => target.elementToken === tokenForElement(candidate)).map((target) => target.key)
            : [];
          let directTextOnly = false;
          if (candidate) {
            const visibleTextNodes = textNodes(candidate);
            directTextOnly = visibleTextNodes.length > 0 && visibleTextNodes.every((textNode) => textNode.parentElement === candidate);
          }
          const roles = [...new Set(measuredTargetKeys.map((key) => targets.find((target) => target.key === key)?.role).filter(Boolean))];
          rawNodeMappings.push({
            rule: rule.id,
            nodeIndex,
            selectorIndex,
            selector,
            matchCount: matched.length,
            roles,
            measuredTargetKeys,
            directTextOnly,
            elementToken: candidate ? tokenForElement(candidate) : null,
            recognized: !selectorError && matched.length === 1 && measuredTargetKeys.length > 0 && directTextOnly && roles.length === 1,
            selectorError,
          });
        }
        if (selectors.length === 0) rawNodeMappings.push({
          rule: rule.id,
          nodeIndex,
          selectorIndex: null,
          selector: null,
          matchCount: 0,
          roles: [],
          measuredTargetKeys: [],
          directTextOnly: false,
          elementToken: null,
          recognized: false,
        });
      }
    }
    return {
      targets,
      rawNodeMappings,
      viewport: { width: innerWidth, height: innerHeight },
      targetRootCounts: {
        readiness: readinessStatus.length,
        answers: answerRoots.length,
        disclaimers: disclaimers.length,
      },
    };
  }, axeResults.incomplete || []);
  const violations = Array.isArray(axeResults.violations) ? axeResults.violations : [];
  const incomplete = Array.isArray(axeResults.incomplete) ? axeResults.incomplete : [];
  const rawAxe = {
    counts: {
      violations: violations.length,
      incomplete: incomplete.length,
      passes: Array.isArray(axeResults.passes) ? axeResults.passes.length : null,
      inapplicable: Array.isArray(axeResults.inapplicable) ? axeResults.inapplicable.length : null,
    },
    violations,
    incomplete,
  };
  return { ...dom, rawAxe };
}

async function captureAssistantAxeIncompleteSnapshot(page, axeResults) {
  const snapshot = await captureAssistantContrastSnapshot(page, axeResults);
  const mappedKeys = new Set((snapshot.rawNodeMappings || []).flatMap((mapping) => (
    Array.isArray(mapping.measuredTargetKeys) ? mapping.measuredTargetKeys : []
  )));
  snapshot.targets = (snapshot.targets || []).filter((target) => mappedKeys.has(target.key));
  snapshot.requiredRoles = [...new Set(snapshot.targets.map((target) => target.role))];
  return snapshot;
}

module.exports = {
  captureAssistantAxeIncompleteSnapshot,
  calculateContrast,
  captureAssistantContrastSnapshot,
  evaluateAssistantContrastAudit,
  parseRgb,
};
