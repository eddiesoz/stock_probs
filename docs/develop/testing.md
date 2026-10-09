---
title: "Testing"
description: "Local developer checks for Python, APIs, persistence, browser behavior, bounded builds, backups, providers, and architecture."
---

# Testing

## Reviewing incomplete contrast results

Keep raw axe violations and incomplete results in the evidence. An incomplete result needs
manual review; axe has not definitively classified it as a violation or a pass. See the
[axe results contract](https://github.com/dequelabs/axe-core/blob/develop/doc/API.md#results-object).
Map every exact raw node to the measured direct text, verify its foreground against the nearest
opaque semantic background, and check all line rectangles, clipping and sampled foreground
occlusion. Require independent QA and parent inspection of the bound screenshots. Unknown,
unmapped or unresolved nodes fail the contrast gate; do not suppress the rule or alter the
approved layout solely to clear a resolved classifier result.

The current assistant contrast review and strict raw-axe status are in the
[R-ASTRA-120 ledger](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on).
A manual resolution for measured nodes does not change the strict raw-axe zero-incomplete
requirement.

## Reproducible image-build and source-recovery evidence

Before source edits, save the exact bytes and SHA-256 of each owned baseline file in a task-owned
recovery directory. Require at least 4 GiB free on the build filesystem before starting a Docker
image build; stop the owned build if free space falls below 1 GiB and hold source edits until the
low-disk build has terminated. If the repository filesystem fills, retain terminal evidence under
`/tmp`. Remove only exact fixed-ID cache objects proven task-owned and unused. Never force-remove,
globally prune, or remove protected release images or application data. This procedure does not
authorize a resize above the US$15 monthly total cap including backups and tax. The root
[agent policy](../../AGENTS.md) is authoritative.

For a full schema-12-to-13 pair rehearsal, `--use-deployed-baseline-image` is an optional boolean
that selects the centrally pinned deployed schema-12 image. It is accepted only in full-rehearsal
mode; the default still rebuilds the base image from the verified archive. Before reuse, the helper
checks the immutable image ID, `linux/amd64` platform, expected revision label, and a nonempty valid
retained-tag list. The receipt's `schema12_base_image.mode` distinguishes
`reused_exact_deployed_image` from `locally_rebuilt_from_verified_archive`. A reused protected baseline is not a generated cleanup
target. The helper removes only its task-generated tags after ownership checks, using
`docker image rm --no-prune TAG` so Docker does not remove untagged ancestors. Manual cache cleanup
uses exact fixed image IDs only after provenance and reference checks, as described in the root
[agent policy](../../AGENTS.md). Selected helper tests do not establish that a pair rehearsal ran;
see the [R-ASTRA-120 ledger](../../MVP-PLAN.md) for the current scope.

### Schema-13 rehearsal image cleanup

The rehearsal runner delegates cleanup of a generated recovery image to the bounded builder with
`--retire-schema13-rehearsal-tag TAG --retire-schema13-rehearsal-image-id sha256:<64-lowercase-hex>`.
The operation serializes on the image-ledger lock, checks the required expected ID against a
completed registered recovery row before Docker inventory or mutation, and validates the bound
receipt. It refuses protected or current images, shared or rebound tags, malformed or unregistered
rows, child images, and container references. Removal uses `docker image rm --no-prune` with the
full image ID; the helper checks that the ID and tag are absent before updating and revalidating
the ledger. If image removal is partial, it restores the recorded tag. Keep failed rows for review
and do not edit the ledger by hand, force-remove, or prune globally.

For OCI layer ancestry in a containerd-backed image store, inspect bounded Docker `RootFS`
metadata rather than assuming a `Parent` value is present. The guard accepts only requested,
unique full image IDs with `RootFS.Type=layers` and a canonical nonempty list of at most 128 unique
SHA-256 layer digests. Missing, duplicate, extra, unknown, malformed, unavailable, timed-out, or
over-limit metadata fails closed; preserve equal-layer and strict-prefix ambiguity checks. Capture
Docker stdout incrementally and reject overflow before appending beyond the configured byte cap.
E828's 301-case independent suite and parent source review passed this selected guard scope; its
separate actual recovery-image retirement passed, while its local PR-pair rehearsal failed before
writing the required receipt. See [E828](../../MVP-PLAN.md#r-astra-120-e828-latest-built-candidate-and-recovery-checkpoint).

For E825, a diagnostic confirmed `candidate_ledger_inventory_mismatch` in the pre-repair cleanup
state (receipt SHA-256
`b261bc2fbba5b7594ab25e3293046e28735b8d429fa6badd5799d72df2ae90f7`). The initial helper and
rehearsal candidate passed 172 builder-selected tests with Ruff and format; initial E501 and three
format diagnostics remain recorded as check failures. Initial independent cleanup QA **Failed** on
a P2 because the expected full image ID was not required before deletion. The identity-bound repair
then passed 179 selected tests with Ruff, format, security, and diff checks. Independent re-review
and parent integrated review **Passed** for the four pinned files; the source review confirms the
expected ID is checked before Docker inventory/removal and before ledger mutation. Independent
receipt `/var/tmp/r120-retirement-identity-independent-qa-20261009T1647Z/independent-qa-receipt.json`
has SHA-256 `a04ff94c9e22f89a00021af9b74deede6f748f0ed79727e80df364ffa2493833`; parent review
receipt is linked from the [E825 ledger](../../MVP-PLAN.md). Receipt for the original QA failure:
`/var/tmp/r120-rehearsal-ledger-independent-qa-20261009T1638Z/independent-qa-receipt.json` has
SHA-256 `b139822219e5e1bb194e6b541fd8cee0b3c0351ffaf5a841be300306a1dc5423`; it used mocks and did
not build or delete an image. At the E825 checkpoint, the repaired independent review also used
mocks: no Docker build, image deletion, or actual schema-13 pair rehearsal had run. The separate
bounded-policy helper's 145-test result is a distinct scope. See the [E825 ledger](../../MVP-PLAN.md)
for exact bindings and status.

## Bounded local Docker builds and worker verification

Use `./scripts/local-compose.sh build` or `./scripts/local-compose.sh up --build -d` for local
root-Compose builds. The launcher performs the bounded build; `compose.yaml` intentionally has no
build context and requires its explicit local-image pointer. Keep at least 4 GiB free before an
owned build and stop below 1 GiB. BuildKit's configured 4 GiB maximum-used setting is a periodic
garbage-collection target, not an instantaneous cache quota. See the [local storage procedure](../operations/getting-started.md#local-docker-storage-on-removable-media)
for UUID mounts, backups, cache relocation, and present/absent-medium guards.

Before claiming bounded-build acceptance, bind the setup receipt to the selected controller,
inspect its limits, and prove the actual build worker runs beneath the expected bounded container
ancestor. A controller's `init` process leaf, a TOML file, or a passing mocked test is not worker
cgroup evidence. Keep source QA, controller verification, and actual worker-step evidence separate.
At the E823 checkpoint, worker probe 02 **Failed** because its verifier selected the container's
`init` leaf instead of the bounded ancestor, and completion 03 **Failed** at its timeout while logs
showed Docker Hub DNS timeouts on the default bridge. A successful DNS lookup on the dedicated
owned bridge does not establish a universal cause. E824 supersedes the pending worker result: the
actual network-none worker `RUN` passed strict container-cgroup ancestry verification, with
descendant `memory.max=1342177280` and `cpu.max=100000 100000`. The controller's PID limit of 128
applies to the controller, not the worker. Independent source QA passed the exact setup/producer/wrapper pins in its selected scope (13
producer, 27 consumer, and 8 space-guard cases), and independent normal-user helper QA passed its
read-only setup-receipt, data-root, controller, and cache-volume checks; that helper review made no
build or mutation. The actual setup receipt and worker-step pass prove this bounded worker scope;
they do not establish an application Compose image build, release, or production acceptance. Preserve the earlier failures and see the [MVP plan](../../MVP-PLAN.md)
for receipt details and remaining gates.

E826 then attempted the first actual PR-head application build on pushed, clean head
`ae140dd011ee043cd24c7db84b6922826d012d28`; the bounded build stage **Failed** with exit 1 and
`local_build_failed:bounded_image_build:exit_1`, while the outer rehearsal command exited 2. The
expected candidate receipt was not created, the terminal log was 110 bytes, and independent review
confirmed the candidate tag was absent and BuildKit history ended in `Error`. The independent
review completed at `2026-10-09T17:03:39Z` (receipt SHA-256
`6d7a820ca30db3af13efd95d7871aa42270d0c115e9bf5dcfbad2ead51e7e20f`); its exact Docker-cause
query was **Unavailable**, and browser/runtime acceptance was **Skipped**. The exact failed
subcommand and cause remain **Unproven**; the helper reports only
`fixed_command_unavailable_or_timeout`. The monitor repair addressed a possible false-abort path,
but does not establish the cause of the failed build.
The source-only monitor repair passed 106 builder tests and static checks, then 106 independent
tests with zero failures, errors, or skips; parent source/evidence review passed with integrated
receipt SHA-256 `8850e4efb061b5bd4ea252e9a3d45c6a6530282a60e1294348a0e6293dd5ee2f`. Typed recovery for the in-flight reservation initially failed independent synthetic QA with a P2: an
exclusive-create receipt remained partial after `OSError`, although the ledger was restored and the
reservation retained. The repair passed 132 builder-selected tests, parent source review, and 132
independent synthetic tests with no failures/errors/skips. The first actual release attempt then
failed receipt-path validation with an unchanged ledger; after a narrowly scoped directory-mode
repair, the second actual release passed and removed the in-flight row. Independent read-only
review confirmed the empty candidate ledger, matched receipts, and exact candidate-tag absence. No
Docker/image mutation occurred; the tag check was not a broad image inventory.

A follow-on managed-run-directory repair passed 134 builder-selected tests, parent review, and 134
independent permission tests with static checks. E827 then attempted a second application build on
the then-clean pushed head `83e0b0e1cdfbec8502208c48814a592112c022ea`; the helper exited 1 and outer
rehearsal exited 2. BuildKit reported `cannot copy to non-directory .../lib` at
`COPY --from=opencode-assets /out/ /`. Preserve the raw failure diagnostic and corrected projection
linked in [E827](../../MVP-PLAN.md#r-astra-120-e827-pr-head-candidate-build-failure-and-copy-path-repair);
the initial flat-key projection's null error was incorrect. The explicit-`/usr/lib` copy repair has
seven builder tests, parent source review, and independent two-module QA (154 selected tests plus
Ruff/format checks); that QA preserved the then-unfixed Dockerfile pin. The pin-only follow-on matched
the Dockerfile pin (old prefix `2d9355`, new prefix `f2dc019c`), passed 147 builder tests and parent
constant-only review; supplemental independent review passed the exact pin-only diff and read-only
actual-state checks (empty ledger, exact tag absent, prior receipts unchanged, app health HTTP 200).
See E827 for the bound receipts. The setup receipt is not Dockerfile-bound, so no BuildKit
reinitialization was needed. E813's guide metadata rebind passed against 83e for 94 consumer inputs,
52 assets, 23 artifacts, and 8 PNGs; this does not establish final PR-head guide acceptance. Later
source edits make 83e historical. At the E827 checkpoint, a fresh exact-head image build and
schema-13 pair remained pending; E828 supersedes only the image-build status.

E828 built the latest Linux/amd64 image
`sha256:802319bed035d9f40425c019951e2e764b2e0253d7161da4964f7c2a6d87bb8a` from candidate head
`fb8a9cc6d5f723b976897f3643895c66127a0d27`; its one-shot OpenCode loader probe and active-search-kill diagnostic passed their declared scopes (the kill used a 768 MiB cap). The
two-owner native functional attempt **Failed**. The local schema-13 pair command also **Failed**
without a pair receipt; separate exact-image retirement does not change either result. The
RootFS/stdout guard passed independent 301-case QA and parent source review. A separate provider-response-phase
observer passed 523 builder and 523 independent selected tests plus parent source/evidence review;
no native acceptance, provider cause, or latency repair is inferred. Later diagnostic-source edits
require a new exact-head image before another native run. E828's parent review also passed standalone
guide acceptance bound to this head; PDF/UA, physical mobile, full-app accessibility, actual
combined 1 GB, and PR-bound rollback remain open. Exact receipts and limits
are recorded in the [R-ASTRA-120 ledger](../../MVP-PLAN.md).

E829's bounded read-only GET-observation repair passed parent source review and independent frozen
source/test QA (57 selected tests, zero failures/errors/skips, plus diff, Ruff, and format checks).
The selected scope keeps the original 120-second deadline, retries only transient read-only GET
observations, and leaves authorization, protocol, worker, and permission-reply POST failures
fail-closed. The builder's final focused terminal result remains **Unavailable**; its fixture setup
failures are preserved, and the built image predates the repair. E829's separate two-owner native
attempt **Failed** with cause **Unproven**; no native/provider or release acceptance follows. See
[E829](../../MVP-PLAN.md#r-astra-120-e829-candidate-native-failure-repair-and-guide-checkpoint)
for exact windows, receipts, and remaining gates.

E830 built image `sha256:d2cd30ca3a8d2c792d7362a37c19f9f865d5802542661db62e41d3bf47ab175f`
from PR head `09bdc942982c077535a4841f1439a012834fefc6`; parent review passed only build, context,
stage, and static packet binding. The one authorized native attempt **Failed** (exit 2): owner 0
answered in 48.016 seconds; owner 1 timed out at 120.973 seconds after seven native-search sources
and one approved fetch source without an answer. Both conversation deletes returned HTTP 200. The
cause remains **Unproven**, and a 768 MiB diagnostic is not actual combined 1 GB acceptance.

The follow-up cached-snapshot observer is bounded diagnostic instrumentation: it records only a
closed snapshot of counts/finish classes and cancellation/timeout status from an already validated
GET observation. It makes no extra GET, does not extend the original 120-second deadline, and leaves
authorization/protocol checks and the single permission-reply POST unchanged. Builder-selected
results were reported separately from independent QA. The earlier builder 23-case pre-freeze report
is not accepted. Independent QA of the frozen four-file set passed 21 runtime and 78 parser tests,
zero failures/errors/skips, Ruff/format/diff checks, and unchanged 18-file source pins; its receipt
is `test-results/assistant-r120/coordination/timeout-snapshot-independent-qa-20261009T2044Z/independent-qa-receipt.json`
(SHA-256 `32aad4016965251bc2e3a9aee8f011bfa236a75e97d97d168c1736a269f65b7c`). The parent source
review and integrated evidence review passed for those pinned diagnostic-source/test artifacts.
This QA did not run live runtime, provider, Docker, or service operations; the E830 native failure
and unproven cause remain. The image predates the observer changes, so it does not test that
diagnostic in native execution. See the [E830 ledger](../../MVP-PLAN.md#r-astra-120-e830-current-native-failure-and-bounded-snapshot-checkpoint)
for exact receipts and remaining gates.

E831 built candidate image `sha256:7801b92f125a25a3cfcf112b4d584da76685be73cb9b5e2f8a087beb3fc56479`
from clean pushed PR head `fa3db0e9fd2b48032735474691df900135aa1357`; independent build review passed
its exact-head, source/context, terminal, and 52 served/export binding scope. The one authorized native
attempt **Failed** (exit 2). Its bounded output contains a schema-13 readiness preflight reported ready
after 36 attempts in 18.507 seconds, followed by only a generic app-health/worker-readiness guard
failure. No per-owner answer/tool details, post-run readiness query, or resource sample was retained;
the failure cause is **Unproven**. Independent result-integrity and exact cleanup review passed for
their declared scope, not for native function. The first independent volume check failed only on an
error-text matcher; its corrected exact-reference check passed. No retry, pair rehearsal, kill, or
production operation was authorized or run. A narrow test/probe-only late-failure diagnostic repair
is in progress; independent verification is pending. See the [R-ASTRA-120 ledger](../../MVP-PLAN.md)
for receipt hashes, exact limits, and remaining release gates.

E832 supersedes only E831's pending diagnostic-repair and independent-QA status. The two-file
test/probe-only repair passed the final builder module run (437 tests, zero failures/errors/skips;
Ruff check, format, and diff check passed) and independent focused QA (437 tests, including 19 new
cases; zero failures/errors/skips; 46 before/after source/import/data pins matched). Parent source
and evidence review passed. The change adds bounded output from validated driver/resource/timing
projections and fixed failure-condition codes; readiness/resource predicates and budgets are
unchanged. The first independent baseline verifier attempt failed at setup because it used current
hashes for older recovery copies; the corrected check used the recorded pre-edit hashes and passed.
Warning count is **Unavailable** under `--disable-warnings`, and plugin autoload was disabled; no
async tests ran. This does not repair E831's native failure or establish runtime, provider, Docker,
resource, image, or release acceptance. The follow-up native packet received static path/pin/syntax
Pass only; its candidate identity remains unbound and execution held. Its earlier setup
`AssertionError` remains preserved, and no runtime or Docker operation was invoked. See the [E832
ledger](../../MVP-PLAN.md#r-astra-120-e832-late-failure-diagnostic-only-repair) for exact pins and
receipts.

## Unix-socket test fixtures

Supervisor tests create AF_UNIX sockets. Use a unique, caller-owned short temporary root for
their pytest base directory; evidence-directory names must not determine socket paths. Check
the complete encoded socket-path length before binding. Linux limits pathname sockets to the
length of `sockaddr_un.sun_path`, including its terminator. Preserve a path-length setup failure
separately from product assertions, and rerun only after correcting that fixture boundary.
For live supervisor cases, verify the serving thread exits and its control socket is unlinked;
remove only that run's owned temporary directory after all children have exited.

## Current OpenCode V2 QA contract

Use native OpenCode V2 `build`/`plan` entry points and the Luna profiles: `luna-build` may
implement, `luna-qa` verifies read-only, and `luna-docs` records only the owned documentation.
QA result labels are exactly **Pass**, **Fail**, **Skipped**, and **Unavailable**. A builder
report, implementation presence, generated artifact, skipped check, provider error, or missing
hardware is not acceptance. Native x86_64, emulated ARM64, and physical ARM64/mobile/
screen-reader/true-zoom evidence must remain separately labelled.

After changing project configuration, profiles, commands, plugins, or `.opencode` dependencies,
restart the parent before discovery or runtime acceptance. With `OPENCODE_DISABLE_PROJECT_CONFIG=1`,
project-profile discovery is **Pending**/**Unavailable**. The real V2 provider probe emitted an
error event without a report and is therefore **Unavailable**, not a provider acceptance result.

Native V2 automatically discovers project skills from directory-based
`.opencode/skills/<id>/SKILL.md` definitions; the `skills` configuration array is for additional
later-precedence sources, so an explicit `.opencode/skills` entry is not expected in
`opencode.json`. The eight approved definitions, `metadata.json`, `alwaysApply: false`,
`.opencode/SKILL-INDEX.md`, the
validator allow-list, and `.opencode/skill-history/learnings.md` are static governance/history
artifacts, not native loader proof. Runtime skill discovery is **Unavailable** here because
`OPENCODE_DISABLE_PROJECT_CONFIG=1`; no runtime loader result is inferred. The active history path
is `.opencode/skill-history/learnings.md`; the former flat
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

Ponytail is retired from the current tree and workflow. No package, plugin, dependency pin,
command, boundary review, or smoke check is current. The retained Ponytail reports are historical
overengineering-only evidence and cannot substitute for correctness, security, accessibility,
performance, or release evidence.

The documentation gate is separate and fail-closed. Run the validator, completeness checker,
change-aware checker, isolated self-test, and scoped `git diff --check` as applicable; do not
install hooks or treat the hook's presence as a check result.

The approved project governance set has eight directory-based definitions and no Ponytail skill.
This static count is not native loader/discovery acceptance. The provider/model runtime probe
remains **Unavailable** when it reports `provider.quota`, `Insufficient Balance`, and HTTP `402`;
no runtime, loader, or provider acceptance is claimed from that failure.

## Current research-workspace QA (`R-ASTRA-98`)

The post-reconciliation aggregate command was
`TMPDIR=/home/james/.cache/stock-probs-gate-tmp TASK_ID=R-ASTRA-98 ./scripts/local-gate.sh check`.
Its native-x86_64 receipt at dirty revision `09ba8b8dd285bd64c34241069051936c82c6390b` ran
`2026-09-18T15:47:01Z`–`2026-09-18T15:53:58Z`, **Passed** with exit `0`, and recorded `545`
Python tests passed, `4` deselected, no skipped test reported, and `90.38%` coverage. Frontend
checks passed `17/17`, including typecheck and the Next production build; static routes include
`/`, `/api-docs`, `/overview`, `/research`, `/tools`, `/tools/forecast`, `/tools/live-trading`,
and `/tools/markets`. Completed checks were `documentation-completeness`,
`frontend-npm-ci-typecheck-build-test-stage`, and `python-checks`. The tracked receipt is
`test-results/local-gates/R-ASTRA-98-20260918T154701Z/evidence.json`.

Separate supplied backend QA passed `240` tests. Browser QA passed `4/4` desktop/mobile-emulated
cases with axe `0/0`; live Yahoo checks covered `ACDC`, `SPY`, `SHOP.TO`, `VFV.TO`, and `PNG.V`.
The browser artifact is temporary: `/tmp/opencode/r-astra-98-browser-final-pass`. Native ARM64,
physical mobile, true browser zoom, and actual screen-reader acceptance remain **Unavailable**.
The recorded aggregate is scoped dirty-worktree evidence; it does not itself establish
release/export/commit/push acceptance.

## Run local checks

Bootstrap the pinned development environment:

```bash
./scripts/bootstrap.sh
```

Run the focused checks appropriate to the changed feature:

```bash
.dev-venv/bin/python -m pytest -m "not live"
.dev-venv/bin/python -m ruff check src tests scripts
.dev-venv/bin/python -m mypy src/stock_probs/backup.py src/stock_probs/cli.py
.dev-venv/bin/python scripts/validate_docs.py
./scripts/build-frontend.sh
```

Python tests use temporary databases and injected fixtures. Tests marked `live` contact Yahoo
Finance and are excluded from deterministic gates; a skipped or unavailable provider is not a
pass. Run checked-in isolated browser regressions with `make browser-test`, and the official
headless MCP interaction with `make mcp-smoke`. `scripts/local-gate.sh` provides the fail-closed
aggregate and records revision, architecture and results; a builder run is not independent QA.

The frontend build exports the pinned Next App Router UI and stages it for FastAPI; it does not
start a Next server. The served candidate contains 48 generated files and four authored assets.
Node remains build-only in the container, while the candidate OpenCode/Bun assistant worker runs
privately in that same application container. Keep native runtime checks separate from static
frontend and synthetic fixture checks.

## Assistant verification (`R-ASTRA-120`)

Use focused checks to isolate their boundaries. `tests/test_assistant_delete_session_boundary.py`
checks live-session revalidation around conversation deletion. `tests/test_assistant_native_harness_lifecycle_flows.py`
uses synthetic OpenCode HTTP responses; it does not run the native runtime. The provider-admin
API-flow tests use manager stubs, while `tests/test_assistant_provider_real_manager_http_flows.py`
uses the real `AssistantProviderManager`, a disposable encrypted vault, and public HTTP routes with
synthetic or mocked vendor, native-runtime, and model-catalog inputs. Assistant-help capture,
render, and finalization tests exercise those helpers; they do not establish app accessibility or
final PR-bound guide acceptance. A focused test or synthetic run establishes only its declared
scope, not live provider, native OpenCode, production, or release acceptance.

The browser fixture's startup-cleanup unit regression is run with the pinned project Node runtime:

```bash
.tools/node/bin/node --test tools/browser/tests/fixtures-lifecycle.unit.js
```

After E727's parent-applied patch, this tracked command passed 7/7 synthetic cases. It covers a
synchronous spawn failure and readiness failure with mocked child-process, network, and filesystem
interfaces; it does not verify real child-process readiness, asynchronous child error events, or OS
process reaping. The full browser aggregate must still pass separately.

The supervised native probe retains only normalized diagnostics. Model-discovery warnings use
closed outcome names and bounded numeric counters for catalog reads and the activation barrier;
raw log text, request URLs and owner identifiers are excluded. The existing limits remain four
distinct warning rows and 512 occurrences, with counter and elapsed-time bounds. These rows can
identify the failing stage; they do not establish a timeout cause, correlate an anonymous row to
an owner, or waive the 120-second turn deadline and shared eight-call limit. Host-probe changes
need fresh hash bindings and independent checks, separately from the application image.

The candidate timing schema v5 adds nullable `pre_session_phase` and
`pre_session_failure_code` fields to the existing anonymous terminal row. Values come from closed
allow-lists and are held in the private execution/owner context until that row is emitted. A
pre-session failure cannot coexist with provider request rows, a completed workspace summary, or
a completed terminal status. The host parser preserves older timing schemas and rejects missing,
forged, or contradictory v5 fields. These classifications distinguish the failed boundary; they
do not prove its cause or establish native execution acceptance. No credentials, prompts, native
identifiers, or owner identifiers belong in the retained projection.

### Maintained active-search kill probe preflight

The maintained probe must bind the disposable candidate to the fixed local Docker endpoint
`unix:///var/run/docker.sock` using an isolated temporary Docker config; do not inherit a remote
Docker context or `DOCKER_HOST`. Before a run, verify the local daemon endpoint and exact candidate
identity. The candidate must attach only to its expected per-run user-defined bridge; bind the full
network ID to the expected name, inspect by that ID, and require local `bridge` scope, default IPAM,
and exactly the owned candidate container as the endpoint. Reject a mismatch or any additional
network/endpoint, and clean up only verified owned IDs.

Before accepting a kill result, verify worker and survivor identity against the expected UID, GID and role-group values, and required `CapPrm` and `CapEff`. E768 found missing role-GID and `CapPrm` checks; E769–E772 later passed the repaired source/test review scope only. E769's initial builder fixture failure remains preserved beside its corrected 397-pass/two-warning report. These are source/test findings only. No fresh candidate image, current-image active-search kill, or runtime acceptance is available.

For a future PR-head run, first use a fresh verified build receipt and set `REVIEWED_PR_HEAD_SHA` to its exact current 40-character lowercase PR revision. E775 added optional `--candidate-revision` validation; the default local-source mode remains available. The existing E723 image predates this source-preparation change and is not a current candidate. Set the candidate and volume to their dedicated per-run Docker names from the verified probe/build materials: `assistant-r120-candidate-<12-hex-context-prefix>` and `stock-probs-assistant-r120-<same-prefix>`. The probe resolves these names and rechecks full container, volume, and network IDs. Use the image ID, context digest, and PR SHA from the same fresh verified build receipt. Do not reuse a historical revision value:

```bash
.dev-venv/bin/python -m tests.supervised_assistant_kill_probe \
  --candidate-container "$CANDIDATE_CONTAINER_NAME" \
  --candidate-image-id "$CANDIDATE_IMAGE_ID" \
  --source-context-sha256 "$CANDIDATE_SOURCE_CONTEXT_SHA256" \
  --candidate-volume "$CANDIDATE_VOLUME_NAME" \
  --candidate-revision "$REVIEWED_PR_HEAD_SHA"
```

This is the required module invocation for that PR-bound probe. E775 passed builder source-preparation checks (417 tests passed, 2 explicitly deselected, no failures, errors, or skips); E777 independently passed its source/test scope (417 passed, 2 deselected, 2 warnings, Ruff check/format/diff, and four stable pins). Neither ran Docker or runtime checks. Before runtime acceptance, the trusted local caller and parent must verify the maintained build-receipt SHA and its exact immutable image, context, and PR revision, then recheck the reviewed pair manifest. The PR revision is a local CLI argument, not an MCP input; the default local-source mode remains unchanged.

R-ASTRA-120 remains **In progress**. E725's earlier full-browser failure remains preserved. E765 later passed 191 cases with 3 expected skips and no failures; its four maintained assistant-panel axe snapshots were 0 violations/0 incomplete, which does not establish full-app accessibility. E767 passed fresh-task discovery of all eight tools and one read-only `status` call. E721 security results cover only the selected synthetic scope. No current-image kill, native/provider runtime, full security, or release acceptance is established. See the [authoritative ledger](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on) for exact history and receipts.

### PR-head candidate image build helper

The existing schema-13 rehearsal CLI now has a fixed-source mode for building a private local
image from the exact clean, reviewed head of open PR #1. Use only these mode flags:

```bash
python3 scripts/rehearse_schema13.py \
  --build-pr-candidate \
  --reviewed-pr-head "$REVIEWED_PR_HEAD" \
  --receipt "$PRIVATE_RECEIPT"
```

Set `REVIEWED_PR_HEAD` to the exact lowercase 40-character PR head SHA and `PRIVATE_RECEIPT` to a
private output path. The helper checks that local `HEAD` is that SHA and the worktree is clean,
validates the fixed PR-1/head/base relationship, rechecks the head around the build, and writes a
mode-0600 JSON receipt. The build is local `linux/amd64`, is not published, and requires at least
4 GiB free on every checked build filesystem; it aborts if free space drops below 1 GiB. E678's original independent process-ownership review **Failed** and remains historical. E683
recorded builder checks, and E684 independently passed source/test QA (59/59, exit 0; 149 inputs
unchanged). No actual Docker build or PR-bound rollback rehearsal ran; those acceptance gates remain
open. Do not treat source presence or test passes as build or rollback acceptance.

The later prebuilt-image rehearsal remains separate: it binds an immutable image ID and filtered
context digest to the same reviewed PR head SHA. The production publisher remains unchanged and
still requires a clean revision that matches exact `origin/main`.

### Exact PR-pair review pins

The fixed local review-pin command accepts only an explicit write request:

```bash
python3 scripts/pin_pr_rehearsal_review.py --write
```

Before writing, the helper reads the current commit, requires the exact clean PR-1 source, checks
its fixed candidate/recovery pair manifest and image/source digests, verifies the PR identity, and
binds the pair to that same commit. It accepts no target, path, or credential arguments. The
operator-local record is `$XDG_CONFIG_HOME/signal-ledger/rehearsal-review.json`; when
`XDG_CONFIG_HOME` is unset, the base defaults to `~/.config`. Keep this file outside the repository.
It is private mode `0600` and contains only format version `1`, the reviewed PR-head SHA, and the
pair-manifest SHA-256. It contains no credential material.

For compatibility, the MCP can also read the paired environment variables
`SIGNAL_LEDGER_REHEARSAL_REVIEWED_PR_HEAD_SHA` and
`SIGNAL_LEDGER_REHEARSAL_REVIEWED_PAIR_MANIFEST_SHA256`. A partial pair, malformed value, or
mismatch between the environment pair and metadata file fails closed. Do not set only one variable.
E767 passed fresh-task discovery of all eight configured tools/schemas and one read-only `status`
call. E741's `--write` command was not run; no review metadata was written and no PR-pair rehearsal
occurred. See the [MVP plan](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on)
for current status and detailed evidence.

### Binding browser evidence to the served frontend

Before browser QA or screenshot/capture evidence is claimed for the current frontend, run the full
approved `./scripts/build-frontend.sh` build-and-stage path and verify that every file FastAPI serves
matches the current `frontend/out` export byte for byte: compare all 48 generated Next files and all
four authored `/assets` files (52 served files total) against their matching export paths. An
npm/Next build alone does not prove which bundle the app serves. If any file differs, label results
as stale-stage evidence, rebuild and stage, then rerun the affected browser checks and captures.
The build/stage evidence is recorded in the R-ASTRA-120 ledger. A successful build/stage check alone
is not browser acceptance.

The Playwright journeys emulate system color preference and storage failure, switch among
light/dark/system on both local pages, and exercise print, reduced-motion, forced-colors, CSP, and
contrast behavior. News routes are fixture-fulfilled for not-requested, loading, fresh, empty,
partial, stale, provider-failure, local-unreachable, capacity-busy, and superseded states. The
mixed-feature journey changes theme, runs a forecast, expands from five to ten headlines, checks
local-only application requests and ledger exclusion, then reopens the saved forecast without an
automatic news request.

The M09 local performance profile records theme action, news cache-hit endpoint, ten-item render,
response-byte, and provider-deadline evidence alongside forecast concurrency and process-resource
rows. This is aggregate mixed-load evidence; do not describe the forecast-concurrency row as
simultaneous news traffic unless an artifact actually drives both. Pinned provider-feasibility
evidence and opt-in ACDC/SPY live-news probes remain separate from the deterministic suite; record
their command, environment, UTC, revision, result, and provider availability, and never convert an
unavailable live run into a pass.

## Historical application gate receipt (preserved)

Any Ponytail wording in this receipt is historical and does not describe a current check.

The latest post-ASTRA M09 gate artifact is `test-results/local-gates/M09-20260914T032442Z/`:
**Pass**, exit `0`, dirty `HEAD`
`5633f87f8cff04b5b33640f6633ff31c667c0435`, native x86_64, `2026-09-14T03:24:42Z`–
`03:37:22Z`, command `./scripts/local-gate.sh m09`. Its completed checks include the frontend
npm CI/typecheck/test/build stage, native package, Python checks, responsive browser
visual/accessibility/theme/news, official MCP, explicit ARM64 package/runtime, and mandatory
native M09 performance. The Ponytail interface was available but not invoked; that is not a
clean Ponytail result.

The artifact's Python JUnit reports `444` tests with zero errors and zero failures, with
`89.73%` coverage. Browser artifacts/logs report `64` passed and `2` expected performance
skips; the official MCP check is included in the gate receipt. The native performance summary
has `18` rows: `17` executable rows **Pass** and ARM64 performance **Unavailable**. Current row
values include theme p95 `35.0 ms`, browser render p95 `151.958 ms`, interaction p95
`24.027 ms`, ten-item news render p95 `35.0 ms`, news cache-hit p95 `1.809 ms`, news response
`701` bytes, provider deadline capped at `10 s`, static assets `697,667` bytes below `753,664`,
readiness p95 `2,633.207 ms`, process RSS p95 `144,457,728` bytes, and wheel `307,483` bytes
below `335,872`. The earlier `test-results/local-gates/M09-20260914T002732Z/` receipt and its
values remain historical. The failed rerun at `test-results/local-gates/M09-20260914T031828Z/`
also remains visible; it recorded `46` documentation-link setup errors and is not replaced by the
later pass. QEMU/OCI ARM64 evidence passed for package/runtime/functional scope only; QEMU
`7.2.0` is not ARM64 performance evidence. Physical mobile, actual screen-reader, and true-zoom
evidence remain unavailable.

The existing deterministic build/container receipt remains separate evidence: `26` files /
`703,175` bytes, staged `12` files / `608,713` bytes, an approximately `306,559`-byte wheel,
and amd64 image digest
`sha256:0d68e3d9a78d626a61a1a82c455ea1734ddaa753f562d74022b94986c477bb12` at
`170,062,564` bytes. These values do not replace the current gate's exact `306,553`-byte wheel
receipt.

The unsupported `TASK_ID=R-ASTRA-64` attempt exited `2` with no artifact. The first supported
M09 attempt failed in `test_backup_automation` because of a timing race; supplied `R-ASTRA-65`
repair history records removal of the irrelevant completion assertion and a passing final rerun.
The `R-ASTRA-65` Ponytail observation is historical findings-only: its CSP-regex suggestion is
rejected and nonblocking because production CSP parsing is a security boundary. The final
`R-ASTRA-69` `/ponytail-review` boundary is separately **CLEAN**, returning exactly
`Lean already. Ship.` at `2026-09-14T02:41:58Z`; see the [ASTRA report](../evidence/astra-final-report.md)
for the full reconciliation and limitations.

ARM64 checks must identify whether execution is native or QEMU/OCI-emulated. Emulation can
exercise package, runtime, functional, build, and tool behavior; it cannot prove native
resource performance. See the [MVP plan](../../MVP-PLAN.md) for current gate requirements.
