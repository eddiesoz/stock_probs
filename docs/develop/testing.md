---
title: "Testing"
description: "Local developer checks for Python, APIs, persistence, browser behavior, bounded builds, backups, providers, and architecture."
---

# Testing

## Local browser authentication fixtures

Use development fixture accounts and isolated browser contexts for local QA. Preserve the user's
signed-in tabs and authentication state. Never clear user cookies, browser storage, or profiles to
reset a test. Do not use production local-login flows or claim an MFA bypass; exercise authentication
through development fixtures and isolated contexts.

## Assistant access-failure checks

Native verification must retain the original turn deadline through diagnostic wrappers. Exact
`FreeTierError` responses map to the closed `free_tier_access_error` diagnostic class across the
proxy, runtime, API, and probe; never retain raw provider bodies. A classified rejection is not a
successful model answer. Test safe failure copy through terminal stream completion and saved-chat
reopening, with the saved context matching the submitted context and no automatic retry.

Initial recognized upstream 401, 403 and 429 failures must reach the native client as sanitized
no-store JSON with the original HTTP status before SSE headers. Recheck the active session after
prefetch, close the iterator, and never forward raw provider bodies or invent a retry reset time.
Keep unknown initial failures and failures after the first chunk interrupted; do not emit a clean
completion. A correctly reported 429 is failure handling, not proof that the provider can answer.

Verify that Zen display, validation, policy identity and outbound requests all use the fixed
reviewed chat route even when stored metadata contains a legacy or unrelated base URL. Both the
legacy `/zen/v1` route and `/inference/openai/v1` must preserve known-model exclusions; ambiguous
paths on the same host fail closed, while similarly named unrelated hosts are not globally banned.
Keep session revalidation and stream cancellation covered without a live provider request.

For an isolated worktree, set `PYTHONPATH` to its absolute `src` directory and set
`STOCK_PROBS_BROWSER_RUNTIME` to a task-owned disposable directory. A shared editable environment
can otherwise import another checkout. Bind actual served asset bytes as well as local staged
files; a matching local export alone does not identify the running package.

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

### Selecting a retained local image

Before replacing a local candidate at the three-image retention limit, use
`--expected-local-current-image-id sha256:<full-id> --select-local-current-image-id sha256:<full-id>`
with the bounded builder. The operation locks the ledger, compares the existing pointer against the
expected image, verifies both completed current-role rows and their build receipts, and verifies
Docker image IDs, revision labels, platform, and exact tags before atomically selecting the retained
replacement. It does not delete images, change ledger roles, increase the retention limit, or make
an old candidate automatically eligible for deletion. A stale pointer or failed validation leaves
the pointer unchanged. Record the command and result in a new private receipt. Subsequent exact-ID
cleanup still requires independent provenance, protection, tag, container-reference and bounded
RootFS review, followed by absence verification and the existing retirement acknowledgement.

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

A failed local build retains its exact in-flight ledger row and publishes bounded failure facts.
CLI process-group cancellation does not establish that a remote BuildKit `RUN` stopped. The
failure handler checks the setup-bound full container ID, start generation, configuration and
ownership before stopping only that builder; an uncertain stop or receipt write keeps recovery
held. Preserve the primary build error separately from cleanup errors.

The shared bounded-build deadline begins before `Popen`; pre-launch validation and dispatch time
consume that deadline for every caller. A source or selected-test pass does not establish image,
Docker-runtime, provider, or physical-mount acceptance. The R-ASTRA-121 F6SD-02 narrowed
timeout-finalization result and its earlier full-suite source-review failure are recorded separately
in the [MVP plan](../../MVP-PLAN.md#r-astra-121-f6sd-02-timeout-observer-finalization-follow-up-2026-10-18).

Use the typed `--reconcile-local-inflight-reservation` operation in
`scripts/bounded_docker_build.py` with the exact local tag, revision, context digest and current
role. Supply either the genuine local-failure receipt digest or all four separately hashed
terminal, worker-preflight, cancellation and settled observations. External observations must
remain private on the verified SD mount. External-observation mode rechecks current history.
Genuine-local-failure mode instead requires fresh proof of the same stopped builder generation,
PID zero and an absent or empty bounded descendant cgroup, so history inspection cannot restart
the builder before that proof. Both modes require fresh tag/full-ID absence, protected inventory
and ledger consistency. A complete private receipt is staged before ledger commit/verification
and exclusive publication; a publication error restores the ledger. Missing historical BuildKit
terminal evidence stays Unavailable, and observed historical negative facts are rejected.
Never use the PR-failure mode, edit the
ledger manually, or reconstruct a missing failure receipt. See [E33](../../MVP-PLAN.md#r-astra-121-e33-local-build-failure-and-reservation-recovery).

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

### R-ASTRA-120 E836 current evidence

The complete native-x86_64 canonical local check at clean pushed `0193fb93` passed: 3,255 Python
passes, four opt-in skips, four deselected, 85.70% coverage and 72 frontend checks. Terminal exit,
JUnit, all three ordered subchecks, 590 post-launch authored pins, 80 frontend inputs and 52
served/export pairs were reviewed. Independent exact-owned cleanup passed; full-host FD visibility
remains unavailable. The separate 68-case desktop/Pixel 7 emulation axe matrix passed with zero
violations/incompletes across 72 scans, without establishing physical-mobile or full WCAG acceptance.

The full 196-case browser aggregate failed (189 passed, four failed, three skipped). Two unchanged
real assistant cases subsequently passed under serialized load. A two-spec repair waits for forecast
render completion before opening news and for successful model/context responses before expiring
the session; all four selected desktop/mobile-emulated cases passed. No retry/deadline relaxation,
force-click or product change was made. Independent reuse review matched every authored input
except those two reviewed specs, all frontend inputs and all served files. The failed aggregate
remains preserved until a fresh complete browser run passes. A newly labelled exact-head image and
actual-host/rollback/runtime/guide/owner-canary release gates are still required. See
[E836](../../MVP-PLAN.md#r-astra-120-e836-canonical-browser-and-build-recovery-checkpoint) for exact
receipts, the interrupted build/recovered artifact distinction and earlier setup failures.

## Unix-socket test fixtures

Supervisor tests create AF_UNIX sockets. Use a unique, caller-owned short temporary root for
their pytest base directory; evidence-directory names must not determine socket paths. Check
the complete encoded socket-path length before binding. Linux limits pathname sockets to the
length of `sockaddr_un.sun_path`, including its terminator. Preserve a path-length setup failure
separately from product assertions, and rerun only after correcting that fixture boundary.
For live supervisor cases, verify the serving thread exits and its control socket is unlinked;
remove only that run's owned temporary directory after all children have exited.

Before a full suite, preflight the paths that the actual runner will create; a short manually
selected diagnostic path does not establish that the full runner's temporary root is safe. If a
canonical run fails or is interrupted on socket setup, retain that aggregate and any inconsistent
terminal/JUnit counts as a failure requiring reconciliation. A focused short-path pass can confirm
the fixture boundary for its selection, but it cannot replace a fresh complete canonical run.

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

The later F6 fixture-readiness watchdog sets the fixture startup budget to 30 seconds to match the unchanged Playwright `webServer` timeout. Each readiness fetch uses an abort timeout of `max(1, min(1000, remaining_ms))` milliseconds; retry sleep is capped by remaining time. The 9/9 lifecycle suite uses a fake clock, child process, and fetch; it does not verify real app/browser startup. See the [F6 checkpoint](../../MVP-PLAN.md#r-astra-121-f6-deployment-access-and-startup-diagnostic-checkpoint-2026-10-18).

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
image from the exact clean, reviewed head of open PR #9. Use only these mode flags:

```bash
python3 scripts/rehearse_schema13.py \
  --build-pr-candidate \
  --reviewed-pr-head "$REVIEWED_PR_HEAD" \
  --receipt "$PRIVATE_RECEIPT"
```

Set `REVIEWED_PR_HEAD` to the exact lowercase 40-character PR head SHA and `PRIVATE_RECEIPT` to a
private output path. The helper checks that local `HEAD` is that SHA and the worktree is clean,
validates the fixed PR-9/head/base relationship, rechecks the head around the build, and writes a
mode-0600 JSON receipt. The build is local `linux/amd64`, is not published, and requires at least
4 GiB free on every checked build filesystem; it aborts if free space drops below 1 GiB. E678's original independent process-ownership review **Failed** and remains historical. E683
recorded builder checks, and E684 independently passed source/test QA (59/59, exit 0; 149 inputs
unchanged). No actual Docker build or PR-bound rollback rehearsal ran; those acceptance gates remain
open. Do not treat source presence or test passes as build or rollback acceptance.

The later prebuilt-image rehearsal remains separate: it binds an immutable image ID and filtered
context digest to the same reviewed PR head SHA. The optional `prebuilt-release` publisher mode
checks and publishes that exact completed pair, preserving its original rehearsal receipt and
requiring a clean revision that matches exact `origin/main`. Publication is separate from QA;
it does not satisfy the actual-host, rollback, canary, or rollout gates.
The shared archive scanner must reject altered pinned source, extra token-like bytes, alternate
paths and word-adjacent tokens. Each provenance-verified exception is restricted to its exact
digest, size, path and match spans; exercise both candidate and recovery archives. The fixed
compiled harness is custom-source-pinned; its exempt spans are verified against the pinned public
Bun binary, not an official unmodified OpenCode binary. No whole-file waiver is permitted.


### Exact PR-pair review pins

The fixed local review-pin command accepts only an explicit write request:

```bash
python3 scripts/pin_pr_rehearsal_review.py --write
```

Before writing, the helper reads the current commit, requires the exact clean PR-9 source, checks
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


## Genuine free Zen restoration checks

Compare the same official OpenCode binary, free model and prompt with its ordinary native tools
and the application restrictions before attributing rejection to provider availability. R-ASTRA-121
observed an ordinary built-in free answer, rejection with read/shell registrations removed, and
success when genuine read/shell registrations were retained. This isolates the registration
boundary for the tested model; it does not promise all free models or continuous availability.

Verify the managed read/shell guards against actual compiled native tool calls with permission
already allowed. Force calls only after the provider request declares the target tool; title requests
can contain no tools and are not execution evidence. Check file-content leakage, shell side effects,
and comment-only commands. Synthetic provider responses prove guard behavior, not Zen acceptance.
Then test a real free answer through the application provider route and owner-scoped MCP.
Record whether the fixture overrides readiness, and preserve exact pre-run bindings. A scratch
binary owned by the developer fails the production receipt validator by design. Verify the normal
installed root-owned artifact path in the current image before release. Keep native isolation,
search/fetch, kill/restart, canonical, security, actual-host 1 GB and PR-bound recovery/rollback
checks separate and mandatory. Reuse unchanged UI evidence only at its existing bindings.


For the R-ASTRA-121 rebuilt native executable, refresh the scanner's exact file digest only after
comparing every existing public match span against checksum-verified official Bun 1.4.2 bytes.
Keep the path, size, offsets and all other bytes subject to their existing checks. A file-only scan
or provenance comparison does not replace scans of the final candidate and recovery archives.


### Local build phase observations

The local image build now requests Buildx raw JSON progress only for its opt-in observer. A
bounded background reader discards raw logs and records coarse allowlisted build phases,
completion/cache/error flags and elapsed durations in a genuine failure receipt. Unknown vertex
names are counted without saving their text; later recognized phases remain available as a
partial observation. Frame, byte, vertex and artifact limits stop parsing while the reader keeps
draining. Reader failure, closure or publication does not replace the primary build result.
The original 900-second deadline, disk/mount checks, cancellation and separate ARM Compose path
remain unchanged.
Unit tests do not establish the next actual build's phase or cause.

### Candidate and recovery production baselines

The candidate rehearsal checker distinguishes the running 5ad schema-13 app from the da2764/d3
schema-12 migration fixture. Its recovery alternative requires the exact registered recovery role,
image/archive, pair/overlay/migration, Compose snapshot, schema and disabled-ready projection at
both host and MCP boundaries, with the running container and loopback binding checked again
during monitoring. Negative fixtures must reject partial, mismatched, enabled and stale identities;
the 512 MiB startup and 128 MiB running reserve remain mandatory. A synthetic checker test does
not accept an image transition. Test the exact recovery image on disposable data and a user-defined
bridge, retain post-migration records, and verify a fresh signed backup before an actual-host step.
The current resource failure and backup scope are recorded in [E19](../../MVP-PLAN.md#r-astra-121-e19-installed-rollout-repair-and-signed-schema-13-backup).

For the current R-ASTRA-121 helper, the startup operation budget begins before its bounded settle.
On Linux/glibc, it collects completed Python allocations and calls process-local `malloc_trim(0)`,
then samples host availability at 250 ms intervals for up to 30 seconds before the existing
production/readiness guard records the final startup value. Unsupported allocator environments fail
closed. This is fixed checker behavior, not an environment setting. The 512/128 MiB reserve floors
and 1,080-second absolute budget do not change. E22's five-second observation is historical; the
current bounded wait repair is E29. Independent source/unit/static QA passed 278 tests with one
opt-in local-Docker test deselected, plus Ruff, Ruff security, format and diff checks at pinned
source hashes; builder-selected 24 tests also passed with 255 deselected. Parent source review
passed with no findings. The original preflight **Fail** at 517,480 KiB against the 524,288 KiB
startup floor remains unchanged. T9 separately failed at 519,432 KiB; its twelve later above-floor
observations do not change that result. Those E29 checks did not establish a post-repair host retry,
native answer, fresh image or actual 1 GB acceptance. See [E22](../../MVP-PLAN.md#r-astra-121-e22-startup-reserve-preflight-repair-checkpoint)
and [E29](../../MVP-PLAN.md#r-astra-121-e29-bounded-startup-wait-checker-checkpoint).

The later T13 trial still failed its startup reserve before the SDK or model ran. The subsequent
lazy-provider repair has independent focused checks for fresh-process startup without Yahoo,
pandas, NumPy or curl imports, guarded fixture requests, on-demand synthetic provider calls,
dependency failures, safe API errors and the actual headline client's busy/unavailable branches.
The approved frontend build and stage passed in a source-bound checkout. These checks do not
replace current-image native, actual-host resource, recovery, canonical or release acceptance.
See [E32](../../MVP-PLAN.md#r-astra-121-e32-lazy-provider-startup-and-host-reserve-checkpoint).

The third production-baseline source shape is specifically `temporary_recovery`, not a release or
the retained A9 recovery role. It requires the separately approved fixed 6359 manifest, matching
operation/current records, exact Docker image/tag/platform/revision and loopback identity, ready
assistant-disabled state, and the completed 512 MiB startup-floor phase. Monitoring compares the
whole accepted identity again. The independent 332-test and 52-case selected passes cover mocked
consumer/source behavior only; the image, dynamic approval and host transition remain unbound.
The later local cancellation/reconciliation repair passed 238 tests under explicit child umask
022; its actual typed reservation recovery is recorded at
[E34](../../MVP-PLAN.md#r-astra-121-e34-6359-build-failure-and-stopped-generation-recovery).

The later local build on pushed PR #9 head `63b9da6dd27cbbed1cb973cb5d5442753e285b4f`
**Failed** with Docker `OOMKilled=true`; all 149 application inputs stayed bound and no image was
accepted. The bounded resource sampler ended before the container exit, and no PID-to-strict-cgroup
binding was available, so worker limits and the specific OOM cause remain **Unavailable** and
**Unproven**. Typed reservation reconciliation separately **Passed**, retaining two ledger rows.
This is recovery evidence, not a build or actual 1 GB resource pass. See the [63b9 build and
recovery checkpoint](../../MVP-PLAN.md#r-astra-121-local-63b9-oom-build-and-recovery-checkpoint-2026-10-15)
for exact receipts and limitations.

A subsequent local Dockerfile diagnostic reduced the package-install parallelism argument from 2
to 1. Builder and independent selected scopes each passed 23 tests; the independent review also
matched 49 pins and passed Ruff, security, format and diff checks. This tests a memory-reduction
hypothesis only: the prior OOM's install-versus-compile phase remains unproven, and no image build
or native run has started. The initial temporary-path quota/policy setup failure and the initial
independent umask omission remain preserved separately. See the [serial-install checkpoint](../../MVP-PLAN.md#r-astra-121-63b9-serial-install-diagnostic-checkpoint-2026-10-15).

The resulting 12ed build subsequently failed with a cgroup OOM transition during native
compilation. A continuous 78-row sampler and independently bound live worker establish the local
1280 MiB RAM/768 MiB swap/one CPU/128 PID limits; the high-RSS argument category does not prove
the executable or killed PID. Typed reservation reconciliation passed separately. Keep this failed
build separate from native functional and actual production 1 GB acceptance, and obtain new
discriminating evidence before another build. See the [12ed compilation checkpoint](../../MVP-PLAN.md#r-astra-121-12ed-native-compilation-oom-checkpoint-2026-10-15).

The next native-build candidate fixes Bun's `--smol` mode only for the final build-script command
and its child processes. Check that a host-supplied `BUN_OPTIONS` cannot alter that command's
environment and that package installation/source tests retain their prior environment. The pinned
Bun documentation describes a garbage-collection tradeoff rather than a hard memory cap. The
embedded app build and final compiler still use the same source pins, arguments, targets and
deadlines; a source test pass does not establish lower memory use or a successful image.

Build-controller unit cases that isolate command or backend-stop failures supply a synthetic
`check_space` result alongside their mocked build operations. This avoids depending on the
operator filesystem before reaching the intended assertion. Separate boundary tests exercise
real admission/stop logic with controlled disk inputs; the actual builder still enforces its
4 GiB admission and 1 GiB stop thresholds. See the [F6 canonical disk-seam checkpoint](../../MVP-PLAN.md#r-astra-121-f6-canonical-disk-seam-checkpoint-2026-10-17)
for the preserved aggregate failure and narrow fixture repair.

### F6 9a91 image-build retry checkpoint (2026-10-18)

The first PR #9 build failed during base-image metadata; embedded resolver SERVFAIL was observed,
but the cause remains **Unproven**. A scoped refresh of the exact owned builder resolver and two
public registry lookups passed, permitting one retry. That retry then **Failed** with the bounded
900-second build timeout; its phase observer reached `native_builder_run` but ended **Unavailable**
at the line-byte limit. No image was accepted. The original backend-stop observation remains
**Unverified**; a later exact-generation stop check passed with the worker cgroup absent. The
reservation remains retained pending reviewed typed recovery. Preserve both build failures and
do not infer a native build/runtime cause from the partial phase record. See the
[F6 9a91 build checkpoint](../../MVP-PLAN.md#r-astra-121-f6-9a91-dns-retry-and-bounded-build-timeout-checkpoint-2026-10-18)
for receipts and exact status.

The F6 timeout-reconciliation follow-up independently passed 13 focused cases on repaired source,
including explicit-null versus omitted receipt fields, exact tuple rejection, fresh-stop failure,
and the legacy control. Preserve the earlier candidate's static-review failure and its separate
20-case pass. The actual typed operation and its independent artifact audit passed only their
reservation-release scope. A subsequent exact build-history read showed the native binary,
frontend and Python-package steps completed before the overall assembly deadline; no completed
image or native assistant result follows. See the
[F6 recovery and history checkpoint](../../MVP-PLAN.md#r-astra-121-f6-typed-timeout-recovery-and-build-history-checkpoint-2026-10-18).

### Print media synchronization

The M04 responsive/accessibility journey waits at most five seconds for each emulated print
surface to compute black text on white before recording Light/Dark samples. It retains the
original theme-parity and white-background assertions and its existing 90-second test budget.
This makes the browser state transition explicit; it is not a product CSS change or a confirmed
root cause for the earlier aggregate-only print mismatch. The original single-case reproduction
passed unchanged, while that earlier complete browser aggregate remains failed.
