---
title: "Documentation"
description: "Repository rules for authored pages, authoritative root records, generated exports, taxonomy links, and deterministic audits."
---

# Documentation

For new or changed workspace UI, first inspect the current token and behavior sources and follow
the [design system guide](design-system.md). It records the current product baseline, the approved
Ledger assistant visual contract, and the R-ASTRA-120 candidate status. A mockup, source presence,
build, or screenshot does not prove runtime behavior or acceptance. Update the guide when the
shared visual system intentionally changes, and document shipped behavior only after checking
source and current release evidence. For browser or capture claims, follow the [served-frontend
evidence procedure](testing.md#binding-browser-evidence-to-the-served-frontend) so the evidence
matches the bundle FastAPI actually serves.

Contrast evidence follows the root `AGENTS.md` rule: retain raw axe results and separately
resolve uncertain results with exact-node measurements, independent QA and parent screenshot
review. See [contrast review](testing.md#reviewing-incomplete-contrast-results). A scoped manual
resolution does not establish full application accessibility or change the raw automated result.

## Temporary recovery evidence

Temporary-recovery evidence must bind the approved image manifest, current/operation records,
signed-reader backup verification and the exact source/profiles. Keep source agreement, archive
validation, actual host transition and restoration as separate results. Document missing stage or
import-path setup failures separately from a corrected test run; mocked reserve checks do not
establish actual-host capacity. See [temporary recovery checks](testing.md#temporary-recovery-baseline-checks).

## Same-schema hotfix evidence

For R-ASTRA-121, the separate operational-helper PR #11 candidate adds format 2 with contract
`schema13_same_schema_hotfix_v1`. Keep helper source PR #11, application candidate PR #9, and the
original 5ad schema-13 production artifact used for recovery as distinct identities. The contract
keeps schema 13 on both sides, with no migration, database restore, or recovery overlay; the
separately registered A9 app-only recovery image is not this contract's recovery artifact. Its
recovery check expects the normal shipped supervisor/image with the assistant worker disabled and
no OpenCode process, not an absent executable or package. Link current statuses and findings to the
[E21 evidence ledger](../../MVP-PLAN.md#r-astra-121-e21-format-2-hotfix-and-production-reader-checkpoint);
the persisted applied state must keep every field needed to select the format-2 rollback path.
The current helper received independent selected source/test review (162 passed, one opt-in Docker
test skipped, 266 bindings stable); the later independent process-profile review passed 360 tests
with one direct-Docker test deselected. The local original-image profile diagnostic and its bounded
independent receipt review passed. The reviewer did not rerun tests or start a container, and
effective CPU/PID/swap/tmpfs limits were not all inspected. The two earlier reviewer setup outcomes
remain recorded in the [E22 ledger](../../MVP-PLAN.md#r-astra-121-e22-independent-review-of-the-local-5ad-profile-diagnostic).
A package and manifest were prepared for helper head
`ae1d0a2d9d5e891436732e6655e360b93ecce817`, before three local source changes added the v2
enabled-native phase. The old manifest does not bind those changes. Builder and independent
copied-source checks each passed 373 selected tests with one Docker test deselected. Actual
Docker/native-phase execution, archive scanning, pair publication, host resources, installation,
rollback, and production acceptance remain **Pending**. The publisher/helper pair-locator issue is
also open. See [E23](../../MVP-PLAN.md#r-astra-121-e23-enabled-native-phase-source-qa-and-package-identity)
for the bound evidence and preserved setup results.

E24 adds the published revision and actual-host preflight failure without changing E23's source-time
checkpoint. Record the host rehearsal as **Fail** and the independent exact-input/structured-result
review as a separate scoped **Pass**. SDK transport completion does not accept the typed operation;
the post-call inspect also has a receipt-creation time, not an exact invocation time. See
[E24](../../MVP-PLAN.md#r-astra-121-e24-host-reserve-preflight).

E25 adds a source-only maintenance-helper checkpoint: bootstrap v2 has five fixed assets, and the
helper's scoped production path disables the assistant on the existing 5ad schema-13 image without
building, pulling, force-recreating, changing the data volume, or altering Compose/loopback
configuration. The prior four-asset statement remains historical. Its builder regression run
passed 462 selected tests with one skip and one Docker integration case deselected; independent
review passed the selected suite and source bindings. Its separate requested rollback-failure
coverage check **Failed** because `install_rollback_unverified` at
`scripts/pr_rehearsal_bootstrap.py:503` still lacks a test assertion; this is a coverage gap, not a
source-defect finding. Do not promote this to installation, actual-host or production acceptance. See
[E25](../../MVP-PLAN.md#r-astra-121-e25-maintenance-only-assistant-disable-and-failure-edge-checkpoint).

For the original 5ad schema-13 release, both disable and compensation recreate the same image with
Compose flags `--no-build --force-recreate --pull never`; the flow verifies the original volume,
schema, and loopback binding.

E26 adds the missing rollback-failure test as a test-only change. The builder's two-module suite
passed 463 tests with one skip; independent QA passed the two changed regression cases and scoped
source/static checks, but did not rerun the full suite for the new test pin. E25's coverage finding
remains in its historical checkpoint. See
[E26](../../MVP-PLAN.md#r-astra-121-e26-install-rollback-failure-regression-supplement).

E27 records the state-writer fault repair for PR11-MAINT-01. The builder's two-module suite passed
466 tests with one skip; independent Astra re-review passed three actual-writer fault regressions
and scoped input/static checks. This is not full security or release acceptance. E25's coverage
finding and E26's test-only supplement remain historical; installation, host, production, recovery,
resource, and publication-locator gates remain open. See
[E27](../../MVP-PLAN.md#r-astra-121-e27-maintenance-state-writer-fault-repair).

E28 records the pushed PR #11 draft at `d0236e56f88489b63e2a3f3164cdd77158df02b2`. Independent
transport QA **Failed overall** on a reproduced mocked TOCTOU race, despite the separately corrected
17 transport and 18 helper test counts and passing static checks. At that checkpoint, the private-
copy repair's final tests and independent re-review remained pending; live scanning/publication was
unavailable. At that checkpoint, the new transport source review remained pending. The
authored-documentation validator, completeness check, and scoped change-aware check passed. See
[E28](../../MVP-PLAN.md#r-astra-121-e28-pushed-pr-checkpoint-and-hotfix-transport-finding).

E29 records the later bounded-final-wait repair and independent scoped pass: 21/21 transport tests,
Ruff check, and format. E28's failed TOCTOU review and the intermediate snapshot-copy review's
unbounded-wait finding remain historical. The docs now distinguish local publisher snapshot
validation/upload/readback from the production consumer's installed-helper and expected-pair check.
No live publication, installation, runtime, host, or release acceptance follows. See
[E29](../../MVP-PLAN.md#r-astra-121-e29-bounded-hotfix-publisher-review-and-flow-separation).


Local image replacement evidence must distinguish selecting a retained current image from retiring
an obsolete candidate. The bounded builder's typed selection compares the expected full image ID,
verifies both ledger-bound receipts and Docker identities, and atomically updates only the local
pointer. Document the private command receipt and keep subsequent provenance, protection, reference,
RootFS, absence and retirement-acknowledgement evidence separate; selection alone is not cleanup
acceptance or a product release. See [the local selection procedure](testing.md#selecting-a-retained-local-image).

For a local-build failure, record the primary error, CLI cancellation, actual builder/worker
state, reservation state and receipt publication separately. A missing historical BuildKit result
is Unavailable even when fresh history and image inventory show absence. Typed external-observation
reconciliation is a distinct recovery scope; it does not turn the failed build into a success.
The genuine-local-failure mode can use fresh proof of the same stopped builder generation and an
absent/empty bounded cgroup when historical cancellation or history is unavailable. Historical
false facts still fail closed. Keep that local recovery separate from the temporary production
baseline's approval/manifest/current-record and host/MCP schema checks; static consumer agreement
does not prove installation, image availability or a host transition.
See [the local-build recovery procedure](testing.md#bounded-local-docker-builds-and-worker-verification).

## Local build phase evidence

For the local-build phase observer, publish only its bounded sanitized projection. Raw BuildKit
vertex names, commands, URLs, digests, logs and warning/error payloads are not evidence artifacts.
Keep partial or unavailable observations separate from the primary build failure and its cause;
never infer a successful build from parser tests. The reader uses the pinned Buildx/BuildKit JSON
shape and leaves existing build deadlines and failure recovery in force.

## Codex project configuration

Codex loads repository policy from root `AGENTS.md` and trusted-project settings from
`.codex/config.toml`. The Codex configuration mirrors the local Playwright MCP command and
loopback flags in `opencode.json` and raises the instruction byte limit so the full root
policy can load. The project-scoped `luna-build`, `luna-qa`, and `luna-docs` TOML files in
`.codex/agents/` mirror the current ownership split. Their instructions guide task ownership;
the active Codex permission mode governs actual filesystem access.

[`model-routing.json`](../../model-routing.json) is the single maintained source for model,
reasoning-effort, and role assignments. Codex and OpenCode model fields are synchronized
projections; maintain the manifest, then run `python3 scripts/sync_model_routing.py --write` to
update them or `python3 scripts/sync_model_routing.py --check` to detect drift. The synchronizer
changes only designated model/effort fields and fails closed when the expected structure differs.
Tests read the manifest instead of pinning model-version strings. Historical GPT-5.6 and Astra
receipts remain unchanged and do not define current roles. User-authorized workflow exceptions
must remain limited to the named task and be recorded in `AGENTS.md` when the correction changes
durable repository policy.

Codex discovers repository skills in `.agents/skills/`. Eight relative symlinks point to the
maintained OpenCode skill directories, preserving one source for their instructions and
references. When an approved skill is added or retired, update the corresponding Codex
symlink and this mapping. The documentation gate covers `.codex/**` and `.agents/skills/**`.
`$project-handoff`, `$project-qa`, and `$project-resume` are
Codex skill entry points for the three OpenCode command workflows. OpenCode-specific
runtime statements inside shared skills apply only to OpenCode; use the Codex agent roles
and this section for Codex discovery and ownership.

Config parsing and filesystem presence are static checks. A fresh Codex task in a trusted
project is needed to observe agent, skill, and MCP discovery after a configuration change.
This Codex setup does not alter prior OpenCode receipts or establish provider, project-profile,
release, export, or remote acceptance.

Project configuration text is not runtime-discovery evidence. E767 independently observed eight
deployment tools and a read-only status call. The current assistant checkpoint is
[E836](../../MVP-PLAN.md#r-astra-120-e836-canonical-browser-and-build-recovery-checkpoint).
Its complete canonical local check and 68-case axe matrix passed for their declared scopes. The
full browser aggregate failed; later selected real-flow and sequencing checks passed without
replacing that aggregate. Recovered image identity is not native/runtime acceptance. Exact input
bindings permit scoped reuse; a separate release aggregate is not inferred. Production remains
schema 12 without promotion. Physical mobile, true zoom, actual screen-reader and PDF/UA evidence
remain unavailable. The MVP ledger preserves exact receipts, failures and limitations.

The detailed E823–E830 narrative below is retained as historical scoped evidence.
E823/E824 storage and bounded-worker results remain passed for their recorded scopes, and E825's
identity-bound cleanup repair passed its selected tests and independent/parent source review. The
first actual PR-head application-candidate build then **Failed** with
`local_build_failed:bounded_image_build:exit_1`; its expected receipt was not created and no image
was accepted. The helper identifies only `fixed_command_unavailable_or_timeout`; the exact failed
subcommand and cause remain **Unproven**. The source-only monitor repair addresses a possible
false-abort path but does not prove the build-failure cause. It passed 106 independent tests and
parent source/evidence review. Typed reservation recovery then failed synthetic independent QA with
a P2: a partial exclusive-create receipt remained after `OSError`, although the ledger was restored
semantically, so retry remained blocked. The frozen source repair passed 132 selected builder tests
and parent source review; independent synthetic QA passed 132 tests with no failures/errors/skips.
The actual typed reservation release passed on its second attempt; the candidate ledger is empty (the
in-flight row was removed), and the initial failed receipt remains unchanged. Supplemental
independent review confirmed the exact pin-only diff, empty ledger, absent candidate tag, unchanged
setup/failure receipts, and app health HTTP 200; it did not perform Docker/image mutation or a broad
image inventory. A follow-on managed-run-directory repair passed 134 builder-selected tests and
parent review; independent permission QA passed 134 selected tests with static checks. The latest candidate image build passed, but the schema-13 pair is not accepted. E827's second build,
targeting the then-clean pushed head `83e0b0e1cdfbec8502208c48814a592112c022ea`, also **Failed**:
BuildKit reported `cannot copy to non-directory .../lib` at `COPY --from=opencode-assets /out/ /`.
The raw diagnostic is recorded in E827; the first projection incorrectly showed a null error. The
explicit-`/usr/lib` copy repair passed seven builder tests, parent source review, and independent QA
(154 selected tests plus Ruff/format); that independent review preserved the then-unfixed Dockerfile
pin. The pin-only follow-on matched the Dockerfile pin (old prefix `2d9355`, new prefix `f2dc019c`),
passed 147 builder tests and parent constant-only review; the supplemental independent review passed
its exact diff and actual-state scope. The setup receipt is not Dockerfile-bound, so no BuildKit
reinitialization was needed. The latest current-state read confirmed the SD UUID/mount, Docker root,
four cache binds, active Docker/containerd mount dependencies, and application health HTTP 200. Fresh
archive-metadata checks and physical absent-medium startup remain unavailable. E813's guide metadata
rebind passed on 83e for 94 consumer inputs, 52 assets, 23 artifacts, and 8 PNGs (receipt SHA-256
`fd763fb3916cdd3fef86303c0d12d46da0c24e044e7dc35d83d38d919f220908`); this is the bound guide scope,
not final current-head guide acceptance. Later source changes require a fresh exact-head image build;
the read-only production status/inspect pair is not a deployment mutation. Earlier failures retain
their declared scope. For a native-runtime repair, establish real functional
behavior before rerunning the full release aggregate, and retain every failed or interrupted
aggregate. Required security, resource, rollback and release gates remain mandatory.

The candidate
local PR-pair helper
`python3 scripts/pin_pr_rehearsal_review.py --write` and its fixed metadata contract are described
in [developer testing](testing.md#exact-pr-pair-review-pins), [local configuration](../configure/local-configuration.md#local-pr-rehearsal-review-metadata),
and [getting started](../operations/getting-started.md#review-a-pr-pair-before-rehearsal).

The current PR #9 startup-reserve checker has a bounded 30-second read-only observation before its
unchanged final guard. E22's five-second observation remains historical; the 512/128 MiB floors and
1,080-second operation budget are unchanged. E29 records independent local source/test review and
parent review, while a fresh host retry, image, native answer, and actual 1 GB acceptance remain
unverified. Map coverage for this deployment-review path includes this guide, developer testing,
local configuration, getting started, and the workflow policy in `AGENTS.md`.

### Source-bound build recovery

For source-bound Docker work, preserve each owned source baseline as exact bytes plus SHA-256 before
editing, require 4 GiB free before a build, stop an owned build below 1 GiB free, and hold source
edits until a low-disk build terminates. For R-ASTRA-120, place task-generated bulk recovery, QA,
and build artifacts on the SD-backed `test-results/` or `/var/tmp/r12r` mounts. Before writing,
verify UUID `54243c97-49f4-4cf6-a8cb-f6c0f3d48f4e` with `findmnt`; if the expected mount is absent
or mismatched, stop rather than falling back to the main filesystem or `/tmp`. Cleanup is limited
to exact fixed-ID cache objects proven task-owned and unused; never force-remove, globally prune,
or delete protected release images or application data. The
[testing guide](testing.md#reproducible-image-build-and-source-recovery-evidence) gives the
operator-facing procedure; the root [agent policy](../../AGENTS.md) is authoritative.

### Local deployment MCP boundary

Both `.codex/config.toml` and `opencode.json` declare the enabled local
`signal-ledger-deploy` MCP with `./scripts/deploy-mcp.sh`. The wrapper runs the separate,
locked `tools/deploy_mcp` project over stdio; Codex allows a 30-second startup and 1,800-second
tool deadline, while OpenCode declares the same catalog and execution limits. This is a static
configuration contract. It does not prove that a running parent loaded the server or that an SSH
target is configured.

The R-ASTRA-120 deployment MCP candidate has eight typed operations: `inspect`, `plan_deploy`,
`deploy`, `status`, `rollback`, `refresh_operator_access(operator_ipv4_cidr)`, `rehearse_pr_pair`,
and `set_assistant_rollout`. A fresh locked Python SDK stdio client discovered all eight and read
production status without mutation. A later fresh Codex task also discovered all eight and passed
read-only `inspect` and `status` (E90); parent correlation identifies task
`01a10e2a-ec7e-7b33-aee1-2288ddc0bbad`, although the receipt does not include that task identity.
An earlier root/current-task metadata snapshot exposed six tools. The later current-root
observation (E105) exposed eight and passed one read-only `status` call; the earlier six-tool count
remains historical. The default
release shape accepts a
40-character reviewed commit, a 64-hex archive
SHA-256, and a full `sha256:<64-hex>` Docker image ID; the publisher derives the GitHub Release
tag and asset URL from that commit. The controller reads one fixed target and SSH identity from
its process environment, then sends bounded JSON through `ssh -T` to the fixed remote command
`signal-ledger-deploy-helper`. Tool requests cannot provide shell text, arbitrary host or
filesystem paths, URLs, Compose edits, registry names, mutable tags, or Docker-socket operations.
The helper verifies the fixed release asset bytes before loading the image, then checks image ID,
platform, revision, Compose bytes, schema, backup, and readiness before promotion. An explicit
`SIGNAL_LEDGER_IMAGE_PUBLISH_MODE=ghcr` remains a compatibility transport for already staged
GHCR plans; it is not the default. Rollback is schema-compatible and responses are bounded and
credential-free. The R-ASTRA-120 candidate adds a recorded schema-13 recovery selector. Document
its exact image, revision, schema, and readiness guards in [getting started](../operations/getting-started.md)
and record local test versus live PR-rehearsal evidence separately in the [MVP plan](../../MVP-PLAN.md).

The `refresh_operator_access(operator_ipv4_cidr)` operation is constrained to one canonical IPv4
`/32` and the fixed `linode_firewall.signal_ledger` operator SSH rule. It uses the fixed external
private Terraform state and the existing clean-tree, exact-`origin/main`, reviewed-revision source
gate; it accepts no caller-supplied command, path, state, or credential. A tool listing does not
establish a live firewall refresh or deployment.

For R-ASTRA-120, retain the client/task distinction in each guide and status summary. A fresh
official locked Python SDK stdio client at `2026-10-05T13:17:09Z`–`13:17:12Z` discovered all eight
operations and completed read-only production `status`; this is a runtime discovery **Pass** for
that client and MCP server. A later fresh Codex task also **Passed** discovery of all eight MCP
operation names and one read-only `inspect` and `status` call each (E90). The parent correlates it
to task `01a10e2a-ec7e-7b33-aee1-2288ddc0bbad`; the discovery receipt omits the task identity and
explicitly does not include it. A later current-root snapshot (E105) exposed all eight names and passed read-only status; this
updates only that root observation. Preserve its earlier six-name snapshot and E90's separate
fresh-task result as distinct observations. Neither result establishes mutating-tool execution,
health-readiness, or release acceptance. The initial SDK
probe attempt failed because the harness read `isError` instead of the SDK's `is_error`; correcting
the probe required no product change. The operations guide records the assistant-help renderer's
exact three required arguments and manifest/QA-receipt binding. Generated capture bundles and
preview files remain ignored evidence artifacts, not authored documentation topics.

The current `.codex/config.toml` supplies the fixed target through a nonsecret `env` table:
the host, restricted deployment user, and operator-owned paths for the SSH identity and known-host
file. The key and known-host bytes remain outside the repository; no credential value belongs in
the configuration or authored documentation. Static discovery in a fresh CLI task found the
server and its typed tools (the task ID was not supplied). The locked stdio discovery check
initialized the fixed-target server, listed six typed tools for its then-current revision, and
completed read-only `inspect` with `is_error=False` and bounded text content; credential bytes
were not printed. That historical protocol result does not establish runtime discovery of the
R-ASTRA-120 additions. An earlier Codex client invocation was **Unavailable** under the host
approval boundary at that checkpoint. E90 later records a fresh-task discovery **Pass** for the
eight operation names and read-only calls; it does not establish execution of mutating tools or
deploy/rollback acceptance.

After changing either MCP configuration, `scripts/deploy-mcp.sh`, `tools/deploy_mcp/**`, or its
lock, restart the parent process and open a fresh Codex/OpenCode task to verify that the server
appears in the tool catalog and that its typed tools are discoverable. A configuration parse,
file-presence check, or the editing session is not runtime discovery evidence. Earlier client
invocation attempts that were unavailable due to the host approval boundary remain historical;
E90's fresh-task result closes only its declared metadata/read-only discovery scope. With
`OPENCODE_DISABLE_PROJECT_CONFIG=1`, OpenCode project MCP discovery is **Pending**/**Unavailable**
and no deployment or provider acceptance may be inferred.

## Current native OpenCode V2 documentation workflow

Native OpenCode V2 is the current operational workflow. The builtin `build` and `plan` entry
points are configured in `opencode.json`; `.opencode/agents/luna-docs.md` owns only
`AGENTS.md`, `README.md`, `MVP-PLAN.md`, `MVP-ROADMAP.md`, and authored `docs/**/*.md`.
`.opencode/agents/luna-build.md` owns implementation/tests and `.opencode/agents/luna-qa.md`
performs read-only independent verification. Legacy V1/Astra/SOL/Orchestrator references in
the evidence ledgers are preserved historical receipts, not current documentation ownership.

OpenCode project configuration is loaded by the parent process. Restart after changing
`opencode.json`, a profile, command, plugin, or `.opencode` dependency; file presence does not
prove discovery. With `OPENCODE_DISABLE_PROJECT_CONFIG=1`, project-profile discovery and runtime
acceptance are **Pending**/**Unavailable**. The real V2 provider probe emitted an error event
without a report, so it is **Unavailable** evidence and must not be described as provider or
project-profile acceptance. After Codex project-configuration changes, open a fresh Codex task
before checking discovery. A successful manifest check or synchronized file is static evidence;
no runtime model/profile discovery pass is inferred from it.

### Project skill loader boundary

Native V2 automatically discovers project skills from directory-based
`.opencode/skills/<id>/SKILL.md` definitions. The `skills` configuration array supplies additional
later-precedence sources, so an explicit `.opencode/skills` entry is not expected in
`opencode.json`. The eight approved directory-based definitions are governance entries only; the
R-ASTRA-119 addition is `beta-testing-email-workflow`. Their
`metadata.json` files,
`alwaysApply: false`, `.opencode/SKILL-INDEX.md`, the allow-list in `scripts/validate_docs.py`,
and `.opencode/skill-history/learnings.md` support static consistency and history; none is native
loader/discovery proof. R-ASTRA-119 builder validation passed at `2026-10-04T01:07:12Z`–`01:07:33Z`
with `9` categories, `13` topics, `8` governance entries, and `60/60` focused governance tests
(one Starlette/httpx deprecation warning) at revision
`da2764e8477698fa7d686be93a4711e35478e802`. This is static builder evidence, not independent skill
QA. Native runtime skill discovery is **Unavailable** in this harness because
`OPENCODE_DISABLE_PROJECT_CONFIG=1`; no runtime loader result is inferred. The active history path
is `.opencode/skill-history/learnings.md`; the old flat
`.opencode/skills/learnings.md` path is retired.

The coordinator's exact CLI rerun returned `opencode v2.0.7` from both `opencode --version` and
`/home/james/.local/opt/opencode-v2/opencode --version`; `/home/james/.local/opt/opencode-v2/opencode debug --help`
listed only `agents`, `config`, and `paths`; and
`printenv OPENCODE_DISABLE_PROJECT_CONFIG` returned `1`. These version/help facts do not establish
skill discovery.

Loader-boundary evidence is separated. Supplied builder static evidence recorded config/docs tests
`73/73`, comment tests `5/5`, validator `9` categories/`13` topics/`7` governance entries,
documentation self-test `26/26`, completeness `111` mapped files, and dirty-tree coverage `154`
inputs/`0` violations, with Ruff/security/comment audit `203` files plus JSON/frontmatter,
shell-syntax, and diff checks **Pass**. Independent Luna QA passed the static loader-boundary
scope on native x86_64 at dirty revision `09ba8b8dd285bd64c34241069051936c82c6390b`: exactly seven
directory `SKILL.md` files, no flat skill files, history-path migration, no explicit skills config,
retired Ponytail absence, and docs/map semantics **Pass**. This is independent static QA, not
native runtime discovery, provider runtime, release, or clean-scope acceptance; clean-scope proof
remains **Unavailable** because of the broad pre-existing dirty worktree, and no provider runtime
or service restart was invoked.

Ponytail is retired from the current tree and workflow. No local package, plugin, dependency pin,
command, boundary review, or acceptance gate is current. The retained Ponytail receipts in the
evidence taxonomy are historical overengineering-only records and are not documentation-gate
inputs for the current workflow.

## Documentation gate

`documentation-map.json` maps OpenCode and Codex configuration, profiles, skills, commands,
and the documentation gate to this page. Its additional workflow-policy rule also requires
`AGENTS.md`. `.githooks/pre-push` runs `scripts/check-doc-coverage.py` and fails closed when
the checker or map is missing, Python is unavailable, completeness fails, or a mapped change
lacks a documentation update. Use these read-only checks directly when the hook is not installed:

```bash
python3 scripts/check-doc-coverage.py --root . --map documentation-map.json
python3 scripts/check-doc-coverage-self-test.py
```

The change-aware checker and self-test do not install hooks or mutate Git. A deliberate exception
is explicit (`Doc-Gate: exempt`), not inferred from a builder report or an unavailable check.

The current documentation map includes a narrow `deployment-review-pins` rule for
`scripts/pin_pr_rehearsal_review.py` and its fixed review-pin source contract in
`tools/deploy_mcp/pr_rehearsal.py`. It requires `docs/develop/documentation.md`,
`docs/develop/testing.md`, `docs/configure/local-configuration.md`, and
`docs/operations/getting-started.md`; the additional `workflow-policy` rule also requires
`AGENTS.md`. This explicit path coverage was added by the coordinator. A successful
completeness/change-aware run applies only to the current map and the paths supplied to that run. If a UI change needs change-aware
documentation coverage, the tooling owner must map the actual changed source paths to the relevant
authored guide; keep any new rule narrow enough that unrelated interface edits do not require
cosmetic edits to the map's target page. A new Develop topic also requires one category-index link
and an entry in the validator's `CATEGORIES["develop"]` list. These taxonomy/configuration changes
are owned by the tooling owner, not by the authored-documentation lane.

Document removable-media recovery and local Docker storage in the existing
[Getting started operations guide](../operations/getting-started.md#local-docker-storage-on-removable-media).
Keep durable storage safeguards in `AGENTS.md` and task-specific receipts and status in
`MVP-PLAN.md`; do not add a category or duplicate the evidence ledger. The existing documentation
map already reaches the operations guide and requires `AGENTS.md` for workflow-policy changes.
A documentation link alone does not establish path coverage for a later source or configuration
change.

The current documentation map includes the narrow `bounded-docker-build-workflow` rule for
`compose.yaml`, `scripts/arm64-smoke.sh`, `scripts/bounded_docker_build.py`,
`scripts/local-compose.sh`, `scripts/publish-production-image.sh`, `scripts/rehearse_schema13.py`,
`scripts/r120-buildkitd.toml`, `scripts/setup_bounded_buildkit.py`,
`tests/test_bounded_build_entrypoints.py`, `tests/test_bounded_docker_build.py`,
`tests/test_production_deploy_helper.py`, `tests/test_schema13_rehearsal.py`,
`tests/test_setup_builder_inventory.py`, and `tests/test_setup_builder_space_guard.py`. It requires
this page, [developer testing](testing.md), and [getting started](../operations/getting-started.md);
the separate workflow-policy rule requires `AGENTS.md`. Keep this path coverage aligned as the
local build command contract changes. Record current runtime acceptance in the task ledger and
reflect operational status in the operations/testing guides; the map describes source coverage, not
runtime acceptance. The optional `prebuilt-release` publisher mode uses the completed schema-13
pair receipt and fixed revision-named artifacts; keep its verification and release prerequisites
documented in the operations and testing guides when changing that contract.
The `release-archive-credential-coverage` rule maps the shared archive scanner and its tests to
this page, the testing guide, and the operations guide; the additional workflow-policy rule also requires
`AGENTS.md`. Keep the documented coverage aligned with scanning the manifest, referenced
Config, every regular outer member, and nested layer contents under one decompressed-byte bound.
Exceptions require exact public provenance, path, size, digest and match spans. Archive-scanner
changes require the testing and operations guides to describe individually provenance-bound
exceptions and retained credential checks. Capture and diagnosis allowlists, genuine pre-snapshots,
and immutable receipts follow the root agent policy.
The merged application PR #1 and follow-on PR #2 are historical. The current fixed rehearsal
binding targets restoration PR #9, retaining exact repository, open-state, main-base, and reviewed-
head checks.
A prose statement here does not replace a passing completeness and change-aware
coverage check.

The approved project governance set now contains eight directory-based skill definitions:
`documentation`, `development-conventions`, `stock-probability-skill-maintenance`,
`local-gate-evidence`, `browser-qa`, `database-conventions`, `security-audit`, and
`beta-testing-email-workflow`. This static definition count is not native loader or runtime discovery
acceptance. Earlier seven-entry counts and independent seven-skill checks remain historical receipts.
The current `R-ASTRA-98`
product evidence and its limitations are documented in the root records and [dashboard
usage](../usage/dashboard.md); no retired Ponytail check is required for documentation
completeness or acceptance. The current private deployment reconciliation covers the Terraform
roots, cloudflared host-unit and update path, source-gated bootstrap, recovery rehearsal, canary
guard, and scoped infrastructure tests in the root ledgers. `R-ASTRA-104` adds optional invitation
SMTP pass-through in `compose.production.yaml` and the fixed host updater
`infra/linode/update-host-compose.sh`. The SMTP variables are documented in
[local configuration](../configure/local-configuration.md), the operator/admin behavior and fixed
updater in [getting started](../operations/getting-started.md#invitation-email-and-host-compose-update),
and this page records their coverage rule. `R-ASTRA-106` extends the accepted SMTP ports to implicit
TLS on `465` or `2465`, retains STARTTLS on `587`, and adds the constrained operator-access MCP
operation. Its Resend follow-on also covers the `mail.jtmb.cc` sending-domain records in
`infra/cloudflare/main.tf`, the fixed typed-controller operator refresh, the
`smtp.resend.com:2465` transport check, and the constrained credential-installer workflow. Coverage
for those changes belongs in `AGENTS.md`, this page, the root plan and roadmap,
[`local configuration`](../configure/local-configuration.md), and the production section of
[`getting started`](../operations/getting-started.md#resend-sending-domain-and-credential-workflow).
The domain/DNS/TLS checks do not establish API-key creation, host installation, SMTP acceptance,
live sending, mailbox delivery, or production email acceptance. The initial builder and repaired
installer QA were observed against local revision `42cf0f40c98404d55585745b10311354661a5195`;
that installer is included in pushed `main` checkpoint
`329fdc595483fa3b112b98c7788d808348638faa`, reported as matching `origin/main` with a clean tree
at that checkpoint.
The initial independent QA P1/P2 findings remain recorded as failure evidence; the repaired QA
recheck passed `13` tests, including command parse/probe and incomplete-read rollback, for its
declared local scope. This does not establish host installation, SMTP send, mailbox delivery, or
production acceptance.
Keep this page and AGENTS policy coverage current whenever those production settings, DNS records,
or updater/installer invariants change. The updater only installs the checksum-verified Compose
file; deployment and live delivery are separate evidence.

The historical schema-8 passkey deployment reconciliation records the owner-only canary, recovery pass, and private
deployment of the final clean-main image at revision `2de5e9f199cd145707f95e81d389c40b2ab3c32a`.
Its archive SHA-256 is `b856795831b6fb46e94e330370e003843b266ad85f22e8d95ef7624536b2ac48`, image
ID is `sha256:ae7991f35a2093b145245f8037a3227981b09051805467870f759c0752bbfc3d`, and the fixed
typed-MCP retry plan is `2d8b0fe91ed01b55f1625c27edcc620b`; the first plan failed transiently with
`remote_operation_failed`. Deploy returned deployed/readiness schema `8`; status reported the
current revision, `failed: null`, `loopback_only: true`, and pre-deploy backup
`pre-deploy-2de5e9f199cd1457-751c7459.spbackup`. The prior 11fa origin-navigation image and E49
remain historical scoped evidence. A live expired-session reload showed `Sign in first` and
`Open sign in` and hid `Create passkey`; opening sign-in and continuing with GitHub returned to
`/passkey?mode=enroll&next=/overview`, showed `Signed in as jtmb`, and showed `Create passkey`.
No passkey ceremony or saved-data check was completed. The source-reviewed session-recovery fix at
`a1d868287a729c75d9b8628f612a856db132374a` is included in the final image; its local build/typecheck,
`28` frontend tests, and browser `4/4` had passed. Owner passkey enrollment and saved-data
verification remain pending. This is historical passkey evidence, not TOTP acceptance evidence.

The historical `R-ASTRA-102` documentation boundary covered the then-deployed schema-9 release:
GitHub OAuth plus a six-digit TOTP authenticator code, its one-time legacy-passkey migration,
hashed single-use recovery codes, and production GitHub-auth TOTP step-up for administrator backup/restore. The migration
route is not the current setup flow. `R-ASTRA-110` and the `R-ASTRA-102` checks and release details
below remain historical evidence. The R-ASTRA-111 schema-11 baseline was deployed at pushed
revision
`82f2dfed76f6aee2a1ef9c3decd675ed72d89fed`, schema 11. Its migration cleared OAuth transaction
rows and preserved user/session/research rows; the deployment verified a schema-10 pre-migration
backup and installed production Compose ingress attribution through the existing reviewed
host-Compose updater. The
corrected local gate, scoped Sol security review, independent Luna Docker bridge regression, and
bounded public probes passed for their declared scopes; the earlier gate failure on stale schema-10
expectations remains historical. SMTP was unconfigured during R-ASTRA-111 deployment checks;
R-ASTRA-112 later enabled production SMTP and confirmed delivery of an owner-bound invitation to
Gmail's Spam folder. This was an operator service-function test, not an authenticated HTTP/browser
test; inbox placement was not achieved for this test, while new-user onboarding remains unverified. See the
[R-ASTRA-112 evidence](../../MVP-PLAN.md).
`R-ASTRA-113` extends this coverage to email-only invitation creation and GitHub-verified address
binding at redemption. Keep the exact request and fail-closed matching rules in the
[API reference](../reference/api.md#email-invitation-contract), the administrator procedure in
[getting started](../operations/getting-started.md#invitation-email-and-host-compose-update), and
the identity threats in the [threat model](../security/threat-model.md). Update `AGENTS.md`,
`README.md`, the [MVP plan](../../MVP-PLAN.md), and the [roadmap](../../MVP-ROADMAP.md) with the
same task ID and evidence-backed status. GitHub email verification uses the authenticated email
list and the `user:email` scope; the official [GitHub endpoint reference](https://docs.github.com/en/rest/users/emails#list-email-addresses-for-the-authenticated-user)
is the permission/response source. Keep email-only sends separate from the older numeric-ID code
flow, and never infer mailbox placement or invitation redemption from local QA or the R-ASTRA-112
service-function delivery check. For R-ASTRA-113, independent local QA and the final native-x86_64
gate passed (`796` Python tests), and the reviewed schema-12 release was deployed at pushed revision
`4cc5c8502ec93c57947958ee07f891b45e98d870`. Three invitations were submitted through production
service functions and Resend showed all three delivered. Three personal-Gmail messages are
recorded in the same invitation thread: the original notice and two later support replies. This
did not exercise the authenticated HTTP/browser send. One recipient mailbox classified
its invitation as Spam; other mailbox placement/read status is unavailable. R-ASTRA-113 remains
**In progress** overall: recipient feedback and sanitized logs support one invitee's redemption,
TOTP enrollment, and private API access, but not browser-rendered UI. Another valid invitation was
rejected; verified-email mismatch is an inference. The complete receipts and R114/R115/R116 repair history are in the
[MVP plan](../../MVP-PLAN.md); R-ASTRA-112's Gmail Spam result remains separate.
`R-ASTRA-118` is **Completed for its declared local QA, deployment, and same-thread retry scope**.
It documents the active email-bound invitation mismatch distinction while preserving the existing
atomic no-consume behavior, fixed HTML error redirects, JSON compatibility, and UI guidance across
the API, operator, and threat-model documentation. The full gate and deployment receipts are in the
MVP plan. The remaining invitee's actual sign-in confirmation remains pending; physical iOS behavior
is unavailable.

`R-ASTRA-119` adds the approved `beta-testing-email-workflow` project skill and documents its
authorization in `AGENTS.md`. Independent review found and repaired an ambiguous release-announcement
rule; five sanitized scenarios passed. Hold release announcements until the exact reviewed revision
is confirmed deployed and service health is confirmed; wording cannot bypass that gate. The standing
notice applies to the existing opted-in beta cohort only, using the established sender and release
context; docs/skill commits do not trigger notices. Check send history, honor opt-outs, avoid contact
harvesting or new recipients, and distinguish sent/delivered/inbox/read status. The R-ASTRA-118
support retry already covered its deployed version, so no duplicate release notice is due. Runtime
skill discovery is **Unavailable** until directly checked in a fresh task; static admission does
not prove loading. See the [MVP plan](../../MVP-PLAN.md) for the initial finding and repair receipt.
Backup/restore compatibility and caller limits are documented in the
[backup guide](../operations/backup-restore.md) and [API reference](../reference/api.md).
Independent scoped QA and Astra's security re-review are recorded in the root plan. Its local gate
**Passed** for its
declared scope: receipt `test-results/local-gates/R-ASTRA-102-20260928T201109Z/evidence.json` reports
`704` Python tests passed, `4` live tests deselected, `85.10%` coverage, frontend typecheck/build and
`28` frontend tests, and documentation coverage. The earlier aggregate failure remains visible as
historical evidence: four stale schema expectations and 84.88% coverage. The reviewed app revision
`403cd79b08f90b49603cec3152b4f1e07b91d730` was committed and pushed with exact `origin/main`
matching. Its GitHub Release archive SHA-256 is
`811229e8355679f08d1a0857426cbec3526cee492417e50a5f9fe760e98894f4`, and publisher re-download
verification passed. The Linux/amd64 image is `103146866` bytes with ID
`sha256:76283822fb01ba19ead18037d3396b81db5c804e41d0203dfbaae04c3c3abb8f`; restricted MCP plan
`5b757cb6e2cb2b8d97b85613a4b5504b` deployed it, with inspect/status schema `9`, `ready`,
`loopback_only: true`, and verified pre-deploy backup
`pre-deploy-403cd79b08f90b49-3055603f.spbackup`. Before that successful retry, the first official
MCP `plan_deploy` call for the same revision/archive/image returned bounded
`remote_operation_failed`; the remote remained on its prior healthy schema-8 image. The cause was
not established. Fixed structured-helper plan `5b757cb6e2cb2b8d97b85613a4b5504b` then succeeded and
the subsequent official MCP deploy passed. Live Cloudflare probes returned the recorded
health/auth/authenticator `200`, sign-in redirect `303`, and private-history `401` responses with
`no-store`/`DYNAMIC`. The IAB reached the one-time legacy-passkey migration route; its button
remained `Waiting for passkey…`, reloading cancelled it, and sign-out returned to `/sign-in`.
Owner TOTP enrollment, live mobile sign-in, and browser-rendered saved-data access remain
**Unavailable**. Documentation validation remains a documentation gate, not a release or security
acceptance.

Authored guides live under `docs/` in task-oriented categories. Every page has `title` and
`description` frontmatter, one primary topic, a lowercase hyphenated filename, and relative
links. Category `index.md` pages provide navigation rather than duplicating topic prose.

## Source boundaries

- [`MVP-PLAN.md`](../../MVP-PLAN.md) is the authoritative contract and evidence ledger.
- [`MVP-ROADMAP.md`](../../MVP-ROADMAP.md) is the authoritative dependency/status summary.
- [`AGENTS.md`](../../AGENTS.md) controls repository ownership and evidence discipline.
- [`README.md`](../../README.md) is the root landing page and concise quick start.
- [`SESSION-EXPORT.md`](../../SESSION-EXPORT.md) is generated and overwritten only by export
  gates. Never move it into `docs/` or edit it as authored prose.

Guides should explain stable behavior and link to root records for volatile milestone facts.
Do not copy evidence bundles, fabricate a future revision, or convert implementation presence
into acceptance. A code example must use placeholders or deterministic public fixture values,
not credentials, private paths, or copied runtime output.

## Audit workflow

1. Identify the single category and topic before adding a page.
2. Check source code for behavior and root ledgers for contract/status claims.
3. Add the page to its category index and ensure the root documentation index reaches it.
4. Run `.dev-venv/bin/python scripts/validate_docs.py`.
5. Review the changed paths and record the actual pre-change and post-change checkpoint states.

The project `documentation` skill contains the agent-facing version of this workflow. Skill
or configuration-time changes require an OpenCode restart before discovery can be validated;
the editing session itself is not proof that the restarted process loaded them.

## Historical application receipts (preserved)

All Ponytail references in the receipts below are historical, overengineering-only evidence. The
retired adapter/package/plugin is not a current workflow dependency or gate.

`R-ASTRA-70` is **Completed** for its declared documentation-only portable-link repair: eight
ignored-artifact links were changed to inline code. The current `R-ASTRA-71` documentation
reconciliation records the named initial ASTRA failure, the `R-ASTRA-66`–`R-ASTRA-69` repair
progression, the clean final `R-ASTRA-69` Ponytail boundary, independent repair QA, and the
accepted final ASTRA scope. The earlier `R-ASTRA-64` reconciliation remains historical. The
current final ASTRA session is `ses_f622707a4ffeAE3Zx8Lt2zYiC1`, reviewer `ASTRA`, model
`openai/gpt-6-astra`, on native x86_64 with official MCP/headless Chromium `153.0.8010.12`,
reviewing `/` and `/api/v1/docs` at `320x844` and `1280x1000` in Light and Dark; its scope is
accepted with no blockers. Physical mobile, actual screen-reader, true-zoom, fresh ASTRA
axe/screenshots, and native/physical ARM64-performance evidence remain unavailable. Local and
ignored artifact paths in documentation remain inline code, never Markdown links.

`R-ASTRA-72` records the validated rename to exact `Orchestrator` and the required parent-process
restart. Independent post-restart QA passed the declared rename/restart-validation scope; full
evidence and limitations are recorded in [`docs/evidence/astra-final-report.md`](../evidence/astra-final-report.md).
No release, export, commit, push, or remote result is implied.

The earlier `R-ASTRA-64` receipt described `development-conventions` as the eighth opt-in project
skill in that historical catalog, and fresh discovery was recorded as **Pass**. The R-ASTRA-71
reconciliation recorded seven approved directory-based skill definitions/governance entries after
Ponytail retirement; this historical static count did not establish native loader/discovery
acceptance. The current eight-entry catalog is recorded above. Skill/profile activation still
requires a parent OpenCode restart and independent post-restart discovery; implementation presence
does not create that gate effect.

The validator checks heading anchors, high-confidence credential patterns, duplicate taxonomy
links, exact description parity between the skill frontmatter, project catalog metadata, and
skill index, and the active skill's 500-line limit. Prose duplication is a manual review rather
than a validator heuristic. These are static governance checks; metadata, the index, the
allow-list, and `SKILL.md` frontmatter do not establish that a native loader discovered a skill.
Native V2's directory-based auto-discovery is the loader boundary, and runtime discovery remains
**Unavailable** in this harness.


## R-ASTRA-121 free OpenCode restoration evidence

The free-only OpenCode restoration precedes the seven-feature releases. The documentation map
covers the packaged native SDK declaration record, managed execution guards, provider consumers,
and their regressions. Keep the user correction in `AGENTS.md` and outcomes in `MVP-PLAN.md`.
A genuine free answer from an isolated application fixture is functional evidence for that fixture.
If its wrapper supplies guard readiness, it does not verify production receipt enforcement.
Only the installed root-owned, nonwritable receipt and matching binary can establish the normal
managed-worker readiness path. Preserve failed baseline and guard-fixture attempts separately;
never reconstruct a missing contemporaneous wrapper or source binding.


The PR #9 rehearsal documents two distinct baselines: the current schema-13 production image
observed by read-only inspection, and the historical schema-12 migration/recovery origin. Keep
live production identity and health guards and their consumer receipt validation aligned with the
exact observed deployment; do not replace the historical migration origin or infer current health
from it. See [the operational procedure](../operations/getting-started.md) and the R-ASTRA-121
MVP ledger for source and runtime evidence separately.


PR #9 checker diagnostics retain only the closed reserve phase and below-threshold numeric KiB
readings; host and controller tests validate this boundary. Document actual host failures separately
from local pair, native and canonical passes. Browser fixture checkpoints record only synthetic
stage/status/timing and public module/process information, with no user prompts or capabilities.
A focused browser pass does not replace a failed full aggregate. See the R-ASTRA-121 E14 ledger.


Rehearsal baseline changes require the mapped testing, configuration and operations pages plus
`AGENTS.md`. Document the running candidate or recovery role separately from the immutable
schema-12 pair seed; an exact image allowlist is a guard, not evidence that the image served
production or met the resource floors. Keep source checks, local disposable compatibility, signed
backup verification and actual-host observations separate in the [E19 ledger](../../MVP-PLAN.md#r-astra-121-e19-installed-rollout-repair-and-signed-schema-13-backup).

For the current PR #11 follow-on, coverage also spans the exact 6359 temporary-recovery consumer
and the known 67723 installed-helper receipt. Update `AGENTS.md`, this page, testing, operations and
the MVP ledger together. Keep the retained 5ad/A9 identities, immutable original helper backup,
source/mock QA, actual-host preflight and restoration as separate facts; a build does not establish
host acceptance. The later c408 helper install/readback, local 6359 fixture profile, archive scan,
and actual archive-parser failure have separate scopes. The exact-tag/canonical-alias parser repair
passed 56 selected tests and the retained-archive smoke, with `fstat.st_uid` mocked; actual
root-owned admission and host transition remain unavailable. Preserve the prior failed QA receipt.
The full F6 aggregate remains failed at 195/2/3, with two raw-axe attachments unavailable out of
24; the focused four-case follow-up passed for its selected desktop/mobile and four raw-axe snapshot
scope only. See the [latest PR11 checkpoint](../../MVP-PLAN.md#r-astra-121-pr11-installed-helper-local-6359-profile-and-archive-parser-checkpoint-2026-10-16)
and the [initial consumer/install checkpoint](../../MVP-PLAN.md#r-astra-121-pr11-temporary-recovery-consumer-and-installer-receipt-checkpoint-2026-10-16).

The later PR #11 Docker profile repair passed 33 builder and 33 independent focused tests, with
scoped source review and static checks passing. A separate two-file run reported 617 passed and
one skipped but had a workflow-compliance failure because it included a possible Docker integration
test without JUnit; Docker execution and exact cleanup remain unavailable. The actual V5 host
command failed with exit 1; its emitted workflow record reported unavailable at operation
identity, and the pair rehearsal did not run. Read-only profile and
canonical-manifest/archive diagnostics passed only their stated scopes; a counterfactual use of the
repaired profile function still failed the existing approval-format check. Preserve the strict
canonical serializer requirement and do not treat the diagnostic as an installed-helper or
host-transition pass. See the [Docker profile and admission checkpoint](../../MVP-PLAN.md#r-astra-121-pr11-docker-profile-repair-and-actual-host-admission-failure-2026-10-16).

The lazy-provider startup repair is documented in the API, testing and operations guides and
[E32](../../MVP-PLAN.md#r-astra-121-e32-lazy-provider-startup-and-host-reserve-checkpoint). Preserve
its local import-memory and focused QA scope separately from the failed host startup guard.
Changed recovery-overlay bytes require fresh image/pair bindings; an earlier image cannot inherit
the source repair or the new frontend build result.

The PR #11 helper-upgrade contract keeps the immutable original helper backup separate from the
pre-install helper used for compensation. Document both identities, require the exact reviewed
intermediate receipt and sidecar pins before upgrading, and retain a failed-upgrade/retry test.
The identity parser must follow the actual subprocess producer's text contract. See the
[F6 runtime/helper checkpoint](../../MVP-PLAN.md#r-astra-121-f6-native-results-and-deployment-helper-repair-2026-10-16)
for scoped evidence; source/unit checks do not establish installed-helper or host acceptance.

The subsequent PR #11 V7 host trial **Failed** at `admin_step_up` before either owner's model,
turn, or tool activity. Its bounded receipt omitted the safe error code and HTTP status, so the
specific cause remains **Unproven**. Source inspection confirms a fresh TOTP value is generated
immediately before the step-up POST; this rules out only the stale-precomputed-code hypothesis. The
pair phase failed, while restore, the recorded owner-canary-to-invited setting phases, and final
5ad/schema-13 readiness passed for that trial. These operational phases do not deploy a new
application release or establish an owner canary answer. See the
[V7 and backup-retention checkpoint](../../MVP-PLAN.md#r-astra-121-pr11-v7-host-trial-and-backup-retention-checkpoint-2026-10-16).

The managed backup pool reached the 32-artifact limit. One archive was verified without promotion,
independently copied opaquely to the approved SD volume, and moved with `NOREPLACE` into the
same-volume retained-backup directory. The post-move readback observed 31 active artifacts and
the retained archive; a later host trial created another backup, so that earlier count is not a
current inventory. The signed-reader, copy, move, and receipt-integrity results are recorded in the
plan. Key rotation and retirement remain held by task policy until that archive is re-admitted,
verified, coordinated into rotation, and its independent copies are rebound; this is not an
automatic application guard. Independent QA of the bounded failure-projection repair passed 14
JUnit cases and its scoped lint/format/diff checks on the verified SD mount; the original misplaced
builder run retains its storage-compliance failure. The repaired retention utility passed independent source/test QA with 26 cases and its configured,
security, and format checks; the earlier three-finding review remains preserved. That QA did not execute the production move, which has a
separate one-shot receipt and readback review. Neither source QA nor receipt-chain review establishes
native/runtime or release acceptance. The existing 1 GB host, backups, and US$15 monthly cap remain
in force, and the native/resource, exact-PR recovery, browser, canonical, guide, canary, and release
gates remain open.


The pushed PR11 diagnostic-projection commit `d6064e68026a5315e6f03337ad78ba74e7ff6c2e` passed
packaging with the F6 and 5ad archives unchanged; installation was not invoked. Independent
readiness review failed because the installed helper matched the candidate digest but its generic
identical-digest branch rejected the exact prior E1/556 receipt. Source review corrected the preliminary DD7-branch attribution for the readiness failure: the
independent receipt identifies rejection in the generic identical-digest branch. Separately, the
builder-reported pre-edit DD7 test-fixture failure had stale current-source hashes; its raw artifact
is **Unavailable**, with no independent reproduction or reconstructed baseline. The scoped builder repair passed 22 focused tests, and independent QA passed 22 tests with zero
failures, errors, or skips. Review confirmed exact E1 constants against the actual `d040d87b`
receipt and the known-E1/exact-candidate receipt rule; its synthetic DD7 sidecars do not establish
real historical-DD7 reinstall acceptance. No host install or runtime was exercised. The a6 journal archival and 32-artifact readback
passed separately. See the [d6064e6 bootstrap-readiness checkpoint](../../MVP-PLAN.md#r-astra-121-pr11-d6064e6-bootstrap-readiness-checkpoint-2026-10-16).
