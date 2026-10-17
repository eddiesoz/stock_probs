---
title: "Local configuration"
description: "Supported Stock Probability environment variables for local runtime settings, production invitation email, storage, providers, timeouts, and fixtures."
---

# Local configuration

The application reads a small environment-only configuration. Keep machine-local values out
of tracked files and shell history when they could expose private locations.

| Variable | Default | Constraint and effect |
| --- | --- | --- |
| `STOCK_PROBS_DATA_DIR` | `data` | Runtime root. The server places `stock_probs.sqlite3`, `backups/`, and `.backup-auth.key` beneath it and hardens sensitive paths. |
| `STOCK_PROBS_PROVIDER` | `yahoo` | Either `yahoo` for live provider requests or `fixture` for packaged deterministic data. |
| `STOCK_PROBS_PROVIDER_TIMEOUT` | `8` | Finite provider timeout from 1 through 20 seconds. News applies an absolute end-to-end deadline of `min(this value, 10 seconds)`. |
| `STOCK_PROBS_BACKUP_INTERVAL_SECONDS` | `86400` | Due-backup interval checked at `serve` startup; finite seconds from 60 through 2678400. |
| `STOCK_PROBS_HOST` | `127.0.0.1` | Environment values are restricted to `127.0.0.1`, `localhost`, or `::1`. |
| `STOCK_PROBS_PORT` | `8000` | Integer from 1 through 65535. |
| `STOCK_PROBS_FIXTURE_NOW` | unset | Timezone-aware ISO-8601 clock used with fixture-driven runs. |

## Ledger assistant candidate settings

These source settings belong to the R-ASTRA-120 candidate. They do not enable the production
assistant, which remains disabled on schema 12 while the required acceptance gates are open.
Do not enable rollout based on configuration presence.

The managed worker source fixes `BUN_OPTIONS` to `--smol` and discards any caller-supplied
value. This candidate asks Bun to collect garbage more frequently; it can reduce heap growth
at the cost of latency. It is not an operator setting, a memory cap, or a verified resource
improvement. The local image containing this setting completed search and fetch, but its
two-user native run failed final-answer acceptance. A lower sampled peak does not establish a
causal improvement or the combined 1 GB resource gate. The US$15 monthly Linode cap includes
tax and existing backups; the 1 GB plan and backups remain in place.

The candidate native image builder separately fixes `BUN_OPTIONS=--smol` for the pinned Bun
compilation command and its embedded app/Vite children. The strict build environment ignores the
host's `BUN_OPTIONS`; dependency installation and selected source tests keep their existing build
environment. This is fixed build behavior rather than a configurable application setting. It does
not change the installed runtime flags, container limits or build deadlines, and needs a fresh
image build before any reduction in build memory can be claimed.

The current source also uses the native V2 build-agent system prompt to request concise final
answers by default, preserving necessary caveats, citations, retrieval dates and user-requested
detail. This is fixed product guidance, not an output-token override. Its latency effect remains
unverified until a refreshed image passes the same native workload. The
[V2 agent system documentation](https://opencode.ai/v2/docs/agents#system) describes the
supported prompt field; configuration alone is not runtime acceptance.

The maintained application catalog also defines
`runtime_policy.native_output_token_budget`, currently 4096. Native model aliases receive a
protocol-specific output body limit, and the provider gateway rejects requested limits above
the catalog budget. Compatible chat, Responses, and Gemini requests default an omitted output
limit to this value; Anthropic retains its required `max_tokens` field. This is an output ceiling,
not a guarantee of answer length, latency, or provider acceptance. Loading is deferred until
assistant use, and a missing or malformed policy fails closed. The pinned harness must still
verify the body override through an actual native request before this can satisfy a release gate.

| Variable | Default | Constraint and effect |
| --- | --- | --- |
| `STOCK_PROBS_ASSISTANT_ENABLED` | `0` | Boolean switch for candidate assistant service registration. Production Compose defaults it to false. |
| `STOCK_PROBS_ASSISTANT_ROLLOUT` | `disabled` | One of `disabled`, `owner_canary`, or `invited`; production default is `disabled`. |
| `STOCK_PROBS_ASSISTANT_CANARY_GITHUB_IDS` | empty | Comma-separated positive numeric GitHub account IDs for an owner-canary rollout. Empty by default. |

The candidate's `disabled` transition persists its marker and invokes the fixed in-place
assistant-kill client. Owner-canary and invited-user transitions recreate the application
service. Configuration presence cannot verify the kill control, worker readiness, security
profile, or recovery behavior. Keep rollout disabled until the exact-image runtime, resource,
recovery, and deployment gates pass. The authoritative
[R-ASTRA-120 evidence ledger](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on)
records individual failures, repairs, and current acceptance limits.

The illustrated assistant help guide is generated from revision-bound browser QA artifacts, not
from environment variables. Its renderer requires explicit `--capture-root`, `--manifest`, and
`--revision` arguments; the manifest binds eight synthetic screenshot hashes and an independent QA
receipt to the same reviewed application revision. Capture correctness, HTML accessibility,
PDF visual review, and final PR-bound acceptance are separate checks. See the evidence ledger
for their current results and [getting started](../operations/getting-started.md#ledger-assistant-help-guide-capture-pipeline)
for the controlled capture/render workflow. A dirty working revision or an old preview is not a
substitute for current reviewed captures.

## Local PR-rehearsal review metadata

The R-ASTRA-120 deployment MCP can load two nonsensitive review pins from the operator-local
`$XDG_CONFIG_HOME/signal-ledger/rehearsal-review.json` file (default base: `~/.config`). Keep
`XDG_CONFIG_HOME` absolute and outside the repository so the metadata remains private and
untracked. The file is mode `0600`, owned by the current operator, and has the fixed schema
`format_version`, `reviewed_pr_head_sha`, and `reviewed_pair_manifest_sha256`; it stores only a
commit SHA and a pair-manifest digest, never credentials.

The compatibility environment pair is `SIGNAL_LEDGER_REHEARSAL_REVIEWED_PR_HEAD_SHA` plus
`SIGNAL_LEDGER_REHEARSAL_REVIEWED_PAIR_MANIFEST_SHA256`. They must be set together and match the
file when both sources exist. A partial, malformed, unsafe, or disagreeing value fails closed. The
explicit `python3 scripts/pin_pr_rehearsal_review.py --write` command verifies the current clean
PR-1 source and exact candidate/recovery pair before writing; it was not run in E741, so no review
metadata write is evidenced. E762 and E766 later passed selected source and receipt-integrity
reviews only; neither executed the CLI, changed the private metadata, or invoked runtime tools. The
current `.codex/config.toml` names eight MCP operations in text, but the file alone does not establish live Codex tool discovery. E767 later passed fresh-task
discovery of all eight configured tools/schemas and one read-only `status` call; no mutating
operation was invoked. Future configuration changes require another fresh Codex task. See the
[developer testing guide](../develop/testing.md#exact-pr-pair-review-pins) for the command contract
and [getting started](../operations/getting-started.md#review-a-pr-pair-before-rehearsal) for the
operator sequence.

The PR #9 reserve checker uses a fixed, read-only startup observation of at most 30 seconds before
the existing final memory and readiness checks; there is no environment variable to configure this
wait. It preserves the 512 MiB startup and 128 MiB running floors and the 1,080-second absolute
operation budget. E22's five-second wait is historical. E29's local source/test and parent reviews
do not establish a host retry, deployed checker, native answer, or actual 1 GB acceptance.

## Authentication settings

Authentication is disabled by default for the local development path. Production requires GitHub
authentication and fails startup unless the HTTPS origin, unique session secret, secure host-only
cookies, owner account, and GitHub OAuth settings are valid. Keep credentials outside tracked
files and command arguments.

| Variable | Default | Constraint and effect |
| --- | --- | --- |
| `STOCK_PROBS_ENV` | `development` | One of `development`, `test`, or `production`. |
| `STOCK_PROBS_AUTH_MODE` | `disabled` | One of `disabled`, `local`, or `github`; production requires `github`. |
| `STOCK_PROBS_AUTH_SESSION_SECRET` | Development-only value | When authentication is enabled, use at least 32 bytes. Production rejects the development default. |
| `STOCK_PROBS_AUTH_SESSION_IDLE_SECONDS` | `1800` | Idle expiry must be at least 300 seconds and no greater than the maximum session expiry. |
| `STOCK_PROBS_AUTH_SESSION_MAX_SECONDS` | `86400` | Absolute expiry must be at least the idle expiry and no greater than 2678400 seconds. |
| `STOCK_PROBS_AUTH_INVITATION_TTL_SECONDS` | `86400` | Invitation lifetime from 60 through 604800 seconds. |
| `STOCK_PROBS_PUBLIC_ORIGIN` | unset | Required when authentication is enabled; production requires the exact public HTTPS origin. Local mode derives a loopback origin when omitted. |
| `STOCK_PROBS_AUTH_COOKIE_SECURE` | `0` outside production; `1` in production | Production requires secure cookies. |
| `STOCK_PROBS_AUTH_COOKIE_DOMAIN` | unset | Production cookies must remain host-only; do not set a parent domain. |
| `STOCK_PROBS_GITHUB_CLIENT_ID` | unset | Required with `github` mode. |
| `STOCK_PROBS_GITHUB_CLIENT_SECRET` | unset | Secret; required with `github` mode. |
| `STOCK_PROBS_GITHUB_REDIRECT_URI` | unset | Required with `github` mode and must match the registered callback. |
| `STOCK_PROBS_OWNER_GITHUB_ID` | unset | Positive numeric GitHub account ID; required in production. |
| `STOCK_PROBS_TRUSTED_PROXY_HOSTS` | `127.0.0.1,::1,localhost` | Comma-separated proxy addresses trusted for forwarded request metadata. |
| `STOCK_PROBS_BOOTSTRAP_USERNAME` / `STOCK_PROBS_BOOTSTRAP_PASSWORD` | unset | Optional development local-account credentials; forbidden in production. |
| `STOCK_PROBS_BOOTSTRAP_MEMBER_USERNAME` / `STOCK_PROBS_BOOTSTRAP_MEMBER_PASSWORD` | unset | Optional development member credentials; forbidden in production. |

Invitation expiry defaults to one day. The supported range is 60 seconds through seven days;
`STOCK_PROBS_AUTH_INVITATION_TTL_SECONDS` changes that lifetime.

`R-ASTRA-111` deploys GitHub OAuth admission limits: at most 8 starts per effective
caller and 64 total starts per application process in a rolling minute, plus at most 8 outstanding
transactions per caller and 128 total. Per-minute counters are process-local; outstanding
transaction counts are stored with OAuth state. Callers sharing an effective source IP, such as
behind a shared NAT, share the caller limit. The source uses the socket peer address and accepts
`CF-Connecting-IP` only when that peer matches `STOCK_PROBS_TRUSTED_PROXY_HOSTS`; it does not use
other forwarded-IP headers. The source change adds explicit production Compose ingress
attribution, installed through the existing reviewed host-Compose updater. The current deployment
is R-ASTRA-111 at schema 11; its migration cleared in-progress OAuth transactions, so any sign-in
already underway must restart. SMTP variables were absent at the R-ASTRA-111 deployment checkpoint.
R-ASTRA-112 later configured and enabled production invitations with the fixed Resend settings
below; its owner-bound test email was delivered to Gmail but landed in Spam. See the
[R-ASTRA-111 and R-ASTRA-112 evidence](../../MVP-PLAN.md).

Use the supported CLI to run the app: it disables Uvicorn proxy-header rewriting so the
application can inspect the socket peer before applying the trusted-proxy rule. If launching
Uvicorn directly, pass `--no-proxy-headers`; forwarded-header rewriting can replace the peer address
used for caller admission.

## Production invitation email

The production Compose service accepts optional SMTP settings for administrator-sent email
invitations. Leave all six variables unset or empty to keep email disabled; the administrator can
still create a single-use invitation code and share it privately. Set all six together to enable
mail. A partial or invalid configuration fails closed during application startup. See the
[invitation email and host Compose update](../operations/getting-started.md#invitation-email-and-host-compose-update)
section for identity, TLS, and delivery behavior.

| Variable | Constraint |
| --- | --- |
| `STOCK_PROBS_INVITE_SMTP_HOST` | Hostname or IP literal; do not include a URL scheme or path. |
| `STOCK_PROBS_INVITE_SMTP_PORT` | `465` or `2465` with `implicit_tls`, or `587` with `starttls`. |
| `STOCK_PROBS_INVITE_SMTP_USERNAME` | Required non-empty ASCII value, at most 320 characters. |
| `STOCK_PROBS_INVITE_SMTP_PASSWORD` | Required non-empty ASCII value, at most 2048 characters; treat as a secret. |
| `STOCK_PROBS_INVITE_SMTP_SECURITY` | `implicit_tls` with port `465` or `2465`, or `starttls` with port `587`. |
| `STOCK_PROBS_INVITE_EMAIL_FROM` | Valid ASCII sender mailbox address. |

The reviewed Resend sending-domain setup uses `mail.jtmb.cc`, with the fixed production values
`smtp.resend.com`, port `2465`, username `resend`, `implicit_tls`, and the sender mailbox
`invites@mail.jtmb.cc`. Three DNS-only records for that domain are managed in Cloudflare
Terraform. The domain was reported verified through a Resend free account created with Google SSO
at approximately `2026-10-01T14:04Z`; public DNS resolution and the post-apply no-change plan were
also reported. These checks establish domain and DNS preparation only.

Supply credentials through the operator-controlled production environment outside the repository.
Do not put SMTP values in tracked files, command arguments, logs, or documentation. The client
validates the SMTP server certificate and uses a 10-second socket timeout for each socket
operation; this is not a total deadline for the entire submission.

The pending operator workflow accepts one private, one-line Resend API-key file through the fixed
`infra/linode/install-resend-smtp-key.sh --api-key-file FILE` entry point. It is intended to set the
fixed Resend SMTP values, recreate the fixed production Compose app without building or pulling a
new image, and require readiness. The installer QA was observed against local revision
`42cf0f40c98404d55585745b10311354661a5195`; that installer is included in pushed `main` checkpoint
`329fdc595483fa3b112b98c7788d808348638faa`, reported as matching `origin/main` with a clean tree
at that checkpoint.
Initial independent QA found a P1 remote-shell quoting blocker and a P2 incomplete-read rollback
blocker; the repaired QA recheck passed `13` tests, including command parse/probe and incomplete-read
rollback, for its declared local scope. At checkpoint `329fdc595483fa3b112b98c7788d808348638faa`,
the report said it matched `origin/main`, the tree was clean, and no API key existed at that time.
A later operator observation reported `email_invites_enabled=false` in production; its timestamp was
not supplied. This was point-in-time evidence; a later read-only SSH recheck timed out before any
value was returned, so the setting remained unavailable at that checkpoint. Local QA reported 25
fake-SMTP cases plus invitation-expiry coverage; those did not establish host installation or live
sending.

`R-ASTRA-112` later installed a user-authorized sending-only Resend key using the fixed installer.
Production email invitations are now enabled with `smtp.resend.com`, port `2465`, `implicit_tls`,
username `resend`, and sender `invites@mail.jtmb.cc`; the secret remains outside the repository.
An operator-created owner-bound test invitation was delivered to Gmail, where SPF/DKIM passed but
the message landed in Spam; inbox placement was not achieved for this test. This confirms delivery,
not an authenticated browser/API email-submission flow. See the [R-ASTRA-112 evidence](../../MVP-PLAN.md).

For a reproducible local dashboard:

```bash
STOCK_PROBS_DATA_DIR=/tmp/stock-probs-doc-example \
STOCK_PROBS_PROVIDER=fixture \
STOCK_PROBS_FIXTURE_NOW=2025-01-10T17:03:00+00:00 \
  .dev-venv/bin/python -m stock_probs.cli serve
```

The CLI's `--host` and `--port` override listener values for that invocation. A non-loopback
CLI host is unsupported and requires the explicit `--allow-non-loopback` acknowledgement;
prefer the loopback default. Provider credentials are not part of this application's tracked
configuration.

News safety and cache bounds are fixed rather than additional settings: request limits are 1
through 10 (default 5), one retrieval may run at a time, and the raw provider body is capped at
256 KiB. The in-memory cache keeps at most 32 symbols, 32 KiB per entry, and 1 MiB total. A
non-empty entry is fresh for five minutes and stale-eligible for at most 30 minutes; an empty
entry lasts 60 seconds, and a failed provider attempt is suppressed for 30 seconds. The absolute
deadline covers receipt and parsing, uses the configured timeout when it is below 10 seconds,
and is never extended by an automatic provider retry. The browser also stops waiting after a
fixed 10 seconds; a user may explicitly retry a failed request. Neither bound is separately
configurable.

Every CLI command may initialize persistence and apply pending migrations: `migrate`, `serve`,
`backup`, `restore`, `backup-key rotate`, and `backup-key retire`. The repaired protection creates
and verifies a pre-migration backup before any of those paths upgrades an existing older schema;
fresh and current databases need none.

After migration, `serve` authenticates every managed artifact before newest selection for its due
check. A corrupt or wrong-key artifact blocks the check and startup. The newest artifact is then
verified with `require_active_schema=false`, so a recent pre-migration artifact can suppress a
current-schema due backup. Creation is rejected at 32 existing artifacts or when the candidate
would make total managed storage exceed 256 MiB; exactly 256 MiB is allowed. These limits do not
expire active query history. See [backup and restore](../operations/backup-restore.md) for the
trust-key lifecycle, restore behavior, and exact managed-name constraint.

Continue with [getting started](../operations/getting-started.md).


## Free Zen native tool registration repair

R-ASTRA-121 preserves genuine OpenCode V2 read and shell SDK registrations for reviewed Zen
models while prohibiting their execution in Signal Ledger. The supervisor fixes
`STOCK_PROBS_MANAGED_ASSISTANT=1` in the worker environment. Checksum-pinned native guards
abort before filesystem access, shell parsing, or execution, including saved permission grants.
The verified managed build must bind both original and patched read/shell source digests.
The location and session rules change read/shell to `ask` only for Zen with verified guards;
`execute`, edits, subagents and unrelated permissions remain denied. The application separately
rejects unsupported permission events. This variable is fixed internal policy, not an operator
option for enabling shell access.

The provider route accepts the pinned SDK declarations only for an authorized Zen turn with
verified native transport/guards. It preserves their actual descriptions and schemas. Missing,
modified or unverified declarations fail closed. The current repair is a candidate: local real-Zen
answers do not establish production rollout, installed-image readiness, or actual 1 GB acceptance.
The existing host, backups and US$15 monthly cap remain fixed.


The current fixed restoration rehearsal target is PR #9. The operator cannot supply another PR
number through MCP. Bootstrap, local verification and the installed helper must agree on that
identity and the exact clean candidate head/pair. Earlier PR #2 receipts remain historical. A helper
commit on PR #9 requires a new exact-head image label and pair, even if application context bytes
are unchanged; never relabel the earlier image or claim unchanged helper/runtime acceptance.


### Rehearsal baseline identity

The candidate source also recognizes a separately approved `temporary_recovery` baseline. It is
fixed to the reviewed 6359 source/overlay and schema 13, and requires bounded root-owned approval,
manifest, operation and current-state records to match the actual image/container and ready
assistant-disabled projection. Only the completed startup-floor phase admits a rehearsal; the
512 MiB startup and 128 MiB running floors remain unchanged. This is neither a configuration
shortcut nor a retained-release identity. Current source/mock passes do not show that the running
MCP process loaded this consumer or that a temporary image was built, approved or started.

The candidate rehearsal checker uses a separate fixed running-production identity; the schema-12
PR-pair fixture remains unchanged. The registered schema-13 recovery alternative is an exact
source allowlist with a disabled-ready requirement, not a configurable arbitrary image, archive
or database. It does not lower the startup/running memory floors or replace the reviewed PR's
candidate/recovery pair. Source presence does not prove host installation or production acceptance;
see [E19](../../MVP-PLAN.md#r-astra-121-e19-installed-rollout-repair-and-signed-schema-13-backup).

### Same-schema hotfix contract

The separate R-ASTRA-121 operational-helper PR #11 candidate adds a format-2
`schema13_same_schema_hotfix_v1` contract. It binds helper source PR #11, application candidate PR
#9, and the original 5ad schema-13 production artifact as the recovery identity; it keeps schema 13
on both sides and declares no migrations, restore, or recovery overlay. The installed PR #10 helper
and historical PR #2 format-1 schema-12-to-13 pair remain separate. The format-2 recovery check
expects the normal shipped supervisor/image with its assistant worker disabled and no OpenCode
process, not removal of an executable or package. The current helper's independent selected
source/test review passed 162 tests with one opt-in Docker test skipped and 266 stable bindings;
its installed production metadata remains unavailable on the local host. The local recovery profile
diagnostic against the original 5ad image failed on observed supervisor and app command shapes. A
focused repair passed 33 synthetic tests. The follow-up independent process-profile QA passed
360 tests with one direct-Docker test deselected, and a local original-image diagnostic passed. The
bounded diagnostic receipt then passed independent offline review in E22; the reviewer did not rerun
tests or start a container, and effective CPU/PID/swap/tmpfs limits were not all inspected. A
format-2 package and manifest were prepared for helper head
`ae1d0a2d9d5e891436732e6655e360b93ecce817`. The later enabled-native phase changes three
helper-source files, so that manifest does not bind the current source. Builder and independent
copied-source checks each passed 373 selected tests with one Docker integration test deselected;
neither ran Docker or exercised the new native-phase orchestration. The candidate archive has not
passed the required contents scan or pair publication, and the new source needs its own bound
package. Host pair, actual 1 GB, installation, rollback, and production acceptance remain open. See
the [E21 contract and status](../../MVP-PLAN.md#r-astra-121-e21-format-2-hotfix-and-production-reader-checkpoint),
[E22 review](../../MVP-PLAN.md#r-astra-121-e22-independent-review-of-the-local-5ad-profile-diagnostic),
and [E23 current checkpoint](../../MVP-PLAN.md#r-astra-121-e23-enabled-native-phase-source-qa-and-package-identity).
Applied-state persistence and helper-revision substitution passed their selected synthetic review;
neither establishes installation or production acceptance.

E24 records the published native phase and the first actual-host call. The call failed before
candidate actions at the 512 MiB startup reserve check (367,872 KiB available); SDK transport success
is not rehearsal acceptance. Independent source-path review found the guard returned before candidate
native/recovery operations, but did not independently verify container/asset cleanup. Production
remained on the original ready 5ad schema-13 image with assistant enabled, invited rollout and
loopback-only access. The inspect receipt's creation time is not its tool invocation time. The actual
combined 1 GB gate and release acceptance remain open. See
[E24](../../MVP-PLAN.md#r-astra-121-e24-host-reserve-preflight).

E25 describes a separate maintenance-helper candidate scoped to disabling the assistant on the
existing 5ad schema-13 release. It uses the same image and Compose definition with
`--no-build --force-recreate --pull never`, preserving the exact existing volume, schema, and
loopback binding. The
candidate records runtime/configuration and original rollout mode and compensates failures without
claiming a restore that was not observed. Re-enable only through disabled/ready, owner canary, then
invited rollout. Its bootstrap now pins five fixed assets, including
`scripts/production-deploy-helper.py`; older four-asset wording is historical. This is source and
builder-test evidence only: the independent selected suite passed, but its requested
rollback-failure coverage check found one missing assertion at
`scripts/pr_rehearsal_bootstrap.py:503` (`install_rollback_unverified`). This is a test-coverage gap,
not a source-defect finding; no install, host call, production change, or release is established. See
[E25](../../MVP-PLAN.md#r-astra-121-e25-maintenance-only-assistant-disable-and-failure-edge-checkpoint).

E26 adds a test-only assertion for helper-install rollback failure. Its builder two-module suite
passed 463 tests with one skip; independent QA passed the two changed cases and scoped pins/static
checks, while the full suite was not independently rerun for that new test pin. E25's original
coverage-gap result is preserved. Source security review and operational acceptance remain open.
See [E26](../../MVP-PLAN.md#r-astra-121-e26-install-rollback-failure-regression-supplement).

E27 records the minimal PR11-MAINT-01 state-writer repair. The builder's two-module suite passed
466 tests with one skip, and independent Astra re-review passed three real writer-fault regressions
plus its bound input/static checks. This narrow review does not establish a full security audit,
installation, host, production, recovery, resource, or release acceptance; the publication-locator
gap remains open. Preserve E25 and E26 as separate historical evidence. See
[E27](../../MVP-PLAN.md#r-astra-121-e27-maintenance-state-writer-fault-repair).

At the E28 checkpoint, PR #11's artifact transport remained on hold: independent QA reproduced a
mocked scan/upload TOCTOU race even though the corrected selected counts were 17 transport and 18
helper tests passed.
The required repair at that checkpoint was to stage verified private copies and scan and upload
those same copies; final tests and independent review were pending. Its proposed sequence conflated
publisher validation with the production consumer's installed-helper identity check; E29 corrects
the distinction below. No install, deployment, live publication, or native acceptance was
established. See
[E28](../../MVP-PLAN.md#r-astra-121-e28-pushed-pr-checkpoint-and-hotfix-transport-finding).

E29 supersedes that pending status for the scoped local source review: independent QA passed 21
transport tests and Ruff check/format after the private-snapshot and bounded-wait repairs. These
checks did not run publication or installation. The local publisher validates clean exact
`origin/main` source and its fixed package, stages verified private copies, scans/uploads those same
copies, and verifies downloaded readback. The root-owned installed-helper record and expected pair
digest are checked by the production consumer before it derives the helper-head pair URL; the local
publisher does not check remote installation metadata. See
[E29](../../MVP-PLAN.md#r-astra-121-e29-bounded-hotfix-publisher-review-and-flow-separation).
