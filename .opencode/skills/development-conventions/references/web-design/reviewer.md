---
title: "Web Design Reviewer — Visual Inspection and Fixing Workflow"
impact: MEDIUM
impactDescription: "Systematic approach to detecting and fixing design issues in web applications"
tags: [web-design, review, ui, layout, responsive, accessibility]
---

## Web Design Reviewer — Visual Inspection & Fixing

### Prerequisites

1. Target website must be running (local dev server, staging, or production)
2. Browser automation must be available (screenshot capture, navigation, DOM retrieval)
3. Access to source code when making fixes

### Workflow

```
Step 1: Information Gathering → Step 2: Visual Inspection → Step 3: Issue Fixing → Step 4: Re-verification
```

### Step 1 — Information Gathering

- Confirm URL with user if not provided
- Detect framework, styling method, and source locations from workspace files
- Identify styling method: CSS, SCSS, Tailwind, CSS Modules, styled-components, Emotion, CSS-in-JS

### Step 2 — Visual Inspection

**Layout Issues:** element overflow (high), element overlap (high), alignment issues (medium), inconsistent spacing (medium)

**Responsive Issues:** non-mobile friendly (high), breakpoint issues (medium), touch targets (medium)

**Accessibility Issues:** insufficient contrast (high), no focus state (high), missing alt text (medium)

**Visual Consistency:** font inconsistency (medium), color inconsistency (medium), spacing inconsistency (low)

Test at viewports: 375px (mobile), 768px (tablet), 1280px (desktop), 1920px (wide)

### Step 3 — Issue Fixing

Prioritize: P1 = Fix Immediately (layout affecting functionality), P2 = Fix Next (degrading UX), P3 = Fix If Possible (minor inconsistencies)

**Fix Principles:**
1. Minimal changes — only what's needed to resolve the issue
2. Respect existing patterns — follow the project's code style
3. Avoid breaking changes — be careful not to affect other areas
4. Fix one issue at a time and verify each

### Step 4 — Re-verification

1. Reload browser, capture screenshots of fixed areas
2. Compare before and after
3. Verify fixes haven't affected other areas
4. If more than 3 fix attempts for a specific issue, consult the user

### Recommended Tools

For this repository, use only the pinned `./scripts/playwright-mcp.sh` entry in `opencode.json` with
`--headless`, `--isolated`, and the configured loopback host/origin allowlists. That project contract
overrides generic `@latest` examples and alternative browser runners.
