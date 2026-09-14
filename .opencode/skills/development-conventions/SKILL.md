---
name: "development-conventions"
description: "Action-oriented conventions for writing, reviewing, and testing source code and documentation across README/docs, APIs, Next.js 16 App Router, Python, Go/Rust, regex, Mermaid, gitignore, web/UI, mail, and Ingenium-specific work."
---

# Development Conventions

Unified, action-oriented conventions for source editing, review, and tests. Detailed rules live in the matching references below.

## 🔴 Mandatory Reference Gate

Before acting, read [`references/useful-comments/guidelines.md`](references/useful-comments/guidelines.md) for **every source edit or source review**. For **every behavioral source change, test edit, test review, or test execution**, also read [`references/testing/patterns.md`](references/testing/patterns.md); Python work additionally requires the matching Python test references. For domain work, read only the matching references below. Do not act until all mandatory and matching references are read. Repository-specific safety and test instructions override generic examples. Avoid loading unrelated references.

## When to Use

- README or documentation work: read the README or documentation-writing reference; include API documentation references when documenting an API.
- API work: designing, implementing, reviewing, or testing HTTP routes, handlers, controllers, status codes, error responses, auth, pagination, rate limits, idempotency, or aggregation.
- Next.js 16 App Router work: any `app/` route, Server Component, Client Component, fetch/cache policy, build configuration, route/navigation behavior, Server Action/form/mutation, streaming/loading/error state, metadata/SEO, or cross-file hygiene review; read only the relevant category references.
- Python work: any `*.py` edit, review, build, lint, type-check, or test; read build/test, typing/docs, testing/tools, and style/security references as applicable, plus the mandatory testing reference for behavioral changes and test work.
- Go or Rust work: any Go or Rust source, test, review, formatting, lint, or build; read the language-conventions source index.
- Regex work: creating, reviewing, escaping, or optimizing a regular expression; read the regex reference.
- Mermaid work: creating or reviewing a Mermaid diagram; read the Mermaid reference.
- Gitignore work: editing or reviewing `.gitignore` patterns; read the gitignore reference.
- Testing work: writing, changing, reviewing, or running unit, integration, E2E, Playwright, or pytest tests; read the testing reference and any matching domain reference.
- Web/UI work: reviewing or changing layout, responsive behavior, accessibility, visual consistency, dashboard UI, overlays, cards, or browser-facing behavior; read the web-design and matching Ingenium visual/UI references.
- Mail work: changing mail UI, sync, cache, settings, or SmartReply behavior; read the mail-app UI source index and only its matching linked references.
- Ingenium-specific work: changing MCP/API/core layering, dashboard conventions, seeding, tool parity, project operations, or aggregated endpoints; read the matching Ingenium source indexes and references.

## Reference Files

### README, API, Python, and general conventions

| File | Description |
|------|-------------|
| [`references/create-readme/guidelines.md`](references/create-readme/guidelines.md) | README Writing Guidelines — Emoji Use, Sections, Formatting |
| [`references/api-design/status-codes.md`](references/api-design/status-codes.md) | HTTP Status Codes — Be Precise, Never Default to 200 or 500 |
| [`references/api-design/error-responses.md`](references/api-design/error-responses.md) | Error Response Shape and Versioning — Standardize All Error Output |
| [`references/api-design/api-patterns.md`](references/api-design/api-patterns.md) | API Patterns — Auth, Pagination, Rate Limiting, Idempotency, Conventions |
| [`references/python-conventions/build-and-test.md`](references/python-conventions/build-and-test.md) | Build and Test Commands — Default Fallback Commands for Python Projects |
| [`references/python-conventions/typing-and-docs.md`](references/python-conventions/typing-and-docs.md) | Type Hints and Docstrings — Mandatory Typing, Google-Style Documentation |
| [`references/python-conventions/testing-and-tools.md`](references/python-conventions/testing-and-tools.md) | Testing and Tools — pytest, ruff, mypy Conventions |
| [`references/python-conventions/style-and-security.md`](references/python-conventions/style-and-security.md) | Style, Security, and Framework Conventions — File Organization, Naming, Error Handling, Security |
| [`references/regex-reference/patterns.md`](references/regex-reference/patterns.md) | Regex Reference — Common Patterns, Escaping, Backtracking Prevention |
| [`references/mermaid/diagrams.md`](references/mermaid/diagrams.md) | Mermaid Diagrams — Mandatory Visual Documentation |
| [`references/gitignore/patterns.md`](references/gitignore/patterns.md) | Git Ignore Conventions — Patterns, Structure, and Rules |
| [`references/testing/patterns.md`](references/testing/patterns.md) | Useful Tests — Patterns That Actually Catch Bugs |
| [`references/web-design/reviewer.md`](references/web-design/reviewer.md) | Web Design Reviewer — Visual Inspection and Fixing Workflow |
| [`references/write-docs/guide.md`](references/write-docs/guide.md) | Writing Documentation — READMEs, API Docs, ADRs, Project Docs |
| [`references/useful-comments/guidelines.md`](references/useful-comments/guidelines.md) | Useful Comments — Self-Explanatory Code with Minimal Comments |

### Next.js 16 App Router

| File | Description |
|------|-------------|
| [`references/nextjs-conventions/build-barrel-files.md`](references/nextjs-conventions/build-barrel-files.md) | Submit buttons read parent-form pending state from `useFormStatus` — not from a prop drilled in |
| [`references/nextjs-conventions/build-dynamic-imports.md`](references/nextjs-conventions/build-dynamic-imports.md) | Every Server Action that writes data must invalidate the routes/tags that surface that data |
| [`references/nextjs-conventions/build-external-packages.md`](references/nextjs-conventions/build-external-packages.md) | Mutations from forms run through Server Actions — not custom API routes + client `fetch` |
| [`references/nextjs-conventions/build-optimize-package-imports.md`](references/nextjs-conventions/build-optimize-package-imports.md) | Import from the source module, not from a barrel `index.ts` — barrel re-exports pessimize tree-shaking |
| [`references/nextjs-conventions/build-turbopack-config.md`](references/nextjs-conventions/build-turbopack-config.md) | Split heavy components that aren't visible at first paint into separately loaded chunks |
| [`references/nextjs-conventions/cache-fetch-options.md`](references/nextjs-conventions/cache-fetch-options.md) | Mark Node packages with native bindings or non-bundleable resolution as serverExternalPackages |
| [`references/nextjs-conventions/cache-react-cache.md`](references/nextjs-conventions/cache-react-cache.md) | Declare package-flat-export libraries in optimizePackageImports so the compiler tree-shakes them |
| [`references/nextjs-conventions/cache-revalidate-path.md`](references/nextjs-conventions/cache-revalidate-path.md) | Don't disable Turbopack's persistent caching — the defaults are what give 5-10× faster restarts |
| [`references/nextjs-conventions/cache-revalidate-tag.md`](references/nextjs-conventions/cache-revalidate-tag.md) | Make every server `fetch` declare its caching intent — never let the default behavior be the documentation |
| [`references/nextjs-conventions/cache-segment-config.md`](references/nextjs-conventions/cache-segment-config.md) | Wrap per-request fetchers with React `cache()` so calls from multiple Server Components in one render dedupe |
| [`references/nextjs-conventions/cache-use-cache-directive.md`](references/nextjs-conventions/cache-use-cache-directive.md) | Every Server Action that mutates data must invalidate the routes/tags that surface it — the failure mode is silent staleness |
| [`references/nextjs-conventions/client-children-pattern.md`](references/nextjs-conventions/client-children-pattern.md) | Call `revalidateTag(tag, cacheLife)` with a profile — never invoke the old one-arg API |
| [`references/nextjs-conventions/client-hydration-mismatch.md`](references/nextjs-conventions/client-hydration-mismatch.md) | Declare route-level caching intent via segment-config exports — `dynamic`, `revalidate`, `generateStaticParams` |
| [`references/nextjs-conventions/client-third-party-scripts.md`](references/nextjs-conventions/client-third-party-scripts.md) | Mark cacheable Server Components/functions explicitly with `'use cache'` — never rely on implicit caching |
| [`references/nextjs-conventions/client-use-client-boundary.md`](references/nextjs-conventions/client-use-client-boundary.md) | Server content reaches inside a Client Component via `children` or named slots — not by being imported |
| [`references/nextjs-conventions/cross-boundary-coherence.md`](references/nextjs-conventions/cross-boundary-coherence.md) | SSR and client initial render must produce identical HTML — defer browser-only or time-varying values to a post-mount effect |
| [`references/nextjs-conventions/cross-component-consolidation.md`](references/nextjs-conventions/cross-component-consolidation.md) | Wrap third-party scripts in `next/script` with the right `strategy` — never `<script src=...>` in the layout `<head>` |
| [`references/nextjs-conventions/cross-dead-code.md`](references/nextjs-conventions/cross-dead-code.md) | Push the `'use client'` directive down to the interactive leaf — not up at the route/layout |
| [`references/nextjs-conventions/cross-extract-shared-logic.md`](references/nextjs-conventions/cross-extract-shared-logic.md) | Audit `'use client'` placement across the route tree — demote files (or whole subtrees) that don't need the client |
| [`references/nextjs-conventions/cross-prop-shape-drift.md`](references/nextjs-conventions/cross-prop-shape-drift.md) | Consolidate near-duplicate routes/layouts/components into one with variants or composition |
| [`references/nextjs-conventions/meta-generate-metadata.md`](references/nextjs-conventions/meta-generate-metadata.md) | Delete unreachable routes, unused Server Actions, and orphan components/utilities |
| [`references/nextjs-conventions/meta-opengraph-images.md`](references/nextjs-conventions/meta-opengraph-images.md) | Extract duplicated server-side fetchers/actions into a shared module |
| [`references/nextjs-conventions/meta-robots.md`](references/nextjs-conventions/meta-robots.md) | Converge on canonical names when the same concept wears different prop/param names across routes and components |
| [`references/nextjs-conventions/meta-sitemap.md`](references/nextjs-conventions/meta-sitemap.md) | Dynamic routes export `generateMetadata` so each variant gets per-resource title/description/OG image |
| [`references/nextjs-conventions/route-intercepting-routes.md`](references/nextjs-conventions/route-intercepting-routes.md) | Generate per-page OG images at the route via `opengraph-image.tsx` — not a static fallback in `public/` |
| [`references/nextjs-conventions/route-not-found.md`](references/nextjs-conventions/route-not-found.md) | Make crawl rules explicit via `app/robots.ts` and per-page `metadata.robots` — don't rely on "they won't crawl this" |
| [`references/nextjs-conventions/route-parallel-routes.md`](references/nextjs-conventions/route-parallel-routes.md) | Generate sitemaps at build/request time from the actual data — never hand-maintain `public/sitemap.xml` |
| [`references/nextjs-conventions/route-prefetching.md`](references/nextjs-conventions/route-prefetching.md) | Modal/lightbox detail views with shareable URLs should use intercepting routes — not client-state modals |
| [`references/nextjs-conventions/route-proxy-ts.md`](references/nextjs-conventions/route-proxy-ts.md) | A missing dynamic resource calls `notFound()` to produce a real HTTP 404 — never returns "not found" inline JSX with a 200 status |
| [`references/nextjs-conventions/server-avoid-client-fetching.md`](references/nextjs-conventions/server-avoid-client-fetching.md) | Multi-region layouts that show independent content per region should use parallel-route slots, not one mega `page.tsx` |
| [`references/nextjs-conventions/server-component-streaming.md`](references/nextjs-conventions/server-component-streaming.md) | Tune `<Link prefetch>` to traffic likelihood — disable on low-traffic links, prefetch-on-hover for conditional routes |
| [`references/nextjs-conventions/server-data-colocation.md`](references/nextjs-conventions/server-data-colocation.md) | Network-boundary logic (auth, redirects, header rewrites) lives in `proxy.ts` — not the deprecated `middleware.ts` |
| [`references/nextjs-conventions/server-error-handling.md`](references/nextjs-conventions/server-error-handling.md) | Initial page data lands in the HTML via a Server Component — never via `useEffect`+`fetch` or client-side data libraries |
| [`references/nextjs-conventions/server-parallel-fetching.md`](references/nextjs-conventions/server-parallel-fetching.md) | Wrap each independently-paced async leaf in its own `<Suspense>` so fast content streams without waiting for slow tiles |
| [`references/nextjs-conventions/server-preload-pattern.md`](references/nextjs-conventions/server-preload-pattern.md) | Each Server Component fetches the data it renders — pull data to the leaf, not the route root |
| [`references/nextjs-conventions/stream-error-tsx.md`](references/nextjs-conventions/stream-error-tsx.md) | Contain each async failure to its own subtree via `error.tsx` or `ErrorBoundary` — one bad fetch must not take down the route |
| [`references/nextjs-conventions/stream-loading-tsx.md`](references/nextjs-conventions/stream-loading-tsx.md) | Independent server fetches run concurrently — sequential `await` is a server-side waterfall |
| [`references/nextjs-conventions/stream-nested-suspense.md`](references/nextjs-conventions/stream-nested-suspense.md) | Trigger critical data fetches at the top of the route via a `preload` call — don't wait for the descendant to mount |
| [`references/nextjs-conventions/stream-skeleton-matching.md`](references/nextjs-conventions/stream-skeleton-matching.md) | Every route should have an `error.tsx` next to it — a failed fetch must not kill the framework chrome |
| [`references/nextjs-conventions/stream-suspense-boundaries.md`](references/nextjs-conventions/stream-suspense-boundaries.md) | Every route should have a `loading.tsx` next to its `page.tsx` — never leave navigation showing a blank screen |
| [`references/nextjs-conventions/action-optimistic-updates.md`](references/nextjs-conventions/action-optimistic-updates.md) | Next.js 16 App Router review/refactor algorithm: category-major judgment, scoped or repository-wide audits, coverage, and findings |
| [`references/nextjs-conventions/action-pending-states.md`](references/nextjs-conventions/action-pending-states.md) | Next.js review categories and impact levels: build, cache, server, route, action, stream, metadata, client, and cross-file hygiene |
| [`references/nextjs-conventions/action-revalidation.md`](references/nextjs-conventions/action-revalidation.md) | Server Actions return a typed error/state result — never throw silently or rely on the client to know what failed |
| [`references/nextjs-conventions/action-server-action-forms.md`](references/nextjs-conventions/action-server-action-forms.md) | Mutations whose UI outcome is predictable apply optimistically with `useOptimistic` — automatic rollback on server failure |
| [`references/nextjs-conventions/_sections.md`](references/nextjs-conventions/_sections.md) | Source section template retained with the imported Next.js convention set |

### Migrated source indexes

| Source | Description |
|--------|-------------|
| [`references/sources/api-aggregation-patterns/`](references/sources/api-aggregation-patterns/source-index.md) | Aggregated API endpoints for dashboard views |
| [`references/sources/api-aggregation-patterns/references/getProjectDetail-pattern.md`](references/sources/api-aggregation-patterns/references/getProjectDetail-pattern.md) | Detailed aggregated project endpoint pattern |
| [`references/sources/ingenium-ops/`](references/sources/ingenium-ops/source-index.md) | Ingenium MCP/API layering, dashboard consistency, seeding, and tool parity |
| [`references/sources/ingenium-ops/references/dashboard-ui.md`](references/sources/ingenium-ops/references/dashboard-ui.md) | Ingenium dashboard component patterns |
| [`references/sources/ingenium-ops/references/layered-crud.md`](references/sources/ingenium-ops/references/layered-crud.md) | Ingenium layered CRUD pattern |
| [`references/sources/ingenium-ops/references/mcp-tool-parity.md`](references/sources/ingenium-ops/references/mcp-tool-parity.md) | Ingenium MCP and API parity pattern |
| [`references/sources/language-conventions/`](references/sources/language-conventions/source-index.md) | Go and Rust idioms, error handling, formatting, and testing |
| [`references/sources/mail-app-ui-conventions/`](references/sources/mail-app-ui-conventions/source-index.md) | Mail sync, progress, explicit UI, cache, sender, and settings rules |
| [`references/sources/visual-standards-conventions/`](references/sources/visual-standards-conventions/source-index.md) | Ingenium overlay, status-card, CSS-variable, and orchestration visual standards |
