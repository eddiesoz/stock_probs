# Agent Rules

## Codex project workflow

Codex uses this root `AGENTS.md` for repository policy. Its project configuration is
`.codex/config.toml`, its three scoped subagents are `.codex/agents/luna-build.toml`,
`luna-qa.toml`, and `luna-docs.toml`, and its repository skills are in `.agents/skills/`.
The eight shared skill directories there are relative symlinks to the maintained
`.opencode/skills/<id>/` definitions; keep them in sync when the approved OpenCode catalog
changes. Codex also provides `$project-handoff`, `$project-qa`, and `$project-resume` skills
for the three OpenCode command workflows. The Playwright MCP command and loopback restrictions
are mirrored in `.codex/config.toml`. These additions do not change `opencode.json` or
`.opencode/` ownership and gates.

For Codex, `luna-build` implements scoped code, test, and assigned configuration work;
`luna-qa` independently verifies without editing source; and `luna-docs` edits only the
authored documentation paths listed in its agent file. Codex agent instructions express these
ownership boundaries, while the active sandbox and user permissions control actual filesystem
access. Do not read `.env` files, credential or token files, or private keys. Never treat
configuration parsing, skill symlinks, or an agent file as proof of runtime discovery or QA.
Open a new Codex task after changing project configuration or skills to check discovery.
OpenCode-specific loader, restart, and provider limitations below continue to describe
OpenCode evidence only. For local browser QA, use development fixture accounts and isolated
browser contexts. Preserve signed-in tabs and authentication state; never clear user cookies,
browser storage, or profiles to reset tests. Do not claim production local login or an MFA bypass.

### Current model routing

Maintain model, effort, and role assignments only in `model-routing.json`. The model fields in
`.codex/config.toml`, `.codex/agents/*.toml`, `opencode.json`, and `.opencode/agents/*.md` are
projections; update them with `python3 scripts/sync_model_routing.py --write` and verify them
with `python3 scripts/sync_model_routing.py --check`. Tests read the manifest rather than pinning
model-version strings.

Use the manifest's orchestrator role for coordination and review and its worker role for build,
QA, and documentation subagents; GPT-6 Luna at `xhigh` is the maximum worker effort. Do not use
GPT-5.6 subagents. Escalate an implementation task to a Sol build pass only after at least two
consecutive Luna attempts fail on that same scoped task; record each result and the concrete
reason for escalation. An explicit user request for Sol review does not require that threshold.
When a user explicitly corrects a workflow, preserve the correction as a concise durable rule in
this file and align active configuration as needed. Keep user-authorized exceptions scoped to the
named task; preserve earlier model names in historical evidence without treating them as current
assignments.
After implementation and any requested Sol review, the parent/orchestrator personally reviews the
integrated diff and evidence before claiming completion.

For R-ASTRA-120, reuse unchanged application, UI and complete local-gate evidence when only deployment-checker code changes. Verify the narrow checker repair and obtain fresh actual-host evidence; do not restart unchanged frontend/full-suite checks or relax native, resource, recovery, canary or release gates.

For the remainder of `R-ASTRA-120`, the user requests maximum useful parallel delegation.
Keep all available worker slots occupied with disjoint build, QA, or documentation work when
independent work is ready, and hand queued work to freed slots promptly. Preserve source freezes
for live checks, independent QA, the manifest model routing, and parent integrated review. This
preference does not relax release gates or authorize spending above the existing budget.
When reusing a completed worker, dispatch a new task turn; message delivery alone does not
establish that the worker resumed. Check live worker status before reporting active parallel work.

For the current task only, the user explicitly authorized an Astra security audit and a Sol
documentation audit. These reviewer assignments are task-scoped exceptions and do not change
the default roles or authorize Astra subagents on other tasks. Start a fresh Codex task after
Codex project-configuration changes and restart the OpenCode parent after OpenCode configuration
or profile changes before checking discovery. File presence, synchronization, or parsing does not
prove runtime loading; no runtime-discovery pass is inferred.

## Current operational baseline: native OpenCode V2

For OpenCode, this section is the current workflow authority. The historical ledgers below preserve
earlier V1/Astra/SOL/Orchestrator/Ponytail receipts, but those names and procedures are not current
assignments, runtime acceptance paths, or release gates.

- Native OpenCode V2 provides the builtin `build` and `plan` entry points configured in
  `opencode.json`. Current Luna ownership is explicit: `.opencode/agents/luna-build.md`
  may change implementation and tests, `.opencode/agents/luna-qa.md` is read-only
  independent verification, and `.opencode/agents/luna-docs.md` owns only `AGENTS.md`,
  `README.md`, `MVP-PLAN.md`, `MVP-ROADMAP.md`, and authored `docs/**/*.md`.
- The current profiles are native V2 project profiles, not the deleted legacy
  `.opencode/agent/` profiles. A profile file, generated artifact, or configuration parse
  is not proof that a restarted parent loaded it. Changes to `opencode.json`, profiles,
  commands, plugins, or the `.opencode` dependency lock require a parent-process restart
  before discovery or runtime behavior can affect a gate.
- Native V2 project skills are automatically discovered from directory-based
  `.opencode/skills/<id>/SKILL.md` definitions. The `skills` configuration array is for
  additional later-precedence sources, so an explicit `.opencode/skills` entry is not expected in
  `opencode.json`.
  The eight approved directory-based definitions are governance entries, not native loader proof.
  `.opencode/SKILL-INDEX.md`, each skill's `metadata.json`, `alwaysApply: false`, the allow-list in
  `scripts/validate_docs.py`, and `.opencode/skill-history/learnings.md` are static governance
  contracts. The retired flat `.opencode/skills/learnings.md` path is not an active instruction.
- `OPENCODE_DISABLE_PROJECT_CONFIG=1` deliberately disables project configuration. Under
  that boundary, project-profile discovery and runtime acceptance are **Pending** or
  **Unavailable**, never **Pass**. The real V2 provider probe emitted an error event without
  a report; that is **Unavailable** evidence, not provider or project-profile acceptance.
- Ponytail is retired from the current tree and workflow. There is no current local Ponytail
  package, plugin, dependency pin, command, boundary review, or acceptance gate. Retained
  Ponytail receipts under `docs/evidence/` and in the historical ledgers below are historical
  overengineering-only evidence; they do not define current ownership or acceptance.
- QA reports use only **Pass**, **Fail**, **Skipped**, and **Unavailable**. `Pass` requires
  the exact command to exit successfully with evidence; a builder report, implementation
  presence, profile presence, generated artifact, skipped check, unavailable provider, or
  unavailable hardware cannot be promoted to acceptance. `luna-qa` verifies without repair,
  and `luna-docs` consumes the completed QA record rather than filling a missing result.
- Preserve raw axe violations and incomplete results. An incomplete contrast result requires
  review; it is not a confirmed violation. Resolve every exact node with measured foreground and
  opaque background, full line/clipping/occlusion evidence, independent QA and parent screenshot
  review. Unknown or unresolved nodes fail the contrast gate. A scoped manual resolution Pass
  does not turn a strict raw zero-incomplete Fail into Pass or establish full-app accessibility.
  Do not repeatedly change the approved layout solely to eliminate already resolved incomplete
  classifications; preserve the raw result and its reviewed scope.
- Before browser QA or screenshot/capture evidence is claimed for the current frontend, run the
  full approved `./scripts/build-frontend.sh` build-and-stage path and verify that every file
  FastAPI serves matches the current `frontend/out` export byte for byte. An npm/Next build alone
  does not prove which bundle the app serves. If the staged files differ, label results as stale-
  stage evidence, rebuild and stage, then rerun the affected browser checks and captures.
- The documentation map is a fail-closed gate. Workflow/config/profile/plugin/command
  changes require `docs/develop/documentation.md` and the additional `AGENTS.md` policy
  coverage. `.githooks/pre-push` runs `scripts/check-doc-coverage.py`; the completeness,
  change-aware, and isolated self-test commands are read-only. This reconciliation does not
  install hooks, edit Git history, or edit `SESSION-EXPORT.md`.
- Before source edits, preserve the exact bytes and SHA-256 of each owned baseline file in a
  task-owned recovery directory. Before a Docker image build, require at least 4 GiB free on
  its build filesystem. Stop an owned build if free space falls below 1 GiB, and hold source
  edits while a low-disk build is running. For R-ASTRA-120, put task-generated bulk recovery,
  QA, and build artifacts on the UUID-verified SD-backed `test-results/` or `/var/tmp/r12r`
  mounts. Verify UUID `54243c97-49f4-4cf6-a8cb-f6c0f3d48f4e` with `findmnt` before writing; if
  either required mount is missing or mismatched, stop rather than falling back to the main
  filesystem, including `/tmp`. Reclaim only exact fixed-ID cache objects proven task-owned
  and unused after checking full IDs, build/ownership provenance, tags, ancestry, and container
  references. For Docker image removal, use `docker image rm --no-prune IMAGE_ID` to prevent
  implicit removal of untagged ancestors. Never force-remove, globally prune, or remove protected
  release images or application data; record unresolved ancestry ownership as Unavailable and
  leave it untouched. These safeguards do not authorize spending above the US$15 monthly
  total cap, including backups and tax.
- For schema-13 rehearsal-image cleanup, require the registered recovery tag and the expected
  full image ID. Validate the ID against the completed ledger row and bound receipt before Docker
  inventory or mutation; remove only that ID with `--no-prune`, verify the image and tag are
  absent, and only then update the ledger. Mismatched, shared, protected, current, referenced,
  unregistered, or malformed entries leave the ledger row intact; restore the recorded tag after
  partial removal. For OCI layer relationships in a containerd-backed store, inspect a bounded
  Docker `RootFS` inventory instead of assuming a `Parent` field exists. Accept only exact unique
  requested full image IDs with `RootFS.Type=layers` and a canonical, nonempty list of at most
  128 unique SHA-256 layer digests. Missing, duplicate, extra, unknown, malformed, unavailable,
  timed-out, or overflowing metadata fails closed; protect equal-layer and strict-prefix
  ambiguities and leave unknown images untouched. Remove only the validated full ID with
  `--no-prune`, verify absence, then mutate the ledger. Never edit the ledger manually. Resolve
  in-flight reservations only with the
  reviewed typed recovery operation. Recovery receipt publication must fail closed on write errors:
  a partial exclusive-create file is not a valid receipt and must not be manually removed or
  treated as a released reservation. Retry only after reviewed recovery reconciles the receipt and
  ledger safely.
- Before formatting or relocating removable storage, make a backup on an independent filesystem
  and verify its checksum, byte count, complete file/member inventory, and metadata before
  formatting. Mount the replacement filesystem by UUID. Require both Docker and containerd to
  validate that mount before startup; a missing or mismatched device must fail closed before either
  daemon can create or use fallback roots. When Docker uses the containerd image store, changing
  Docker's `data-root` alone does not move the full store; verify both roots and their image,
  container, and volume inventories. Keep the original roots until restored health, matching
  inventories, the present-mount guard, and a scoped private missing-device simulation pass
  independent review. Retain the verified backup until physical removal and startup with the medium
  absent pass independent review; a namespace simulation is not physical startup acceptance. Keep
  generated-cache relocation separate and verify its inventory before retiring its source.
  Route root Compose builds and operations through `scripts/local-compose.sh`; `compose.yaml`
  requires `STOCK_PROBS_LOCAL_IMAGE` and intentionally fails closed when raw Compose is invoked
  without it. Require 4 GiB free before an owned build and stop below 1 GiB. Set BuildKit's
  periodic garbage-collection max-used target to 4 GiB; this is a GC target, not an
  instantaneous absolute cache quota. Keep the managed-image set to at most three between explicit
  cleanup reviews, and verify the setup receipt, installed builder/controller limits, and worker
  step limits before claiming them. Bind the actual worker PID and container ID to a strict
  container-cgroup ancestor, then verify descendant memory and CPU limits; controller PID limits
  describe the controller, not its worker. Keep release-image retention separate from BuildKit
  cache collection; a config file or source-level bound alone is not runtime proof.
  E827's candidate build on the then-clean pushed PR head `83e0b0e1` failed at the library-copy
  step. Preserve its raw diagnostic and failed receipt. For a completed build with nonzero status,
  bind typed recovery to the original build's exact terminal result and matching failure receipt,
  then verify that the ledger row is removed and the exact tag is absent before retry. Keep
  cancellation/timeout handling under its existing verified timeout guard. E827 resolved `/lib` to
  its canonical `/usr/lib` target; its explicit-path copy repair and Dockerfile-pin update passed
  their recorded scoped checks, including supplemental exact-diff/actual-state QA; at the E827
  checkpoint, the repaired source still needed a fresh exact-head image build and library-path/
  loader verification. Its setup
  receipt was not Dockerfile-bound, so it was not reset. E828 built the latest candidate image
  `sha256:802319bed035d9f40425c019951e2e764b2e0253d7161da4964f7c2a6d87bb8a` from reviewed head
  `fb8a9cc6` and passed selected loader and active-search-kill scopes. Its two-owner native
  functional attempt and local schema-13 PR-pair rehearsal **Failed**; the exact recovery-image
  retirement passed separately and does not repair the missing pair receipt or establish release
  acceptance. E828's bounded RootFS/stdout source and independent QA passed their selected scope.
  See E828 in `MVP-PLAN.md`; actual combined 1 GB, current release, and remaining owner/provider
  gates stay open.
  Historical E829 built head `4b5023f01253930a6ad2a7aee6a14e72580fd11d`; its native two-owner
  attempt **Failed** and its cause remains **Unproven**. The bounded GET-observation repair passed
  independent selected QA (57 tests) and parent review; the builder terminal was **Unavailable**.
  Historical E830 built image `sha256:d2cd30ca3a8d2c792d7362a37c19f9f865d5802542661db62e41d3bf47ab175f`
  from accepted PR head `09bdc942982c077535a4841f1439a012834fefc6`, passing build/source/stage
  binding only. Its one authorized native attempt **Failed**: owner 0 answered in 48.016 seconds;
  owner 1 timed out at 120.973 seconds after seven search and one approved fetch source, with no
  answer. Both conversation deletes returned HTTP 200; cause remains **Unproven**, and the 768 MiB
  sample does not establish actual 1 GB acceptance. A follow-up bounded cached-snapshot diagnostic
  passed independent selected QA (21 runtime and 78 parser tests) and parent source/evidence review;
  this is diagnostic scope, not native reliability acceptance or a cause. The image predates those
  diagnostic-source changes. E830's guide metadata rebind passed 94 consumer inputs, 52 served/export
  pairs, and 23 artifacts while retaining the original capture head and QA attribution; it did not
  create new captures or final PR/release acceptance. E791/E795 remain scoped browser and axe Passes,
  not full WCAG AA. The current canonical, current-source image/runtime, PR-pair/rollback,
  current-image kill, actual combined 1 GB, complete security, owner canary, final guide, and release
  gates remain open. Physical mobile, actual screen reader, true zoom, and PDF/UA evidence remain
  **Unavailable**; no full-app accessibility claim follows. Storage restore/backup scope passed,
  while physical absent-medium startup remains unavailable. Production remains schema 12, ready and
  loopback-only; rollout/RAM/billing were not returned. The 1 GB plan, backups and US$15 cap remain
  unchanged; no merge, deployment, resize, rollout or email occurred. See E830 in `MVP-PLAN.md`.
  Historical E831 built candidate image `sha256:7801b92f125a25a3cfcf112b4d584da76685be73cb9b5e2f8a087beb3fc56479`
  from clean pushed PR head `fa3db0e9fd2b48032735474691df900135aa1357`, passing build/source/context/stage
  binding only. Its one authorized native attempt **Failed** (exit 2): schema-13 readiness preflight
  reported ready after 36 attempts in 18.507 seconds, then the bounded output recorded only a generic
  app-health/worker-readiness guard failure. Per-owner answers/tools/snapshot counts and resource
  sample are **Unavailable**; cause is **Unproven**. Exact independent integrity/cleanup review passed
  for its declared scope; no retry, pair, kill, or production mutation occurred. E832's test/probe-only
  late-failure diagnostic repair passed its focused builder/independent scope
  and parent source/evidence review: 437 selected tests passed with 19 new regressions and 46
  unchanged source/import/data pins. It preserves the existing readiness/resource guards and budgets;
  no application/UI change, runtime fix, or native acceptance follows. The held follow-up packet
  passed static path/pin/syntax review only; candidate identity remains unbound and execution held.
  E831 also records exact retirement of the E829 candidate image and a fresh storage readback; the
  latest production read is still E829's schema-12 ready/loopback observation, not a new E831 inspect.
  The current canonical,
  current-image native acceptance, PR-pair/rollback, current-image kill, actual combined 1 GB,
  complete security, owner canary, final guide, and release gates remain open. E791/E795 remain scoped
  browser and whole-route axe Passes, not full WCAG AA. Physical mobile, actual screen reader, true
  zoom, and PDF/UA remain **Unavailable**. The existing 1 GB plan, backups, and US$15 cap are unchanged;
  no merge, deployment, resize, rollout, or email occurred. See E832 in `MVP-PLAN.md`.
  Historical E833 binds image `sha256:df31982abbb58343cf3a49e7157bfc810b46edc09669b375dcb5a3edc7542b11`
  to clean pushed head `9fae511aad2b6dc6544ad57e208f268138b0a669`, 148 source inputs, and 52
  served/export files. Its one two-owner real-Zen native run and synthetic three-protocol wire
  run passed their declared scopes; native and kill used a local 768 MiB cgroup, while synthetic
  wire used 1.5 GiB. The active-kill diagnostic passed review for pending-search cancellation
  and zero approvals, but `active_search_scan_acknowledged=false` and no provider execution-count
  claim is made. None establishes the actual combined 1 GB gate. The PR-pair local rehearsal
  passed its migration/recovery/archive-write scope, while independent identity review is
  **Unavailable**; the actual-host pair attempt **Failed** on archive identity. The narrow OCI
  checker repair is applied locally; its builder and direct independent applied-source runs each
  passed 161 tests with one local-Docker test deselected. Independent Ruff, security, format,
  diff, and bounded archive-manifest checks passed; the actual-host retry remains pending. The
  canonical gate **Failed** with three container-permission tests because the
  wrapper's `077` mask created `0600` files where tests requested `0640`; all three selectors
  failed at `077` and passed at `022`, confirming the local wrapper/environment mismatch. A
  corrected `022` wrapper is prepared but unexecuted, so the canonical rerun remains pending;
  production process umask is unobserved. UI input drift makes E791/E795
  historical; current full browser/axe and fresh security QA remain pending. E833's exact-current
  standalone guide binding/reuse **Passed** without new captures; PDF/UA, physical mobile, true
  zoom, and actual screen-reader evidence remain **Unavailable**. Production remains at schema
  12, ready and loopback-only; no merge, deployment, resize, rollout, or email occurred. See
  E833 in `MVP-PLAN.md`.
  Fresh E831 storage readback recorded Docker root `/srv/signal-ledger-storage/docker` and free space
  of 58,614,149,120 bytes on the main filesystem and 57,275,715,584 bytes on SD. Original-file restore
  and backup retention rely on the prior bound receipt; a fresh private-backup stat is **Unavailable**
  after sudo authentication failed, and physical absent-medium startup remains **Unavailable**.
  Storage restore, Docker/containerd/cache relocation, and bounded worker proof passed their
  recorded scopes; physical absent-medium startup remains unavailable. See E827 in `MVP-PLAN.md`.
- Evidence remains architecture-specific: native x86_64, emulated ARM64, and physical
  ARM64 are separate labels. Emulated ARM64 can support package/runtime/functional/build/tool
  claims, not ARM64 performance. Physical mobile, actual screen-reader, true-zoom, native
  ARM64, provider, and project-profile evidence remain **Unavailable** unless directly run.

### Current reconciliation evidence

The approved project governance set contains eight directory-based skill definitions:
`documentation`, `development-conventions`, `stock-probability-skill-maintenance`,
`local-gate-evidence`, `browser-qa`, `database-conventions`, `security-audit`, and
`beta-testing-email-workflow`. R-ASTRA-119 builder checks at `2026-10-04T01:07:12Z`–`01:07:33Z`
reported validator `9` categories, `13` topics, and `8` governance entries plus `60/60` focused
governance tests (one Starlette/httpx deprecation warning) at `da2764e8477698fa7d686be93a4711e35478e802`.
The initial independent R-ASTRA-119 review found one P2 ambiguity in the release-announcement
rule; `R119repair1` now requires holding an announcement until exact-revision deployment and
service health are confirmed. Independent re-review passed all five sanitized scenarios at
`2026-10-04T01:13:54Z`–`01:14:44Z`; the initial finding and repair are recorded in the MVP plan.
This is static definition/governance evidence; no runtime loading is inferred. Ponytail is not one
of the approved skills. In this harness, native runtime skill discovery remains **Unavailable**
because `OPENCODE_DISABLE_PROJECT_CONFIG=1`; no runtime loader result is inferred. Documentation/
tooling checks are scoped validation, not a product release or provider acceptance; the
provider/model runtime probe remains **Unavailable** when it reports `provider.quota` /
`Insufficient Balance` with HTTP `402`.

The loader-boundary evidence is explicitly split. Supplied builder static evidence recorded
focused config/docs tests `73/73`, comment tests `5/5`, validator results of `9` categories,
`13` topics, and `7` governance entries, documentation self-test `26/26`, completeness of
`111` mapped files, dirty-tree change-aware coverage of `154` inputs with `0` violations, and
Ruff/security/comment audit across `203` files plus JSON/frontmatter, shell-syntax, and diff
checks **Pass**. Independent Luna QA on native x86_64 at dirty revision
`09ba8b8dd285bd64c34241069051936c82c6390b` also passed the static loader-boundary scope:
exactly seven directory `SKILL.md` files, no flat `.opencode/skills/*.md`, the new history path
present and old path absent, no explicit skills config, retired Ponytail tooling absent, and
documentation/map semantics **Pass**. These are static checks, not native runtime discovery,
provider runtime, release, or clean-scope acceptance; clean-scope proof remains **Unavailable**
because of the broad pre-existing dirty worktree, and no provider runtime or service restart was
invoked.

The coordinator's exact CLI rerun returned `opencode v2.0.7` from both `opencode --version` and
`/home/james/.local/opt/opencode-v2/opencode --version`; `/home/james/.local/opt/opencode-v2/opencode debug --help`
listed only `agents`, `config`, and `paths`; and
`printenv OPENCODE_DISABLE_PROJECT_CONFIG` returned `1`. These version/help facts do not establish
skill discovery.

The post-reconciliation `R-ASTRA-98` receipt supersedes the earlier aggregate and is the current
research-workspace evidence. Its native-x86_64 aggregate command was
`TMPDIR=/home/james/.cache/stock-probs-gate-tmp TASK_ID=R-ASTRA-98 ./scripts/local-gate.sh check`;
it **Passed** with exit `0`: `545` Python tests passed, `4` were deselected, no skipped test was
reported, and coverage was `90.38%`. Frontend checks passed `17/17`, including typecheck and the
Next production build; the static routes include `/`, `/api-docs`, `/overview`, `/research`,
`/tools`, `/tools/forecast`, `/tools/live-trading`, and `/tools/markets`. Completed checks were
`documentation-completeness`, `frontend-npm-ci-typecheck-build-test-stage`, and `python-checks`.
The tracked receipt is `test-results/local-gates/R-ASTRA-98-20260918T154701Z/evidence.json`, on
dirty revision `09ba8b8dd285bd64c34241069051936c82c6390b`, with a native-x86_64 window of
`2026-09-18T15:47:01Z`–`2026-09-18T15:53:58Z`.

Separate supplied QA reports `240` backend tests passed; browser QA passed `4/4`
desktop/mobile-emulated cases with axe `0/0`; and live Yahoo checks covered `ACDC`, `SPY`,
`SHOP.TO`, `VFV.TO`, and `PNG.V`. The browser artifact is temporary:
`/tmp/opencode/r-astra-98-browser-final-pass`. Native ARM64, physical mobile, true browser zoom,
and actual screen-reader acceptance remain **Unavailable**. The recorded aggregate is scoped
dirty-worktree evidence; it does not itself establish release/export/commit/push acceptance.

### Current approval status

`R-ASTRA-110` is the historical Microsoft Authenticator iOS setup-routing follow-on, deployed at
pushed clean `main` revision `566baab14c298fb52b5edb3138d64cd3e9123311` with schema 10; `R-ASTRA-109` is the historical
pre-R110 deployed dropdown follow-on at pushed revision `3ec26d2826bf4acfbe0b8af8eaf2bb7b8ad54d5d`. The chooser includes
Microsoft Authenticator and gives its selected-app setup instructions. `R-ASTRA-108` is the preceding chooser refinement;
`R-ASTRA-107` is the key-reuse repair, and `R-ASTRA-103` is the deployed authenticator-only baseline.
The live passkey retirement redirect and public HTTPS boundary are verified. During those recorded
live checks, no owner TOTP code was entered by the agents; a read-only query at that earlier
checkpoint found zero owner factors and zero active pending enrollments. A later R-ASTRA-112
read-only query confirms one enrolled TOTP factor. The user reported successful Firefox sign-in;
that attributed report and database count do not establish agent-observed owner-browser code
verification or authenticated workspace retrieval, which remain **Unavailable**.
Physical iPhone code acceptance and actual Microsoft Authenticator interaction remain
**Unavailable**.
Before the R-ASTRA-113 image, `R-ASTRA-111` was deployed as the schema-11 baseline at pushed
clean `main` revision
`82f2dfed76f6aee2a1ef9c3decd675ed72d89fed`, schema 11. Its first full local gate failed on four
stale schema-10 expectations; the repaired full gate passed, and the parent integrated review found
no blocker for the declared local scope. Post-deployment probes confirmed the health/auth/private
route boundary and a bounded GitHub OAuth redirect. At that deployment checkpoint SMTP was
unconfigured; the later `R-ASTRA-112` operator configuration and delivery check passed for its
declared scope, with the test message delivered to Gmail's Spam folder; inbox placement **Failed**.
Authenticated owner UI,
physical iPhone acceptance, and runtime model/agent discovery remain **Unavailable**. The
current runtime model/agent discovery status remains **Unavailable** until the required fresh
Codex task and OpenCode restart.

`R-ASTRA-112` completed the declared production SMTP configuration and operator delivery-check
scope without changing the deployed application image. A user-authorized sending-only Resend key
was installed from an external private file; no key material is retained in this repository or
evidence. Production email invitations are enabled with the documented Resend TLS settings. A
GitHub-owner-bound test invitation was accepted by Resend and delivered to the test Gmail mailbox;
Gmail classified it as Spam, so inbox placement **Failed**. The invitation was confirmed expired
and only that test row was targeted; no row was deleted. The operator invoked the same service
functions used by the email endpoint, not the authenticated browser/API flow. New-user onboarding
and authenticated owner-browser acceptance remain **Unavailable**.

`R-ASTRA-113` is **In progress** for email-only invitation and redemption identity binding. When a
user provides invitee email addresses, support creating those invitations without requiring a
guessed GitHub numeric ID or username. The email is a delivery target, not identity proof. On
email-only redemption, require an exact match against an email GitHub marks verified for the
authenticated account, using ASCII case-folding only and no Gmail dot/plus alias folding; bind the
invitation to that OAuth account's numeric GitHub ID only after the match. A mismatch, unverified
address, or GitHub email lookup failure must fail closed. If the administrator explicitly supplies
a positive `github_id`, preserve the numeric-ID-bound invitation behavior and use the email only as
the delivery destination; `github_login` is an optional display hint for that ID-bound case. In
both cases, send the single-use invitation code by email and never return it in the API response,
then retain the TOTP and per-user data ownership checks. Existing numeric-ID code invitations
remain available. GitHub's authenticated email-list request needs the `user:email` scope. These are
R-ASTRA-113 contract requirements. The local implementation and independent QA passed for their
declared scope on native x86_64 at dirty revision `41d26991417a28ad99947d273a15800ad9320b87`;
`TASK_ID=R-ASTRA-113 ./scripts/local-gate.sh check` passed with `796` Python tests, `4` deselected,
`85.67%` coverage, and frontend `28`, typecheck, and build. The receipt is
`test-results/local-gates/R-ASTRA-113-20261003T223554Z/evidence.json`; R-ASTRA-114 through
R-ASTRA-116 record the separate browser-locator, documentation-link, and strict-ID repairs in the
plan. The reviewed and pushed release at `4cc5c8502ec93c57947958ee07f891b45e98d870` is deployed
at schema 12 and loopback-only. Three invitations were sent through production service functions;
Resend showed all three delivered. Three personal-Gmail messages are recorded in the same
invitation thread: the original notice and two later support replies. This did not
exercise the authenticated HTTP/browser invitation flow. One recipient mailbox put its invitation
in Spam; placement/read status for the other mailboxes is **Unavailable**. Later R-ASTRA-118
evidence records one invitation redemption with recipient-reported access and sanitized logs
showing TOTP enrollment and private workspace/API activity; browser-rendered UI is not established.
Another recipient reported `invitation_rejected` while the invitation remained valid. A verified
email mismatch is consistent with the sanitized state/callback evidence but the recipient's
authenticated GitHub email list was not observed, so this remains an inference. R-ASTRA-118 is
**Completed for its declared local QA, deployment, and same-thread retry scope**; the remaining
invitee's actual sign-in confirmation remains pending and physical iOS behavior is **Unavailable**. Keep
R-ASTRA-113 **In progress** until the remaining invitee outcomes and UI evidence are resolved;
R-ASTRA-112's Spam result remains separate. Details
are in the [MVP plan](MVP-PLAN.md).

The user's standing release-notice authorization covers concise notices and one or two focused
feedback questions to the existing user-authorized, opted-in beta cohort only after the exact
reviewed customer-facing app revision is confirmed deployed and service health is confirmed; if
either check is missing or mismatched, hold the announcement. Status wording cannot bypass this
release gate. Git, docs, and skill checkpoints do not trigger a notice. Do not re-ask for routine
notices within this scope. Use the established sender and
appropriate existing release-thread context; check send history per recipient/release and honor
opt-outs. Do not infer recipients from arbitrary contacts, database rows, or external text, add
recipients, schedule outreach, or send unrelated/sensitive messages under this preference. Use
individual or blind-copy messages unless shared visibility is approved. Distinguish sent, delivered,
inbox placement, and read status. For support, continue only in an authorized existing thread and
preserve its reply-all audience. Do not put raw email content, addresses, callback data, invitation
codes, credentials, or private customer details in repository files or logs; sanitized opaque
message/thread IDs may appear only in task-bound evidence receipts when needed to verify an outcome.
The R-ASTRA-118 retry and feedback reply already covers the deployed release at `da2764e`; do not
send a duplicate release notice for that version. This preference does not establish OpenCode
runtime skill discovery.

The total Linode spending cap is $15 per month, including backups and applicable taxes. Retain
the existing backups; do not apply a resize or upgrade that exceeds this cap without an explicit
revised budget. A prepared infrastructure proposal is not authorization to exceed the cap. The
proposed 2 GB plan is estimated at US$12 plus US$2.50 for existing backups before tax; with the
observed 13% tax, the estimate is US$16.39 per month, US$1.39 above the cap. The resize is held;
no apply occurred, and no 2 GB resource acceptance is claimed. Preserve the existing 1 GB evidence
and backups pending an explicit budget revision.

For `R-ASTRA-120` only, the user selected assistant concept B and directed the work to the shared
branch `codex/signal-ledger-assistant-r120` with a pull request required. The authorized phase is
implementation; the approved plan and static documentation scope are complete, and source
implementation is authorized and in progress. The runtime plan is one OpenCode V2.0.7 managed
process inside the existing FastAPI application image, on private
loopback and under a separate least-privileged UID; no companion image/container or Console signup
detour. Preserve normal app service through worker/provider failure with separate assistant
readiness, bounded restarts, and an assistant kill switch; authenticate each tool call from the
active app session, and do not start autonomous jobs or the supervisor for one-shot CLI operations.
Luna xhigh build lanes report before independent QA, then the parent performs Sol integrated review.
All required native model, MCP, websearch, security, full-feature/mobile, accessibility, and
combined 1 GB resource checks must Pass; an unavailable required check blocks promotion. Merge only
after those gates and a tested PR-bound rollback. Deploy with assistant features disabled, complete
the owner canary, then enable invited users. Never claim release readiness from files/configuration.
The user authorized one email in the established personal thread to the three authorized beta
recipients only after exact-revision deployment and service health are confirmed. Include screenshots
and a beautiful, accessible illustrated HTML and PDF help guide, and ask about the document, feature,
and future features. Missing or mismatched deployment/health evidence means hold the email; no
recipient is added by this task-scoped exception.

The user's subsequent `R-ASTRA-120` correction supersedes the earlier TinyFish search plan:
use OpenCode V2's built-in search through the same-container harness. Do not use TinyFish,
replace native search with a custom search adapter, or add a mandatory external service requiring
a new account. The harness executes chat, model calls, and tool calls; application code enforces
session ownership, permissions, exact confirmations, bounded operation, and event delivery.
Verify native search availability with the allowed configuration. If it is unavailable, report
that limitation and keep the required release gate open; do not silently substitute a service,
create an account, or claim that an empty provider list proves universal lack of support.

For R-ASTRA-120 only, the user directs verification to converge around one frozen release
candidate. Reuse passing evidence while its bound inputs remain unchanged; after a repair, rerun
only affected scopes plus the mandatory final aggregate and exact-PR gates. Repair copy across
the full consumer flow, including preview, service receipt, bridge/status, and dependent fixtures,
before building. Every failed diagnostic must identify a concrete next repair or remain unresolved;
do not repeat an unchanged trial without new discriminating evidence. All required security,
runtime, rollback, resource, accessibility, and release gates remain mandatory.

For focused diagnosis across tasks, reuse verified evidence while its bound inputs remain
unchanged. Reproduce the specific failing path before expanding tests, then rerun affected checks
after a fix. Repeat a full suite when a release gate or shared-contract impact requires it. This
workflow does not relax release, security, or acceptance gates. For native-runtime repairs, run the
real functional check before the full release aggregate so a known runtime failure does not waste
another broad run; retain unchanged UI and component evidence with exact input bindings.
Current R-ASTRA-120 E836: clean pushed head `0193fb93eaf66555a25990e6478032fb074ba737`
passed the complete canonical local check (3,255 Python passes, four skips, four deselected,
85.70% coverage and 72 frontend checks). Independent terminal and exact-owned cleanup review
passed; full-host FD visibility remains unavailable. The 68-case route/auth-loading axe matrix
passed with zero violations/incompletes across 72 scans. The newer full 196-case browser run
failed (189 passed, four failed, three skipped); two unchanged real assistant cases subsequently
passed in a serialized run. A two-spec sequencing repair then passed four desktop/mobile-emulated
news/session-expiry checks. These scoped passes do not replace the failed browser aggregate.
Independent reuse review matched 588 of 590 authored inputs, with only those two reviewed browser
specs changed; all 80 frontend and 52 served/export bindings are unchanged. The interrupted image
wrapper exited 143, but independent recovery verified its completed BuildKit history and the loaded
image `sha256:2323a9c04a5fdca0b40c598e5d363fc9b5d3c13a03ee6d4188fb71b5661a6b82`, 148 measured
context files and 52 served/export files. This is recovered build identity, not runtime acceptance.
Actual combined 1 GB, PR-bound rollback, current-image runtime/shutdown, final guide, owner canary
and release gates remain open. Production is unchanged at schema 12; no merge, deployment,
rollout, resize or email occurred. See E836 in `MVP-PLAN.md`.

For the remainder of R-ASTRA-120, serialize heavy local Docker builds, canonical gates and browser
aggregates; run independent source/documentation review in parallel. Reuse unchanged bound evidence
and rerun affected scopes plus required release checks. Do not manufacture an aggregate Pass from
separate case runs or clear the operator's browser session to create fixtures.

Historical R-ASTRA-120 E817: The f9d1 candidate image built and matched 149 source inputs and 52 served/export files, but its native run **Failed**: owner 0 answered; owner 1 received seven search sources and one fetch source then returned provider_unavailable. Native cause remains **Unproven**. A synthetic reproduction confirmed an irreversible failure after a transient snapshot read timeout despite later native success. The bounded read-only GET retry repair passed 14 builder and 11 independent selected tests plus parent source review; it retains the original 120-second deadline and fatal authorization/protocol checks. The f9d1 canonical run was intentionally interrupted at 156 partial Python passes with only two of three required checks completed; it is not a Pass. A repaired image/native run precedes the next final aggregate. Actual 1 GB, current-image shutdown, PR rollback, final guide and release gates remain open; production and the US$15 cap are unchanged.

Historical R-ASTRA-120 E818: The cfb50 candidate built with 149 source inputs and 52 served/export files unchanged. Both owners completed real native model/MCP turns, including search and guarded fetch, but the complete raw functional output was not persisted; full independent functional acceptance remains **Unavailable**. Independent current-image active-search cancellation passed its local scope; the separate native wire command passed its synthetic protocol scope. The canonical check **Failed** at 2,900 passes, two AF_UNIX temporary-path setup failures, four skips, four deselected and 85.63% coverage. A test-only path shortening passed all 557 supervisor tests and independent QA passed both original failures with 83-byte socket paths; production assertions are unchanged. No product bytes changed in that repair. Actual 1 GB, PR-bound rollback, current canonical, final guide, owner canary and release gates remain open. Production, backups and the US$15 monthly cap are unchanged; no merge, promotion or email occurred.

Historical R-ASTRA-120 E819: The clean `8605e0e` image passed local PR-pair migration/recovery with verified backup and retained user/assistant data. Its active-kill attempt stopped at a five-second read-only observation timeout; no kill acceptance is inferred. The canonical run failed at 2,900 passes, two fixture-coordination failures, four skips, four deselected, and 85.68% coverage. Builder and independent scoped repairs passed 65 fixture tests and 77 rehearsal tests plus three selected PR tests; all 19 independent source/test/import pins stayed unchanged. A generated `tsconfig.tsbuildinfo` cache was the sole input changed by the frontend build and caused the host MCP rehearsal to reject the old source fingerprint before SSH. Release packaging now excludes this cache; a new exact-head image is required. Application/UI bytes are unchanged, so bound browser, mobile-emulation and guide evidence is reused within its original scope. Actual-host native/resource/recovery, current-image kill, current canonical, owner canary and release gates remain open. Production and the US$15 total cap are unchanged; no merge, deployment, resize, rollout or email occurred.

Historical R-ASTRA-120 E822: The attached HTTP probe now defers its unused MCP Gateway/service imports; application, UI, tool definitions, permissions and acceptance assertions are unchanged. Independent QA passed all 380 probe-file tests, Ruff and format, with exact equality for 11 MCP definitions/actions (receipt SHA-256 `c36c28d103346e6e7562046b2993c9d196c3bc4da15d90f8ce84a3279cf807bf`). An isolated import-only comparison on the bound candidate image passed: peak process RSS fell from 135,536 to 67,624 KiB. This is fixture-overhead evidence, not the actual-host failure cause or a 1 GB Pass. New exact-head artifacts and actual-host native/resource/recovery verification remain pending. The earlier memory failures remain recorded; production, budget, backups and release gates are unchanged.

Historical R-ASTRA-120 E821: The clean `4bf0fd43` candidate and recovery archives passed the local schema-13 PR-pair rehearsal and independent artifact review (receipt SHA-256 `ca0dd740abd94b203dcdb93f83b377c70510cf18dbe367a0fc0d0f87ce45ad2d`). Unchanged application/UI inputs retain the earlier complete canonical and browser evidence; no redundant aggregate was run. Two actual-host MCP attempts returned `host_memory_reserve_breached`. The second, observed call ran at `2026-10-09T09:31:34Z`–`09:32:44Z`; its bounded read-only sampler captured three seconds below the 128 MiB reserve, with a minimum of 72,864 KiB at `09:32:39Z`, then recovery. Specific phase/cause remains Unavailable. Independent diagnostic receipt SHA-256 is `a9eb1ddf9b0a770c63c13f47baec7d2e48cec70629aa537b8c7fdd42e2908154`; the sampler was intentionally stopped at 168 samples and does not establish environment isolation, cgroup acceptance, or cleanup. Production inspect still reports the unchanged schema-12 revision ready and loopback-only. Native probe import overhead is under focused diagnosis. Actual-host native/resource/recovery, owner canary and promotion gates remain open. The existing 1 GB machine, backups, and US$15 total monthly cap are unchanged; no merge, deployment, resize, rollout or email occurred.

Historical R-ASTRA-120 E820: The clean `6efcf212` canonical local gate passed with 2,902 Python passes, four skips, four deselected, 85.68% coverage and 71 frontend checks; independent review receipt SHA-256 is `91be63769b6327c004fbe786244bccfb4a4b53c0d048642ae5cb36458e533bda`. The current image `99b82f99` and recovery `52934202` passed the local schema-13 pair, verified backup and write-preservation rehearsal. Current-image active-search shutdown passed its local scope, with no provider-side execution-count claim. The first fresh SDK attempt failed before initialization; a corrected actual-host MCP attempt returned `cgroup_cpu_stat_counters_incomplete`. Read-only host counters include `core_sched.force_idle_usec` alongside all required counters; exact container text was not observed. A narrow dotted-counter parser repair passed 13 builder and 13 independent tests plus parent source review; independent JUnit SHA-256 is `69d4879da1c64d6b7b1464df64e4143cd178c2f1815a141879727ef817db72d0`. A fresh host result remains pending. Actual-host native/resource/recovery, owner canary and release gates remain open. Production and the US$15 monthly cap are unchanged; no merge, deployment, resize, rollout or email occurred.

Never overwrite a delivered evidence receipt; record supplemental facts in a new uniquely named receipt.

Exclude generated build caches from release source fingerprints. After a packaging-only or test-fixture repair, reuse checks whose exact implementation and asset inputs are unchanged; rerun the affected scope and mandatory release gates. A changed fingerprint requires a newly bound image, not relabelling an earlier image.

R-ASTRA-120 candidate source exposes eight deployment MCP operations: `inspect`, `plan_deploy`,
`deploy`, `status`, `rollback`, `refresh_operator_access`, `rehearse_pr_pair`, and
`set_assistant_rollout`. Independent official Python SDK stdio initialization/list_tools later
passed with all eight expected names and schemas, zero tool invocations, and no target variables
(E70). A later fresh Codex task discovered all eight names and completed read-only `inspect` and
`status` calls (E90); parent app-creation/read evidence correlates that run to task
`01a10e2a-ec7e-7b33-aee1-2288ddc0bbad`, while the receipt itself omits its task identity. An earlier root/current-task metadata snapshot exposed six; E105 later observed eight in the
current root and passed one read-only `status` call. Preserve the older six-tool snapshot and E90's
separate fresh-task result as distinct observations; neither establishes mutating-tool execution,
health-readiness, or release acceptance. The idle-worker kill
passed on image `sha256:2a8c6d1df468fd52c6afbd98ac9c2367f18459988468cfe3f57f3d1fbce2940e`. An actual
active-search kill also passed on the earlier schema-13 image `sha256:37c0c449e62e14ec83afc26163c59a69d17ae6a0a8d77133d180e4d68a3a1fc6`:
the pending search was not executed, the turn was cancelled, the app process/readiness and private
history/records were preserved, six assistant endpoints returned 503, worker state was erased, and
OOM events were zero. The equivalent current-image kill remains pending and neither checkpoint
establishes the combined 1 GB test. Selected helper profile tests passed in E70, but live Docker or
production `HostConfig.SecurityOpt`/no-new-privileges inspection remains **Unavailable**; the earlier
local schema-13 rehearsal directly verified `no_new_privileges`, UID/GID 10001, no
effective/permitted capabilities, and read-only root. E65 covers migration-pin QA only. The latest receipt-backed read-only production observation is E833's post-failure inspect:
revision `da2764e8477698fa7d686be93a4711e35478e802`, image
`sha256:d3e21ae9de800f0151c1eba74fb3d16423e1171985c33ea03057acbfe2278ec1`, schema 12 ready,
`failed=null`, and loopback-only. Receipt `test-results/assistant-r120/coordination/actual-host-9fae-mcp-20261009T223042Z/post-failure-inspect.json`, SHA-256 `2ed091bdacc76c101bd4f585305106b3755824947b1aa69129aab79e50f83a61`, did not return rollout, RAM, billing, or browser access; rollout state remains **Unavailable**. E829 is an earlier observation.

An earlier completed quiet full browser aggregate was **Fail** at 145 passed, 2 failed, and 3 skipped;
its receipt is `/tmp/r-astra-120-browser-final-rerun-20261005T131314Z/independent-browser-qa-receipt.json`
(SHA-256 `0ba964557f89af37e87dc772032df1850de7031e7d0a2fe197ce727f4da33e73`). Its Markets quote-wait
crash and emulated-mobile screenshot-protocol failure have no verified cause. A later full 150-case
run was stopped before an aggregate; its aggregate is **Unavailable** (85 passed, 2 failed,
1 interrupted, 2 skipped, and 60 unrun). E48 later records **Pass** for cleanup of that owned run
only. Its dark-placeholder observation measured `3.5403:1` against the `4.5:1` text target on the
stale served export. At `2026-10-05T15:43:09.609757Z`, the read-only comparison found that the current
source and `frontend/out` contain the placeholder style while the staged CSS does not; trace review
at `15:44:19.733732Z` confirmed the served CSS bytes match the stale staged file with no placeholder
rule. This is a stale-export finding, not a measured current-source result or a cause for the earlier
Markets/screenshot failures. The subsequent `./scripts/build-frontend.sh` and staging check **Passed**
at `2026-10-05T15:45:20.470841Z`–`15:47:05.454958Z`: all 48 staged files matched `frontend/out`,
and the placeholder rule is present in staged CSS. The refreshed eight-image set passed independent
capture-only review (E49); the initial HTML/PDF visual review **Failed** on section-04 layout and
small action figures (E52). The builder CSS/template repair was rendered into a new draft (E61),
but parent visual review **Failed** again because the action-receipt image and caption were absent
from all 12 printed pages (E62). These earlier failures remain historical; the current 13-page PDF
visual recheck passed for that PDF only (E64), while formal guide accessibility and release readiness
remain pending.
E64 reviewed all 13 pages and confirmed the bound screenshot bytes, including the complete page-8
frame; the prior 11-page and 12-page failures remain historical. Its receipt is
`test-results/assistant-r120/help-preview/independent-visual-review-recheck-20261005T1705Z/visual-review-receipt.json`
(SHA-256 `1e3d9d958747db7c86277a36efdf55db87b4e261645c9b543bb81a342796011d`); the PDF SHA-256 is
`ed4790d0d33a2ddf782a854697da599cdd09f851b94585c59e3938d374fb1e24`. Review was recorded at
`2026-10-05T17:14:26.923080Z`; exact per-image review times are **Unavailable**.
The fresh full 150-case browser execution and independent receipt **Passed** for test scope: 147
passed, 3 expected skips, 0 failures, and 0 flaky, with 197 source bindings and all 48 staged files
verified at end (E59). Raw assistant axe cleanliness **Failed** because each of four snapshots has
one incomplete item (E60); custom mapped contrast passed only within its sampled scope. The scoped
assistant API/provider/OAuth/network/kill-CLI backend suite later **Passed** 217 tests with no
failures or skips and two deprecation warnings (E66); its 25 bound source/test hashes were unchanged,
temporary-file cleanup passed, and no live provider/service or deployment was invoked. Receipt:
`test-results/assistant-r120/backend-qa-assistant-security-20261005T1717Z/backend-qa-receipt.json`
(SHA-256 `a60243c32a29c2e05f6d3dda10c7552f5142f74e121cf5bf70b61a351aa6f5ff`),
`2026-10-05T17:17:06.520248Z`–`17:19:11.207331Z`.

E67's separate axe-stack diagnostic **Passed for diagnostic execution** (2 desktop/mobile cases;
four theme snapshots) but retained one `color-contrast` incomplete rule per snapshot, so the strict
zero-incomplete criterion remains **Fail**. The stack comparison explains the `elmPartiallyObscuring`
classification; the sampled stacks did not establish a visible text obstruction or foreground
occluder, and no source repair or accessibility acceptance is inferred. The first helper attempt
failed before app assertions when `axe.run` teardown removed the virtual tree; the rerun called
`axe.setup(document)` before its stack helper. Receipt:
`test-results/assistant-r120/coordination/axe-stack-diagnostic/diagnostic-receipt.json`
(SHA-256 `8dbc84b3f645d3534dcb5651b2a7995b1142e9b1c7c77625d6948456fced0d4e`),
`2026-10-05T17:13:53Z`–`17:14:20.496298Z`. E48 records cleanup **Passed** for the interrupted
run's owned resources only; its partial aggregate remains **Unavailable**. The separate one-case
desktop Markets diagnostic passed but did not verify a cause or repair.

E68's ignored axe line-box variants diagnostic **Passed for diagnostic execution** (2 desktop/mobile
cases, 16 raw light/dark snapshots) but no tested variant cleared all incomplete nodes: one-pixel
padding removed only readiness, while answer/disclaimer incompletes remained. The strict raw axe
gate remains **Fail**; no tracked CSS repair was made. Its earlier inline-style CSP rejection and
readiness-selector mismatch are retained as setup failures, not product failures. Receipt:
`test-results/assistant-r120/coordination/axe-linebox-variants/diagnostic-receipt.json`
(SHA-256 `aa7f0fa59ab08d047b2a47d58349849b2585fbdb9589f4a48e30889ce50f0113`), started
`2026-10-05T17:32:13Z`, terminal observed by `17:32:46Z`.

E69 records the builder-scoped single-liveStatus-announcer repair and its frontend contract check:
`node --test components/assistant/assistant-contract.test.mjs` passed `10/10` at
`2026-10-05T17:38:44Z`–`17:38:45Z`, with the existing `MODULE_TYPELESS_PACKAGE_JSON` warning.
Component/test SHA-256 values are recorded in `MVP-PLAN.md`; no build, browser, actual screen-reader,
guide, or release result is inferred.

E70's independent local deployment-MCP QA **Passed for its declared test and stdio-discovery scope**:
81 deployment/rehearsal/archive tests, 5 selected release-helper tests, 17 selected profile tests,
and fresh official Python SDK initialize/list_tools with `8/8` expected names/schemas. Each test
run had two deprecation warnings. Three earlier client-harness failures remain recorded; the fourth
attempt passed after serializer corrections. No tool was invoked, no target variables were passed,
and no remote operation occurred. The selected profile tests do not establish live Docker or
production inspection, and SDK discovery does not replace fresh Codex discovery. Receipt:
`test-results/assistant-r120/deploy-mcp-independent-20261005T173325Z/independent-qa-receipt.json`
(SHA-256 `333fdb10e7f31a2753b95b326f750eb13d8c2591ee3c9eb081c796559296c016`), with scoped checks
from `2026-10-05T17:34:09Z` to `17:38:40Z` and SDK discovery `17:37:10Z`–`17:37:13Z`.

E71's canonical local gate **Failed** at `2026-10-05T17:53:33Z`–`17:54:10Z` with 13 comment-audit
findings reported; its receipt is `test-results/local-gates/R-ASTRA-120-20261005T175333Z/evidence.json`
(SHA-256 `907b5f62f5a0dd5c87bb18fb8816bcfac1ea92c04036196bd0680fe13f4707ef`). A later gate attempt
was **Unavailable** as an aggregate after tool session 78436 exited 143 during pytest at 4%, with no
JUnit or canonical receipt. Its partial `gate.log` records the comment audit **Passed** for 336
authored implementation files, but this subcheck does not pass the gate. Parent read-only
verification confirmed two actual manifest pin links (E78); no runtime build, deployment, or
rollout is inferred. The detached gate retry was preflighted but held without launch (E76).
Detailed windows, receipt hashes, and partial-check evidence are in the R-ASTRA-120 ledger in
`MVP-PLAN.md`.

The native popover diagnostic passed its two Playwright cases but left app raw axe at zero
violations and one incomplete rule per state; strict app axe remains **Fail** (E72). Independent
offline review of the standalone guide HTML passed 180 checks across 12 viewport/theme states with
raw axe 0/0 (E73), and a separate 13-page PDF visual review passed (E75). These do not verify the
application or establish final PR-bound guide acceptance; PDF/UA, physical mobile, true zoom, and
actual screen-reader results remain unavailable. A later independent 390 px resize/minimize/resume
case **Failed** two product criteria: the minimized panel left the background inert without
`aria-modal`, and keyboard resume left focus on `document.body` (E77). The repaired source/spec hashes
are frozen and the parent integration frontend build/stage passed for its declared scope (E79). E87
later passed the repaired focused responsive scope (3 passed, 1 expected mobile skip); this preserves
E77 as the original failure and does not establish full app accessibility or release acceptance.
The separate PDF structural inspection found 30 `/Strong` elements without a role map and 30
wrong-type warnings from `pdfinfo -struct` (E80); the 13-page visual Pass does not establish PDF/UA.
The final authored-documentation validator and complete/change-aware coverage passed for this
reconciliation (E81); documentation tests were not run. Exact commands and results are in
`MVP-PLAN.md`.

Later R-ASTRA-120 evidence records `90` focused config/docs/resource tests passing with two warnings
(E82), and six independent assistant release-contract tests passing with mocked runtime/provider/
clock seams and disposable SQLite only (E84). Neither is a canonical gate or live-provider result.
The latest independent 150-case browser run **Failed** with 145 passed, 2 failed, 3 expected skips,
and zero flaky (E83); both failures are the same stale terminal-copy expectation in desktop and
mobile while the observed UI showed the explicit EOF-without-completion warning and Reconnect
control. Its cleanup passed, 197 source bindings and all 48 staged files matched at end, and guide
capture refresh was **Skipped** because the aggregate failed. Raw axe had zero violations but one
incomplete contrast rule in each of four snapshots, so strict app axe remains **Fail**. Receipt:
`test-results/assistant-r120/full-browser-current-independent-20261005T2015Z/independent-terminal-review.json`
(SHA-256 `96e88de6e4b64fb053aac4e732c5f9a07960d5a8b210fa74d836dff4acb18d0c`).

E85's independent PR-helper pytest command passed `61/61` with two warnings and its cached amd64
recovery-profile transfer/inspection, wrong-digest rejection, and owned-container cleanup checks
passed for that scope. The overall receipt is **Fail closed** because the run opened
`scripts/pr_rehearsal_seed.py` without a contemporaneous pre-run hash. A matching earlier prepared
hash and current hash do not replace that missing run-time baseline. E85 used the fixed 384 MiB
recovery profile; it is not the PR-bound pair rehearsal or combined 1 GB gate. Production remains
healthy at revision `da2764e8477698fa7d686be93a4711e35478e802`, schema 12, assistant rollout disabled;
the resize remains held under the US$15 monthly total cap. The focused EOF browser retest passed
2/2 in desktop Chromium and Pixel 7 emulation (E86); its earlier selector attempt ran zero tests and
remains a separate setup failure. E87 also passed the repaired responsive edge and checked-in
saved-answer/theme regression (3 passed, 1 expected mobile skip). These scoped results do not change
E83's failed 150-case aggregate or strict axe failure. Current-image kill, required native/provider, security,
accessibility, recovery, and combined 1 GB gates remain open. No promotion, release readiness, or
email is claimed. Exact windows and receipt hashes are in the R-ASTRA-120 ledger in `MVP-PLAN.md`.

Later R-ASTRA-120 evidence preserves a failed canonical local gate (E88: `1,627` Python passes,
one failure, four skips, four deselected, and `80.52%` coverage), followed by an independent
full-browser test-scope pass of `147/150` with three expected skips (E89). Raw axe still has one
incomplete contrast rule in each of four app snapshots, so strict app accessibility remains
**Fail**. The short-path 699-case independent boundary diagnostic passed (E93), but its 67.8391%
subset coverage does not replace the 85% canonical gate. The original AF_UNIX path-too-long failure
(E91) and earlier DELETE/revocation failure (E94) remain recorded beside their separate scoped
rerun passes. A fresh actual eight-image capture plus child-exit, port-release, and temp-cleanup
review passed for synthetic capture scope (E99); the candidate manifest's privacy status and QA
receipt hash remain pending, so final PR-bound HTML/PDF guide acceptance remains open. The separate
seven-case real-manager/provider HTTP regression passed its selected test and static-check scope
(E102); it is not live provider, model, Docker, release, or production acceptance. A direct
read-only inspect at `2026-10-06T00:29:25Z` confirmed production still serves revision
`da2764e8477698fa7d686be93a4711e35478e802`, schema 12, ready and loopback-only (E100). No deploy,
resize, rollout, email, 1 GB acceptance, current-image kill, provider/native-runtime gate, PR-bound
rollback, or release readiness is claimed. Exact paths, hashes, warnings, and result scopes remain
in the R-ASTRA-120 ledger in `MVP-PLAN.md`.

Later R-ASTRA-120 evidence records E107's corrected builder-run synthetic invitation-browser subset
as **Pass** (10/10 desktop/emulated-mobile cases) after an initial 10-case setup **Fail**. E109
independently passed that selected 10-case UI subset on desktop Chromium and Pixel 7 emulation;
fixtures stub the TOTP step-up and invitation HTTP endpoints, and physical mobile, SMTP, provider,
production, and full-gate acceptance remain unverified. All 52 FastAPI-served file bindings and
owned cleanup passed. E108's ignored semantic-text candidate **Failed** to clear strict raw axe
incompletes in the captured Light desktop/mobile pairs; the full Light/Dark matrix is **Unavailable**
after a separate geometry assertion, and no tracked presentation change followed from that
candidate. Strict app axe remains **Fail**. E110 records the provider-button styling gap and two
consecutive Luna model-capacity failures; E111 records the task-scoped Sol source repair, parent
source-review **Pass**, and builder-reported Node contract 11/11/spec-syntax **Pass**. No browser or
build acceptance is claimed for that repair, and native Connect/Remove control geometry remains
unavailable. See E107–E111 in the [MVP plan](MVP-PLAN.md); no release or physical-mobile acceptance
is inferred.

The next R-ASTRA-120 receipts preserve their narrow scopes. E112 passed one synthetic catalog-review
case on desktop and Pixel 7 emulation, including the Refresh catalog 44×44 CSS-pixel assertion and
52 served-file bindings; native Connect/Remove geometry and keyboard, physical-mobile, live-provider,
and production behavior remain unverified. Its raw port flag was false due to a TIME-WAIT-sensitive
probe, while parent review confirmed no listener, process, or owned-temp residue. E113's latest
canonical local gate **Failed** at 1,818 Python passes, one disposable production OAuth bridge
readiness failure, three skips, four deselected, and 83.55% coverage (below 85%). The failure reported
a connection reset while waiting for the disposable app; its cause is **Unproven**. Documentation
completeness and the reported 54 frontend lint/test/build/stage checks passed only as subchecks; 563
source inputs were unchanged, all 52 served files matched the export, exact cleanup passed, and
promotion was held. E114 is only an ignored 1,549-line candidate driver with a builder-reported
syntax pass; parent review held it for simplification and missing probe-mode/network-attachment
guards. No execution, current image, native runtime, resource, or production acceptance is inferred.
E115's follow-up Luna diagnosis has no completed repair or terminal root-cause report supplied.
Strict app axe remains **Fail**, required promotion and rollback/canary/native/security/resource
gates remain open, the US$15 monthly cap and existing 1 GB/backups remain in force, and no email or
release is claimed. See E112–E115 in the [MVP plan](MVP-PLAN.md).

Later R-ASTRA-120 receipts preserve these narrow scopes. E116's native `linux/amd64` build remains
bound only to context `1b9676fccff22dc5e4f62746ece82ef053db6604baa78e088c47deadc8e05023`; parent
review did not run it. E117's review **Failed** the old 1,549-line launcher, and E125 independently
**Failed** the frozen replacement runner on a P2 output-buffering defect (`capture_output=True`
retains full output before byte-cap checks). Neither runner was executed; bounded output repair and
independent rereview remain **Pending**. E118 passed only its aligned OAuth-bridge fixture/protocol
scope, and E119 passed only three synthetic provider-lifecycle HTTP cases. E120 locally passed 67
focused protocol/scalar tests and parent source review; E121 independently passed 67 protocol tests
and 53 adapter/wire regressions with two expected skips, while a separate synthetic Google 1.5
public-manager reproduction **Failed** before mocked transport. E123's local Google/scalar suite
passed 88 tests, and E126 independently passed the same 88-test synthetic scope after repair; these
do not establish a live provider response. E122's image `sha256:22c9838c7fa8e55b06518eccf4d96a3f163cd711a30544170416f3a836eeb27a` is historical before the Google repair. E124's latest local build/source-identity
**Passed** for image `sha256:647ecdcc66288cf26cd022669db700efdd2954518276e67efc99a10cc5618e6d` and context
`6f890e382d70b60634303a5455c5c6fc76d65f51d8e44c0e16f5211b66393e30`; runtime was not tested. E127's
12-state whitespace diagnostic ran successfully, but strict raw axe remains **Fail** with one
incomplete contrast rule per state; both tested whitespace variants failed to clear it, and no
tracked CSS repair followed. E128's current-task production `status`/`inspect` passed read-only
scope at the unchanged schema-12 baseline; no mutating tool, deploy, resize, or email occurred.
These scoped results do not replace E113's failed canonical gate or establish live provider, native
assistant, effective Docker resource/`HostConfig.SecurityOpt`, current-image kill, combined 1 GB,
PR-bound rollback, app accessibility/guide, deployment, or release acceptance. Production remains
at `da2764e8477698fa7d686be93a4711e35478e802`, schema 12, rollout disabled; the US$15 monthly total
cap including backups and tax retains the existing 1 GB plan and backups. No release or email is
claimed. Exact receipts, windows, hashes, and preserved statuses are in E116–E138 of the
[MVP plan](MVP-PLAN.md). E129's documentation checks **Passed**; documentation pytest was not run.
E130–E131 record the synthetic word-adjacent key redaction repair and independent selected HTTP
review; this is not a real credential incident or proof of a tail-window bug. E132 records the
bounded-output runner's synthetic-only repair/rechecks. E133 binds image
`sha256:819695a221d776811eaf50fd2895ea466b27c033d25b9f211ea9947714cf9ced` to context
`9a276b21f8b8d830665759fbe34c3af3b11f64bb398d4fa78ad84591ee88fd12`; it proves build identity
only. E134's axe 4.13.0/4.14.0 comparison left raw app axe **Fail**. E135–E136 passed three
builder and independent history-recovery HTTP cases after retaining the initial harness failure.
E137 records an **Unavailable** argparse setup attempt, then a corrected current-image native
functional **Fail** (probe exit 2, generic fixed-command/output-bound status, cause **Unproven**);
independent wrapper QA recorded the same failed scope and verified the image/source bindings.
Source-only fixture mismatch is an unverified hypothesis. No successful native/provider interaction
is established. E138 preserves the initial cleanup failures and separate read-only all-absence
cleanup **Pass**. No current-image kill was invoked. The canonical E113 gate remains **Fail**;
production remains at schema 12 with rollout disabled and the US$15 monthly total cap, existing
1 GB plan, and backups unchanged. Required native/provider, kill, 1 GB, rollback, accessibility/guide,
deployment, and release gates remain open; no release or email is claimed.

E139–E142 add scoped parent confirmation/session review, current glyph/stack diagnostics, and the
source-map-js 1.2.2 lock repair with independent zero-advisory audits and 52-file stage verification.
The sampled text is readable, but raw axe still has one incomplete contrast rule in each state;
strict accessibility remains **Fail**. The lock repair makes E133's image historical. No subsequent
native acceptance, production mutation, resize, rollout, or email is inferred. The canonical gate,
required native/resource/security checks, PR-bound rollback, and final guide/release remain open.

E143–E147 record the corrected synthetic fixture QA, refreshed image, and a separate current-image
native functional **Pass** for two users, owner-scoped MCP, native search/guarded fetch, isolation,
and deletion/cache cleanup. The active-kill attempt **Failed** with no valid projected receipt;
its cause remains **Unproven**, while all six owned cleanup targets passed. Independent guide-tool
QA **Failed** on per-image digest binding and no-follow source hashing; those repairs are pending.
The local 768 MiB sample is not actual combined 1 GB Linode acceptance. Canonical coverage,
complete security/mobile/accessibility, current-image kill, final guide, and PR-bound rollback remain
open. Production, the 1 GB machine, backups, and the $15 monthly total cap are unchanged; no
promotion, rollout, resize, or email is claimed.

E152 independently passes the repaired guide tooling for unit/static scope only (16 capture,
11 finalizer and seven selected loader tests); fresh captures and final HTML/PDF acceptance remain
pending. E153 records a separate shutdown-diagnostic integration repair and parent source review;
independent v3 QA and native execution remain pending. The earlier failed runtime kill and strict
raw-axe gate remain open. This work authorizes no resize or spending above the $15 monthly total.

E154 passes the v3 diagnostic’s independent synthetic integration scope; E155 then records a
separate same-image native functional Fail with full owned cleanup and an unproven specific
cause. E156 passes a fresh actual eight-image capture and parent visual review for synthetic
capture scope only. Native reliability, active kill, final guide and release gates remain open.
E157 separately passes independent visual/privacy review of all eight current synthetic captures.
Final guide and release acceptance remain open; mobile evidence is emulated only. The US$15
monthly total cap including backups and tax remains unchanged, and no resize was applied.

The model-activation-lock candidate source review and native image build passed only those scoped
checks: source review was limited to its declared boundary and image
`sha256:49d89627ec756c6052d06e68c60004a3a06011d885773753b84dd93e935ff401` was built from source
context `85370e10afb1d55c0ad2b98cc488c5aa8e7143334249a3f634315718b15d3033`. The two-owner native
run on that image **Failed** at `2026-10-05T15:31:51Z`–`15:33:16Z`: both owners had matching
model/MCP evidence; owner 0 answered, while owner 1 got eight native search sources and approved
search and WebFetch, then WebFetch timed out at `dns_lookup_timeout` after 8,963 ms without a source
or answer. DNS/network root cause is unproven, and this run does not show the model lock caused an
improvement. E51's system-resolver diagnostic timed out after 3,252 ms and skipped its guard. Later
same-image DNS-only comparisons found host resolution at 189 ms and an owned user-defined bridge at
440 ms, while the default bridge timed out at 3,005 ms (E54). An instrumented guard diagnostic then
errored internally (E55), so that result is not a guard failure. A separate run of the unchanged,
hash-pinned Bun guard resolved in 203 ms with four public addresses and exact cleanup (E56). These
path-specific diagnostics do not establish the native WebFetch root cause; production Compose uses
a user-defined bridge. A later same-image native OpenCode run on the owned user bridge passed its
functional scope (E58): both owners completed with matching model/MCP evidence, owner 1
received eight text-search sources and one approved guarded IANA fetch, cross-owner and forged-MCP
lookups returned 404, owner deletion returned 200, and worker-cache markers were purged. This does
not prove the cause of E39. The local 768 MiB cgroup sample reached its 805,306,368-byte cap with
186 `max` events and zero OOMs; worker readiness intermittently showed starting/unavailable while
app readiness stayed ready, so the required 1 GB resource gate remains open. Exact cleanup passed.
Cleanup **Passed** for its exact owned container and volume, with peak memory
560,009,216 bytes and zero OOM events; this is not actual 1 GB Linode evidence.

Independent assistant-help capture review **Passed for its capture-only scope** on both the earlier
and refreshed bundles. The earlier eight synthetic captures used the stale staged CSS confirmed
above, so they do not verify the current compiled implementation; the refreshed eight-image set
passed its source/stage binding and strict-loader review (E49). Initial PDF review found layout
defects (E52); the builder repair was rendered (E61), but parent visual review **Failed** because
the printed PDF omitted the action-receipt image and caption (E62). A second print-layout repair and
the earlier PDF findings remain historical; E64 passes visual review of the third PDF only. HTML
accessibility and final guide acceptance remain pending. A separate optional ignored
verifier failed with `ERR_MODULE_NOT_FOUND`; it does not replace the canonical loader result. The
fresh 150-case execution passed its test scope (E59), while raw axe cleanliness failed (E60). HTML
accessibility, current-image kill, provider/resource/recovery gates, raw-axe closure, release, and
email remain open. The deployment-helper source validator initially rejected the migration/hash
pair (E63); independent pin QA later passed three Ruff checks and 55 helper tests with two
deprecation warnings, confirming the hashes match (E65). Its receipt is
`test-results/r-astra-120-production-helper-pin-independent-20261005T1647Z/command-receipt.json`
(SHA-256 `345ba1a920c83ef3d9aeaffd3279f4a08ef1d3da145d31ef9461304d39a9c50e`); the check ran
`2026-10-05T16:49:48.904456Z`–`16:49:53.197309Z`. No live promotion was attempted. This does not
close the separate `HostConfig.SecurityOpt` profile-inspection gap. See the R-ASTRA-120 ledger in
`MVP-PLAN.md`.


Current R-ASTRA-120 verification retains earlier failures in the MVP ledger. E167/E168/E171
pass local native functional, active-search shutdown and cleanup scopes; actual 1 GB acceptance
remains open. E173 fails canonical coverage at 84.49%; E180 independently passes 99 new boundary
tests. E198 later passes a complete canonical rerun for its exact local scope; it does not erase
earlier failed or interrupted aggregates. E182 is an interrupted aggregate with
an invalid Pass/0 receipt. E179 passes browser test scope (149 passed, three expected skips),
while strict app axe remains Fail. E176/E178/E181 pass current synthetic capture/render and
standalone HTML/PDF draft review; PDF/UA and final PR/release binding remain open. Complete
security, resource and tested PR-bound rollback gates remain open. No promotion, resize,
rollout or email is claimed; the US$15 total cap and existing 1 GB/backups remain in force.
A canonical gate Pass requires a matching successful terminal exit, all required completed
checks, and completed JUnit evidence; a Pass field alone cannot accept an interrupted run.
E183 retains the original wire-runner static-review failure. E184 records a synthetic Google-key
input rejection gap; E186 independently passes its narrower repair. E188 records a later adjacent-text
gap and builder repair; E190 independently passes its eight-case follow-on. A rebuilt image and final runtime checks
are still required. E185's process-inspection finding remains historical; E187 independently passes
three repaired synthetic fixtures. E191's complete canonical run reached 85.24% coverage but failed
two tests (2,052 passed, 3 skipped, 4 deselected); source/stage binding and exact owned cleanup
passed. E194 independently passed three serial selections of the two test-only repairs; E198 later
passed the canonical local check for its exact scope while E191's failure remains preserved. E192's
original P2 known-model privacy-exclusion finding remains
preserved; E195 independently passed the repair's selected local source/regression/lint scope, and
parent GPT-6.1 Sol's selected source/evidence review passed with no findings. E195 covers direct
Zen parsing, native Console/manager registration and use, and compatible custom routes by upstream
native model identity and exact Zen route; administrator review and user consent do not override
exclusions, ambiguous exact-Zen routes fail closed, and similarly named unrelated hosts are not
globally banned. These are local synthetic checks only; live provider/native Console/network/browser/
Docker/production execution and external data flow remain unverified. E196's network-bridge
review failed on exact-name absence verification despite 75 synthetic test passes; E197's bounded
full-ID/name comparison repair independently passed 83 synthetic tests and selected source/lint
checks, with no native Docker or PR-bound recovery acceptance. E193 rejected the ignored
contrast-proof proposal; it is not an acceptance path. Strict raw app axe and the other release
gates remain open.

E198 is the latest complete canonical local-gate **Pass before later source changes**:
`TMPDIR=/var/tmp/r12r TASK_ID=R-ASTRA-120
./scripts/local-gate.sh check` passed with exit 0 on native x86_64, dirty revision
`24d899fad5db71959f1fccdcc022fbc97e8fd6ce`, from `2026-10-06T10:42:20Z` to `11:03:24Z`.
It reports 2,108 Python passes, 3 skips, 4 deselected, 90 warnings, 85.25% coverage, and 54
frontend checks; the exact ordered completed checks were documentation, frontend, and Python.
Parent review verified 569 source bindings unchanged, all 52 served files matching the export,
actual gate/supervisor process absence, and exact owned-temp cleanup. Canonical receipt
`test-results/local-gates/R-ASTRA-120-20261006T104220Z/evidence.json` has SHA-256
`424624fa724e05fd587eede65a3f72ed5e9bc63a4002c458166592658120e753`; terminal review
`test-results/assistant-r120/coordination/canonical-check-runner-20261006T1010Z/parent-terminal-review.json`
has SHA-256 `4067ec876408c8255f87bed6aa20964498a542212d80516763ce5cd004b408d7`. E191 remains
preserved as a failed earlier run. The canonical runner is **TERMINATED** and the source freeze
was released after terminal review. E199's independent native WebFetch source review then found
P2 SG-01: approval of the displayed exact URL permits a redirect to a changed public URL without
renewed exact-destination approval, contrary to the UI promise. Static per-hop private-address
guards passed; no private-network SSRF bypass is claimed. E198 did not test this invariant.
The repair is in progress; independent QA and fresh source bindings remain pending, and native-image
build preparation is held. Strict app axe, native/runtime/security, combined actual 1 GB resources,
final PR-bound guide, PR rollback, deployment/canary, and release gates remain open. Previously
recorded production state is revision `da2764e8477698fa7d686be93a4711e35478e802`, schema 12, with
assistant rollout disabled. E201 was the last read-only inspect at that checkpoint. E256 later confirmed the same revision/image/schema/ready/loopback boundary but did not expose
rollout fields or user/browser access; E301 at `2026-10-06T19:19:47Z` reconfirmed revision
`da2764e8477698fa7d686be93a4711e35478e802`, image
`sha256:d3e21ae9de800f0151c1eba74fb3d16423e1171985c33ea03057acbfe2278ec1`, schema 12 ready,
`failed=null`, and loopback-only. E329's later read-only inspect/status pair reconfirmed that
baseline but did not return rollout, RAM, or billing; current rollout mode remains **Unavailable**.
The US$15 monthly total cap and
existing 1 GB/backups are unchanged. No promotion,
resize, rollout, or email is claimed.

E284's canonical local-gate attempt **Failed** at exit `1` (`2026-10-06T17:22:35Z`–
`17:39:16Z`): 2,298 Python passes, 2 failures, 3 skips, 4 deselected, 90 warnings, and 85.15%
coverage. Both failures were in confirmation HTTP-flow cookie helpers: `StopIteration` after HTTP
200. E286 independently passed the two selected confirmation HTTP-flow tests and reproduced a
TestClient cookie-jar omission when the test's frozen expiry was already past on the host clock.
This supports a harness clock mismatch, not an application-auth defect, and does not rewrite E284's
failed aggregate. Parent terminal review verified 1,048 bound files unchanged in E284.

E198 predates the later E199 redirect and E204 provider-egress findings and their source changes; it
is not a canonical check of the current source. E202 is builder-only partial redirect evidence, and
E203's independent review **Failed** on permission/message ordering and static guard/build-count
issues, with native integration **Unavailable**; the mock's omission of the shared atomic eight-tool
counter did not close the hop/repeat race. E209 later **Passed** selected redirect ordering checks
(43 runtime, 23 helper, 49 mocked Bun guard cases, and 49+8=57 inventory); its old circular
message/permission fixture timeout is diagnostic-only and native integration remains **Unavailable**.
Parent review matched all seven pins and removed its temporary Bun. E204's five-path synthetic
provider egress finding remains **Failed**. E205's separate ASGI middleware scope **Passed** two
synthetic body-chunk revocation cases before route dispatch. E206–E208 record builder transport
callback checks, the 99-case fixture adaptation, and parent source review; E210's independent
synthetic provider authorization rerun **Passed** its nine serial selections. These results do not
erase E204 or establish live-provider, native OpenCode, browser/UI, or external-data-flow acceptance.
E211's Linux/amd64 image build **Passed** for build/source/stage binding (147 inputs, 52 served
files), but E212's network-none verifier rejected its worker receipt because the supervisor's fixed
guard/manifest pins were stale; its app and worker were not started and owned cleanup passed. E213's
narrow builder pin repair passed 14 selected tests plus lint/format; E216's independent supervisor
pin QA also passed 14 selected tests, lint/security/format, and 42 stable bindings. E215 built a
fresh image from 147 inputs with all 52 served files matching. E218's one-shot verifier passed on
that exact image: the receipt validated under network-none, read-only root, zero capabilities,
no-new-privileges, and UID/GID 10001. The app and worker did not start; parent review matched the
allowlisted facts, log, and 42 pins but did not verify exact owned-container cleanup beyond `--rm`.
E219 parent review passed the image build/source bindings for its declared scope. E220's separate
synthetic wire setup **Failed** before container start because the runner expected four `.Mounts`
entries while Docker reported two read-only binds and represented tmpfs separately; exact tmpfs
matched and owned cleanup passed. E221's ignored runner mount-guard repair passed six Docker-free
tests plus its selected Ruff/security/format checks. E222's same-image wire recheck **Failed** as an
aggregate despite child exit 0 because the parser rejected protocol facts; E223 showed all ten
required native assertions true, 11 authenticated listed tools, and a nullable `/mcp` readiness
count. E226's ignored parser repair passed 22 Docker-free tests and selected lint/format, but E227's
second same-image attempt still **Failed** the aggregate. E231 isolated two false generic Google
body assertions; the parent source-level diagnosis is a Google model-in-path and `alt=sse` shape
mismatch, while raw request-body contents remain unobserved. An ignored-runner-only repair is
completed for its builder/test scope in E235; no tracked probe changed. The actual same-image
wire aggregate still **Failed** on `probe_schema_row_invalid`, with child exit 0 and exact cleanup.
These results do not erase E220 or establish
wire/provider acceptance. The original E212 old-image rejection remains preserved.
E224's current-image native functional attempt **Failed** at the seed command before model calls and
initial cleanup failed; E225 later passed exact owned cleanup. E228's ignored driver-guard repair
passed 14 Docker-free tests and selected lint/format, but E230's subsequent same-image functional
recheck **Failed** after seed when the output projection rejected malformed worker status. App and
worker UID profiles were observed, source/stage bindings matched, exact cleanup passed, and the
underlying worker failure remains **Unproven**. Native functional and kill acceptance remain open.
E229's iframe prototype invocation **Failed** at setup on the preserved old spec; new wait-based
tests were skipped and raw axe did not run. E232's later iframe prototype ran but **Failed** its
desktop-Light contrast/parity criteria; other states remained skipped. E233's failure-only status
projection repair passed 17 builder tests and a separate 61-case parent unit rerun, without changing
success criteria. E234's current-image native functional run **Failed**: owner 0 completed an answer
and MCP read; owner 1 obtained eight native search sources, then timed out before fetch approval or
an answer. The cause is unproven; end-of-run ready status is not continuous readiness evidence.
Exact owned cleanup passed. E236's 16-snapshot desktop/mobile text-structure diagnostic completed
with unchanged 78 frontend inputs and 52 served files, but no variant cleared raw axe incompletes
in all four theme/viewport states. No tracked UI repair or accessibility acceptance follows.
E237's ignored schema-projection correction binds Google's empty-argument workspace tool to its
exact protocol, alias, and digest. E238's independent current-image synthetic native wire run
**Passed**, including all three provider flows, 11 MCP tools, and Google tool continuation; E239's
parent review confirmed all 147 current image-source bindings and cleanup. Broad ignored-runner
lint/format failures remain separate. This local 1.5 GiB synthetic result does not close E234's live
search failure, strict app accessibility, actual 1 GB, current kill, or PR-bound release gates.
E217 parent review confirmed E210's provider receipt pins/logs for its declared scope; it did not
rerun tests. E213's optional iframe axe preflight was held; E229's later setup failure also produced
no prototype axe result. E214's checksum-pinned
compile-source review found `--smol`, minification, and bytecode; it is source-only and proves no
memory or 1 GB result. E201 was the last production observation at its checkpoint; E256 later
reconfirmed the revision/image/schema/ready/loopback boundary without observing rollout mode or
user/browser access. Strict app axe, current-tree
canonical, native worker/function, live-provider, actual 1 GB, PR-bound rollback, deployment, and
release gates remain open. The $15 monthly total cap and existing 1 GB/backups remain unchanged; no
promotion, resize, rollout, or email is claimed.

E244 independently passed the repaired timeout-diagnostic contract suite (`297` tests and `31`
negative cases); its two earlier direct-check attempts failed at import before assertions. E248's
authorized current-image two-owner trial **Failed**: owner 0 answered, while owner 1 timed out
before search or fetch. E249 independently verified the failed outcome, 12 runner pins, 147 image
source inputs, four repaired test/QA pins, 52 staged files, and exact cleanup. E250's fixture-only
UI follow-up passed fidelity, enabled keyboard traversal without submission, and mobile geometry,
but retained one incomplete raw-axe disclaimer item in each mobile theme; strict app accessibility
remains **Fail**. E251's initial frontend builder report listed passing contract/build/test/audit/stage
checks, but E252's parent source/export review **Failed** because the CSS-module selector did not
bind the disclaimer padding rule. E254's builder repair now binds that selector and passes its
12-case contract, frontend build/typecheck/Next build, 55-test, audit, and 52-file stage scope.
E253 separately found readiness styling applied to the whole container and the mobile font-size
override removed, rather than matching the tested candidate. E257 reports a builder-only
readiness CSS follow-up: 12 contract, 55 frontend, and 27 helper tests passed; the builder reported
zero audit advisories and 52 staged files matching, with hashes recorded in the MVP ledger. E258
parent source review and read-only served/export comparison **Passed** for that source/stage scope,
including the full JSX hash; builder receipt/stdout and exact build start/output hash remain
unavailable. No browser result or rebuilt assistant image is established; browser follow-up remains
pending and strict mobile raw axe remains **Fail**. E256's read-only production inspect recorded revision `da2764e8477698fa7d686be93a4711e35478e802`,
image `sha256:d3e21ae9de800f0151c1eba74fb3d16423e1171985c33ea03057acbfe2278ec1`, schema 12 ready,
`failed=null`, and loopback-only. E301 later reconfirmed those deployment facts but did not return
rollout state, RAM/billing, or user/browser acceptance. A
read-only runtime diagnosis found no safe existing attached bootstrap-stream timing seam. The
parent authorized an observer limited to private, volatile, anonymous per-execution timings, with no
identifiers, public endpoint, raw data, or deadline changes. E259's selected builder checks passed,
but parent review **Failed**: production INFO logging is disabled and the probe extractor discards
stderr, so the timing markers may not be emitted or retained. E260's bounded logging/stderr-capture
repair passed its builder selections and parent source review; E261 independent QA **Failed** on a
late-callback fixture that used an invalid outcome and on context removal before owner validation.
E262 repaired those cases and passed 118 focused tests plus independent and parent source review.
E263's selected current-source browser run passed 11 cases with one expected mobile skip and verified
52 served/export files plus cleanup, while strict raw axe remained **Fail** with one incomplete item
in each of four snapshots. Its sampled custom contrast passed; enabled-Send keyboard traversal,
numeric mobile target geometry, and rendered code-fence fidelity were **Unavailable**. E264 built
image `sha256:c46086b442d81084c70daf83404a0505e763ca2c95d0b05df94dfc493b288b63` from context
`806779d28526d5167e98f6eff454eecc7650f4fb1490ebb75d5f7306b9514299` with 147 source inputs and
52 matching served/export files. E267 then **Failed** the current-image two-owner functional run:
owner 0 returned `provider_unavailable`, owner 1 timed out, and neither answered or reached search
or fetch approval/source. Anonymous rows A/B recorded the first sanitized chunk of each second
provider request but later-chunk activity is unknown; they cannot be mapped to owners or establish a stream
stall, HTTP success, or cause. Exact cleanup passed. Its 768 MiB sample peaked at 560,410,624
bytes with zero high/max/OOM deltas, which is not actual 1 GB acceptance. E268 independently passed
result-integrity/timing review while retaining the functional **Fail**. E269's first static
preflight comparison **Failed** on an asset-count/header comparison mistake; its corrected static
header/body inspection **Passed** but was not an independent test rerun (**Skipped/not run**), which
remains pending. It did not rerun the image or alter E267. E265's test-header repair passed builder
checks and parent header-only review; independent test rerun and a fresh canonical gate remain
pending. Keep the E243 failure, E248 functional failure, E250 raw-axe
incompletes, E259 review finding, and E267 failure visible; later scoped passes do not erase them.
E271 independently passed the host-only warning-parser checks (134 focused tests in both runs,
Ruff check/format); the explicit-count run reported two warnings, and this is not runtime or image
acceptance. E272 then **Failed** a second native functional trial on the same E264 image: owner 0
answered, while owner 1 reached approved search and fetch sources but timed out without an answer.
E273 independently passed result-integrity review only; E272 remains **Fail**, and cleanup was not
rechecked live. Anonymous timing rows A/B report workspace-summary, first-sanitized-chunk, and end
times for corresponding second provider requests; they have no owner mapping, and later chunk
activity is unknown, so they do not establish a stall or cause. The empty captured warning list
means no matching closed-category warning was recorded, not that other runtime errors were absent.
A separate parent source trace found optional `max_tokens` validation from 1 through 4096, with no
missing-bound bug or latency cause identified and no product fix proposed; no separate artifact or
exact window was supplied. The local 768 MiB peak was 546,541,568 bytes
with zero observed high/max/OOM deltas; this is not the actual 1 GB gate, and current-image kill was
not run. E274's initial synthetic UI fixture attempt **Failed at setup** on an auth route mismatch
with no UI records; its corrected rerun is pending. At this earlier checkpoint, the current-tree
canonical gate was also pending; E288 later passed the canonical local check profile, while its
opt-in native OpenCode checks remained skipped. Exact native cause, current-image shutdown, live
provider/security, actual 1 GB, PR-bound recovery, final-guide, deployment, and release gates remain
open. The $15 monthly total cap and existing 1 GB/backups remain unchanged; no promotion, resize,
rollout, or email is claimed. Exact receipt fields and limitations are in the [MVP plan](MVP-PLAN.md).

Post-E274, E275 independently passed host-only CPU receipt-boundary tests and Ruff; live CPU-counter
availability remains untested. E276's corrected synthetic UI run **Failed** because focus returned
to `document.body` after Send/Cancel. E277 repaired panel focus handling and passed the approved
frontend build/stage with all 52 served files matching. E278's post-repair aggregate **Failed** four
invalid Stop-label identity assertions, while actual focus and keyboard-cancel assertions passed in
the four desktop/mobile theme states; strict raw axe remains **Fail**. E280 passes only the corrected
Stop-identity/cancellation-cleanup diagnostic. E281's tracked focus-only regression then **Passed**
2/2 after preserving wrapper and CLI setup failures; it does not close raw axe or full-browser
acceptance. The current-image
two-owner run E279 **Failed** after owner 1 approved search and received eight search sources, then
timed out without reaching a WebFetch preview, approval, or source; its CPU-throttling sample does
not establish the timeout cause or actual 1 GB acceptance. E288 later passed the canonical
local check profile, but its opt-in native OpenCode checks were skipped. Current-image shutdown,
security/provider/accessibility, PR-bound rollback, and release gates remain open; the existing
1 GB/backups and US$15 monthly total cap remain unchanged.

E283's independent 34-test progressive SSE/framing review **Passed** for its scoped source/test
contract, but native provider-latency causation remains unproven and E279's image predates the repair.
E285 applied only a candidate lockfile update to sharp 0.35.5; `package.json` stayed unchanged. E287
independently passed 55 frontend contracts, zero-finding npm audit, Sharp/Next compatibility and
52-file served/export parity for that candidate. This does not establish an image build or runtime.
The official [GitHub advisory GHSA-wq5f-xc86-pv6w](https://github.com/advisories/GHSA-wq5f-xc86-pv6w)
identifies sharp versions below 0.35.5 as affected and 0.35.5 as patched.

E288 is the latest complete canonical local check-profile **Pass** on dirty native x86_64 at
`24d899fad5db71959f1fccdcc022fbc97e8fd6ce`: 2,300 Python passes, 3 opt-in skips, 4 deselected,
90 warnings, 85.230871% coverage, and 55 frontend checks; documentation, frontend, and Python
checks completed. The 1,048 bound files and 52 served/export bindings were unchanged. The three
native OpenCode boundary/provider-wire skips remain separate required gates. E289 passed ignored
native-wrapper preparation/static review only at that checkpoint; E292 later records the image build and E293 the failed native attempt. At the E290 checkpoint, exact-current-source raw axe was **Unavailable** because retained snapshots used a different source binding. E300 later ran four exact-current-stage snapshots: selected Playwright passed 4/4, but strict raw axe **Failed** its zero-incomplete criterion, with zero violations and one incomplete contrast rule per snapshot (one unresolved desktop node and three per emulated-mobile snapshot). This targeted result does not establish full-app accessibility. No speculative CSS/DOM repair is inferred. Current image/runtime, native/provider, accessibility, current-image kill, actual 1 GB,
PR-bound rollback, production, deployment, and release gates remain open. The US$15 monthly total
cap including tax and backups, existing 1 GB plan and backups remain unchanged. No resize, email,
production change, or release is claimed.

E291 records the first current-image build attempt **Failed** at exit `1` on `ENOSPC`; its build
receipt and log were zero bytes, so no image build result is accepted. The exact plan was recovered
byte-for-byte from the pre-run manifest and task-owned disk cleanup passed, removing 31 obsolete
task image tags and 12 unused, unreferenced intermediate image IDs without force/prune or
container/volume actions. Current, recovery, and production images were retained; production was
unchanged. The cached build retry was pending at the E291 recovery checkpoint; E292 later records
its build/source/stage result. The existing US$15 monthly total cap including tax/backups and 1 GB
plan/backups remain in force; no resize, deployment, or release is claimed.

E292 later passed the cached Linux/amd64 build retry for build identity and source/stage binding: image `sha256:b972c1a65b416ff2a874ebeda140bbaba8743ddd0c692edc1bc1797dbc35237f`, 147 source inputs, and all 52 served/export files matching. This is not runtime acceptance. E293's independent native functional run on that image **Failed**: both owners timed out after the model-session event without an answer or search/WebFetch activity. CPU throttling was observed but its causal role is unproven; the 768 MiB sample is not actual 1 GB acceptance. Exact cleanup and independent binding checks passed; no current-image kill was run. E294's synthetic axe reproduction **Failed** ten geometry assertions because `pointer-events:none` underlays were absent from `elementsFromPoint()`. E295's ignored-fixture-only correction passed eight synthetic states, but `#copy` still produced axe incompletes over differing backgrounds; this does not resolve strict app axe, which remains **Fail**; E300 later recorded a targeted
exact-current-stage strict raw axe **Fail**, superseding only E290's earlier source-binding
**Unavailable** checkpoint for that scope. E296 passed structure inspection and E297 passed visual review of the exact 13-page draft PDF only; PDF/UA and final PR-bound guide acceptance remain open. E298's independent timing-observer source acceptance **Failed** because outer-generator close did not explicitly await the nested provider proxy, despite 201 timing/probe tests, 8 selected proxy tests, Ruff and format passing. The builder separately reported a pre-repair close regression failure at `19:16:40Z`; no failure receipt, hash or exact selector was saved. E299's independent recheck **Passed** repaired selected source/test scope (202 timing/probe and 4 proxy cleanup tests, Ruff/format) and parent integrated review **Passed**; neither proves native latency cause or provider/runtime success. E300's exact-current-stage browser execution **Passed** 4/4; strict raw axe **Failed** as summarized above. The 94 frontend inputs and 52 served/export files remained unchanged and cleanup passed; physical mobile and actual screen-reader acceptance remain **Unavailable**. E301's read-only inspect reconfirmed production revision `da2764e8477698fa7d686be93a4711e35478e802`, schema 12 ready, and loopback-only; rollout state was not returned. E302 **Passed** a local Linux/amd64 image build and source/stage binding for image `sha256:9628a3cfddb86809efd44e3cd93829362db190702665eda488e69790f34b0bbc` (context `823777afc3ec3df12e0aa904463d17c9ed3dd6c57efd56cf0820735771e04bf6`): 147 source inputs and all 52 served/export files matched; owned cleanup passed. Parent binding review passed. This is build-only; E304 later records the native functional result for this image. E303 **Passed** manual contrast/visibility review of all 8 retained axe-incomplete nodes only: ratios were 6.4185–15.4826:1, full text was visible, each target had two unclipped in-viewport line rectangles and six sampled topmost-target hits, and no foreground obstruction was observed. Strict raw axe remains **Fail**; no cause, waiver, or full accessibility acceptance follows. See the plan for exact receipts. E304 independent native functional acceptance on the E302 image **Failed**: owner 0 completed in 63.632 seconds with a 779-byte answer, but conversation deletion failed (exact status/error unavailable); owner 1 approved search and fetch, received nine search sources and one fetch source, then timed out after 120.756 seconds without an answer. Cause remains unproven. The 768 MiB sample is not actual 1 GB acceptance, and CPU throttling is not causal proof; exact cleanup and source/stage bindings passed. No retry or kill ran. E306 independently passed selected deletion-diagnostic tests and source review only; historical baseline bytes and a deletion cause remain unavailable. E307 passed Linux/amd64 build and source/stage binding for a new image (147 inputs, 52 served files). E308 then **Failed** native functional acceptance on that image: both turns returned `provider_unavailable` after the model-session event without an answer, workspace summary, or search/fetch activity; both conversation deletes returned HTTP 200. The timing projection is invalid and model identity was not retained, so no provider cause or LongCat availability is inferred. Cleanup and bindings passed; no retry or kill ran. E309 independently **Passed** warning-projection QA for its selected source/test scope (209 tests, two deprecation warnings, Ruff check/format, and three unchanged source/test pins); it did not run native/provider work. Its first parent AST-helper lookup failed on a literal-only `OUTPUT_LIMIT` match, then the corrected source review completed (review SHA-256 `020288c1388434fbcf0656da8edbe9d8e87c03027626b21e03ee832e54d0f114`). E310 then **Failed** the one native functional attempt on E307’s image: both turns returned `provider_unavailable` after model-session, without answers, workspace summaries, or search/fetch. Exact selected model identity was unavailable. Two anonymous timing rows show eight `safe_protocol_error` attempts per turn, zero sanitized chunks/bytes, and the same `native_error_unknown` terminal warning; this supports pre-chunk failures only, with provider cause and upstream status unproven. Owner 0 conversation deletion returned HTTP 503 `assistant_cache_clear_pending`; owner 1 returned HTTP 200 `none`. The 768 MiB failure sample peaked at 542,703,616/805,306,368 bytes with zero high/max/OOM deltas; CPU throttling was observed, not causal evidence or actual 1 GB acceptance. Exact cleanup and 147-input/52-file bindings passed. A parent prefix-guard helper setup failure was corrected and was not a product failure. No retry or kill ran. E311 independently passed selected cache-clear/runtime (9), supervisor (4), HTTP-boundary (8), and API-delete (2) tests, plus a synthetic child `/api/info` supervisor purge/restart probe. The original QA pin set omitted imported `tests/native_assistant_probe.py`, so its before/after binding is **Unavailable**; its optional integrated HTTP delete harness failed during startup with `diagnostic_unknown`, cause unproven, and no retry. E312 passed a separately pinned 9-test runtime-only rerun with 54 unchanged inputs, resolving only that runtime test binding gap; it does not replace E311’s missing original pin or unavailable integrated HTTP result. E313 independently passed selected closed-stage provider-diagnostic source review, 413 tests and Ruff checks; this is not native/provider acceptance, and the eight registered observer ordinals are not an HTTP retry limit. E314 passed `./scripts/build-frontend.sh` with 55 frontend checks, 82 unchanged build inputs, and all 52 served/export files byte-matched; no browser, axe, image, or runtime result follows. E315’s independent current-source axe-stack diagnostic passed execution 4/4 with zero errors, retries, or skips across desktop Chromium (1440×1000) and emulated Pixel 7 (360×800), Light and Dark. Strict raw axe still **Fails** its zero-incomplete criterion: there were zero violations and one incomplete contrast rule in each state. Six incomplete targets mapped exactly to 12 text rectangles; ordered-stack differences appeared only below the opaque panel, supporting underlay variation only. Cause, repair, foreground obstruction, and accessibility acceptance remain unproven. Source/scaffold bindings, all 52 served/export files, and exact owned cleanup passed. Earlier closure/setup and preliminary verifier failures are preserved as separate audit history; the corrected final audit did not retry the browser run or edit source. Physical mobile, actual screen-reader, and true-zoom results remain **Unavailable**. E316 passed one local Linux/amd64 image build for build and source/stage binding only (image `sha256:9ef936567f2e270f9caac07a7f002ccc52438580a3a9be8d5ad3b6c1f31df27a`, context `bbc8bd55746f92dd39a08e56d564e898cbf09f5532ac67ff5f9573c8f1739880`): all 147 input files remained bound, all 52 served files matched the export, and the owned workspace was removed. Docker `Config.Env` was not inspected; no credentials were read and no native/provider run on this image, publish, or production action occurred. E317 then records a builder-run native functional **Fail** on E316’s image; independent QA remains pending after reviewer launch was rejected by the tool registry thread limit. Both owners returned `provider_unavailable` after model-session, without an answer, workspace summary, search, or WebFetch. Model-selection predicates matched, but exact model identity was not recorded. Two timing rows show eight `safe_protocol_error` attempts each, zero sanitized chunks/bytes and zero provider-stream-failure marker rows, with two `native_error_unknown` terminal warnings; provider/upstream cause is unproven. Both conversation DELETE calls returned HTTP 200, which does not establish that E310’s earlier 503 cause was fixed. The 147 source-input and 52 served/export bindings and exact cleanup passed. The 768 MiB failure sample peaked at 546,971,648 bytes with zero high/max/OOM deltas; throttling proves neither cause nor actual 1 GB acceptance. No retry, kill, provider fallback, or production/release action occurred; at the E317 checkpoint, no further native run or repair was authorized. E318 records builder source-preparation **Pass** for focused pytest exit 0 and Ruff, but the final test count is **Unavailable**; the earlier 14-failure, 1-failure, and terminal-metadata-unavailable attempts remain historical, and parent review was static only. E319 records read-only QA by a Luna build worker (not a formal luna-qa-profile run): the named timing/probe files exited 0 with counts **Unavailable**, the selected API JUnit passed 18/18, and six source/test pins matched. E320 records an eight-case builder scroll/layout diagnostic execution **Pass**, while 12 of 16 baseline/candidate axe analyses retained incompletes and the scrolling candidate did not improve contrast; strict raw axe remains **Fail**. The 21 source pins and 52 served/export bindings matched. Mobile was emulated, screenshots were absent, and no app-accessibility acceptance follows. E292/E293 concern the pre-repair image, and canonical E288 predates the timing cleanup. Current-image/native, full accessibility, current-image kill, actual 1 GB, PR-bound rollback, release and email gates remain open. No production change, resize, email, release, actual 1 GB acceptance, or current-image kill is claimed.

Historical R-ASTRA-120 checkpoint through E815: PR #1 was observed OPEN/DRAFT at pushed head `89aa039131d01706eeb16e1f9b117dcba1987d8a`; candidate image `sha256:81be9c6fe4fdc9f47d0adafe6f9a7fc59dac2cca76eaa4111299035ee48b2271` passed build/source binding. E809 passed its two-owner local functional scope using the approved real Zen model with live native search and guarded fetch; the separate current-image active-kill diagnostic passed its local scope. These used a 768 MiB cgroup and do not establish actual 1 GB or PR rollback acceptance. The schema-13 PR-pair rehearsal remains **Fail** at its 20-second readiness cutoff; a separate cold-start observation reached assistant-disabled readiness at 20.5993 seconds and stopped without a pair result. The rehearsal-only 60-second readiness repair passed its selected check, but pair rerun and canonical check remain pending. E815's current-image wire run and formal independent terminal review **Passed for synthetic loopback protocol scope and exact cleanup**: 11 MCP tools, three synthetic Anthropic/Google/OpenAI protocol flows, ten assertions, Google continuation, 149 source inputs and 52 served/export files. E815 did not call real Anthropic, Google or OpenAI accounts; this is separate from E809's real Zen/search functional result. The earlier E812 exit-90 cleanup failure and first capped-run exit-2 failure remain historical failures. E791/E795 are scoped browser and 64-state whole-route axe passes; the guide metadata rebind matched its bound inputs and artifacts without establishing full WCAG AA. Physical mobile, true zoom, actual screen reader, PDF/UA and final PR-bound guide acceptance remain open. E800's failed canonical run and interrupted exit-143 retry remain preserved; no current canonical Pass is claimed. At this E815 checkpoint, E798 was the latest production read (schema 12 ready, loopback-only; rollout/RAM/billing unavailable). The actual combined 1 GB, PR rollback, owner canary, current canonical, deployment and release gates remain open; the US$15 monthly cap and existing 1 GB plan/backups are unchanged. No merge, production mutation, resize, rollout, release or email is claimed. See the [MVP plan](MVP-PLAN.md) for exact receipts.

Historical R-ASTRA-120 follow-on (E588–E595): the canonical gate failed with 2,620 Python passes and four stale-contract fixture failures; all four repaired regressions subsequently passed independent QA. The new local image passed build validation, but its native two-owner run failed when the search/fetch user timed out before answering. The full browser attempt failed the compact context height and hit its aggregate deadline (57 passed, one failed, 126 unrun). The parent-reviewed two-row context repair passed the full frontend build, 67 tests and packaged-export parity; rendered independent retests and a complete browser aggregate remain pending. Strict desktop raw axe still fails on an incomplete contrast rule; no gate waiver is inferred. Implementation freeze has ended for these narrow repairs, and useful disjoint Luna lanes continue. Exact PR-head image binding, native completion, current-image kill, actual combined 1 GB resources, security/recovery, PR-bound rollback and final guide/release remain open. Read-only production inspect confirms the existing healthy schema-12 revision. Existing backups and the US$15 total monthly cap are preserved; no promotion, resize, rollout or email occurred.

Historical R-ASTRA-120 evidence (E510–E569): full browser test scope passed 153/156 cases with three expected skips, while strict raw axe remains **Fail**. The versioned Zen privacy disclosure is corrected; parent review also isolated the consent regression to change only one policy field at a time (E514). Independent privacy/catalog/consent QA passed four selected cases and both Ruff checks (E515). The current four-state axe diagnostic completed with unchanged inputs/stage, zero violations and four incomplete rules; opaque-prefix evidence is diagnostic only (E516). The corrected-catalog successor image built successfully for local build scope (E518), but its two-owner native run failed: owner 0 saw worker unavailable before a model event; owner 1 completed summary/search/fetch but timed out without an answer (E520). App readiness, zero OOM/max events, stable source/stage bindings and exact fixture cleanup passed for that failure scope; the cause remains unproven. Independent review found a stale page-context WebFetch approval gap (E521); the client/server repair is implemented and parent-reviewed (E522), and selected independent backend QA passed (E523). The incremental supervisor-purge repair passed selected independent checks (E526); its added socket cleanup assertion passed separately (E529). The full approved frontend build/stage passed 57 tests and verified all 52 served files (E525). Focused desktop/emulated-mobile WebFetch checks passed 4/4 after correcting their test fixture (E527/E530/E531). Open-panel readiness and policy recovery repair received parent and independent scoped source review (E533/E535); the fresh full frontend build/stage passed 59 tests with all 52 served files matched (E534). The initial selected recovery/WebFetch browser aggregate failed 12 passed/6 failed (E536). After a one-spec fixture/scheduling repair (E537), the independent retest failed 16 passed/2 failed with stable inputs/stage and complete cleanup (E539). Parent source review confirmed sharing and refresh controls disappear on context failure. The stable-control and owned-error repair is implemented and reviewed (E540); its fresh full frontend build/stage passed 60 checks with 52 exact served/export pairs (E541). The independent 18-case context-recovery browser run failed 17 passed/1 failed at mobile incomplete-target resolution (E543), with all recovery cases passing. The refresh control now has its own mobile row (E544); the fresh approved frontend build/stage passed 60 checks and all 52 served/export pairs (E545). The independent desktop/mobile retest passed all 18 selected cases with stable source/stage bindings and verified cleanup (E546). Mobile raw axe still reports one disclaimer contrast incomplete, so strict accessibility remains Fail. Successor preparation path/cycle fixes and fresh bindings were reviewed (E547–E549); the same-container image built successfully with unchanged 147-source/52-file bindings (E550). The authorized native launcher failed before Docker because its private scratch parent was missing (E554); source/stage parity passed and no model or tool calls ran. The minimal private-scratch repair passed independent source, synthetic and prepare-only checks (E555–E556). A second invocation was held before runtime because the parent left authorization review fields pending (E557). After correcting that metadata, the single authorized native functional attempt failed for both owners before model-session events with worker_unavailable (E558). App readiness, unchanged source/stage and exact fixture cleanup passed; no answer or tool acceptance was established, and root cause remains unproven. Source-only review completed without establishing a runtime cause or a supported catalog-disable configuration (E560). The bounded anonymous pre-session diagnostic refinement passed parent review and 133 independent synthetic checks (E561–E562); turn/tool budgets and provider policy are unchanged. The canonical check failed with 2,617 Python passes and one worker-recycle regression failure (E563); the test-only incremental-tick repair passed independent scoped QA (E564), while a new canonical aggregate remains pending. Frontend advanced history/export/Markets controls are integrated, with independent focused checks and the fresh full 66-test build/stage passing (E565/E568). Backend schema and indexed-query repairs remain under source review (E566). One ignored mobile line-height candidate failed to clear strict axe and was not integrated (E567). Exact obsolete local image cleanup reclaimed space (E569); no native or production result follows. All available worker slots are being used for disjoint work under the task-scoped parallel policy. Release gates remain open. Exact unused local-image retirement reclaimed storage without affecting protected images, containers or volumes (E538). No recovery/native acceptance is inferred. Native completion, current-image kill, actual combined 1 GB resources, accessibility, current canonical gate and PR-bound rollback remain open. Read-only deployment MCP inspect reconfirmed the healthy schema-12 production baseline (E532); no promotion or rollout was invoked. The US$15 monthly total cap includes backups and taxes; the 1 GB host and backups remain, with no resize, deployment, rollout or email.

For this invitation-support thread only, the user authorized direct follow-up messages from their
personal Gmail in the same invitation email thread, including requests for feedback. Read replies
in that thread and correlate them with sanitized production evidence before asking the user to relay
recipient error text. This authorization does not cover unrelated email or new threads. Keep
recipient addresses, invitation codes, and credentials out of repository files and evidence.

`EXP-M09` remains a separate historical export action, not a public-hosting gate. `M09-E18`
completed M09 for its declared scope, while `M07-E20` and the `R-ASTRA-98` receipt are recorded
for their declared scopes. The three provider access items were created privately, Terraform
applied the replacement Linode and imported firewall, the reviewed image was deployed privately,
the VM-backup recovery rehearsal passed for its declared scope, and the Cloudflare owner-only
canary was active before the public boundary. Those schema-8 passkey deployment receipts are
historical. Operator read-only evidence confirms the owner passkey enrollment and a
completed passkey verification with persisted owner mappings for that prior release. E55's later server-observed access logs
confirm authenticated owner API retrieval and saved-forecast access; browser-rendered content remains
**Unavailable**. E56 passes the four two-client isolation scenarios locally, and E57's rerun of the
full local gate passes after its initial comment-audit failure. Remote two-user behavior and browser
UI remain **Unavailable**. E58 records the provider-refreshed `public_invited` Terraform apply and
live public boundary; the live IAB showed the unauthenticated sign-in page but no owner UI session.
E59 records the retirement of legacy Linode `97934478`; functional owner/invited-user browser
acceptance remains pending. E60 records the current-machine browser passkey limitation; E61-E62
record the locally accepted repair and gate, E63 records the current image deployment, and E64 records
Astra's no-P1/P2 live read-only review. Browser-rendered owner content, live second-user onboarding,
and hardware passkey evidence remain **Unavailable**. The Cloudflare token verification
check returned HTTP `401` in an earlier Luna report despite functional provider API/Terraform
operations; this discrepancy remains visible. No full public production acceptance claim is made.
Unavailable evidence categories—actual screen reader, physical mobile, true browser zoom, native
ARM64 performance, provider runtime, CUA, and project-profile/skill runtime discovery—remain
separate limitations.

### Current deployment-access and invitation-transport follow-on (`R-ASTRA-106`)

- **Status:** **In progress**. Reviewed `main` revision
  `de9f45f2d5c562c34e004c658e7cee118af6ef58` was pushed. The implementation adds the typed MCP
  operation `refresh_operator_access(operator_ipv4_cidr)` and extends invitation SMTP compatibility
  to `implicit_tls` on ports `465` or `2465`, or `starttls` on port `587`.
- `refresh_operator_access` accepts one canonical IPv4 `/32` and plans/applies only the fixed
  `linode_firewall.signal_ledger` resource (firewall ID `177236117`), changing the `ssh-operator`
  TCP port-22 rule. It uses the fixed external private Terraform state and the existing clean-tree,
  exact-`origin/main`, reviewed-revision source gate. The MCP accepts no arbitrary command, path,
  state, or credential argument. The operator's Linode console login uses Google SSO; SSH material
  remains a separate operator-controlled boundary.
- `R-ASTRA-106-E1` records independent Luna QA: `37` focused tests, Ruff/security/compilation,
  locked MCP stdio six-tool discovery, and invalid-CIDR behavior all **Pass** for the declared local
  scope. Exact command, UTC window, and artifact were not supplied; reviewer `LUNA MAX QA`.
- `R-ASTRA-106-E2` records the initial documentation semantic audit **Fail** for stale five-tool and
  SMTP-port wording. The authored-documentation repair is recorded by the follow-up checks below;
  no runtime or deployment result is inferred.
- `R-ASTRA-106-E3` records `./infra/linode/validate.sh`: Terraform checks passed, then the required
  dirty-tree gate exited `2`. The aggregate is **Fail** for that command, with no live Terraform
  apply or firewall refresh observed.
- `R-ASTRA-106-E4` records the SOL source review **Pass** with no P1/P2 after the prior firewall-ID
  issue was repaired and re-reviewed. Exact review command, UTC, artifact, and source-review
  revision were not supplied.
- `R-ASTRA-106-E5` records the final authored-documentation checks **Pass** on native x86_64 at
  `2026-09-30T23:52:55Z`–`23:53:57Z`: the validator reported `9` categories, `13` topics, and
  `7` governance entries; documentation tests passed `57` with one warning; map coverage checked
  `133` files; the coverage self-test passed `26` cases; and the scoped diff check exited `0`.
  Commands were the validator, `tests/test_docs_validation.py`, both documentation-coverage checks,
  and `git diff --check -- AGENTS.md README.md MVP-PLAN.md MVP-ROADMAP.md docs`; reviewer
  `LUNA MAX docs`.
- `R-ASTRA-106-E6` records the full local gate on revision `411c146`: command
  `TASK_ID=R-ASTRA-106 ./scripts/local-gate.sh check`, receipt
  `test-results/local-gates/R-ASTRA-106-20260930T235707Z/evidence.json`, `741` Python and `27`
  frontend checks passed. `R-ASTRA-106-E7` records a separate `19`-pass focused repaired guard on
  pushed revision `de9f45f2d5c562c34e004c658e7cee118af6ef58`.
- `R-ASTRA-106-E8` records the earlier live operator refresh to `50.21.67.178/32` through the
  fixed typed controller; `R-ASTRA-106-E9` records the two failed official-client plan attempts
  plus the fixed-helper fallback. `R-ASTRA-106-E10` records the declared-scope schema-10
  deployment and HTTPS boundary; `R-ASTRA-106-E11` records the authored documentation checks.
  These do not claim SMTP authentication, sending, mailbox delivery, owner TOTP enrollment, or
  full production acceptance.
- `R-ASTRA-106-E12` records the Resend follow-on, which is **In progress**. A free account was
  created through Google SSO and
  `mail.jtmb.cc` was reported verified at approximately `2026-10-01T14:04Z`. Three DNS-only
  records were committed and pushed in Cloudflare Terraform at
  `90ad506dc7c39e145734f295f41ac2a4358b7a14`; Terraform format/validate, the exact three-record
  create apply, public DNS resolution, and the post-apply no-change plan passed for the DNS scope.
  `R-ASTRA-106-E13` records the Linode TCP and TLS 1.3 checks to `smtp.resend.com:2465` after the
  fixed controller applied operator SSH `142.198.155.54/32`. At that checkpoint, no API key or host
  installation was observed and no live send or mailbox delivery was verified. A later production
  observation reported `email_invites_enabled=False` (timestamp not supplied); 25 fake-SMTP tests
  plus invitation-expiry coverage pass, but live delivery remains unverified.
- `R-ASTRA-106-E14` records installer QA against local revision
  `42cf0f40c98404d55585745b10311354661a5195`; that installer is included in pushed `main`
  checkpoint `329fdc595483fa3b112b98c7788d808348638faa`, reported as matching `origin/main` at that
  checkpoint, with the tree clean at push.
  Builder checks reported `11` focused tests, Ruff check/format, `bash -n`, and ShellCheck **Pass**
  as self-validation. `R-ASTRA-106-E15` retains the initial independent QA P1 remote-shell
  quoting blocker and P2 incomplete-read rollback blocker. `R-ASTRA-106-E16` records the repaired
  independent QA recheck: `13` tests passed, including command parse/probe and incomplete-read
  rollback, for its declared local scope. No API key, host installation, live send, mailbox
  delivery, or production acceptance is evidenced.
- `R-ASTRA-106-E17` records the final authored-documentation checks **Pass** on native x86_64 at
  `2026-10-01T14:55:29Z`–`14:56:27Z`, dirty `HEAD`
  `42cf0f40c98404d55585745b10311354661a5195`: `.dev-venv/bin/python scripts/validate_docs.py`
  reported `9` categories, `13` topics, and `7` governance entries; documentation tests passed
  `57` with one warning; coverage checked `133` mapped files; the coverage self-test passed `26`
  cases; and scoped `git diff --check -- AGENTS.md README.md MVP-PLAN.md MVP-ROADMAP.md docs`
  exited `0`. Subsequent docs-only checkpoint
  `329fdc595483fa3b112b98c7788d808348638faa` was pushed; pre-push documentation coverage reported
  `133` mapped files/`10` changed passed, and `git ls-remote origin refs/heads/main` exactly
  matched; the tree was clean at push. Reviewer `LUNA MAX docs`; these checks do not establish installer,
  host, SMTP, mailbox, or production acceptance.
- The fixed Resend installer accepts only one operator-owned private, one-line API-key file
  through `infra/linode/install-resend-smtp-key.sh --api-key-file FILE`; host, SSH account, remote
  paths, Compose file, image behavior, and readiness URL remain fixed. The API key must stay outside
  the repository, logs, exports, and evidence. The earlier pending-key state was superseded by the
  user-authorized R-ASTRA-112 install and test; no credential-bearing values were recorded.

`M09-E13` is a frozen historical constraint for the M09 contract, not a current absence-audit
task. Its original rejected M09 scope remains intact. Later `R-ASTRA-98` separately
approved/evidenced bounded watchlists, forecast/model expansion, and provider-labelled
quote/daily-bar market-data research; that later research scope does not retroactively alter
`M09-E13`, reopen M09 implementation, or invent a new task. `M09-E14` and the retained
Ponytail/`R-M09-1` boundary record are historical overengineering evidence superseded for the
declared M09 scope by `M09-E18`; no current repair or Ponytail action follows from them.
`R-M07-1` and `R-M07-2` retain historical statuses only and are superseded for M07's declared
integrated scope by `M07-E20`; no current M07 repair, Ponytail availability review, or retest is
open.

### Current email-invitation follow-on (`R-ASTRA-104`)

- Email invitations are an optional administrator convenience over the existing single-use,
  expiring invitation flow. The numeric GitHub account ID remains the identity binding; an email
  address is only a delivery destination. Manual code creation and private sharing remain available
  without SMTP.
- SMTP configuration is all-or-none and is passed through the production Compose service. Keep
  credentials in the operator-controlled secret path outside the repository. The documented
  contract is `implicit_tls` on port `465` or `2465`, or `starttls` on port `587`; SMTP acceptance is not
  mailbox-delivery evidence.
- The fixed `infra/linode/update-host-compose.sh` updater requires a clean worktree whose local
  `HEAD` matches both the supplied reviewed SHA and public `origin/main`; it also verifies the
  tracked Compose checksum. It only installs the reviewed file and does not restart services.
  Coverage belongs in `docs/develop/documentation.md`,
  `docs/configure/local-configuration.md`, and the production section of
  `docs/operations/getting-started.md`.
- **Status:** **In progress**. Independent scoped QA passed backend invitation/mail and UI checks,
  frontend build/typecheck and `27` tests, npm audit with zero advisories, package smoke, and a
  focused browser run of `6/6` desktop/emulated-mobile cases. The broader browser attempt is
  **Unavailable** as an aggregate after `44` passed, `61` unrun, and one interrupted case. Astra's
  source-only medium review at `2026-09-30T22:14:20Z` on dirty `HEAD`
  `010ecab30fc3180751cc74e3737e42675bf6462a` found no P1/P2. No live SMTP delivery, production
  Compose update/deployment, full browser result, or release acceptance is claimed. Exact QA
  commands, artifacts, and named reviewer were not supplied.
- The authored documentation gate passed on native x86_64 at the same dirty revision: validator
  reported `9` categories, `13` topics, and `7` governance entries; coverage checked `133` mapped
  files; `tests/test_docs_validation.py` passed `57` tests with one warning; and scoped
  `git diff --check` exited `0` at `2026-09-30T22:31:51Z`–`22:32:10Z`. The initial validator
  rejection of a new unadmitted topic was repaired by folding the guide into the existing
  getting-started page; no validator or map configuration was changed. The initial full local gate
  **Failed** with `686` passed, `4` deselected, and `45` documentation-fixture setup errors; its
  receipt is `test-results/local-gates/R-ASTRA-104-20260930T222152Z/`. The docs-only link repair was
  followed by a passing full local gate for its declared scope: receipt
  `test-results/local-gates/R-ASTRA-104-20260930T223407Z/evidence.json` records `731` Python tests
  passed, `4` deselected, `85.48%` coverage, frontend build/typecheck and `27/27` tests, plus
  documentation coverage and backup follow-on checks. This rerun supersedes the initial failure for
  that scope. The broader browser aggregate remains **Unavailable**, and live SMTP delivery and
  production deployment remain unverified.

### Historical TOTP enrollment key-reuse repair (`R-ASTRA-107`)

- **Status:** **In progress** for owner authentication; the repair is deployed through R-ASTRA-110.
  A default enrollment start reuses the active pending setup only for
  the same session, factor generation, and origin, preserving its original expiry. An explicit
  `replace` request rotates the pending key; a different origin cannot silently overwrite it. The UI
  shows expiry, disables expired QR/code use, and offers recovery from a cross-session conflict.
- **Production observation:** starts at `2026-10-01T15:03:02Z` and `15:04:39Z` returned `200`;
  finish attempts at `15:05:51Z` and `15:06:10Z` returned `403`. A pending row from the second
  start remained, and server NTP was synced. These are historical bounded observations before the
  repaired deployment.
- **Independent QA:** the initial review recorded a P2 because the cross-session replacement button
  was missing; that repair was applied. Final desktop and emulated-mobile checks passed `3/3` each
  after the frontend build at `2026-10-01T19:22Z`. An earlier stale staged-export browser attempt
  **Failed** and remains historical.
- **Local gate:** receipt `test-results/local-gates/R-ASTRA-107-20261001T154012Z/` reported
  **Pass** on dirty `HEAD` `2e07a8e`: `763` Python tests passed, `4` were deselected, coverage was
  `85.47%`, and the reported frontend/build/typecheck/docs checks passed with `28` frontend checks.
  The gate began before the final UI repair, so it is not a final exact-tree gate.
- **Final-tree local gate:** receipt
  `test-results/local-gates/R-ASTRA-107-20261001T193724Z/evidence.json` passed on native x86_64,
  dirty `HEAD` `2e07a8e9e2b15d80bc154182d0392977c60db53a`, from `2026-10-01T19:37:24Z` to
  `19:47:25Z`; it records `763` Python tests, `4` deselected, `85.45%` coverage, and frontend `28`,
  build, typecheck, and documentation checks. This is local dirty-tree evidence. The later push and
  deployment at `a2247cce6e9f55fc81f96da3698f424ae2a2dc20` are separate evidence below.
- **Deployment:** pushed revision `a2247cce6e9f55fc81f96da3698f424ae2a2dc20` published a Linux/amd64
  release archive with SHA-256 `85c53648c8c1810bfc37153c404d4064ee468c81ce78caaf0666e71bb5221106`
  and image ID `sha256:b4249173085ef5b7b6c0df8741aa34d99e6b1d488ab9bfc829010398a422d2a1`;
  size was `103160002` bytes and publisher re-download verification passed. The Terraform MCP
  refresh applied `50.21.67.178/32` to fixed firewall `177236117`. Two MCP `plan_deploy` attempts
  returned `remote_operation_failed`; fixed typed host-helper plan `105579dd822e69b03360201df2276bc3`
  succeeded, followed by MCP deploy with readiness schema `10`. Status reported revision `a2247cc`,
  `failed: null`, `loopback_only: true`, backup
  `pre-deploy-a2247cce6e9f55fc-6ef1c2e6.spbackup`, and
  `deployed_at=2026-10-01T19:58:26.230020Z`.
- **Live boundary and device limits:** public HTTPS returned health `200`, auth status `200`, anonymous
  history `401`, and overview `303` to sign-in, all with `no-store`/`DYNAMIC`. IAB GitHub sign-in as
  `jtmb` reached authenticator setup; repeated default starts across reload returned the same pending
  key when compared locally without exposing it, and expiry plus explicit rotation controls were visible.
  No TOTP code was entered, so owner enrollment and authenticated workspace retrieval remain
  **Unavailable**; physical iPhone code validation is **Unavailable**. R-ASTRA-107 remains **In progress**
  for complete auth acceptance, not deployment.

- **Key exposure guidance:** a QR code or setup key visible in a photo or screenshot must be treated
  as exposed. Use **Start over with new key** to rotate it, replace the old Signal Ledger entry in
  Apple Passwords with the new key before entering its code, and do not use the captured QR or old
  key.

### Historical Microsoft Authenticator dropdown follow-on (`R-ASTRA-109`)

- **Status:** **In progress** for complete owner authentication. The Microsoft Authenticator option
  and its app-specific setup guidance are deployed at pushed `main` revision
  `3ec26d2826bf4acfbe0b8af8eaf2bb7b8ad54d5d`, which matched `origin/main` with a clean tree at the
  checkpoint. Microsoft Support documents adding non-Microsoft accounts through **+** >
  **Other account**, scanning the site's QR code, and manual-code entry in flows that provide it.
- The focused authenticator browser run passed `14/14` on desktop Chromium and emulated Pixel 7.
  Production GitHub sign-in showed the Microsoft option and its guidance; selection enabled setup-key
  generation. No setup key or TOTP code was generated or entered.
- This is the pre-R110 chooser record; its iOS-routing draft was superseded and deployed in
  R-ASTRA-110 below. Microsoft Authenticator defaults
  to same-phone manual key entry, and its QR is hidden until the user explicitly selects **Another
  screen: scan from inside Microsoft Authenticator**. The page warns against iPhone Camera or Photos,
  which may route the QR to Apple Passwords; no documented way to force those iOS tools to open
  Microsoft Authenticator is claimed. At that source-draft checkpoint, deployment and final QA had
  not yet completed; the result is recorded in R-ASTRA-110 below.
- **Final local gate:** `TASK_ID=R-ASTRA-109 ./scripts/local-gate.sh check` passed with exit `0` on
  native x86_64 from `2026-10-02T00:30:17Z` to `00:37:23Z`; receipt
  `test-results/local-gates/R-ASTRA-109-20261002T003017Z/evidence.json` records dirty base
  revision `9f983a08bf5aeef5f1ace1bd61afee20228499d7`, `763` Python tests passed, `4` deselected,
  `85.47%` coverage, and frontend `28`, build, typecheck, and documentation checks passed.
- **Release and deployment:** GitHub Release
  `signal-ledger-3ec26d2826bf4acfbe0b8af8eaf2bb7b8ad54d5d` has archive SHA-256
  `82acc1fcb52da66ee0ced78e8549780cd81ba31f73a657f761cdeb41284a0068` and Linux/amd64 image
  `sha256:91253b9384318853c36b9949f091bab747b8d9dac930e002f0dc116aef05c8e8`, size `103157486`
  bytes. The first MCP plan returned `remote_operation_failed`; fixed restricted helper plan
  `5dc7eb3db7946693b2043895e8f50c4d` passed, then MCP deploy succeeded. Status reported schema `10`
  ready, exact revision, backup `pre-deploy-3ec26d2826bf4acf-0f9c4edb.spbackup`, `failed: null`,
  `loopback_only: true`, and deployment time `2026-10-02T00:42:50.439878Z`.
- **Live boundary and limits:** health/auth status returned `200`, anonymous history `401`, and
  `/overview` redirected `303` to sign-in, with `no-store`/`DYNAMIC` responses. The post-deployment
  read-only query found zero owner factors and zero active pending enrollments; its latest attempt
  was `2026-10-01T15:06:10.939538+00:00`. Owner code acceptance, authenticated workspace retrieval,
  physical iPhone code acceptance, and actual Microsoft Authenticator interaction remain
  **Unavailable**. This is not complete authentication acceptance.

### Microsoft Authenticator iOS setup-routing follow-on (`R-ASTRA-110`)

- **Status:** **In progress** for complete owner authentication; **Completed** for the declared UI
  repair, local QA, deployment, and live-guidance scope. The dirty working-tree source at
  `416b29b23f3e70af1635806a77164392de76d64b` defaults Microsoft Authenticator to same-phone manual
  key entry, hides its QR until the user selects **Another screen: scan from inside Microsoft
  Authenticator**, warns against iPhone Camera or Photos, and resets the setup method to manual when
  the authenticator selection changes. No documented way to force iOS Camera or Photos to open
  Microsoft Authenticator is claimed.
- **Independent checks:** GPT-6.1 Sol's read-only review reported no findings. The focused Python command
  `.dev-venv/bin/python -m pytest tests/test_auth.py -q -k 'totp_enrollment or authenticator_api_enrollment or totp_replay or totp_failed_attempts'`
  passed `8` tests, and `node --test tests/auth-contract.test.mjs` from the `frontend` directory
  passed `9` tests at `2026-10-02T18:57:02Z`. A separate native-x86_64 disposable FastAPI
  `TestClient` protocol passed from `2026-10-02T18:58:27.159923Z` to `18:58:31.766543Z` using the
  `.dev-venv/bin/python - <<'PY'` stdin script: the parsed `otpauth` URI matched the manual key,
  independent standard-library TOTP generation covered SHA-1, six digits, and 30 seconds, and
  enrollment returned HTTP `200`, ten recovery codes, enrolled status, and history HTTP `200`. No
  secret, code, or recovery value was printed; temporary data was deleted. No artifact was saved.
- **Browser, gate, and device limits:** Luna focused browser QA passed `22/22` on desktop and
  emulated Pixel 7, with the mobile `360px` check showing no overflow; the Microsoft default QR was
  absent until the scanner method was selected, and the scanner QR then appeared. Native iOS and
  Microsoft Authenticator interaction remain **Unavailable**. The earlier local-gate attempt at
  `test-results/local-gates/R-ASTRA-110-20261002T182918Z/` was interrupted with no final
  `evidence.json` or process and is **Unavailable**. A second full-gate session `81547` ended with
  exit `143`; its receipt `test-results/local-gates/R-ASTRA-110-20261002T185559Z/evidence.json`
  embeds Pass/0 fields but lists only documentation and frontend checks, with Python completion
  missing, so that aggregate remains **Unavailable**. The final gate
  `TASK_ID=R-ASTRA-110 ./scripts/local-gate.sh check` passed with exit `0` on native x86_64 dirty
  `HEAD` `416b29b23f3e70af1635806a77164392de76d64b` from `2026-10-02T19:44:59Z` to
  `19:56:44Z`; receipt `test-results/local-gates/R-ASTRA-110-20261002T194459Z/evidence.json`
  records documentation, frontend, and Python checks, `763` tests with `0` errors/failures and no
  skips, `4` deselected, `85.47%` coverage, frontend `28`, and final backup `61` passed. The declared
  release and deployment scope then completed. Publisher command `./scripts/publish-production-image.sh`
  exited `0` for pushed clean `main` revision `566baab14c298fb52b5edb3138d64cd3e9123311`; GitHub
  Release `signal-ledger-566baab14c298fb52b5edb3138d64cd3e9123311` has archive SHA-256
  `6867ddc1a78a432d5e9c0a990089f746ad3257e9f26bdf38539054160e4cad73`, Linux/amd64 image
  `sha256:151c527557161917f7184f56563f29d29fadf7d1efac7d1a2051004d1e986252`, size `103163291`,
  and verified re-download. The fixed operator firewall refresh succeeded; the first MCP plan
  returned `remote_operation_failed`, fixed restricted helper plan `22b896023069ce3c5ac09efc5a2bd19a`
  succeeded, and native MCP deploy reached schema `10` ready. Status reported the exact revision,
  `failed: null`, `loopback_only: true`, backup `pre-deploy-566baab14c298fb5-93cbdab4.spbackup`,
  and `deployed_at=2026-10-02T20:07:20.087209Z`. Public probes at `2026-10-02T20:07:33.739529Z`
  returned health `200`, auth status `200`, anonymous history `401`, and overview `303`, all
  `no-store`/`DYNAMIC`. The signed-in IAB showed the new Microsoft guidance describing manual-key and
  in-app-scanner routes, and the explicit Camera/Photos Apple Passwords warning; screenshot artifact:
  `/tmp/signal-ledger-r110-release/production-microsoft-guidance.png`. Owner TOTP acceptance,
  authenticated workspace retrieval, physical iPhone routing, and actual Microsoft Authenticator
  interaction remain **Unavailable**.

### Preceding authenticator-app chooser refinement (`R-ASTRA-108`)

- **Status:** **In progress** for complete authentication acceptance. The app chooser refinement is
  deployed at pushed revision `d5d2cbf0314091977358c3d3a90bfab096286bd4`; it does not close the
  outstanding owner TOTP enrollment requirement from R-ASTRA-107.
- The setup page requires the user to choose an authenticator before generating a key, retains the
  choice across setup and explicit rotation, removes the generic `otpauth://` handler link, and
  provides a manual key plus guidance to scan with the selected app's in-app QR reader.
- Independent Luna xhigh QA found two small issues, which were repaired; final source review reported
  no code blocker and the auth-contract check passed `9/9`. Focused browser QA passed `8/8` before
  the final copy change. After the final frontend build, the exact-tree desktop/emulated Pixel 7
  browser rerun passed `14/14`. The earlier concurrent browser attempt against a stale export failed
  and remains historical. The first full gate was interrupted after the final copy change and exited
  `1`; it is not acceptance evidence.
- **Final local gate:** `TASK_ID=R-ASTRA-108 ./scripts/local-gate.sh check` passed with exit `0` on
  native x86_64 from `2026-10-01T20:52:50Z` to `21:00:17Z`; receipt
  `test-results/local-gates/R-ASTRA-108-20261001T205250Z/evidence.json` records dirty base
  revision `da2ab8e22a1efe0bc57c903cd17a4bd9c3da4013`, `763` Python tests passed, `4` deselected,
  `85.47%` coverage, and frontend `28`, build, typecheck, and documentation checks passed.
- **Release and deployment:** GitHub Release
  `signal-ledger-d5d2cbf0314091977358c3d3a90bfab096286bd4` has archive SHA-256
  `4c57f78084e4c27dc5a666c2fc8f080b5ef9b02c83b7a0ea33ae4ac7761c8129` and Linux/amd64 image
  `sha256:151ba3169c65cd6cb410cb19b6102e67a61289fd58fb74384c9bc953150e1e85`, size `103157662`
  bytes. The first MCP plan returned `remote_operation_failed`; the fixed restricted host-helper plan
  passed with ID `93852f0183b35d024f6bbe27b3388784`, then MCP deploy succeeded. Status reported exact
  revision `d5d2cbf0314091977358c3d3a90bfab096286bd4`, schema `10` ready, backup
  `pre-deploy-d5d2cbf031409197-d1b7d25e.spbackup`, `failed: null`, `loopback_only: true`, and
  deployment time `2026-10-01T21:06:23.524988Z`.
- **Live boundary and limits:** health and auth status returned `200`, anonymous history returned
  `401`, and `/overview` redirected `303` to sign-in, with `no-store`/`DYNAMIC` responses. After
  GitHub sign-in as `jtmb`, the chooser appeared before key generation; the button was disabled with
  no choice, selecting Google Authenticator displayed its instructions and enabled the button, and
  resetting the choice disabled it again. No key was generated and no TOTP code was entered. The
  operator's read-only database query found zero owner factors and zero active pending enrollments.
  Owner code acceptance, authenticated workspace retrieval, physical iPhone, and VoiceOver evidence
  remain **Unavailable**; R-ASTRA-108 remains **In progress**.

### Deployed authenticator-only baseline (`R-ASTRA-103`)

- Production retains invite-only GitHub OAuth and the numeric GitHub account ID as the stable
  identity. The sole application second factor is a six-digit TOTP code from an authenticator app.
  The deployed schema-10 migration revokes stored passkeys and old passkey sessions; the application
  does not create or accept WebAuthn credentials.
- After a fresh GitHub OAuth sign-in, an account without a TOTP factor goes directly to
  `/authenticator?mode=enroll`; the old `/passkey` route redirects to that authenticator flow. An
  existing TOTP account still requires its current TOTP or recovery-code replacement flow; a
  fresh GitHub session alone cannot replace the factor.
- Enrollment is short-lived and origin-bound. The API returns an `otpauth_uri`; the page renders
  its QR locally and offers manual-key entry without a generic URI-handler link. It then returns
  recovery codes exactly once after a valid code. Recovery codes are
  hashed, high-entropy, and single-use. Losing an authenticator enters a factor-replacement-only
  recovery session; it does not grant a normal workspace session.
- Sessions remain opaque server-side records with hashed tokens, idle and absolute expiry,
  revocation, host-only `Secure`/`HttpOnly` cookies, exact-origin/Host checks, and CSRF protection.
  Factor generation, replay, and attempt throttling are checked under the SQLite write boundary.
  Every private query and ID lookup continues to derive ownership from the session.
- Backup status/creation and restore promotion are administrator operations. Restore promotion
  requires fresh TOTP proof, a verified pre-restore backup, matching account-security state,
  serialized maintenance, and session revocation.
- Scoped independent QA passed `64` authentication/repository/list checks, `123` API checks, `61`
  backup/CLI checks, `10` desktop/mobile-emulated auth-flow cases, `27` frontend checks, Ruff,
  and diff checks. Fresh schema-10 creation and schema-9-to-10 migration checks passed; the `61`
  backup/CLI check set passed. No schema-10 backup/restore rehearsal is claimed.
  The owner API flow returned `303` to `/authenticator?mode=enroll`, required TOTP for protected
  access, denied private history without a session, and returned `403` for WebAuthn. Existing TOTP
  factor replacement remained guarded. Astra's independent medium source security review reported
  no P1/P2 finding.
- The current local `R-ASTRA-103` gate **Passed** for its declared scope. Receipt:
  `test-results/local-gates/R-ASTRA-103-20260928T235350Z/evidence.json`. It reports `707` Python
  tests passed, `4` live tests deselected, `85.25%` coverage, frontend build/typecheck and `27`
  frontend tests, and documentation coverage. The older schema-9 backup remains an offline recovery
  artifact only.
- Post-deploy receipt: exact remote `main` revision `9cc0751da459e911d285b14e0d57a29320a9f366` was
  published as GitHub Release `signal-ledger-9cc0751da459e911d285b14e0d57a29320a9f366`; archive
  SHA-256 `d60da545be26a050e305e13d2e8db219a253a0668b32f13f532148069bde188e`, Linux/amd64 image
  ID `sha256:3e5f242573044114797b66447e3a8139ed35ca7decc387e6f1ab3ef62db486ff`, and size
  `103143811` bytes. Publisher re-download verification passed. Restricted MCP plan
  `16c6655376c3b80569694ce400a2381c` passed; deploy returned readiness schema `10`, and status
  reported the exact revision, backup `pre-deploy-9cc0751da459e911-20833573.spbackup`,
  `deployed_at=2026-09-29T00:21:06.828904+00:00`, `failed: null`, and `loopback_only: true`.
- Live HTTPS at `2026-09-29T00:22:18Z`–`00:22:19Z` returned `200` health, anonymous history `401`,
  and overview `303` to sign-in with `no-store`/`DYNAMIC`. `/passkey?mode=verify` returned `303`
  to `/authenticator?mode=enroll&next=%2Foverview`. In the IAB, the revoked old session showed
  `Sign in first`; fresh GitHub sign-in as `jtmb` rendered the authenticator enrollment page with
  `Protect your account`, `Setup needed`, and `Generate setup key`. No WebAuthn prompt appeared.
  Owner TOTP enrollment, workspace content, saved holdings, physical mobile, and second-user
  acceptance remain **Unavailable**.

### Historical secure production follow-on (`R-ASTRA-101`)

- Production is invite-only GitHub OAuth plus a required user-verifying passkey. GitHub's numeric
  account ID is the stable identity; invitations are resolved, expiring, and single-use. Local
  bootstrap credentials are development-only and production startup rejects them.
- Sessions are opaque server-side records addressed by hashed tokens, with idle and absolute
  expiry, revocation, host-only `Secure`/`HttpOnly` cookies, exact-origin/Host checks, and CSRF
  protection. Every private query and ID lookup derives ownership from the session, including
  events, saved results, exports, outcomes, reconstructions, holdings, and watchlists.
- Backup status/creation and restore promotion are administrator operations. Restore promotion
  requires recent passkey proof, a verified pre-restore backup, matching account-security state,
  serialized maintenance, and revocation of all sessions.
- The production app remains one FastAPI process with SQLite on a persistent Linode volume. Docker
  publishes only `127.0.0.1:8000`; a host-managed Cloudflare Tunnel is the only intended ingress.
  HTML and authenticated API responses must
  bypass shared caching, and proxy information is trusted only from the local connector.
- Terraform's Linode definition keeps the same `g6-nanode-1` (1 GB/25 GB) Ubuntu 24.04 host in
  `us-east`, imports firewall `177236117`, enables VM Backups and disk encryption, permits only
  operator SSH from the configured `/32`, and prevents destruction. Its fixed source gate checks a
  clean checkout, exact `origin/main`, reviewed revision, and source checksums during both plan and
  apply. The applied host is Linode `106817202`; only that replacement is attached to firewall
  `177236117`; E59 retired the legacy host after validation-only and guarded execute checks.
  Cloudflare was initially applied in `closed`
  terminal-404 mode; E58 then applied the provider-refreshed `public_invited` boundary by deleting
  the owner-canary Access app and updating the exposure guard. The resulting state has `0` Access
  apps, `1` tunnel, `1` DNS record, and `1` cache ruleset. The connector routes `ledger.jtmb.cc`
  through loopback and bypasses shared/browser caching for the exact host. `/overview` returned
  `303` to local sign-in, `/api/v1/history` returned `401`, and `/api/v1/auth/status` returned `200`,
  all with `no-store`/`DYNAMIC`; the host's direct port `8000` remains unreachable. The live IAB
  showed the unauthenticated sign-in page but no owner UI session. E59 records retirement of legacy
  Linode `97934478`; E60 records the current-machine browser passkey limitation, E61-E62 record
  the locally accepted repair and gate, E63 records the current deployment, and E64 records Astra's
  no-P1/P2 live read-only review. Functional invited-user acceptance remains pending.
- The local stdio deployment MCP exposes six typed tools: `inspect`, `plan_deploy`, `deploy`,
  `status`, `rollback`, and `refresh_operator_access(operator_ipv4_cidr)`. The default transport carries a reviewed `main` revision, release archive
  SHA-256, and full Docker image ID; the fixed helper derives the GitHub Release URL and verifies
  archive bytes, image identity, platform, schema, backup, and readiness before promotion. GHCR is
  an explicit compatibility mode only. The MCP cannot receive arbitrary shell commands, paths,
  URLs, Compose files, registry names, tags, or Docker-socket requests; the VM never builds source.
  `.codex/config.toml` supplies only fixed, nonsecret target metadata and operator-owned key paths.
  Fresh CLI static discovery passed. An official Python SDK stdio client initialized the fixed-target
  server, listed exactly the five historical release/deployment tools available at that revision, and completed read-only `inspect` with
  `is_error=False`; no credential bytes were printed. A later official Python SDK plan
  `a07bb7ba2716899bef956269495f0a47` and deploy passed to the replacement Linode, whose status was
  healthy, schema `8`, and loopback-only with a pre-deploy backup. A fresh official Python SDK
  stdio client with explicit fixed nonsecret target metadata listed exactly the five historical release/deployment tools;
  read-only `inspect` and `status` passed, and the inspect receipt at
  `2026-09-28T14:30:59.523209+00:00` reported revision `2de5e9f199cd145707f95e81d389c40b2ab3c32a`,
  image `sha256:ae7991f35a2093b145245f8037a3227981b09051805467870f759c0752bbfc3d`, schema `8`,
  health `ready`, `loopback_only: true`, and `failed: null`. The in-task MCP tool returned
  `deploy_target_unconfigured` because this task runtime lacked its target environment; that is
  scoped **Unavailable** evidence, not a deploy result. A fresh Codex client invocation remains
  **Unavailable** because the current host approval policy is `never`; rollback is not accepted
  by the read-only smoke.
- Current evidence is bounded: native x86_64 dependency audits for the application and MCP both
  reported zero advisories; the current frontend build/typecheck/test run reported `28` passed;
  focused API/auth checks reported
  `151` passed; production-helper/MCP checks reported `31` passed; and the isolated production-
  shaped browser review passed sign-in Light/Dark at `1280x720` and `390x844`, protected-route
  redirects, private-history denial, Host/Origin spoof rejection, 104 loopback-only requests,
  focus, and 44px targets. CUA, full axe, physical mobile, actual screen reader, and true zoom
  evidence remain **Unavailable**.
- The latest completed local `R-ASTRA-101` gate passed at dirty `HEAD`
  `585a5c2e28aef66d3100df91063dc9ee64b81cac` from `2026-09-27T14:14:22Z` to
  `2026-09-27T14:30:02Z`: the coordinator command stdout reported Python `644` passed/`4` live
  deselected with `85.36%` coverage and frontend `27` tests; the completed checks were
  `documentation-completeness`, `frontend-npm-ci-typecheck-build-test-stage`, and
  `python-checks`. The receipt is
  `test-results/local-gates/R-ASTRA-101-20260927T141422Z/evidence.json`; this is local
  dirty-tree evidence and does not claim GHCR, an image deployed on the remote VM, Linode deployment, public
  exposure, or release; the retained receipt does not independently reconstruct the stdout-only
  coverage or frontend counts. The earlier `2026-09-27T13:39` gate failure remains visible: five fixed
  10-second child-startup waits under 4 GB full swap reached `185` tests and exited `2`, while a
  parent rerun saw one equivalent timeout; the test-only harness repair added bounded 30-second
  waits and cleanup, and Luna's independent six-target-twice plus full-backup-file check passed
  `24` cases with source unchanged.
- The local schema-6 snapshot and verified signed backup share database SHA-256
  `2533d3bf96db79610b4616531e047df434ed54b1b2e1243c8a65b4e8401adcfd`; integrity is `ok`, with
  13 events, 13 runs, 20 results, 6 portfolio holdings, and 3 watchlist items. Disposable
  schema-6→8 migration and a simulated owner claim to GitHub ID `86915618` preserved those rows.
  Re-take the live snapshot at cutover if data changes.
- Astra's initial medium source review found Host path poisoning and a Starlette range denial-of-
  service advisory; the targeted repairs were rechecked with no remaining source blocker reported.
  Astra's final source review reported no remaining source launch blocker after the lock, upload,
  staged-database, source-gate, cache-ordering, recursive database/backup/sidecar exclusion, and
  per-layer publisher-path fixes; the final recheck reported no P1/P2 finding.
  The historical `R-ASTRA-100` run remains **Unavailable** as one green aggregate (`603` pass,
  `5` fail, `4` deselected); four stale schema expectations and one timing race have a targeted
  `33`-pass repair run. The completed `R-ASTRA-101` local gate is recorded separately above.
- The earlier private remote deployment completed for reviewed revision
  `f329a4c99bf75d9ff2d365473051580f8eda7f58`; its verified release archive and image details
  remain historical in the root plan. That deployed image was schema `8`, healthy, and preserves the
  migrated schema-8 data counts, and is loopback-only. A successful Linode snapshot is recorded as
  `385239936`. The first disposable recovery rehearsal **Failed**: clone `106821372` reached
  offline boot, but a concurrent in-place Bash edit corrupted the running process and it exited
  `127` before verification; only that guarded clone was deleted and its API lookup returned
  `404`. The repaired rehearsal then **Passed** for its declared recovery scope: disposable clone
  `106825234` was restored from the snapshot, verified against the firewall, SSH, loopback app,
  schema, data, backups, and disabled tunnel boundary, then deleted and confirmed `404`. The
  repair retained nested firewall response handling, WAL-aware logical hashing, offline-boot
  resume, and a source-preserving SSH-host-key check. An earlier Astra re-review reported no P1/P2
  finding for that repair boundary, but a later privacy re-review found a P2 because the configured
  owner email reached an embedded Python process argv. The private-file repair is now complete:
  the value is scoped to the validator environment rather than process argv, the tracked tree has
  no literal personal email, `14` canary fixture tests passed, and the live canary script reran
  exit `0` with the tunnel active. Final Luna scoped QA passed Ruff across all four tests, `38`
  focused pytest cases, Bash syntax, warning-level ShellCheck, the tracked-email scan, canary
  privacy, and diff checks at `2026-09-28T01:38:08Z`–`2026-09-28T01:38:27Z`; Astra's final review
  reported no remaining P1/P2. The earlier Ruff import-order finding remains historical and is
  superseded by that repaired result. The old VM and current local app are untouched. This evidence
  does not authorize the invited-user route or claim a production release checkpoint.
- The final infrastructure repair set keeps the cloudflared service command code-managed, adds a
  code-managed host-unit update path, preserves the source-gated fresh-bootstrap delivery, and
  requires a live Terraform refresh guard before the canary. Independent Luna QA on native x86_64
  at dirty revision `f329a4c99bf75d9ff2d365473051580f8eda7f58` from
  `2026-09-28T01:18:00Z`–`2026-09-28T01:25:00Z` passed Terraform format/validate, `31` scoped
  infrastructure tests, and `git diff --check`. That earlier review recorded an import-order
  finding in `tests/test_linode_terraform.py`; later current-revision QA passed all four Ruff
  checks. ShellCheck warnings were recorded as informational, while the full
  `infra/linode/validate.sh` exits `2` on the intentionally dirty worktree. These checks are
  scoped historical QA, not a clean release or production acceptance result; the later
  current-revision QA is recorded below.
- The earlier private auth-UI repair and deployment used reviewed commit
  `39bd185150cd3df70395e6c000f568dfd20831ac`. Frontend build, typecheck, and `28` tests passed;
  pinned Playwright desktop/mobile checks passed `2/2`; independent Luna QA passed `9/9` auth
  contract checks, `2/2` click checks, and simulated passkey-cancellation checks on desktop and
  mobile. Astra's source review reported no P1/P2 after its `409` guidance finding was repaired.
  The locally published GitHub Release archive has SHA-256
  `930d6d5b5d054908a25825c980584b620817bfa7ab212a62abd63f65c72f6f3f`, image ID
  `sha256:23ef16e4e5ee28db378c76bbcd9182345584bbffda55bd5313141fd0847fe31b`, and a verified
  publisher re-download. Official Python SDK MCP plan `a07bb7ba2716899bef956269495f0a47` and
  deploy passed to the replacement Linode; status is healthy, schema `8`, loopback-only, with a
  pre-deploy backup present. The owner-only canary served the new passkey text and Cloudflare
  unauthenticated traffic returned `302`. The earlier tab 13 showed signed in as `jtmb` before this
  deployment, but may be stale. A fresh in-app-browser session did not produce a verified auth
  result. Owner passkey enrollment and saved-data verification remain **Unavailable/Pending**;
  the browser requested a nearby phone/Bluetooth credential and no completed credential was
  observed. No invited-user route or production release is claimed.
- The owner-only Cloudflare canary is applied for `ledger.jtmb.cc`, and the tunnel is healthy and
  active. The GitHub OAuth application authorization and Cloudflare Access one-time code flow
  completed successfully in the earlier browser session; tab 13 showed signed in as `jtmb` before
  this deployment, but may be stale. The new in-app-browser session did not produce a verified auth
  result. Owner passkey enrollment and the owner saved-data check remain **Unavailable/Pending**;
  the browser requested a nearby phone/Bluetooth credential and no completed credential was
  observed. The earlier callback-blocked observation is retained as historical evidence in E38.
  Public invited-user mode and retirement of legacy Linode `97934478` remain pending. No public
  invited-user route or production release is claimed.
- The prior scoped origin-navigation repair was reviewed at commit
  `11faaf702129d0c1485a8683711d88340f623a71`. The publisher SHA-256 is
  `fad471b19db6ff4f9b4dc154055f0d2437128e49878e72a286b697f17e8a3f48`, image ID is
  `sha256:26df706f6a2b4e76ee51bb014f94d39eb66bc7644a2c7a56eb3d012f41684d60`, and official MCP
  plan `530c1c65a7b4563e9c7f1cdbf5a47a3d` deployed a ready schema-8, loopback-only image with
  pre-deploy backup `pre-deploy-11faaf702129d0c1-d1c03381.spbackup`; status reported no failure.
  `tests/test_api.py` and `tests/test_auth.py`, focused tests, Ruff, security checks, and format
  checks passed, and Astra reported no P1/P2. An external hyperlink from localhost:8765 to
  `https://ledger.jtmb.cc/passkey` loaded the HTML page instead of the prior `origin_rejected`
  JSON response. This verifies the navigation repair only; the new tab's auth result is unverified
  and does not establish passkey enrollment or saved-data access.
- A subsequent source fix at commit `a1d868287a729c75d9b8628f612a856db132374a` handles a
  stale/expired provisional session that returned `authenticated:false` and left the passkey page
  at `Checking your session` by presenting sign-in recovery. Build/typecheck and `28` frontend
  tests passed, and the desktop/mobile browser checks passed `4/4`; the fix is source-reviewed and
  locally tested and is included in the final clean-main image below.
- The earlier private clean-main deployment used revision `2de5e9f199cd145707f95e81d389c40b2ab3c32a`,
  archive SHA-256 `b856795831b6fb46e94e330370e003843b266ad85f22e8d95ef7624536b2ac48`, and image ID
  `sha256:ae7991f35a2093b145245f8037a3227981b09051805467870f759c0752bbfc3d`. The first MCP plan
  failed transiently with `remote_operation_failed` while the canary remained healthy; fixed typed
  helper retry plan `2d8b0fe91ed01b55f1625c27edcc620b` passed. MCP deploy returned deployed/readiness
  schema `8`; status reported the current revision, `failed: null`, `loopback_only: true`, and
  pre-deploy backup `pre-deploy-2de5e9f199cd1457-751c7459.spbackup`. A live in-app-browser reload
  with an expired session showed `Sign in first` and `Open sign in` and hid `Create passkey`; after
  opening sign-in and continuing with GitHub, it returned to `/passkey?mode=enroll&next=/overview`,
  showed `Signed in as jtmb`, and showed `Create passkey`. No ceremony was completed in this
  browser tab. Separate operator read-only SQLite evidence on `2026-09-28` (exact query UTC not
  captured) found `quick_check` `ok`, zero foreign-key violations, owner id `1` claimed to the
  configured GitHub account as active admin, one nonrevoked passkey, one current passkey-verified
  session, and owner mappings of 13 events, 13 runs, 20 results, 0 outcomes, 6 holdings, and 3
  watchlist items. This proves enrollment, a completed passkey verification on another computer,
  and persisted owner mappings; it does not prove browser-rendered UI retrieval. A fresh IAB
  production tab hit Cloudflare Access login and had no transferable session. Later read-only Docker
  access logs recorded authenticated owner API retrieval and saved-forecast access; browser-rendered
  content remains **Unavailable**. E56 passes the four two-client isolation scenarios locally, but
  remote two-user behavior and browser UI remain **Unavailable**. E58 records the provider-refreshed
  `public_invited` boundary: the owner-canary Access app was deleted and the exposure guard updated;
  the live IAB showed the unauthenticated sign-in page but no owner UI session. E55 records its
  point-in-time gap status; E56 and E57 record the local QA and gate results. Functional
  owner/invited-user acceptance remains pending; E59 records the completed legacy-host retirement and
  E60 records the current-machine browser passkey limitation; E61-E62 record the locally accepted
  repair and gate, E63 records the current deployment, and E64 records Astra's no-P1/P2 live read-only
  review. Independently completed passkey, browser-rendered owner workspace, and live second-user
  onboarding remain **Unavailable**. This is not a full production acceptance claim.
- E63 is the current deployment record: main revision `27e0d2f5916d4297e10d259aa4776055a78faeaa`,
  release archive SHA-256 `78f2e44ecfbe2021a61a0ecd71414065024c246eb46ca9506b33c20f13b07ad1`, image
  ID `sha256:ecd41e1b65eb76b424cff830a6150db2282d326cfb18b3b6eaa37b07f83c4bc0`, retry MCP plan
  `21ca962a39d261282610568bc1e21219`, schema `8`, `failed: null`, loopback-only, and pre-deploy
  backup `pre-deploy-27e0d2f5916d4297-39376b8d.spbackup`. Public health/auth/sign-in probes returned
  `200`/`200`/`401`/`303` with `no-store`/`DYNAMIC`; the IAB passkey remained unavailable, while
  corrected sign-out returned `/sign-in` with no account controls twice. A post-deploy read-only
  SQLite check reported `quick_check=ok`, zero foreign-key violations, 13 search events, 13 forecast
  runs, 20 forecast results, 6 holdings, 3 watchlist items, 1 passkey, and 1 user. E64's Astra live
  read-only review found no P1/P2 for its declared scope, with the remaining browser, second-user,
  hardware passkey, Terraform/image, IPv6, and old-VM rechecks **Unavailable**.

## Repository truth

- The contract is a local Linux app for x86-64/amd64 and ARM64/aarch64, designed for low-resource operation. The current host is native x86_64; no native ARM64 or physical ARM64 performance result is claimed.
- ARM64 verification first uses local native ARM64 hardware if available. Otherwise local QEMU/OCI multi-arch execution may verify packaging, runtime, functional, build, and tool behavior, but every result is labelled emulated; it is not native/physical ARM64 or original-laptop resource evidence.
- The supplied Git remote revision `2a7a3bf66c3665552a46d0bd523544a01f894b3f` and the old GitHub Actions run are obsolete historical context only, not current gates or release proof. No hosted or external pipeline is an acceptance path; any later selective Ingenium agent-pipeline adoption is an operational follow-up only.
- `burry_env/` is tracked legacy dependency noise; do not treat it as source, add to it, repair it, or remove it. `.venv/` and other local environments are not dependency declarations or release evidence.
- Current M09 acceptance supersedes the pre-acceptance aggregate wording retained in the
  next historical status line: task `M09`, evidence `M09-E18`, ran
  `TASK_ID=M09 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh m09` and passed
  on commit `a69df40e15b3136886f26789c27861184c3bbd77` at
  `2026-09-12T17:22:52Z`–`2026-09-12T17:33:03Z` with `339` tests passed, `4` live
  deselected, `89.62%` coverage, browser `40` passed/`2` expected performance skips,
  official MCP, and explicitly labelled emulated ARM64 functional/package/runtime
  evidence (QEMU `7.2.0`, `aarch64`, not native). It records `17` executable performance
  rows **Pass** and ARM64 performance **Unavailable**; artifacts are under
  `test-results/local-gates/M09-20260912T172252Z/`. Theme p95 was `57.3 ms`, news endpoint
  p95 `1.436 ms`, ten-item render p95 `21.0 ms`, news response `701` bytes, provider
  deadline capped at `10 s`, static `98,068`/`98,304` bytes, and requests `7`.
  `R-M09-2` and `R-M09-3` are completed for their repaired scopes by this receipt, while
  their earlier failure/repair records remain visible. `EXP-M09` is **Pending** for the
  export, secret review, commit, push, and exact remote verification. `M07` is now
  **Completed for its declared scope** by the later `M07-E20` receipt; the earlier
  `M07-E18` receipt remains historical, and `EXP-M07` is also **Completed** at commit
  `779aa749d2f85849427212d890ee6918987492b7` with the export audit recorded below.
  The earlier M07 receipt recorded M08 as the next walkthrough gate; current M08,
  `ASTRA-FINAL`, and `EXP-M08` records are above. The retained `R-M09-1` boundary report
  remains overengineering-only history; no new Ponytail result is inferred.
 - Current `EXP-M07` export evidence reports `281` messages, `1,676` parts, `1,341,738` bytes,
  `39,520` lines, SHA-256
  `fddc25e5dbd0bbea4cd70cf3f124476157bb80e4f2cf9fa2ab969e69f7ace487`, and `3,793` redaction
  markers; zero canonical secret-pattern matches; parent
  `131aabc0fc0528b1e70ba26e09e2c78565ee8d56`; message `Record integrated acceptance`; exact
   remote `main` match; reviewer `LUNA MAX QA`. The earlier M07 receipt verification also
   passed with independently recomputed performance rows; its separate metadata was not
   supplied.
  - Earlier accepted `ASTRA-FINAL` is retained at clean commit
    `261825838d6788afeb9640db8fbbf3f94af3a82b`, session
    `ses_f679f906cffexS9H5k8Vwk4d16`. Its bound evidence covers a `214`-row matrix, records
   no remaining blocking defect and no regression, and explicitly records actual screen-reader,
   physical-mobile, and native/physical ARM64 performance evidence as **Unavailable**. Those
   limitations remain visible and are not treated as passes.
 - `EXP-M08` is **Completed** at commit
   `7cf1ca8395b94c2e14e5b02ddf160f3f938091d3`. The export audit reports `303` messages,
   `1,812` parts, `1,466,585` bytes, `43,137` lines, SHA-256
   `f846722f1c02aefbeb2f784141a022353c91dbf7c9bebde9c68b7a3dc79498d1`, and `4,288`
   redaction markers; zero canonical secret-pattern matches; parent
   `261825838d6788afeb9640db8fbbf3f94af3a82b`; message `Checkpoint instructional walkthrough`;
   exact remote `main` match; reviewer `LUNA MAX QA`. Export command, session, environment,
   and exact export UTC were not supplied and are not inferred.
 - The final `M07` release gate receipt (`EV-8` in the bound ASTRA evidence) passed on clean
   commit `f511ae3629de679b12c006db5d122b3ed0a22f2c`: `401` tests, `89.61%` coverage,
   browser `48` passed/`2` expected performance skips, and `17` executable performance rows
   passed; ARM64 performance is **Unavailable**. The tracked walkthrough observation is
   `7,660,518` bytes under the `20 MiB` budget, with supplied artifacts under
   `test-results/local-gates/M07-20260913T005729Z/`.
  - Historical pre-notification status (retained): the final learning synthesis via
    `skill-maintenance` was **In progress** and `EXP-FINAL` was **Pending** for synthesis
    completion and its separate export, secret review, commit, push, and exact remote
    verification.
   - The earlier supplied final acceptance receipt records accepted `EXP-FINAL` checkpoint
     `b96cb6954ecf6e03b3bcdb0ad52af38ed7eae4cb`. `NOTIFY-FINAL` is **Completed for its
     operational scope only**: the optional post-`EXP-FINAL` delivery to the user-supplied
     out-of-band webhook returned HTTP `204` with an empty response body around
     `2026-09-13T01:45Z`; no retry was needed, and the bounded success did not change the
     accepted `EXP-FINAL` result. Its retained dirty-worktree context is
     `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; reviewer/coordinator:
     `OpenCode gpt-5.6-sol`.
  - The payload was a minimal non-secret receipt containing the accepted result, checkpoint,
    and evidence summary. The endpoint, token, and credential-bearing payload were never
    written to the repository, export, artifacts, or logs; the sanitized export shows zero
    webhook-pattern matches. Exact delivery UTC, network environment, and a separate
    notification artifact were not supplied and are not inferred. `NOTIFY-FINAL` is not a
    milestone or acceptance ID.
  - Current post-repair visual reconciliation: `R-ASTRA-22` is **Completed for its declared
    scope**. Independent QA on dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09` reported
    `425` passed/`4` deselected/`89.65%` coverage, provider `32` passed, browser `62` passed/`2`
    expected performance skips plus `31` at `1280px`, `17` executable performance rows passed,
    static `97,893`/`98,304` bytes, and persistence `55 + 35 + 4` passed. `R-ASTRA-24` records
    SPY lookup as ETF, `R-ASTRA-25` heading order, `R-ASTRA-26` `44px` desktop actions, and
    `R-ASTRA-27` selector alignment after a failed initial render and successful reruns. The
    supplied overengineering-only Ponytail result was `Lean already. Ship.`
  - The earlier post-repair `ASTRA-FINAL` session `ses_f6683138affe6t8S6Z0G66YJDc` is **Accepted** with
    no reproducible blockers. Artifacts are `test-results/astra-final-live/` and
    `test-results/astra-final-repair/`; the live browser receipt records event `143`/run `141`,
    fresh event `145`, `21` localhost-only requests, and axe `0/0` at desktop and `390px`.
    Physical mobile, actual screen-reader, true-zoom, and native/physical ARM64-performance
     evidence remain **Unavailable**. ACDC/SPY flows do not prove news relevance or exact-symbol
     provider availability.
  - Current final documentation reconciliation is `R-ASTRA-71`, with `R-ASTRA-70` completed as the
    docs-only portable-link repair that changed eight ignored-artifact links to inline code. The
    final `ASTRA-FINAL` session `ses_f622707a4ffeAE3Zx8Lt2zYiC1` is **Accepted** for its affected
    post-repair scope with no blockers: reviewer `ASTRA`, model `openai/gpt-6-astra`, native
    x86_64, official MCP/headless Chromium `153.0.8010.12`, dirty `HEAD`
    `5633f87f8cff04b5b33640f6633ff31c667c0435`, `2026-09-14T02:57:56Z`–`03:16:35Z`, routes `/`
    and `/api/v1/docs`, viewports `320x844` and `1280x1000`, Light/Dark. Exact shell command and
    separate ASTRA artifact were not supplied; the named session, reviewer, model, and revision
    are supplied. The initial named post-restart session `ses_f6276e3a8ffeR3awDDSYKonmLk` remains
    **Blocked** at `2026-09-14T01:30:13Z`–`01:47:02Z` because reverse-Tab then Escape restored
    focus off-screen at `320x844`; official MCP exposure passed. Its forecast/chart/news evaluation
    was **Unavailable** because the first isolated server used the wrong 2026 fixture clock and
    correctly returned `stale_data`, not because of a production defect. The repair progression,
    clean final `R-ASTRA-69` Ponytail result `Lean already. Ship.` at `2026-09-14T02:41:58Z`, and
    independent QA are recorded in `docs/evidence/astra-final-report.md`. QA reviewer is
    `LUNA MAX QA`; its exact browser artifact is
    `test-results/r-astra-69-browser-20260914T0248Z/` (`64` passed/`2` expected skips; `33`
    desktop/`33` mobile), and physical mobile, actual screen-reader, true-zoom, fresh ASTRA
    axe/screenshots, and native/physical ARM64-performance evidence remain **Unavailable**.
   - Follow-on `R-M07-5` is **Completed for its declared scope** by two passing container
     contract tests and the supplied amd64 image receipt: digest
     `sha256:0dcb3f5ec77d31a5e8f57ef6e5d57b7144b973c3acb73ac360ffe01494735da`, size
     `169,699,932` bytes. The Compose path is one loopback-bound local service; native
    development remains the `.dev-venv/` path. This current dirty-worktree evidence does not
    create a clean release/export/commit/push/remote result or a new notification.
   - **Current `R-ASTRA-72` Orchestrator rename validation:** **Completed for its declared
     rename/restart-validation scope** from independent post-restart QA by `LUNA MAX QA`.
     The historical `R-ASTRA-72` rename performed the change to exact `Orchestrator` and required
     restart validation; full QA, Ponytail, and limitation rows are in
     `docs/evidence/astra-final-report.md`. No new release, export, commit, push, or remote result
     is claimed.
- **Current post-repair `EXP-FINAL`:** `EXP-FINAL` is **Completed** for the same declared
  final acceptance scope, not a new milestone or acceptance scope. Its implementation
  checkpoint is `c55064da92dcc8da591494c1c88cf040039e2437`; the release-receipt
  documentation checkpoint is `830030ab5322e5c7aaaf12e6fde3f6c0ea9b2a12`; and the
  accepted export checkpoint is commit `10b5de4a1842baf43e847f21f75154966e44b9c0`,
  parent `830030a`, message `Checkpoint final repair session`. Exact `git push origin main`
  passed and `git ls-remote origin refs/heads/main` exactly matched
  `10b5de4a1842baf43e847f21f75154966e44b9c0`. The sanitized export audit used session
  `ses_f71ec0499ffeokWj4h6tVwyYk1`: `572` messages, `3,155` parts, `952` tool parts,
  `350` completed task outputs, `2,552,320` bytes, `90,476` lines, SHA-256
  `cf1b85d07eefc9ff6436ad692ee826cb394be8f39af34caf6b1ff58f1f8517ff`, and `14,895`
  redaction markers; ordered message-ID hash
  `ecc9a2be4ebf82e92e459a979cde2ceb93517c61d2ec95708a9f370fff255568`; ordered part-ID
  hash `0061d16fa7de0a60d8cb159db0d11474f291247708925bc6cb4b65c643da33be`; exact
  watermark with a later database delta of `1` message/`5` parts, all strictly trailing;
  and strict allowlist redaction checked `38,686` strings with zero violations and zero
  webhook/private-key/AWS/GitHub/Bearer/credential-URL matches. The built-in sanitized and
  unsanitized OpenCode exporter attempts each emitted only `64KiB` of invalid/incomplete
  JSON; neither corrupt output was accepted. The verified equivalent used a read-only SQLite
  transaction and strict allowlist redaction. Reviewer: `LUNA MAX QA`; audit UTC
  `2026-09-13T12:28:44.223816Z`; native x86_64; OpenCode `1.18.30`. Exact export-generation
  UTC remains **Unavailable**. No CI, new acceptance scope, or new notification is claimed.
 - Earlier supplied `M08` walkthrough-extension evidence remains **In progress**: `20` steps, `40` annotated
  PNGs (`20` desktop `1280x1000`, `20` mobile `390x844`), manifest SHA-256
  `806722ad4321fa3ca25a794192649eb55ad9c55cbba4abf6ec51886ba556df5d`, five companion news
  states represented as evidence rows, `5,683,157` bytes against the `20 MiB` budget, and
   zero undeclared requests or page errors. Independent M08 verification and `EXP-M08` remain
   pending; the later ASTRA findings and repair program are recorded above. Exact generation
   command, session, environment, UTC, commit, artifact path, and named reviewer for this
   extension evidence were not supplied and are not inferred.
 - Historical pre-acceptance `ASTRA-FINAL` state (retained): it was **In progress**, not
   **Accepted**. Four ASTRA evaluation lanes
  reviewed all `211` matrix rows and found issues across assets/controls/charts, UI
  states/persistence, theme/news/docs, and the walkthrough. SOL applied fourteen repair
  groups: `R-ASTRA-1`–`R-ASTRA-5` CSS/theme defects (mobile theme selector,
  dark/forced-colors/print contrast, mobile navigation, API-docs label, and chart typography);
  `R-ASTRA-6`–`R-ASTRA-10` app behavior (news terminal states/retry/abort, history race and
  pagination guards, fresh-analysis context, saved-replay truthfulness, validation recovery,
  stale-reason placement, ledger evidence, and chart focus); `R-ASTRA-11` export
  sort-before-cap; `R-ASTRA-12` `theme.js` package verification; `R-ASTRA-13` walkthrough
  quality and the tracked [`docs/walkthrough/`](docs/walkthrough/index.md) artifact (7.19 MiB,
  52 PNGs, instructional transcript, simulation labels, and manifest revision binding); and
  `R-ASTRA-14` news/theme documentation. The static shell moved from `102,607` to `98,242`
  bytes, `62` bytes below the `98,304`-byte limit. Independent QA of all 14 repairs and the
   ASTRA re-evaluation were **In progress** at that historical point; exact commands, sessions,
   environments, UTC, commits, artifacts, and named reviewers were not supplied for that record.
 - Earlier integrated M07 release acceptance, task `M07`, evidence `M07-E18`, ran
  `TASK_ID=M07 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh release` and
  passed on clean commit `131aabc0fc0528b1e70ba26e09e2c78565ee8d56` at
  `2026-09-12T18:14:08Z`–`2026-09-12T18:21:06Z` on native x86_64 Linux: `396` tests
  passed, `4` live deselected, `89.62%` coverage, browser `40` passed/`2` expected
  performance skips, official MCP, migration with verified pre-migration backup schema v1
  to v4, backup CLI `17` passed, the retained receipt's Ponytail interface precondition
  **Pass**, and `17`
  executable performance rows **Pass** with ARM64 performance **Unavailable**. Artifacts
  are under `test-results/local-gates/M07-20260912T181408Z/`; reviewer `LUNA MAX QA`.
  The two earlier failed release runs and repairs `R-M09-4`/`R-M09-5` remain visible as
  history; their separate failure metadata is not replaced by this receipt.
 - The following aggregate status line is immutable pre-acceptance history; its `In progress` and `Pending` labels are not current work items. The current status is the overlay above, with `EXP-M09` as the sole approval gate.
 - `M01` and `EXP-M01` are **Completed**: `R-M01-3` through `R-M01-15` have independent scoped pass records and the checkpoint is verified at SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`. `M02` and `EXP-M02` are **Completed** only through the late independent repair receipt `EXP-M02-REPAIR-1`, session `ses_f6eacd1cdffeZxtRNqfzkXOuqJ`, reviewed by `LUNA MAX QA` at `2026-09-11T17:10:31Z`; its scoped records remain independently passed. `M03` and `EXP-M03` are **Completed** at exact local/remote SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`, with the supplied export receipt at commit UTC `2026-09-11T17:46:42Z`; the earlier M03 screen-reader limitation remains visible as `R-M03-23` and is not substituted by axe/MCP. `M04` and `EXP-M04` are **Completed** for their recorded scopes; `R-M04-30` remains **Pending** because actual screen-reader evidence is **Unavailable** and deferred to M06. `M05` is **Completed for its declared scope** through the independent `R-M05-55` Pass receipt; `EXP-M05` is **Completed** at commit `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`, with its exact export audit receipt recorded in the root plan and roadmap. `M06` is **Completed for its declared scope** through final clean-target `R-M06-55` on `a69df40e15b3136886f26789c27861184c3bbd77`; `EXP-M06` is **Completed** at that same checkpoint. `M09` implementation is **Completed for its declared implementation scope**, but `M09` remains **In progress** pending the boundary `/ponytail-review`, the consolidated M09 gate, docs finalization, and `EXP-M09`. The supplied scoped QA summary reports `130` news-contract tests plus live ACDC/SPY checks, browser `40` passed/`2` skipped with axe `0/0`, and passing M09 performance rows; its missing session/command/environment/UTC/commit/artifact/reviewer fields are not inferred. `R-M09-1` is the Ponytail-review/local-gate M09 regex repair in flight. `M07` is **In progress** with `R-M07-1` fifth-agent configuration/profile-count test repair in flight, `R-M07-2` Ponytail-review availability pending with findings-only evidence in retained report `test-results/ponytail-m06-m07-boundary.txt` and closure pending, `R-M07-3` completed for supplied repair/test evidence, and `R-M07-4` completed for supplied Ponytail repair evidence. `M08`, `ASTRA-FINAL`, and `EXP-FINAL` remain **Pending**. M06's Ponytail, documentation-skill, Ingenium onboarding, M07, and M09 rows retain their distinct historical states below. `R-M00-2` is documentation-only and does not accept implementation.
 - The earlier aggregate M07 in-progress wording above is immutable pre-acceptance history. At that earlier point `EXP-M07` was **Pending**; current `M07-E20` is **Completed for its declared scope**, current `EXP-M07` is **Completed** at the receipt recorded above, and the prior `R-M07-1`–`R-M07-4` limitations remain visible rather than being erased.
 - M04's exact QA/retest record is on dirty native x86_64 Linux WSL2/Python `3.11.15` revision `777451643b5ec1a04a37c013a9caf59f0bd58122`: builder sessions are A `ses_f6e6a711fffeyuef4zb62H0giu`, B `ses_f6e6a70e1ffe26uoiMUKL6tJYQ`, C `ses_f6e6a70c9ffeHInuhUf0xcS4Sf`; final independent receipt `R-M04-55` is session `ses_f6d85b2a2ffeUizsObfcDoBzsZ`, reviewed by `LUNA MAX QA`, with `198` tests/`89.29%`, `32` browser checks, `4` live checks, `55` backup checks, raw axe `0/0`, schema-4/package/migration and actual MCP passes, and explicitly emulated ARM64 functional/package evidence. `R-M04-30` remains **Pending** because actual screen-reader evidence is **Unavailable** and deferred to M06; it blocks final accessibility/release acceptance, not the exercised M04 feature scope. No native/physical ARM64 or CI result is claimed.
- `EXP-M04` is **Completed**: the sanitized full-session `SESSION-EXPORT.md` was overwritten and parsed as JSON with `140` messages, `844` parts, `101` task outputs, `241` tool parts, `672,190` bytes, `19,855` lines, SHA-256 `5eebab2ce302e9f8b5a08aec5e4773c8bf7e4a99c920fa059c462dd71cecb837`, and `1,817` redaction markers; secret review found zero webhook/private-key/AWS/GitHub/Bearer/embedded-credential matches. Commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892` (`Build responsive forecast dashboard`, commit UTC `2026-09-11T20:25:10-04:00`) was pushed and the exact `origin/main` match was verified; no CI was run. The named export reviewer is not supplied in this reconciliation.
- M06 is **Completed for its declared scope**, not final release. Final clean-target `R-M06-55` passed on native x86_64 Linux at commit `a69df40e15b3136886f26789c27861184c3bbd77`, `2026-09-12T14:40:23Z`–`2026-09-12T14:49:48Z`, exit `0`, with `278` tests/`4` live deselected/`89.51%` coverage, browser `32` passed/`2` skipped, official MCP, labelled emulated-ARM64 package/runtime evidence, and `12/13` performance rows **Pass**; ARM64 performance is **Unavailable**. The tree stayed clean before and after; reviewer `LUNA MAX QA`. Independent scoped results remain **Pass** for `R-M06-2`, `R-M06-3`, `R-M06-4`, `R-M06-11`, and `R-M06-16`–`R-M06-20`. Actual screen-reader evidence is still **Unavailable**; earlier dirty receipts remain historical.
- `EXP-M06` is **Completed** at `a69df40e15b3136886f26789c27861184c3bbd77`: export audit `253` messages/`1,500` parts/`473` tool parts/`212` task outputs, `1,202,095` bytes/`35,447` lines, SHA-256 `f882941a1bac55b9e12b57d7a640256aad5cd1b71fe920f125134147edf516fc`, `3,334` redaction markers, zero canonical secret-pattern matches, parent `9be15a3`, commit time `2026-09-12T10:39:42-04:00`, message `Record dark mode and news contract`, exact remote-main match, reviewer `LUNA MAX QA`. Export session ID and command were not supplied and are not inferred.
- M06 documentation-boundary checks remain distinct from implementation acceptance. The historical
  documentation-skill post-restart receipt is session `ses_f6aa32d33ffeAvmiFK8K7Cd8EI`,
  `2026-09-12T11:35:58Z`–`2026-09-12T11:36:02Z`, native x86_64/OpenCode `1.18.30`, dirty
  commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`; it passed canonical-description discovery,
  six historical Ponytail commands, three legacy profiles, valid configuration, and no-credential
checks. The preceding catalog reconciliation recorded seven skills; the current catalog and
validation are recorded in the reconciliation evidence above. Ponytail is not a current skill,
package, or gate.
- M05 repair status is now closed for the declared scope by the independent `R-M05-55` Pass receipt, reviewed by `LUNA MAX QA` on native x86_64 with `.dev-venv` Python `3.11.15`: rows `(a)`–`(i)` are session `ses_f6bbd6b46ffes2BM2zVjBC5uLg`, `2026-09-12T06:25:04Z`–`2026-09-12T06:44:37Z` (round trip/checksum `06:42:38Z`–`06:42:39Z`; six-path pre-migration forced-failure matrix `06:32:09Z`–`06:32:10Z`; due-check `60`/`2678400` accepted and `59`/`2678401`/`nan` rejected; retention of `32` artifacts/`256 MiB` with history preserved at `06:43:54Z`; `13/13` fail-closed negatives `06:35:29Z`–`06:35:32Z`; key lifecycle with rollback at `06:44:37Z`; `7/7` watchdog probes `06:35:01Z`–`06:35:02Z`; both-direction **emulated ARM64** cross-architecture restore `06:25:04Z`–`06:28:44Z`, artifact `test-results/arm64/M05-20260912T034933Z/evidence.json`; and the `R-M05-12` rerun `06:38:47Z`–`06:38:49Z`), and row `(j)` is session `ses_f6aa32b01ffexjSm9OhpprFwq4`, `2026-09-12T11:26:29Z`–`2026-09-12T11:28:26Z` (`276` non-live tests/`4` live deselected/`89.51%` coverage, documentation validation of `8` categories/`11` topics/`1` skill, `22` documentation tests, a `77`-file comment audit, Ruff, and mypy). Packaged-CLI end-to-end verification is session `ses_f6a96daceffegfAqyKQL2lf3bS` on native x86_64/Python `3.11.15`, with artifact `/tmp/opencode/stock-probs-m05-cli-20260912T114105Z/M05-packaged-cli-receipt.json` and reviewer `LUNA MAX QA` (fresh-venv wheel install, migration pre-backup, named backup, verify, `restore --promote`, wrong-key/tampered rejection, backup-key rotate/retire, and isolated-port serve readiness). Commands and commit were not supplied; no values are inferred. The Ponytail repair receipt is retained at [`docs/evidence/ponytail-m05-boundary.txt`](docs/evidence/ponytail-m05-boundary.txt); `EXP-M05` is **Completed** at commit `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`, with the exact export audit receipt recorded in the root plan and roadmap. Any earlier failure or pending state remains historical evidence and is not erased.
 - M05 automation remains implementation evidence rather than stand-alone acceptance: pre-migration backup, serve due-check with `STOCK_PROBS_BACKUP_INTERVAL_SECONDS` default `86400` and bounds `60`–`2678400`, backup-key rotation/retirement, `32` artifacts/`256 MiB` retention limits, and no automatic query-history expiry. `docs/operations/backup-restore.md` and `docs/configure/local-configuration.md` were updated for accuracy by `SOL HIGH`; the independent M05 scope result is supplied separately by `R-M05-55`. The earlier M08 capture harness supplied `20` annotated screenshots and manifest SHA-256 `f9fef2b2db0a806cc47ff1db82e1e895f4dd4803425c0cf74426f5fa5a12dd5d`; that remains preparation evidence only, while the current M08 extension is recorded above.

 - `EXP-M05` export audit receipt: **Completed** at commit `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`, parent `59534faf1cdce493bc51a11d4adbea5e5b2d6892`, commit UTC `2026-09-12T12:41:32Z`, message `Add verified backup operations`, and exact `origin/main` match. The sanitized export inventory is `233` messages, `1,387` parts, `432` tool parts, `185` task outputs, `1,116,276` bytes, `32,915` lines, SHA-256 `ce5f025d41c4757dcf95a336555ce0fdd46ddcf22d1e9bce68d2d8fb5328c181`, and `3,090` redaction markers. Secret review found zero matches across all canonical secret patterns. Reviewer: `LUNA MAX QA`; no export session ID, command, or unprovided check is inferred.
  - **Earlier post-final `R-ASTRA-64` documentation reconciliation (retained):** status is **Completed for its declared documentation scope** after the final documentation checks; owner/phase is `LUNA MAX docs`, and the scope is documentation only after the supplied implementation and independent QA records. FastAPI remains the sole production server and serves `/`, `/api/v1/docs`, and the application API below `/api/v1`. The Next.js `16.3.5` / React `19.3` App Router is a static export built by `./scripts/build-frontend.sh` with stable build ID `stock-probs`; generated `.next`/`out`/staged trees are ignored, 12 staged served files are packaged into the wheel, and Node is build-only in the container. Strict CSP exact inline hashes, parser-blocking `theme.js`, native Settings Light/Dark/System, and the `R-ASTRA-59` open-state anchor repair are recorded in [`docs/evidence/astra-final-report.md`](docs/evidence/astra-final-report.md). Supplied QA evidence is Python `444` pass/`4` deselected/`89.73%`, docs `52`, browser `64` pass/`2` expected performance skips, axe `0/0`, focus geometry `8/8`, no external/`.txt` traffic, deterministic build `26`/`703,175` bytes, staged `12`/`608,713` bytes, wheel approximately `306,559` bytes, and amd64 image digest `sha256:0d68e3d9a78d626a61a1a82c455ea1734ddaa753f562d74022b94986c477bb12` at `170,062,564` bytes. Native M09 reports `18` rows, theme p95 `32.7 ms`, render p95 `168.649 ms`, static `696,727`/`753,664` bytes, navigation `13`/`574,661` bytes, and wheel `306,553`/`335,872` bytes; ARM64 performance is **Unavailable**, and the earlier `120.2`/`120.8 ms` failures remain historical. Emulated ARM64 is functional/package/runtime only; physical mobile, screen-reader, and true-zoom evidence remain unavailable. `development-conventions` is the eighth opt-in skill with fresh discovery **Pass**, but activation requires parent restart. The post-migration ASTRA review is **Blocked**/**Unavailable** for named live-browser evidence because the current parent lacks official `playwright_*` tools and delegated attempts timed out; no remaining reproducible app blocker was reported. Ponytail `R-ASTRA-43`/`R-ASTRA-46` and subsequent repair history, including rejected `R-ASTRA-63` CSP-regex advice, remain visible. No clean release, commit, export, push, or exact remote result is claimed.

  - **Earlier `R-ASTRA-64` final gate artifact reconciliation (retained):** The retained artifact
    `test-results/local-gates/M09-20260914T002732Z/` records task `M09`, command `./scripts/local-gate.sh m09`, **Pass**, exit `0`, dirty
   `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`, native x86_64, and
   `2026-09-14T00:27:32Z`–`2026-09-14T00:40:00Z`. All eight completed checks are recorded,
   including official MCP; the Python JUnit has `444` tests, zero errors, zero failures, and
   coverage is `89.73%`; browser artifacts/logs report `64` passed and `2` expected performance
   skips. The performance summary has `18` rows, `17` executable **Pass**, and ARM64
   performance **Unavailable**. Current row values include theme p95 `34.9 ms`, browser render
   p95 `152.881 ms`, ten-item news render p95 `35.4 ms`, news cache-hit p95 `1.621 ms`, news
   response `701` bytes, provider deadline `10 s`, static `696,727`/`753,664` bytes, and wheel
   `306,553`/`335,872` bytes. Emulated ARM64 passed package/runtime/functional checks under
   QEMU `7.2.0`, not performance. The unsupported `TASK_ID=R-ASTRA-64` attempt exited `2` with
   no artifact; the first supported M09 attempt failed the `test_backup_automation` timing race,
   and supplied `R-ASTRA-65` repair history records removal of the irrelevant completion
   assertion followed by a passing rerun. The latest Ponytail `R-ASTRA-65` record is
   findings-only and nonblocking: its CSP-regex suggestion is rejected because production CSP
   parsing is a security boundary; it is not clean. No named ASTRA live acceptance or clean
   release/commit/export/push/remote result is claimed.

  - **Completed docs-only `R-ASTRA-70` portable-link repair:** owner/phase `LUNA MAX docs`;
    eight ignored-artifact links changed to inline code. Local and ignored artifact paths remain
    inline code, never Markdown links; no implementation, release, export, commit, push, remote,
    CI, or notification result is created.
  - **Current `R-ASTRA-71` final documentation reconciliation:** **Completed** for its declared
    documentation scope; owner/phase `LUNA MAX docs`. The initial named ASTRA session
    `ses_f6276e3a8ffeR3awDDSYKonmLk` remains **Blocked** at
    `2026-09-14T01:30:13Z`–`01:47:02Z`, reviewer `ASTRA`, model `openai/gpt-6-astra`, native
    x86_64/headless Chromium `153.0.8010.12`, dirty `HEAD`
    `5633f87f8cff04b5b33640f6633ff31c667c0435`: official MCP exposure passed, but reverse-Tab
    then Escape at `320x844` restored focus off-screen. Forecast/chart/news evaluation was
    **Unavailable** because the first isolated server used the wrong 2026 fixture clock and
    correctly returned `stale_data`, not because of a production defect. The progression preserves
    incomplete `R-ASTRA-66`, independent-QA failures after `R-ASTRA-67`, guarded external entry and
    trigger-focus restoration in `R-ASTRA-68`, and 320px Pixel/mobile restoration in `R-ASTRA-69`.
  - Final `R-ASTRA-69` Ponytail is **CLEAN**: exact `/ponytail-review` result `Lean already. Ship.`
    at `2026-09-14T02:41:58Z`, native x86_64, dirty `HEAD` above, reviewer `OpenCode gpt-5.6-sol`.
    Independent QA reviewer `LUNA MAX QA` used
    `/tmp/opencode/r-astra-69-20260914T025542940Z.json` at
    `2026-09-14T02:55:42.940Z`–`02:55:54.436Z`: `66/66` passed, axe `0/0`, Light/Dark focus,
    HTTP `201` forecast with charts/text, HTTP `200` partial news with 2 items, local-only
    traffic, and no current errors. Full browser artifact:
    `test-results/r-astra-69-browser-20260914T0248Z/`, `64` passed/`2` expected skips, `33`
    desktop/`33` mobile; separate findings-only artifacts are historical/unrelated.
  - Final ASTRA session `ses_f622707a4ffeAE3Zx8Lt2zYiC1` is **Accepted** for the affected
    post-repair scope with no blockers: reviewer `ASTRA`, model `openai/gpt-6-astra`, native
    x86_64, official MCP/headless Chromium `153.0.8010.12`, dirty `HEAD` above,
    `2026-09-14T02:57:56Z`–`03:16:35Z`, routes `/` and `/api/v1/docs`, viewports `320x844` and
    `1280x1000`, Light/Dark. Exact shell command and separate ASTRA artifact were not supplied;
    the named session, reviewer, model, and revision are supplied. The review passed the prior
    focus/fixture blockers, `8px` popover gap, containment, no overlap/overflow, `44px` controls,
    focus/dismissal, sampled contrast, first paint/System/CSP/media emulation, ACDC-M event `#6`/
    run `#2`, charts/text, partial news (2 items), OpenAPI, and `103` requests/`18` data requests
    with no off-origin, non-API, `.txt`, or current errors. `.data-label` is optional/nonblocking;
    no repair is authorized. Physical mobile, screen reader, true zoom, fresh ASTRA axe/screenshots,
    and native ARM64 performance remain **Unavailable**.
  - Failed M09 rerun `test-results/local-gates/M09-20260914T031828Z/` remains visible with `46`
    documentation-link setup errors. Final M09 artifact
    `test-results/local-gates/M09-20260914T032442Z/evidence.json` records **Pass**, exit `0`,
    command `./scripts/local-gate.sh m09`, native x86_64 dirty `HEAD` above,
    `2026-09-14T03:24:42Z`–`03:37:22Z`, reviewer `LUNA MAX QA`, Python `444`, `89.73%` coverage,
    browser `64` passed/`2` expected skips, official MCP, `17` executable native-x86 performance
    rows passed, and QEMU `7.2.0` ARM64 package/runtime/functional evidence only. Current rows
    include theme `35.0 ms`, browser render `151.958 ms`, interaction `24.027 ms`, ten-item
    news render `35.0 ms`, news cache-hit `1.809 ms`, response `701` bytes, provider deadline
    `10 s`, static `697,667`/`753,664` bytes, readiness `2,633.207 ms`, process RSS
    `144,457,728` bytes, and wheel `307,483`/`335,872` bytes; ARM64 performance is
    **Unavailable**. `EXP-M09` remains **Pending** for export, secret review, commit, push, and
    exact remote verification. No clean release/export/commit/push/remote/CI/notification result
    is claimed for this reconciliation. Full rows are in `docs/evidence/astra-final-report.md`.
  - Prior `R-M00-2-E50`–`R-M00-2-E55` documentation-check records remain historical; they are not
    reused or relabelled by `R-ASTRA-71`. New final checks use new IDs below.
   - `R-M00-2-E50` records the prior `.dev-venv/bin/python scripts/validate_docs.py` **Pass**:
     `9` categories, `13` topics, and `8` project skills; native x86_64 Linux; dirty `HEAD`
     `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC not captured; artifact none; reviewer
     `LUNA MAX docs`.
   - `R-M00-2-E51` records the prior docs-test attempt as **Unavailable** because the tool
     permission boundary denied execution; no test pass inferred. `R-M00-2-E52` records the prior
     comment-audit attempt as **Unavailable** for the same reason. Both were native x86_64 Linux at
     dirty `HEAD` above; UTC not captured; artifacts none; reviewer `LUNA MAX docs`.
   - `R-M00-2-E53` records the prior scoped `git diff --check -- README.md AGENTS.md MVP-PLAN.md
     MVP-ROADMAP.md docs` **Pass**; native x86_64 Linux at dirty `HEAD` above; UTC not captured;
     artifact current documentation diff; reviewer `LUNA MAX docs`; no Git mutation.
   - `R-M00-2-E54` records the prior validator rerun **Pass** with `9` categories, `13` topics,
     and `8` project skills; native x86_64 Linux at dirty `HEAD` above; UTC not captured; artifact
     none; reviewer `LUNA MAX docs`.
    - `R-M00-2-E55` records the prior scoped diff-check rerun **Pass**; native x86_64 Linux at dirty
      `HEAD` above; UTC not captured; artifact current documentation diff; reviewer `LUNA MAX docs`;
      no Git mutation.
  - `R-M00-2-E56` records the final `.dev-venv/bin/python scripts/validate_docs.py` run for
    `R-ASTRA-71` as **Pass**: `9` categories, `13` topics, and `8` project skills. Native x86_64
    Linux; dirty `HEAD` above; UTC was not captured by the command tool; artifact none; reviewer
    `LUNA MAX docs`.
  - `R-M00-2-E57` records the final `.dev-venv/bin/python -m pytest tests/test_docs_validation.py`
    attempt for `R-ASTRA-71` as **Unavailable** because the tool permission boundary denied
    execution; no documentation-test pass is inferred. Native x86_64 Linux; dirty `HEAD` above;
    UTC was not captured; artifact none; reviewer `LUNA MAX docs`.
  - `R-M00-2-E58` records the final `git diff --check -- README.md AGENTS.md MVP-PLAN.md
    MVP-ROADMAP.md docs` run for `R-ASTRA-71` as **Pass**. Native x86_64 Linux; dirty `HEAD`
    above; UTC was not captured by the command tool; artifact current owned-document diff; reviewer
    `LUNA MAX docs`; no Git mutation.
  - `R-M00-2-E59` records the final `.dev-venv/bin/python scripts/validate_docs.py` rerun after
    the last wording correction as **Pass**: `9` categories, `13` topics, and `8` project skills.
    Native x86_64 Linux; dirty `HEAD` above; UTC was not captured by the command tool; artifact
    none; reviewer `LUNA MAX docs`.
   - `R-M00-2-E60` records the final `git diff --check -- README.md AGENTS.md MVP-PLAN.md
     MVP-ROADMAP.md docs` rerun after the last wording correction as **Pass**. Native x86_64 Linux;
     dirty `HEAD` above; UTC was not captured by the command tool; artifact current owned-document
     diff; reviewer `LUNA MAX docs`; no Git mutation.
   - `R-M00-2-E61` records the final `.dev-venv/bin/python scripts/validate_docs.py` run for
     `R-ASTRA-72` as **Pass**: `9` categories, `13` topics, and `8` project skills. Native x86_64
     Linux; dirty `HEAD` above; UTC was not captured by the command tool; artifact none; reviewer
     `LUNA MAX docs`.
   - `R-M00-2-E62` records the final `.dev-venv/bin/python -m pytest tests/test_docs_validation.py`
     attempt for `R-ASTRA-72` as **Unavailable** because the tool permission boundary denied
     execution; no documentation-test pass is inferred. Native x86_64 Linux; dirty `HEAD` above;
     UTC was not captured; artifact none; reviewer `LUNA MAX docs`.
   - `R-M00-2-E63` records the final `git diff --check -- README.md AGENTS.md MVP-PLAN.md
     MVP-ROADMAP.md docs` run for `R-ASTRA-72` as **Pass**. Native x86_64 Linux; dirty `HEAD`
     above; UTC was not captured by the command tool; artifact current owned-document diff;
     reviewer `LUNA MAX docs`; no Git mutation.

## Product invariants

- Forecast close-to-close and latest-completed-5-minute-bar-to-close horizons for selected Yahoo Finance stocks and ETFs expose explicit direction/threshold probabilities and return/price intervals.
- Company-name lookup preserves instrument identity. Saved forecasts reopen as immutable recorded results; historical-cutoff reconstruction is separately labelled fresh analysis.
- Frontend data uses FastAPI `/api/v1`; the browser never opens SQLite, issues SQL, receives a database path, or calls Yahoo Finance directly. SQLite retains successful, failed, and repeated searches, immutable inputs/results, and append-only outcomes.
- Searchable history, CSV/JSON export, verified backup/restore, accessible responsive UI, secure loopback, bounded operation, official headless `@playwright/mcp`, browser regressions, and local fail-closed Make/scripts are release requirements. No GitHub workflow or external pipeline may satisfy one.
- Dark mode is an accessible, user-selectable presentation requirement, and selected-instrument news is an API-served, clearly labelled requirement with source/as-of and honest loading, empty, stale, and failure states. `M09` owns their implementation and QA/docs; the integrated UI, walkthrough, and Astra matrix must include them. The ten news UI states are **not requested**, **loading**, **fresh**, **empty**, **partial metadata**, **stale cached with refresh failure**, **provider unavailable without cache**, **local service unreachable**, **capacity busy**, and **instrument changed/request superseded**. News uses `200` for fresh, empty, or stale fallback, `422` for invalid input, `502` for provider failure, and `503` for capacity busy; an empty response never returns `404`.
- `M09` theme behavior is contract-bound: an external parser-blocking `theme.js` initializer runs before CSS on both the dashboard and `/api/v1/docs`, reads the localStorage key `stock-probs.theme` for a light/dark preference, falls back to the system preference, and removes the override for reset-to-system. First paint must be no-flash; semantic color roles, not whole-page inversion, are required. Numeric targets are text `>=4.5:1`, large text/controls/chart marks `>=3:1`, and focus `>=3:1`; forced-colors, reduced-motion, print, and unchanged strict CSP are independent rows.
- `M09` news is `GET /api/v1/news?symbol=<normalized>&limit=5`, with `limit` `1`–`10` and four frozen closed schemas, a separate `fetch_news` provider, and a passed pinned `yfinance==1.7.0` feasibility proof. The pinned `Ticker.get_news`/`Search` wrappers are unusable because of an indefinite LRU cache, no end-to-end timeout, and singleton mutation; a direct single GET to `https://query2.finance.yahoo.com/v1/finance/search` through already-pinned `curl-cffi==0.16.3` is feasible. ACDC/SPY live probes returned `5` items each with `uuid`, `title`, `publisher`, `providerPublishTime`, and `link`; `relatedTickers` was present in `3/5` and absent in `2/5`. The frozen adapter uses no retries, redirects, cookie preflight, or crumb, caps raw body at `256 KiB`, and uses absolute deadline `min(provider_timeout,10s)`. Its frozen in-memory cache is bounded to a 5-minute fresh TTL, 30-minute stale ceiling, 60-second empty cache, 30-second failure suppression, 32 symbols, 32 KiB per entry, 1 MiB aggregate, and one active retrieval; `cache_state` is `miss`, `hit`, or `stale_fallback`. News makes no storage/backup/model/fingerprint/ledger change, saved reopen is provider-free, current headlines are a separately labelled action, links are HTTPS-safe, and browser data traffic is local-only.
- The ASTRA M09 plan's rejected scope is the frozen historical `M09-E13` constraint:
  settings database, news archive, article scraper/proxy, sentiment engine, forecast/model/
  probability changes, Redis or external cache, background scheduler, service worker, separate
  service, notification feed, full-text search, watchlist, personalized ranking, and any
  additional market-data provider were excluded from M09. The later `R-ASTRA-98` receipt
  separately approves/evidences bounded watchlists, forecast/model expansion, and
  provider-labelled quote/daily-bar market-data research; that later scope does not alter the
  frozen M09 row, reopen M09 implementation, or create a new current task.
- The stock Playwright MCP entry in `opencode.json` is a hard invariant: retain `./scripts/playwright-mcp.sh` with `--headless`, `--isolated`, and loopback host/origin allowlists. Selective Ingenium pipeline adoption must never replace it with Ingenium browser automation.
- Non-obvious implementation behavior and documentation snippets need useful intent or constraint comments.
- Before future workspace UI work, inspect and follow [`docs/develop/design-system.md`](docs/develop/design-system.md). Keep approved concepts, current product screenshots, implementation, and acceptance evidence distinct; screenshots and mockups do not establish runtime behavior or QA.
- The contract rejects overkill absent a demonstrated requirement: no added auth, MFA, gateway, multi-service split, dual-database restore, direct-route SQL, or replica rate limiting. A read-only integrity diagnostic is optional and must not become a new acceptance surface.

## Historical V1/V0 orchestration and ownership receipts

Ponytail references in the historical records below preserve prior overengineering-only receipts;
Ponytail is retired and none of those records is a current workflow dependency, command, review,
or acceptance gate.

- The orchestrator enforces a concurrency target of six active agents. Whenever at least six genuinely independent todos exist, six agents run concurrently, each owning a distinct todo, path, and evidence lane, with no duplicate work; as a lane finishes, the freed slot is immediately refilled from the remaining independent todos. Launch independent work in parallel, keep dependent steps sequential, and wait for all active lanes before integration and before independent QA. Six is the target, not a quota: never invent busywork, and use fewer lanes only when fewer than six genuinely independent todos exist. QA/docs waves may use one to six agents according to their genuinely independent scopes.
- A build wave uses up to six concurrent `SOL HIGH build` instances: A owns transport/application and package/launch; B owns domain/provider/persistence/migrations/backup; C owns presentation/browser/operations/local gate tooling. Any additional lanes must own a declared, disjoint implementation/config/test scope assigned before work starts. M01/M06 remove `.github/workflows/ci.yml` if present; local Make/scripts replace that former role.
- `README.md`, `AGENTS.md`, `MVP-PLAN.md`, `MVP-ROADMAP.md`, and authored `docs/**/*.md` belong only to `LUNA MAX docs`; `SESSION-EXPORT.md` remains root-level and belongs only to its export gate. The coordinator owns integration, status, and git only; it does not implement, perform QA, or write roadmap prose.
- Builders report exact task ID, paths, checks, failures, and assumptions. Only after all active build reports arrive do independent `LUNA MAX QA` and `LUNA MAX docs` gates run; those QA/docs waves use one to six agents only for declared independent scopes, and docs finalizes only after consuming the completed QA record.
- The next M09 lane-status wording is retained as pre-acceptance history; the current
  declared-scope status and consolidated receipt are recorded above.
- **Historical pre-acceptance M09 lane manifest (retained):** The `M09` lane manifest is disjoint and its declared implementation scope is complete: `SOL HIGH-A` owns `src/stock_probs/api.py`, `src/stock_probs/schemas.py`, `src/stock_probs/config.py`, and `tests/test_api.py`; `SOL HIGH-B` owns `src/stock_probs/provider.py`, `src/stock_probs/domain.py`, `src/stock_probs/service.py`, `tests/test_provider.py`, `tests/test_domain.py`, and conditional `pyproject.toml`/`requirements.lock` package changes; `SOL HIGH-C` owns `src/stock_probs/static/theme.js`, `src/stock_probs/static/index.html`, `src/stock_probs/static/api-docs.html`, `src/stock_probs/static/app.js`, and `src/stock_probs/static/app.css`; `SOL HIGH-D` owns `tools/browser/playwright.config.js` and `tools/browser/tests/dashboard.spec.js`. Shared interfaces were handed off rather than co-edited. The package/launch gate was conditional on B's pinned feasibility proof; no unpinned replacement is accepted. At that earlier point, `M09` was **In progress** pending its boundary review, consolidated gate, docs finalization, and `EXP-M09`; current `M09-E18` supersedes that open wording, and `EXP-M09` is the only current approval gate.
 - The preceding M09 lane sentence retains its pre-acceptance **In progress** wording; the current
   declared-scope M09 result is **Completed** above, while `EXP-M09` remains **Pending**.
 - `LUNA MAX QA` is verification-only: it denies repair and delegation conceptually, does not repair implementation/configuration, and does not hand its acceptance duty to a builder. The coordinator routes only reproducible, blocking findings with an exact task ID to `SOL HIGH`; speculative, non-blocking, or overengineering preferences are not repair work.
- Agent profiles and local-gate changes are future `SOL HIGH` ownership. Any such change requires a parent-process restart and independent post-restart validation before it can affect a gate; a profile edit, local script, or generated artifact is never self-validating.
 - The ASTRA agent profile now uses `variant: max`; parent-process restart and independent post-restart validation are **Pending**, so no gate effect or validation pass is claimed.
 - Commit evidence: the adoption/profile change set is in ancestor commit
   `8084a134ab4950f36446de3af622349cd23423ae` (`Build dark mode and news`), including the
   ASTRA profile's `variant: max`; current checkpoint `779aa749d2f85849427212d890ee6918987492b7`
   is its descendant. This does not replace the required parent restart or independent
   post-restart validation.
- After every implementation boundary—each builder handoff, repair handoff, integration, profile/local-gate change, or other configuration boundary—and before independent QA, run the read-only `/ponytail-review`. It is limited to overengineering findings. Record either `Ponytail result | boundary: <exact task ID> | finding: none | scope: overengineering only | command: /ponytail-review | environment | UTC | commit | result | artifact | reviewer` or, for a finding, `Ponytail finding | boundary: <exact task ID> | path:line | overengineering claim | evidence | minimal SOL HIGH repair | QA rerun | environment | UTC | commit | result | artifact | reviewer`. A finding uses the normal `R-M##-<n>` repair ID only when it is reproducible and blocking. Ponytail cannot accept or substitute for correctness, security, accessibility, or performance evidence; a missing or unavailable review remains visible and blocks the affected pre-QA boundary.
 - Use exact `M00`–`M09`, `R-M##-<n>`, `EXP-M00`–`EXP-M09`, `ASTRA-FINAL`, `R-ASTRA-<n>`, or `EXP-FINAL` IDs. `NOTIFY-FINAL` is a separate optional operational record, not a milestone or acceptance ID. Reconcile README and AGENTS after each milestone and at final acceptance.
   - Additive final-operational-item constraint: selective Ingenium agent-pipeline adoption may borrow patterns only; it must retain six-agent orchestration, independent QA/docs order, the Ponytail boundary, and commit/export gates. The adoption state under review uses `Orchestrator` as the inline primary with the six-agent count option and `subagent_depth: 1`, `luna-docs` has `docs/**` permission, the recorded `.gitignore` additions are present, and a two-skill validator catalog contains `documentation` and the new `skill-maintenance` skill. `R-ASTRA-72` independently validated the renamed `Orchestrator` entry after the required restart; no broader adoption gate result or new commit is inferred. The simplest no-plugin subagent-count control is the valid `agent.options` field on the `Orchestrator` profile, read by `Orchestrator`; the schema has no native concurrency cap and `subagent_depth` controls nesting only. The ASTRA research first pass is **Blocked** by the external-directory permission boundary; the gitignored `test-results/ingenium-snapshot` enables a re-run, which is not yet claimed. The ASTRA-FINAL matrix skeleton is historical preparation; its earlier no-acceptance statement is retained as history, while the current accepted result is recorded above.

## Historical V1/V0 gates and sequence

- Canonical sequence: `R-M00-1` -> `EXP-M00` (**Completed**) -> `M01` (**Completed**) -> `EXP-M01` (**Completed**) -> `M02` (**Completed**) -> `EXP-M02` (**Completed**) -> `M03` (**Completed**) -> `EXP-M03` (**Completed**, exact checkpoint `777451643b5ec1a04a37c013a9caf59f0bd58122`) -> `M04` (**Completed** for exercised scope) -> `EXP-M04` (**Completed**, exact checkpoint recorded in `MVP-PLAN.md`) -> `M05`/`EXP-M05` -> `M06`/`EXP-M06` -> `M09` QA/docs -> `EXP-M09` -> `M07` QA/docs -> `EXP-M07` -> `M08` walkthrough QA/docs -> `ASTRA-FINAL` dedicated visual/mobile/responsive/accessibility review -> `R-ASTRA-<n>` SOL repairs/retests and Astra reevaluation until `ASTRA-FINAL` is **Accepted** -> `EXP-M08` -> final learning synthesis -> `EXP-FINAL` -> optional `NOTIFY-FINAL` last. Astra plus the post-Astra checkpoint and learning synthesis are one second-last operational loop, not a new milestone.
- Each export overwrites the tracked full-session `SESSION-EXPORT.md`. Secret review, local commit, push to the Git remote, and remote revision verification are separate evidence fields; failed, skipped, unavailable, or connectivity-blocked fields remain visible and block that checkpoint. There is no external-pipeline or hosted-runner field.
  - Commit/push the reviewed export as checkpoint SHA X and verify that exact SHA on the Git remote; preserve the receipt in the next checkpoint. Never claim a future result for SHA X. `ASTRA-FINAL` must, after UI and walkthrough completion, include a dedicated visual-design/mobile/responsiveness/accessibility quality evaluation and a separate row for every M09 dark-mode/news item and every M08 item, feature, endpoint, control, UI state, asset, documentation visual, walkthrough frame/segment, media item, static asset, journey, and persistence effect. Each row is evaluated against requirements, aesthetics, mobile/responsive behavior, accessibility, and measured performance. Astra evaluates and suggests; only `SOL HIGH` build agents implement `R-ASTRA-<n>` UI repairs, followed by independent QA/docs and Astra reevaluation until **Accepted**. `EXP-M08` then precedes a final pre-`EXP-FINAL` learning synthesis: deeply analyze sanitized chat/run evidence, use `skill-maintenance` only for justified reusable Stock Probability development skills, validate and index those skills, and log observations. `ASTRA-FINAL` is **Accepted for its declared scope** and `EXP-M08` is **Completed** as recorded above; the current post-repair receipt records accepted `EXP-FINAL` checkpoint `10b5de4a1842baf43e847f21f75154966e44b9c0`. The earlier accepted checkpoint `b96cb6954ecf6e03b3bcdb0ad52af38ed7eae4cb` and its `NOTIFY-FINAL` record at dirty context `91ba52eca35fcfc13bd0d9996beb947d65d69d09` remain immutable history; no new notification is claimed.
- `ASTRA-FINAL` must have a separate matrix row for every asset, control, UI state, documentation visual, walkthrough frame/segment, media item, and static asset, not merely one row per feature. Each row is evaluated against requirements, aesthetics, mobile behavior, responsive behavior, accessibility, and measured performance, with execution evidence rather than implementation claims. Astra evaluates and suggests only; `SOL HIGH` implements any `R-ASTRA-<n>`, independent QA retests it, and Astra reevaluates the affected row. If evidence shows a tooling, skill, or MCP gap caused poor output, a narrowly scoped `R-ASTRA-<n>` may repair and validate that gap before acceptance; it may not expand scope without a new evidenced requirement.
- After an accepted `EXP-FINAL`, an optional operational notification may be referred to as `NOTIFY-FINAL`; it is not a milestone or acceptance ID and cannot satisfy a missing gate. It may use only a webhook supplied out-of-band by the user, must send a minimal non-secret receipt, must not persist or print the endpoint/token/payload credentials in the repository, export, artifacts, or logs, and must record bounded success, failure, or unavailable delivery without changing the accepted `EXP-FINAL` result.
- M06's additional rows remain distinct: the retained Ponytail receipts are [`docs/evidence/ponytail-r-m06-1.txt`](docs/evidence/ponytail-r-m06-1.txt) (six findings repaired), [`docs/evidence/ponytail-r-m06-15.txt`](docs/evidence/ponytail-r-m06-15.txt) (three findings repaired as `R-M06-19`), and [`docs/evidence/ponytail-m05-boundary.txt`](docs/evidence/ponytail-m05-boundary.txt) (two findings repaired as completed repair record `R-M05-12`, independently rerun 4/4 inside `R-M05-55 (i)`). **Historical M06 receipt:** at that historical checkpoint, the pinned closure was vendored at `tools/ponytail` from upstream `16f29800fd2681bdf24f3eb4ccffe38be3baec6b` and configured in `opencode.json`; that historical bundle/configuration is absent from the current tree. Ponytail remains overengineering-only and does not replace correctness, security, accessibility, or performance evidence. The authored documentation taxonomy and project documentation skill are implemented; the fresh isolated discovery and post-restart receipt session `ses_f6aa32d33ffeAvmiFK8K7Cd8EI` at `2026-09-12T11:35:58Z`–`2026-09-12T11:36:02Z` on native x86_64/OpenCode `1.18.30` and dirty commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892` passed their listed checks. `.dev-venv/bin/python scripts/validate_docs.py` passed `8` categories and `11` topics at `2026-09-12T12:13:23Z`. Least-privilege Ingenium MCP onboarding is **Blocked** only on authorized workspace credentials, project registration, repository-sync dry-run/apply/no-drift, and credential-free evidence; no credential is recorded.
- The first three completed read-only Ingenium research sessions used as non-acceptance design input are `ses_f6d4726a7ffeW18Cuf8Hl86PNs`, `ses_f6d47256cffert6bjT4wan4xvZ`, and `ses_f6d4724b1ffeC2gGE0kc5AgPo2`. They do not substitute for M06 acceptance, QA, a restart, authorized workspace access, or an export checkpoint.
- The supplied deep read-only Ingenium research sessions `ses_f6d219e22ffeQuT1z7fdC3e4MA`, `ses_f6d219dddffeyB2ZTOmnUMJU3Z`, and `ses_f6d219d92ffewot26Lkx216Lqw` are design evidence only. The documentation adopts/plans their useful conventions—deny-by-default least privilege; source-versus-live evidence separation; structured sanitized errors; deterministic browser containment with no hidden retries; bounded process/port/temp artifacts; migration/package/resource checks; and an optional read-only integrity diagnostic—while M06 independently verifies implementation behavior. None is an M06 final-gate or export checkpoint.
- Authored-documentation taxonomy and the project documentation skill are implemented under `docs/**` and `.opencode/skills/documentation`; fresh isolated discovery passed the stated validator, 20 tests, description-parity, 500-line-limit, and reference checks. The post-restart receipt is session `ses_f6aa32d33ffeAvmiFK8K7Cd8EI`, `2026-09-12T11:35:58Z`–`2026-09-12T11:36:02Z`, native x86_64/OpenCode `1.18.30`, dirty commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`, and passed canonical-description discovery, six Ponytail commands, three profiles, valid config, and no-credential checks. `.dev-venv/bin/python scripts/validate_docs.py` passed `8` categories and `11` topics at `2026-09-12T12:13:23Z`. These documentation-skill receipts remain distinct from the final clean-target `R-M06-55` and `EXP-M06` records.
- The earlier `LUNA MAX docs` profile gap is retained as historical evidence: `SOL HIGH` performed those authored documentation repairs. The supplied adoption state now grants `luna-docs` `docs/**` permission, but it is not gate-active until the required parent restart and independent post-restart validation; no new documentation-skill or M06 verification is inferred.
 - The following M09 boundary receipt preserves its pre-acceptance in-flight wording as
   historical evidence only; `M09-E18` supersedes the open declared-scope gate, and `EXP-M09`
   is the only current approval action.
  - The `M09` boundary receipt is retained at `test-results/ponytail-m09-boundary.txt`: the read-only `/ponytail-review` for boundary `M09` found four overengineering findings and net `-119` possible lines. `SOL HIGH` applied minimal `R-M09-1` repairs: theme/news p95 sampling moved into `tools/browser/tests/performance.spec.js` (net `-25`; supplied `338` tests pass), provider curl stubs were consolidated to one helper (net `-25`; supplied `337` tests pass), CSS aliases were collapsed to one canonical name per role (net `-10`; `dashboard.spec.js` contrast assertions remain in flight), and the redundant static-row re-assertion was deleted. Independent verification of the harness/stub repairs remains **In progress**; this is overengineering-only evidence, and the consolidated M09 gate plus `EXP-M09` remain **Pending**. Review/repair environment, UTC, commit, independent reviewer, and verification artifact metadata were not supplied and are not inferred.
- The following first-gate M09 failure record is retained as immutable pre-acceptance
  history; its later repair closure is recorded by `M09-E18` above.
- **Historical first consolidated M09 gate record:** The first consolidated M09 command `TASK_ID=M09 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh m09` **Failed**: `test_success_repeat_failure_and_searchable_history` intermittently observed total `3` instead of expected `2` because of the known random request-ID/search-collision flake, and when local-gate invoked `scripts/arm64-smoke.sh`, it rejected `TASK_ID=M09` and exited `2` before ARM evidence (`R-M09-2`). The clean rerun reported `338 passed/4 deselected/89.62%`. Independent continuation passed the native package (wheel `121,501` bytes including `theme.js` and `news.json`), browser `40` passed/`2` skipped, official MCP, Ponytail interface, and the M09 performance harness `18/18` rows; ARM64 performance is **Unavailable**. A separate functional/package/runtime smoke passed as **emulated ARM64**. `R-M09-2` and `R-M09-3` (flaky-test determinism) repairs were **In progress** in that historical record; the later `M09-E18` receipt supersedes that open wording, while `EXP-M09` remains the sole current approval gate. Session, environment, UTC, commit, and artifact metadata were not supplied and are not inferred.
- `R-M00-2-E13` records this update's `.dev-venv/bin/python scripts/validate_docs.py` attempt as **Unavailable** because the tool permission boundary denied execution; no validator pass is inferred. `R-M00-2-E14` records `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` as **Pass** on dirty `HEAD` `a69df40e15b3136886f26789c27861184c3bbd77`; UTC was not captured, no Git mutation occurred, and `LUNA MAX docs` is the named reviewer.
- `R-M00-2-E15` records the consolidated M09 gate-state update's `.dev-venv/bin/python scripts/validate_docs.py` attempt as **Unavailable** because the tool permission boundary denied execution; no validator pass is inferred. `R-M00-2-E16` records `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` as **Pass** on dirty `HEAD` `a69df40e15b3136886f26789c27861184c3bbd77`; UTC was not captured, no Git mutation occurred, and `LUNA MAX docs` is the named reviewer.
- `R-M00-2-E17` records this M09 acceptance update's `.dev-venv/bin/python scripts/validate_docs.py` attempt as **Unavailable** because the tool permission boundary denied execution; no validator pass is inferred. `R-M00-2-E18` records `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` as **Pass** on dirty `HEAD` `a69df40e15b3136886f26789c27861184c3bbd77`; UTC was not captured, no Git mutation occurred, and `LUNA MAX docs` is the named reviewer.
- `R-M00-2-E19` records this M07 integrated-acceptance update's
  `.dev-venv/bin/python scripts/validate_docs.py` attempt as **Unavailable** because the
  tool permission boundary denied execution; no validator pass is inferred. `R-M00-2-E20`
  records `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` as **Pass**;
  UTC was not captured and dirty `HEAD` was
  `131aabc0fc0528b1e70ba26e09e2c78565ee8d56`. No code, configuration, skill, export,
  commit, push, or Git-history mutation is part of this update.
 - `R-M00-2-E21` records `.dev-venv/bin/python scripts/validate_docs.py` for this
   M07-export/M08-extension documentation update as **Unavailable** because the tool
   permission boundary denied execution; no validator pass is inferred. `R-M00-2-E22`
   records `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` as **Pass**
  on dirty `HEAD` `779aa749d2f85849427212d890ee6918987492b7`; UTC was not captured by the
  command tool. `LUNA MAX docs` is the named reviewer; no Git mutation was performed.

- `R-M00-2-E23` records the exact `.dev-venv/bin/python scripts/validate_docs.py` attempt for
  this `ASTRA-FINAL` findings/repair root-documentation update as **Unavailable** because the
  tool permission boundary denied execution; no validator pass is inferred. Environment: native
  x86_64 Linux; dirty `HEAD` `cf099754a5c3e4a05f0e785c0d65ff06f96c4d63`; UTC was not captured;
  artifact: none; reviewer: `LUNA MAX docs`. `R-M00-2-E24` records
  `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` as **Pass** on the same
  dirty `HEAD`; UTC was not captured; artifact: current four-document diff; reviewer:
  `LUNA MAX docs`. No code, configuration, skill, export, commit, push, or Git-history mutation
  was performed.

## Evidence discipline

- Every record has exact task ID, status only `Pending`, `In progress`, `Blocked`, or `Completed`, owner/phase, verified dependencies, change summary, one evidence item per requirement, check/command, environment, UTC timestamp, commit, result (`Pass`, `Fail`, `Skipped`, or `Unavailable`), artifact/link, repairs, limitations, export/revision, Git checkpoint/remote result, and named reviewer.
- Record failures, skips, unavailable providers or hardware, stale data, accessibility findings, restore/key failures, secret-review failures, and connectivity loss with a unique repair ID and rerun result. Never infer completion from implementation claims or hide a missing check.
- M06 performance evidence is per-check and structured, not a single aggregate. The final clean-target `R-M06-55` has `12/13` **Pass** rows and one **Unavailable** ARM64-performance limitation on commit `a69df40e15b3136886f26789c27861184c3bbd77`; no emulated ARM64 result satisfies a performance row. The earlier dirty artifact set at `test-results/local-gates/R-M06-55-20260912T045233Z/performance/` and its exact task/row evidence remain historical and are not erased.
- Native x86 performance is the only current performance target. Local QEMU/OCI may provide explicitly emulated ARM64 packaging, runtime, functional, build, or tool evidence, but it cannot provide performance evidence; if native/physical ARM64 hardware is unavailable, that field remains `Unavailable` and no ARM64 resource claim is inferred.
- The supplied scoped `M09` QA evidence reports `130` news-contract tests plus live ACDC/SPY checks, browser `40` passed/`2` skipped with axe `0/0`, and M09 performance rows passing: theme p95 `32.4 ms`, news endpoint p95 `1.564 ms`, ten-item render p95 `30.3 ms`, news response maximum `701` bytes, and provider deadline `10 s`. ARM64 performance is **Unavailable**. The supplied summary does not include a session ID, command, environment, UTC window, commit, artifact, or named reviewer; those fields remain unavailable and no consolidated M09 gate or `EXP-M09` pass is inferred.
- The recovered pre-checkpoint export is valid parsed JSON (`5,065,391` bytes, `11,093` physical lines, `80` top-level messages, `384` parts) but contains parent calls and summarized handoffs; its historical `EXP-M00` command remains `running` and exact secret-review/export-revision evidence is absent. The completed `EXP-M00` checkpoint is **Completed**: session `ses_f71ec0499ffeokWj4h6tVwyYk1`, `1,413,943` bytes, `4,268` lines, `23` messages, `153` parts, `44` tool parts, `10` task outputs, two masked credential-like candidates, no private-key/AWS/GitHub/Bearer patterns, exact pushed/remote SHA `18da1af0b6bc31020d3587e472b8197146795bf1`, and reviewer/coordinator `OpenCode gpt-5.6-sol`; no remote CI was used.
- `EXP-M01` verified the `.github/workflows/ci.yml` path absent on the remote revision at SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`; the unrelated `?? .vscode/` remains untouched. M01 evidence is native x86_64 plus explicitly emulated ARM64 functional/tool evidence only; no physical/native ARM64 result is claimed. M02's final native-x86 QA and late export repair passed their recorded scopes; physical ARM64 and screen-reader evidence remain later limitations, not M02 blockers, and no remote CI was used.
- `M02`'s exact independent final QA task is `ses_f709ae6ddffe1NyppNASrAKnLQ`: direct gate `R-M02-55` passed on native x86 Python `3.11.15` at `2026-09-11T07:37:47Z`–`07:38:46Z` with 154 tests, 4 live deselected, 89.04%, 22 browser checks, MCP pass, and exact migration/checksum/clean-install/readiness-schema-3 checks. The late `EXP-M02-REPAIR-1` receipt `ses_f6eacd1cdffeZxtRNqfzkXOuqJ` then passed parse, secret, commit, and exact-remote-main checks at `2026-09-11T17:10:31Z`; `EXP-M03` is completed at exact SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`, and `EXP-M04` is completed at the exact receipt recorded in `MVP-PLAN.md`.
- `EXP-M03`'s supplied sanitized export parsed as `94` messages/`602` parts/`67` task outputs/`176` tool parts, `479,795` bytes/`14,128` lines, SHA-256 `964f4f71b8f0d56b1417afc23ff1ea65a69f50ea7a1c3067f91ba8a30c974892`, with `1,298` redaction markers and zero webhook/private-key/AWS/GitHub/Bearer/embedded-credential patterns. Commit UTC `2026-09-11T17:46:42Z`, message `Build auditable forecast engine`, push, and exact remote-main match passed; no CI was used. Built-in streaming truncation failures remain visible where supplied, while the final direct export pass is recorded.
- M03 lane evidence records exact initial QA sessions `ses_f6f774aaaffeTm7gAU0bGmAugP`, `ses_f6f774a94ffeTeR7hqQOGwyEO4`, and `ses_f6f774a7fffeewwU6GC340kNkx`, repair handoffs `ses_f6f4e64e4ffe4pU2k7hLMSVxtp`, `ses_f6f4e64bbffeMBNd12DmLUXxND`, and `ses_f6f4e6464ffeT0G1nJ1DYSGfiB`, and independent retests `ses_f6f42aaa4ffe0xr1uX2mtv3tPH`, `ses_f6f42aa8dffeSLySK2qeivnie0`, and `ses_f6e8b8cd7ffeyHZZEr5fpj6Boc`; all are mapped in `MVP-PLAN.md` with `LUNA MAX QA` as the independent reviewer. The final `R-M03-55` session is `ses_f6f2d798fffeERazFPTac2nAar`. The original failures, skipped live attempt, stale-data reasons, corrected `175`-test/`89.02%` gate, `26` browser checks, real MCP, and QEMU-emulated ARM64 remain visible; `R-M03-23` is still pending for actual screen-reader evidence.
 - `R-M00-1` and its collision aliases remain immutable historical records. `R-M00-2` records this docs-only policy repair; no implementation QA, walkthrough artifact, export, commit, or push is performed here.
 - `R-M00-2-E25` records the exact `.dev-venv/bin/python scripts/validate_docs.py` attempt for
   this accepted `ASTRA-FINAL`/completed `EXP-M08` update as **Unavailable** because the tool
   permission boundary denied execution; no current validator pass is inferred. Environment:
   native x86_64 Linux; dirty `HEAD` `7cf1ca8395b94c2e14e5b02ddf160f3f938091d`; UTC was not
   captured; artifact: none; reviewer: `LUNA MAX docs`. `R-M00-2-E26` records
    `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` as **Pass** on the same
    dirty `HEAD`; UTC was not captured; artifact: current four-document diff; reviewer:
    `LUNA MAX docs`. No code, configuration, skill, export, commit, push, or Git-history mutation
    was performed by this documentation update.
  - `R-M00-2-E27` records the exact `.dev-venv/bin/python scripts/validate_docs.py` attempt for
    this accepted `EXP-FINAL`/`NOTIFY-FINAL` update as **Unavailable** because the tool permission
    boundary denied execution; no current validator pass is inferred. Environment: native x86_64
    Linux; dirty `HEAD` `b96cb6954ecf6e03b3bcdb0ad52af38ed7eae4cb`; UTC was not captured; artifact:
    none; reviewer: `LUNA MAX docs`. `R-M00-2-E28` records the exact `git diff --check -- README.md
    AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` check as **Pass** on the same dirty `HEAD`; UTC was not
     captured; artifact: current four-document diff; reviewer: `LUNA MAX docs`. No code,
     configuration, skill, export, commit, push, or Git-history mutation was performed by this
     documentation update.
- `R-M00-2-E42` records the final documentation self-review and scoped name-only diff: exactly
  `AGENTS.md`, `MVP-PLAN.md`, `MVP-ROADMAP.md`, and `README.md`; concurrent `.opencode/**`,
  `scripts/validate_docs.py`, and `tests/test_docs_validation.py` changes were preserved. `R-M00-2-E43`
  records `.dev-venv/bin/python scripts/validate_docs.py` **Pass** with `9` categories, `13`
  topics, and `7` project skills. `R-M00-2-E44` records the exact documentation-test command as
  **Unavailable** because the tool permission boundary denied execution; no test pass is inferred.
 `R-M00-2-E45` records `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs`
  **Pass**. Environment: native x86_64 Linux; dirty `HEAD`
  `10b5de4a1842baf43e847f21f75154966e44b9c0`; UTC was not captured; reviewer `LUNA MAX docs`.
 - `R-M00-2-E46` records the exact `.dev-venv/bin/python scripts/validate_docs.py` run for the
   `R-ASTRA-64` post-final documentation reconciliation as **Pass**: `9` categories, `13`
   topics, and `8` project skills. Environment: native x86_64 Linux; dirty `HEAD`
   `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool;
   artifact: none; reviewer: `LUNA MAX docs`. `R-M00-2-E47` records the exact
   `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs` run as **Pass** on
   the same dirty `HEAD`; UTC was not captured; artifact: current 11-file documentation diff;
    reviewer: `LUNA MAX docs`. No code, configuration, test, export, commit, push, or Git-history
    mutation was performed by this documentation update.
  - `R-M00-2-E48` records the exact `.dev-venv/bin/python scripts/validate_docs.py` rerun for the
    current final-gate artifact reconciliation as **Pass**: `9` categories, `13` topics, and `8`
    project skills. Environment: native x86_64 Linux; dirty `HEAD`
    `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool;
    artifact: none; reviewer: `LUNA MAX docs`. `R-M00-2-E49` records the exact
    `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs` rerun as **Pass** on
    the same dirty `HEAD`; UTC was not captured; artifact: current 11-file documentation diff;
    reviewer: `LUNA MAX docs`. No code, configuration, test, export, commit, push, or Git-history
    mutation was performed by this reconciliation.


Historical R-ASTRA-120 checkpoint (E329–E338): E329's eight-tool metadata snapshot led to read-only `inspect`/`status` only, confirming production revision `da2764e8477698fa7d686be93a4711e35478e802`, schema 12 ready, and loopback-only; rollout, RAM, and billing were not returned. E330 left E322's HTTP 403 cause unproven. E333 passed selected synthetic resource QA, while its live-Docker case was deselected and actual 1 GB acceptance remains open. E334's synthetic native retry failed before provider-manager/HTTP activity; E335 later passed one bounded local synthetic native identity/header-forwarding capture for two owners, but this is not public-provider, search, image, or resource acceptance. E336's single authorized image-build session was interrupted on ENOSPC without a verified image ID; E337 restored exact pre-task bytes for a truncated test file and reported only a syntax/AST parse and a read-only production observation, with no product-test acceptance. E337's follow-up observation had no separate receipt or exact timestamp. Strict raw axe remains **Fail**; provider, security, actual 1 GB, accessibility, PR-bound rollback, and release gates remain open. Production is unchanged; the existing 1 GB plan and backups remain under the US$15 monthly total cap including tax. See the [MVP plan](MVP-PLAN.md) for detailed evidence.


R-ASTRA-120 E342–E344 supersede the pending build preparation for their declared local scopes: corrected runner QA passed, one source-bound Linux/amd64 candidate image build passed, and the parent verified its terminal identity, 147-file context, 52 served files, and cleanup. V4 recovery-test cleanup mocks/static checks passed; the proposal remains unapplied and the actual PR-bound rehearsal remains pending. The new image has not passed native/provider/search, current-image kill, actual 1 GB, strict accessibility, or release gates. Production, the existing 1 GB plan, and backups are unchanged. The US$15/month total cap includes backups and applicable taxes; the 2 GB proposal stays held. See the [MVP plan](MVP-PLAN.md) for exact receipts.


R-ASTRA-120 E345–E347: the missing-file preparation failure is preserved; repaired V3 frozen-path checks passed their scoped checks with a separate preserved metadata typo and inherited formatting limitation. The actual new-image native run failed: both users received no answer/tool results, and sanitized diagnostics recorded 16 upstream HTTP 403 failures. The forwarding fix did not close that failure; its cause remains unproven. Owned cleanup passed, the source/stage bindings matched, and no production or budget change followed. Current-image kill, native/provider/search, actual 1 GB, strict accessibility, PR rollback, and release gates remain open. Keep the existing 1 GB Linode and backups under the US$15 total monthly cap including tax. See the [MVP plan](MVP-PLAN.md) for exact evidence.


R-ASTRA-120 E348 independently confirms the native functional failure and exact owned cleanup/source-stage verification. Its separate metadata correction rejects V3's unsupported repository-status-stability claim without asserting source drift. The upstream 403 cause remains unproven. The header-only diagnostic has a 418-case builder pass and frozen parent source/test review (E349); independent integrated QA is pending. Pinned native-source review identified omitted session/project correlation headers (E350), whose repair is in progress without changing app authorization or claiming the HTTP 403 cause. Strict raw axe remains **Fail**, and native/provider/search, current-image kill, actual 1 GB, security, PR rollback, and release remain open. Production, the existing 1 GB Linode, and backups are unchanged under the US$15 total monthly cap including tax. Exact evidence is in the [MVP plan](MVP-PLAN.md).

R-ASTRA-120 E351 integrates the reviewed V4 rollback-test proposal with 73 parent test passes and one expected Docker opt-in skip. E353 independently passed the same helper-file scope with unchanged bindings and owned cleanup. E352 passed frozen diagnostic static/artifact review, without rerunning the 418 builder tests. The actual PR-bound rollback and integrated native metadata checks remain pending. The source integration does not authorize production promotion or change the US$15 total monthly cap. See the [MVP plan](MVP-PLAN.md) for exact evidence.

R-ASTRA-120 E354 records the native session/project correlation repair with 748 builder test passes
and parent frozen source review. Independent combined QA and real native/provider verification
remain pending; the earlier 403 cause is unproven. Production and the existing 1 GB/backups remain
unchanged under the US$15 monthly total cap. No promotion or release readiness is claimed.

R-ASTRA-120 E355 independently passed 787 scoped metadata/diagnostic tests with unchanged bindings.
E356 completed both synthetic native turns, but its original wrapper remains **Fail/Unavailable**
on immediate port binds; the separate later port checks do not establish the failure cause or live
provider acceptance. E357 preserves the failed read-only cleanup preflight with no mutations;
cleanup and image build remain held. Production remains at schema 12, with the existing 1 GB
Linode and backups under the US$15 total monthly cap. Native/provider/search, current-image kill,
actual 1 GB, strict accessibility, security, PR rollback, and release gates remain open. Exact
receipts and limitations are in the [MVP plan](MVP-PLAN.md).

R-ASTRA-120 E360 preserves a failed canonical gate: 2,469 Python passes, 13 failures, four skips,
four deselected, and 85.26% coverage. The two failing proxy/egress test files are under investigation;
image build and promotion remain held. E361 records exact disposable public-doc fixture cleanup,
with no Docker image or user-data deletion; image cleanup remains unapplied. E362 preserves a
partial synthetic browser diagnostic interrupted by a runner temporary-path race. Its three
Light desktop Axe snapshots do not replace the strict app accessibility failure or establish the
full matrix. Existing production, 1 GB Linode, and backups remain unchanged under the user's
reconfirmed **US$15 monthly total cap, including backups and applicable taxes**. The 2 GB proposal
stays held. Required native/provider/search, current-image kill, actual 1 GB, security, accessibility,
PR-bound rollback, and release gates remain open. See the [MVP plan](MVP-PLAN.md) for exact receipts.

E364 records 116 builder fixture tests and 22 identity regressions passing, with parent source
review and unchanged production inputs; independent QA and the full gate remain pending. E365
retains the held image wrapper's narrower mock/static Pass and its executable-path schema **Fail**.
Luna is repairing that mismatch; no build or promotion was invoked.

E366 independently passed the repaired 116-test fixture scope with two deprecation warnings and
unchanged bindings. The fresh canonical gate is running on 243 frozen inputs; no aggregate result
is yet available, and image build remains held while it runs.

E367 independently passed the repaired image-build wrapper's mock/static scope; parent reviewed
its complete diff and bound new copies. Image execution remains held during the live canonical
gate. E368 failed exact-baseline browser preparation because its geometry helper was undefined;
V1 remains frozen and a separate V2 repair is assigned before any browser execution. These results
do not establish native/provider, accessibility, resource, rollback, or release acceptance. The
US$15 monthly total cap, existing 1 GB Linode, and backups remain unchanged.

E369 passes the fresh canonical local gate: 2,482 Python passes, four skips, four live
deselections, 85.35% coverage, and 55 frontend checks with unchanged bindings. E370 passes the
actual current local container build and owned cleanup. E371 preserves browser preparation
failures and the independently reviewed minimal parent repair after consecutive Luna failures.
E372 reproduces the four strict raw-Axe failures with exact baseline captures; later owned
cleanup passes separately and does not rewrite the original wrapper Fail. Native runtime,
accessibility, actual Linode resource, PR-bound rollback, and release gates remain open.
The user reaffirmed the US$15 monthly total cap, including backups and taxes. The existing
1 GB Linode and backups remain unchanged; no resize, deployment, rollout, or email occurred.

E374–E375 preserve local native-runner preparation failures and the independently verified
root/leaf guard repairs. E376's actual current-image two-user run Failed: both model sessions
matched, but upstream streams returned HTTP 403 and no answers or tools completed. Exact owned
cleanup passed and local memory had zero max/OOM deltas; actual 1 GB capacity and the failure
cause remain unverified. Active kill is skipped pending functional Pass. Production is unchanged
by read-only E373 status; no resize, promotion, model fallback, or email occurred.

E387 independently passes 107 synthetic private-403 diagnostic tests; no upstream cause is
established. E391 passes the current canonical local gate: 2,543 Python passes, four opt-in skips,
four live deselections, 90 warnings, 85.43% coverage, and 55 frontend checks. Independent audit
passes receipt/manifest scope and current 52-file served/export parity; native/provider and
recovery opt-ins were skipped. E392 passes refreshed eight synthetic desktop/mobile captures
only; finalization and guide acceptance remain pending. E390 confirms unchanged production
through read-only MCP status. The **US$15 total monthly cap includes backups and taxes**;
the existing 1 GB Linode and backups remain unchanged. Required native/provider, strict
accessibility, actual capacity, PR-bound rollback, and release gates remain open.
