# Accessibility, responsive, and theme checks

## Accessibility

- Navigate by role and accessible label; prove skip links, focus placement, keyboard selection,
  submit, retry, disclosure, pagination, chart-point focus, and textual chart equivalents.
- Run axe on settled representative success and failure states. Require both `violations` and
  `incomplete` to be empty.
- Keep live-region/loading state, `aria-busy`, `aria-invalid`, nearby validation text, and recovery
  observable.
- Report actual screen-reader evidence as `Unavailable` unless a screen reader was used. Axe,
  keyboard, semantics, and MCP do not substitute.

## Contrast and alternate modes

Compute WCAG relative luminance from rendered or resolved colors. Require 4.5:1 for normal text and
3:1 for large text, controls, focus, and chart marks. Cover semantic roles in light and dark themes,
hover/focus states, forced colors, and print. In forced colors, retain non-color chart distinctions;
in print, verify a legible light surface independent of selected theme.

## Responsive behavior

Exercise the supported width range, including 360, 390, 768, 1024, 1280, and 1440 where relevant.
Compare document width with the visual viewport, check no overlap for labels/chart ticks/loading
badges, and require primary touch targets to be at least 44 CSS pixels. Label Chromium viewport
and touch simulation as emulated mobile, not physical-mobile evidence.

## No-flash theme behavior

On both `/` and `/api/v1/docs`, inspect the external theme initializer in the DOM: it precedes CSS,
is parser blocking, and has no async/defer/module behavior. That loaded-DOM ordering and a post-load
`data-theme` assertion support the implementation contract but do not observe first paint. For
first-paint evidence, use a fresh context, set storage in an init script before navigation, observe
the browser `paint` entries, and record the theme present at `first-paint` without CSP bypass. Then
exercise light, dark, system reset, invalid storage, storage failure, reduced motion, and shared
persistence through actual controls. Screenshots prove only their settled state.
