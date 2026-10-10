---
title: "Design system and Ledger assistant"
description: "The current Signal Ledger visual language, approved assistant visual contract, and R-ASTRA-120 owner-canary status."
---

# Design system and Ledger assistant

This guide describes the visual system already used by Signal Ledger and the approved visual
contract for the Ledger assistant. At E849, the tested PR #2 image is deployed at schema 13, ready
and loopback-only, with rollout control set to `owner_canary`; the actual owner UI/model/action
canary remains pending. E847's reused 193/196 browser aggregate (three expected skips) and 68-case,
72-scan whole-route axe scope (zero violations/incompletes) passed for their unchanged bindings.
The guide passed its declared review scope. These scoped results are not full WCAG AA; physical
mobile, true zoom, actual screen-reader and PDF/UA evidence remain unavailable. E798's focused
checks and its pre-repair HTTP and pre-banner guide failures are historical. See the
[R-ASTRA-120 plan and evidence](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on).

## Source of truth

The packaged workspace stylesheet, [`app.css`](../../src/stock_probs/static/app.css), defines the
current color, type, surface, focus, reduced-motion, forced-colors, and print behavior. The Next.js
workspace uses the same packaged stylesheet through [`layout.tsx`](../../frontend/app/layout.tsx).
Shared route navigation and its selected-page state are defined in
[`workspace-nav.tsx`](../../frontend/components/workspace-nav.tsx); the Tools layout and page
provide the baseline composition in [`tools/layout.tsx`](../../frontend/app/tools/layout.tsx) and
[`tools/page.tsx`](../../frontend/app/tools/page.tsx).

When this guide and the current source differ, treat source as the evidence for current behavior.
Keep the guide current when an intentional shared visual change is made. Proposed assistant styling
must use the existing system unless an approved implementation requirement changes it.

## Current visual language

Signal Ledger uses a quiet research-workspace presentation: cool neutral page and panel surfaces,
dark readable text, restrained teal accents, clear borders, and a small number of semantic status
colors. Navigation and selected instrument context stay visible across workspace routes. The Tools
page groups Forecast, Live Trading, and Markets as separate work areas. Its page tabs only navigate;
changing tabs does not submit a forecast or place a trade.

| Role | Light theme | Dark theme | Use |
| --- | --- | --- | --- |
| Canvas | `#f5f7f8` | `#0d141a` | Main page background |
| Panel | `#ffffff` | `#17212a` | Cards, menus, and assistant surfaces |
| Raised panel | `#ffffff` | `#1b2730` | Emphasized cards and floating surfaces |
| Main text | `#172630` | `#eff4f6` | Headings and primary content |
| Muted text | `#50616d` | `#a9bac4` | Supporting copy and metadata |
| Accent | `#006e67` | `#7bc9c1` | Selected navigation, primary action, links |
| Border | `#dce4e8` | `#34434d` | Grouping and separation |
| Focus | `#007f75` | `#80ded4` | Visible keyboard focus |

Use the existing CSS custom properties (`--canvas`, `--panel`, `--panel-raised`, `--text`,
`--muted`, `--accent`, `--border`, and `--focus`) rather than copying color literals into a new
component. Positive, warning, and failure states use the existing semantic `--good`, `--warn`, and
`--bad` roles. Do not encode a state by color alone.

Typography uses the system sans-serif stack and a 16 px root size. Body copy is compact and readable;
large workspace headings use responsive sizing and close line spacing. Numeric values use tabular
figures. Panels use the shared 10 px radius and restrained shadow. Borders, spacing, and headings
provide hierarchy; avoid adding decorative chrome or a second brand palette.

## Approved Ledger assistant concept

The approved direction is concept B: a Ledger assistant that can explain the current workspace and
offer research help while leaving the selected page and its data visible when space permits. It
uses the existing Signal Ledger surface tokens. The concept image remains a design proposal; the
current branch source implements an assistant candidate and is still under independent QA.

![Approved assistant concept B. This is a design proposal, not a screenshot of shipped or accepted behavior.](../design/assistant-concept-b.png)

The following image is the existing Tools page captured without the assistant. It is the visual
baseline for comparison, not evidence that the assistant is present in the application.

![Current Tools page baseline without the assistant panel.](../design/current-tools-reference.jpg)

### Desktop panel

- Do not open the assistant automatically on page load. Provide a visible, keyboard-operable
  launcher; activating it opens the assistant. The assistant may be collapsed and reopened without
  losing the current page context.
- At a 700 px viewport width or wider, show an approximately 480 px wide panel fixed to the bottom-right
  of the viewport. Bound its height to the available dynamic viewport and scroll its message area
  internally so the header and composer remain reachable.
- Keep the underlying workspace visible and usable. Do not add a page-dimming backdrop, modal
  scrim, or desktop focus trap. Respect viewport edges and keep controls out of system insets.
- Give the header clear controls for assistant title/context, model choice, history, expand or
  restore size, collapse, and close. Every icon-only control needs an accessible name and a 44 px
  minimum target.

### Small screens and on-screen keyboard

At widths below 700 px, the assistant becomes a full-screen modal surface with safe-area padding.
While it is open, the page wrapper is inert and hidden with `visibility: hidden`, preserving its
layout and scroll position. Closing the assistant, unmounting it, or resizing to desktop restores
the wrapper’s prior state. The assistant remains outside that wrapper. Account for the on-screen
keyboard and changing visual viewport so the composer and send control remain visible while typing. Normally keep the message list independently scrollable. While an
exact-URL WebFetch approval is pending, let the transcript use the panel body's main scroll area
so context and status can move out of the way and the complete destination and approval controls
can be inspected together. Keep the warning, URL, expiry and decisions intact; do not shrink text
or touch targets to make the card fit. Do not place essential controls beneath browser chrome or
device cutouts. An ordinary close or Escape restores the user's prior context and focus to the
launcher. A mobile handoff for `notes.set`, `notes.clear`, or `alerts.remove` instead closes the
assistant and moves focus to the matching Live Trading control. The user reviews and completes the
change there; the handoff itself must not set, clear, or remove anything. The action receipt remains
in the conversation and is available after reopening that conversation from assistant history.
`alerts.add` remains a confirmed, browser-local action scoped to the active Live Trading
page/session; it does not create a server-owned alert.

### Conversation structure and states

- Use a clear header and ordered conversation history, with visually distinct user and assistant
  turns. Keep content text selectable and support readable long responses, lists, citations, and
  structured action previews.
- Show the active page or selected instrument as context when it is actually available. Let the user
  remove or change that context; do not imply the assistant can see data it was not given.
- Provide an explicit model picker. Show the selected model and its availability, and do not claim a
  model is ready when runtime discovery or a request is unavailable.
- Provide a history control with honest loading, empty, failure, and selected-conversation states.
  Do not imply cross-device or durable history unless the implemented storage contract supports it.
- Citations must identify the source and relevant date/as-of value when available. Link to the
  underlying first-party page or local workspace record only when that destination exists. Mark
  unavailable citations as unavailable rather than presenting fabricated links.
- Show tool activity as visible, named steps with pending, complete, and failed states. Summaries
  must distinguish retrieved evidence from assistant explanation and preserve provider/source
  attribution.
- Before an assistant-suggested action is applied, show a preview of its scope and expected effect
  and require the user to confirm. A preview is not an action result. Assistant copy must not imply
  that Signal Ledger places trades; trade execution is unavailable in the existing Tools contract.
- Include clear loading, empty, unavailable, error, and cancellation states. Keep status updates
  available to assistive technology without moving focus unexpectedly.

### Static empty-state and disclaimer text

The two static empty assistant messages and the composer disclaimer remain semantic paragraphs.
Render their existing text with unstyled word spans while keeping original whitespace as text nodes.
Preserve the exact copy, natural wrapping, paragraph boundaries, disclaimer `id`, and textarea
`aria-describedby` relationship. Do not add `aria-hidden`, axe exclusions, or a contrast exception.
This markup supports text-word geometry measurements without changing the message's paragraph
semantics or accessible text.

E780's private candidate diagnostic passed 20/20 states with whole-document axe at 0 violations
and 0 incomplete. E783 and E784 each passed the focused saved-empty fixture in two viewport classes
with four Light/Dark whole-document snapshots at 0/0; E786's integrated source review found no
issues in copy, whitespace, paragraph semantics, or the disclaimer relationship. These are scoped
candidate/fixture/source results only. E791 passed the corrected synthetic 196-case desktop/Pixel 7 run (193 passed, 3 expected skips, no failures/flaky) with unchanged source pins, 52/52 served/export parity and cleanup. The four saved-empty whole-document axe snapshots were 0/0, and E793 passed parent visual review of all four images. E795 then passed all 64 whole-route automated Playwright/axe states with zero violations/incompletes, no setup/scan errors or exclusions, stable source bindings, and cleanup. E797 separately failed seeded-volume startup readiness at an outer exec timeout; its cause is unproven, while a parent-reported independent exact-absence audit passed. The browser/accessibility results are scoped automated evidence only; physical mobile, true zoom, screen-reader, and broader accessibility acceptance remain open.
See the [R-ASTRA-120 ledger](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on)
for exact receipts and preserved results.

### Accessibility and display modes

- Make every action keyboard-operable. Maintain a logical reading and tab order, provide a visible
  `:focus-visible` treatment, and keep focus from being obscured by the panel edge or composer.
- Escape closes or collapses the panel when safe; on the full-screen small-screen surface it exits
  to the workspace and restores focus to the launcher. If an action preview is open, Escape first
  dismisses the preview without applying it.
- Use semantic headings, labelled controls, ordered messages, and status announcements. Do not rely
  on color, icons, or animation alone to convey state.
- Preserve the existing light, dark, and system theme behavior by consuming shared semantic tokens.
  Meet the application's text, control, chart, and focus contrast requirements in both themes.
- Honor `prefers-reduced-motion`; transitions must not be needed to understand state or complete an
  action. Under forced colors, retain clear borders, focus, selected state, and control labels
  without depending on shadows or background tints.
- In print, omit interactive assistant controls and retain only content that has a meaningful
  printed representation. Avoid printing hidden controls or decorative chat chrome.

### R-ASTRA-120 source and release status

The deployed PR #2 release mounts the approved desktop panel and narrow-screen full-screen surface
in the same application image. E849 reports the tested image at schema 13, ready and loopback-only,
with verified pre-deploy/pre-migration backups and registered recovery image. The rollout-control
call passed with `owner_canary`; the actual owner UI/model/action canary remains pending. The
owner's current authenticator-code field was empty, so no authenticated owner interaction is
claimed. Invited-user rollout and the announcement remain held.

E847's canonical and 590-check security scopes passed. Its input-bound browser and axe evidence
remains Pass: 193/196 browser cases with three expected skips, and 68 route cases with 72 scans at
zero violations/incompletes. Earlier input-bound current-product native wire/kill scopes passed.
E848 passed the exact-5ad actual-host pair/resource/recovery, actual combined 1 GB and PR-bound
rollback scopes. The guide passed its declared review scope. These results do not establish full
WCAG AA; physical mobile, true zoom, actual screen-reader and PDF/UA evidence remain unavailable.
The E848 deployment failure and
successful failure-path rollback remain historical. The following E245–E797 diagnostics are
historical; their failures remain preserved and do not override the later E847 results for the
explicitly reused browser/axe bindings.
E245's initial ignored UI candidate changed inline-code whitespace and left mobile raw-axe
incompletes; E250's separate fixture-only follow-up preserved text/code fidelity, tested enabled
keyboard traversal without submission, and passed mobile stacked/full-width/44px geometry. Its
desktop Light/Dark raw axe was 0 violations/0 incompletes; mobile Light/Dark each retained one
incomplete disclaimer contrast item, so strict app axe **Failed in that historical snapshot**. E251's builder-reported
source/build checks were followed by E252/E253 source-review **Fails**: CSS-module scoping left the
disclaimer padding rule unbound, and readiness styling was applied to the whole container rather
than the candidate's child span while the mobile font-size override was removed. The fixes are
authorized. E254's builder repair binds the selector and passes its scoped contract/build/stage
checks. E257 reports readiness CSS/contract/build/test/audit/stage scope; E258 parent review
**Passed** the bound source and served/export comparison, including the full JSX hash. E263's
independent selected current-source browser run passed 11 cases with one expected mobile skip,
verified all 52 served/export files, and completed cleanup. E263's strict raw axe **Failed** with one
incomplete contrast item in each of the four actual desktop/mobile Light/Dark snapshots. Sampled
custom placeholder contrast passed only its measurements; enabled-Send keyboard traversal, numeric
mobile target geometry, and rendered code-fence fidelity were **Unavailable**. E267 ran the E264
local Linux/amd64 image in a native two-owner functional trial and **Failed**: one owner returned
`provider_unavailable`, the other timed out, and neither reached search/fetch approval or produced
an answer. E268 independently verified that failure. E272 later **Failed** on the same image: owner 0
answered; owner 1 reached search and an approved IANA fetch, then timed out without an answer. E273
passed result-integrity review only. The 768 MiB sample is not 1 GB acceptance; anonymous timing
rows have no owner mapping and do not identify later-chunk activity, a stall, or cause. E274's first synthetic desktop/mobile UI fixture
attempt **Failed at setup** on an auth-route mismatch and produced no UI records; corrected rerun is
pending. It does not close the earlier raw-axe incompletes. E269's corrected static header/body
inspection passed, but no independent test rerun occurred (**Skipped/not run**) and remains pending.
Those E263 mobile raw-axe and strict-accessibility results are historical. E847 later passed its
bound axe and security scopes; E848 passed the exact-5ad actual-host resource and PR-bound rollback
scopes.
E276's corrected synthetic browser run **Failed** because Send/Cancel left focus on `document.body`.
E277 repaired panel focus handling and passed the approved frontend build/stage with all 52 served
files matching. E278's post-repair aggregate **Failed** four invalid Stop-label identity assertions,
though actual focus and keyboard-cancel assertions passed across desktop/mobile Light/Dark. E280
passed only the corrected stop-control identity/cancellation-cleanup diagnostic. E281 later passed
the tracked focus-only regression 2/2 after preserving its wrapper/CLI setup failures. These narrow
fixture results do not close the raw-axe incomplete or establish full app accessibility.
Mobile viewport evidence is emulated, not physical-device evidence.

The E263 historical checkpoint reported strict app axe **Fail** despite scoped readable-text
measurements. E664's standalone help HTML and PDF reviews apply to the earlier finalized outputs;
the PDF had a tagged-text fidelity **Fail** despite visual review, and E670 later changed the
tracked renderer. Its source review passed. The initial test review found a P2 gap in per-block
boundary/order assertions; a test-only correction then passed independent source/test review and
TAP reported 17/17; the first wrapper left its numeric exit unavailable, then E673 independently
reran the exact command with exit 0 and 17/17. E665's private PDF artifact passed exact-structure
review; it is not a current maintained render. Fresh capture/render/finalization remain pending.
E676's static instruction audit at the 30742 checkpoint found two P2 copy omissions (all-or-none
context selection and email-only invitation verification) plus a P3 “Cancel”/“Stop response” label
mismatch. E679 independently confirmed the corrected copy and source contract for the candidate
template/test bytes, with the Node suite passing 17/17. Separate served/export parity is unavailable
and maintained capture/render/finalization remains pending; this is not rendered-guide
acceptance. Neither the earlier guide result nor scoped contrast measurements establish
application accessibility or release readiness.

E689 independently passed the renderer unit command (17/17, exit 0) for its synthetic layout/PDF
cases. It did not run the maintained capture/finalization/render pipeline or app browser checks, so
fresh guide outputs, PDF/UA, accessibility, and final guide acceptance remain pending. E696's
parent review and E697's independent review passed visual, privacy, and image-integrity checks for
eight synthetic PNGs bound to the earlier `c169` checkpoint only. The manifest's QA binding remains
unavailable, its privacy fields are pending, and finalization/render were skipped. Source changes
require fresh captures before the maintained guide can proceed. See the
[R-ASTRA-120 ledger](../../MVP-PLAN.md) for the receipt and exact limits.

Use the [R-ASTRA-120 ledger](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on)
for exact commands, hashes, failures, repairs and historical checkpoint results. This page specifies
the intended visual and interaction rules; earlier evidence does not supersede them or establish
release readiness.

## Review checklist for future UI work

Before changing a workspace or building on the assistant, inspect this guide and the current
packaged styles and route components. Check the implementation at desktop and narrow mobile widths,
in light and dark themes, with keyboard-only navigation, reduced motion, forced colors, and print
styles. Record what was actually exercised and retain failed, skipped, pending, or unavailable
results as such.

Keep proposed mockups, current product screenshots, implementation, and acceptance evidence
distinct. A concept image establishes the approved visual direction only; a current-page screenshot
shows only the captured baseline; neither proves a running implementation or acceptance result.

[Back to Develop](index.md)
