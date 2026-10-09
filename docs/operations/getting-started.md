---
title: "Getting started"
description: "Install and run Stock Probability locally with the pinned Python environment, migrations, readiness check, and safe shutdown."
---

# Getting started

Stock Probability supports Linux on x86-64/amd64 and ARM64/aarch64 with Python 3.11. The
bootstrap selects exactly Python 3.11.15 and creates `.dev-venv/`; tracked `burry_env/` is
legacy noise and must not be used as the environment or dependency declaration.

```bash
./scripts/bootstrap.sh
./scripts/build-frontend.sh
.dev-venv/bin/python -m stock_probs.cli migrate
.dev-venv/bin/python -m stock_probs.cli serve
```

Open `http://127.0.0.1:8000/`. Readiness is available at
`http://127.0.0.1:8000/api/v1/readiness`, and the local API pointer is at
`http://127.0.0.1:8000/api/v1/docs`.

`./scripts/build-frontend.sh` runs the pinned Next.js `16.3.5` / React `19.3` static App
Router export, typecheck, and frontend tests, then stages the result for the Python package.
Its stable build ID is `stock-probs`. `frontend/.next/`, `frontend/out/`, and
`src/stock_probs/static/next/` are generated and ignored; do not treat their presence as source
or release evidence. FastAPI remains the only production server and `/api/v1` remains the only
application-data boundary. The Docker path uses Node in a build-only stage and copies the staged
static files into the Python wheel; Node is not part of the runtime image.

The default provider is Yahoo Finance and requires network availability. For a repeatable
offline-oriented development run, use the fixture settings in
[local configuration](../configure/local-configuration.md). Startup creates the private data
directory, applies packaged migrations, and marks readiness only after initialization.

Stop the foreground server with `Ctrl-C` and wait for normal process exit. Do not delete the
data directory to clear a port conflict; choose another loopback port. Before migration,
upgrade, or destructive filesystem maintenance, create and verify a managed backup as
described in [backup and restore](backup-restore.md).

## Optional local production Compose path

The root `compose.yaml` provides one minimal local production-style service; it is not a hosted
deployment or a replacement for native development. Use the maintained launcher from the
repository root for every operation on this local Compose service. The Compose file requires
`STOCK_PROBS_LOCAL_IMAGE` and fails closed if called directly without it; the launcher selects and
sets the local image for you.

Build and start the service:

```bash
./scripts/local-compose.sh up --build -d
./scripts/local-compose.sh ps
```

The `up --build` form runs the bounded Buildx build first, then starts Compose without passing a
build request to Compose. To build without starting the app, use
`./scripts/local-compose.sh build`; to start an already-built local image without rebuilding, use
`./scripts/local-compose.sh up -d`. At the E824 R-ASTRA-120 checkpoint, the actual BuildKit setup receipt is complete and a real
network-none worker `RUN` passed strict container-cgroup ancestry verification with its descendant
memory and CPU limits confirmed. Independent normal-user helper QA verified the receipt, data-root,
builder, and cache-volume configuration read-only. This proves the bounded worker-step and helper
verification scopes, not an application Compose image build or release. The launcher still fails closed unless the required setup receipt
and storage checks are valid for a build request; source or configuration presence alone is not
runtime acceptance.

Open `http://127.0.0.1:8000/`. Compose publishes only
`127.0.0.1:${STOCK_PROBS_PORT:-8000}` and keeps the database, SQLite WAL sidecars, trust key, and
managed backups in the named `stock-probs-data` volume mounted at `/data`. The image healthcheck
requests `/api/v1/health`; the runtime image uses UID/GID `10001`, a read-only root filesystem
with a bounded `/tmp`, dropped capabilities, `no-new-privileges`, `128` PIDs, `768m` memory,
`1.0` CPU, and three `10m` JSON log files. Compose defaults `STOCK_PROBS_PROVIDER` to `yahoo`;
set it explicitly only when a deliberate local fixture run is required.

Stop the service without deleting its named volume:

```bash
./scripts/local-compose.sh down
```

Keep at least 4 GiB free on each filesystem used by a build before starting. The bounded builder
stops the owned build if free space falls below 1 GiB. Its BuildKit configuration sets a periodic
garbage-collection max-used target of 4 GiB, reserves 1 GiB, requires 4 GiB minimum free space,
and allows one parallel build. The 4 GiB target is not an instantaneous absolute cache quota.
Treat these as the configured policy; claim effective runtime limits only after the setup receipt,
installed builder inspection, and worker-step cgroup probe pass. Builder setup is a separate,
explicit operation after the Docker root is mounted on the intended UUID and has sufficient free
space. The setup helper dry-runs by default and requires the reviewed mounted-filesystem UUID and
an immutable BuildKit image digest; only the reviewed invocation with `--apply` performs the
root-owned installation. At E824, the setup receipt and actual network-none worker-step cgroup
proof passed; the separate application Compose image build was not run.

The native path above remains the development path: it uses `.dev-venv/`, the local CLI, and
directly selected `STOCK_PROBS_DATA_DIR`/provider settings. The Compose path builds the pinned
wheel image and does not claim native ARM64 performance, physical-mobile behavior, screen-reader
coverage, or true browser-zoom evidence. Physical mobile, actual screen-reader, and true-zoom
evidence are unavailable in the current post-final QA record; emulated ARM64 covers functional,
package, and runtime behavior only, not ARM64 performance.

This Compose path is local development and validation. The invite-only GitHub OAuth/authenticator-app
deployment, local GitHub Release publication (with GHCR as an explicit compatibility transport),
Terraform-managed Linode host, and closed-until-canary Cloudflare Tunnel use the production
procedure below. Do not copy development bootstrap credentials into a production environment.

## Local Docker storage on removable media

Use this procedure for operator-owned local Docker and build storage. It does not migrate the
production application volume or production data.

1. Copy the source medium to an independent, protected filesystem. Before formatting, verify the
   backup checksum and byte count, the complete file/member inventory, and preserved metadata. If
   any check is missing or fails, stop before formatting.
2. Format only the intended partition, then mount it by filesystem UUID. Confirm the expected UUID,
   filesystem type, mountpoint, and read/write state before restoring files.
3. Stop both Docker and containerd while moving their data. If Docker uses the containerd image
   store, move and verify both roots; changing Docker's `data-root` alone does not relocate
   containerd-managed image content.
4. Make both services depend on the expected UUID-mounted filesystem and run a pre-start guard
   that checks the mounted device and filesystem. Use a private mount-namespace simulation to
   verify a missing or mismatched medium fails closed before retiring the original roots; neither
   daemon may create or use an empty fallback root. Treat physical removal and startup with the
   medium absent as a separate acceptance check.
5. Compare the restored image, container, and volume inventories with the source and verify
   application health on the restored data. Keep the original roots until these checks and the
   scoped private absent-medium simulation pass independent review. Retain the verified backup
   until physical removal and startup with the medium absent pass independent review; a simulation
   does not substitute for that check. Quarantine a failed partial copy for review; do not delete it
   as cleanup.
6. Move generated build and test caches as a separate operation. Record and compare their complete
   inventory and metadata, and retain their original copies until the relocated tools pass their
   scoped checks.
7. Bound BuildKit garbage collection to 4 GiB and review managed-image retention separately, with
   no more than three new managed images between explicit cleanup reviews. Confirm the running
   builder's effective controller limits before relying on them. Remove only exact reviewed
   objects; do not use global prune or force removal.
8. For schema-13 rehearsal cleanup, provide both the exact generated recovery tag and the expected
   full image ID registered in the bounded builder's ledger. The helper holds the ledger lock and
   compares the caller's expected ID with the completed recovery row before Docker inspection or
   mutation. It checks the bound receipt, image references, and protected/current inventory,
   removes only that full ID with `--no-prune`, verifies removal, and then updates the ledger. A shared, protected,
   current, unregistered, malformed, child-referenced, or container-referenced image must leave the
   row intact. If cleanup is partial, the helper restores the bound tag. Do not repair the ledger
   manually or substitute a global prune. The initial E825 candidate failed independent review
   because it omitted the expected ID. Its identity-bound repair passed 179 selected tests and
   independent/parent source review, but no actual Docker cleanup or pair rehearsal is recorded.

At the R-ASTRA-120 E823 storage checkpoint, Docker and containerd used the removable-media roots;
the matching image/container/volume inventory and application health passed, and the old main-disk
roots were retired after verification. Both guards passed with the mount present, and a
private mount-namespace simulation made both fail closed; physical removal and daemon startup with
the medium absent remain unverified. Generated-cache copy, activation, and filesystem persistence
checks passed, as did unprivileged read/write/delete checks and the relocated UV/Chromium tool check.
The explicit cache-source mover then revalidated its mandatory guards and retired the four original
cache duplicates; the active SD copies and original backup archives were retained. A final parent
observation confirmed all four cache mounts, absent main-disk Docker/containerd roots, matching
archive size checks, and application health HTTP 200. The earlier read-only preflight used a
computed snapshot and did not establish its optimization assertion; the later explicit mover
freshly revalidated mandatory guards and retired the original cache duplicates. Physical removal
and daemon startup with the medium absent remain unverified. The bounded BuildKit controller is
running with reported limits, but worker probe 02 failed at a verifier boundary that selected the
container's `init` leaf instead of the bounded ancestor. Completion 03 timed out while BuildKit logs
showed Docker Hub DNS timeouts on the default bridge. A dedicated user-defined bridge lookup
succeeded, but it does not establish a universal DNS cause. Those worker-verification failures are superseded by the E824 actual network-none worker `RUN`
Pass, which confirmed strict container-cgroup ancestry and descendant memory/CPU limits. Setup
receipt SHA-256 is `291ca40fc11266bac55fb095a30bcc17e9f0baf49530f72d5f703b300f0d7ceb`; the latest
normal-user helper validation passed at 16:08 UTC with an empty managed-image ledger, no legacy
image adoption, and valid builder inspection/data-root configuration. The managed builder uses the
owned `r120-bounded-build` bridge; the default builder was unchanged. Controller PID limit 128 is
not a worker PID-limit result. At the final actual-host observation, the main filesystem had
59,009,478,656 bytes free and the SD filesystem had 63,949,541,376 bytes free; application health
was HTTP 200. Physical device removal and boot/startup with the medium absent remain unverified.
Keep the original verified backups. No application image was built for this proof, and no release
or production acceptance is claimed. See the [MVP plan](../../MVP-PLAN.md#r-astra-120-e823-storage-recovery-and-docker-migration)
for exact checkpoints, receipts, and preserved failures.

The E825 restore journal now records the successful restore unit's actual `Started` time
(`2026-10-09T11:37:50.332071Z`), successful deactivation
(`2026-10-09T12:06:41.656350Z`), and result `0`; this supplements the earlier restore projection.
The verified SD backup and both main-filesystem archives remain retained. A later transient-unit
`not-found` response with default status fields is not terminal proof. The initial cleanup-helper
candidate passed 172 builder tests and Ruff/format, but independent QA **Failed** on a P2:
expected full image ID was not required before deletion. The identity-bound repair and re-review
passed 179 selected tests with Ruff, format, security, and diff checks; independent and parent
integrated source review passed for that scope. The reviews used mocked Docker and did not run a
Docker build, image deletion, or actual schema-13 pair rehearsal. The separate
candidate-ledger mismatch remains preserved as the diagnostic that motivated the repair. The
physical absent-medium startup check also remains unverified. See the
[developer testing guide](../develop/testing.md#schema-13-rehearsal-image-cleanup) and the [E825
ledger](../../MVP-PLAN.md) for scope and receipt details.

The `2026-10-09T16:44:54.174085Z` mounted-state readback confirmed the SD UUID at the configured mountpoint,
the Docker root beneath that mount, and both daemons active with mount dependencies. It observed
58,940,370,944 bytes free on the main filesystem and 63,949,533,184 bytes free on the SD. This
present-state check does not substitute for physical absent-medium startup.

At the later E826 checkpoint, the first actual application-candidate build on pushed, clean PR
head `ae140dd011ee043cd24c7db84b6922826d012d28` **Failed** with
`local_build_failed:bounded_image_build:exit_1`; its expected candidate receipt was not created,
and the requested image tag was absent. Docker API calls later recovered and application health
returned HTTP 200. The helper reported only `fixed_command_unavailable_or_timeout`; the exact
failed subcommand and cause remain **Unproven**. Independent review confirmed the failed-build result. The
source-only monitor repair passed 106 builder and 106 independent tests plus static checks, with
parent source/evidence review recorded in the integrated-review receipt (SHA-256
`8850e4efb061b5bd4ea252e9a3d45c6a6530282a60e1294348a0e6293dd5ee2f`). Typed
reservation recovery then failed independent synthetic QA with a P2: a partial exclusive-create
receipt remained after an `OSError`, while the ledger was restored and retry stayed blocked.
The source repair passed 132 builder-selected and 132 independent synthetic tests, with parent
review passing. After an initial receipt-path setup failure that left the ledger unchanged, the
actual typed reservation release passed, with an independent read-only review confirming the empty
candidate ledger, matched receipts, and exact candidate-tag absence; no Docker/image mutation
occurred. The check was not a broad image inventory. A follow-on managed-run-directory repair passed
134 builder-selected tests and parent source review; independent permission QA passed 134 selected
tests with static checks; a fresh application build remains pending. The original application-candidate build remains failed; no image or schema-13 pair is
accepted. Preserve the original failed receipt. The `2026-10-09T16:44:54.174085Z` readback
recorded about 55 GiB free on the main filesystem and 59 GiB on SD. A later independent
current-state read passed at `17:27:11Z`, confirming the SD UUID/mount, Docker root, four cache
bind mounts, active Docker/containerd mount dependencies, and application health HTTP 200. Fresh
archive-metadata checks and physical absent-medium startup remain unverified. See the [E826
ledger](../../MVP-PLAN.md).

At E827, the second actual application-candidate build **Failed** on the then-clean pushed PR head
`83e0b0e1cdfbec8502208c48814a592112c022ea`. The bounded helper exited `1`, the outer
rehearsal exited `2`, and BuildKit reported `cannot copy to non-directory .../lib` during
`COPY --from=opencode-assets /out/ /`. The raw diagnostic and corrected projection are linked in
[E827](../../MVP-PLAN.md#r-astra-120-e827-pr-head-candidate-build-failure-and-copy-path-repair);
the initial flat-key projection incorrectly showed null. The read-only failure review confirmed
storage UUID/root, app health, and controller-only limits; its snapshot still showed an in-flight
image reservation. A later typed release passed; supplemental independent review confirmed the empty
ledger, absent exact tag, unchanged setup/failure receipts, and app health HTTP 200. The explicit
`/usr/lib` copy repair passed seven builder tests, parent source review, and independent QA (154
selected tests plus Ruff/format); that QA preserved the then-unfixed Dockerfile pin. The pin-only
follow-on passed 147 builder tests and parent constant review, and its exact diff/actual-state scope
passed supplemental independent review (SHA-256
`0414454819230ddd760c5a6f9da7b29291d698d508edc2f8c6ffa1c26e656693`). The setup receipt is not
Dockerfile-bound, so no reinitialization was needed. E813's guide metadata rebind passed on this 83e
head for 94 consumer inputs, 52 assets, 23 artifacts, and 8 PNGs; final current-head guide acceptance
remains pending. Later source changes make 83e a historical build target. A fresh exact-head image
build must verify library paths and loader behavior; no candidate image or schema-13 pair is accepted.
The earlier E826 failure remains preserved.

## Invite-only production deployment

Production is one FastAPI app with SQLite on a persistent Linode volume, published only through a
Cloudflare Tunnel. Docker binds the app to `127.0.0.1:8000`; there is no public application port,
order routing, brokerage session, real-time claim, or fabricated market depth. Production uses
GitHub's authorization-code flow with state and PKCE, the numeric GitHub account ID as the stable
identity, and a six-digit TOTP authenticator-app code after an administrator-issued, expiring,
single-use invitation. The authenticator code is the sole application second factor. The deployed
schema-10 migration revokes stored passkeys and old passkey sessions; the application does not create
or accept WebAuthn credentials.

`R-ASTRA-111` is deployed at pushed `main` revision
`82f2dfed76f6aee2a1ef9c3decd675ed72d89fed`, schema 11. Its migration clears in-progress OAuth
transactions before storing a hashed caller key; users, sessions, and research records were
preserved, and a verified schema-10 pre-migration backup is available. Sign-in flows already in
progress must restart. OAuth admission is limited to 8 starts per effective caller and 64 per
process per rolling minute, with 8 and 128 outstanding transactions respectively; callers sharing
an effective NAT/proxy address share the caller budget. Production Compose ingress attribution is
installed through the existing reviewed host-Compose updater. The corrected local gate, scoped
security review, Docker bridge regression, deployment, and bounded public probes passed for their
declared scopes; the initial stale-schema full-gate failure remains recorded. See the
[R-ASTRA-111 evidence](../../MVP-PLAN.md).
The supported CLI disables Uvicorn proxy-header
rewriting. Direct Uvicorn launches require `--no-proxy-headers` so caller attribution sees the raw
socket peer. SMTP host settings were absent at the R-ASTRA-111 deployment checkpoint. R-ASTRA-112
later enabled production email invitations and confirmed delivery of an owner-bound test message
to Gmail's Spam folder; inbox placement was not achieved. The operator used the service functions
behind the email endpoint, not an authenticated browser/API flow. Authenticated owner-browser and
physical iPhone acceptance remain unavailable. See [local configuration](../configure/local-configuration.md) and the
[API reference](../reference/api.md) for the caller rules and limits.

### Authenticator enrollment and recovery

After GitHub sign-in and invitation validation, open `/authenticator?mode=enroll`. First choose
Apple Passwords, Google Authenticator, Microsoft Authenticator, 1Password, or another app in the
in-page selector. The page then lets you generate a setup key and shows instructions for the
selected app. The selector guides setup; it cannot launch that app or change iOS link routing.

For Microsoft Authenticator, the enrollment view defaults to **On this phone: copy the setup key**.
Open Microsoft Authenticator, tap **+**, choose **Other account**, and use **Enter code manually**
if that option is offered. Copy the displayed key into the app and return to the page for its
current six-digit code. Microsoft's [instructions for adding non-Microsoft accounts](https://support.microsoft.com/en-us/authenticator/how-to-add-your-accounts-to-microsoft-authenticator)
describe the app's QR and manual-entry routes. If you have another screen, select **Another screen:
scan from inside Microsoft Authenticator**; the page then displays a QR code for Microsoft
Authenticator's own in-app scanner. Do not use iPhone Camera or Photos for this QR code: iOS may
route it to Apple Passwords, and there is no documented way in this flow to force those iOS tools
to open Microsoft Authenticator. If you change the app selection and return to Microsoft
Authenticator, the page resets to manual entry; select the other-screen option again to reveal
the QR.

For other selected apps, copy the manual setup key on the same iPhone or display the page on another
screen and scan it with the chosen authenticator's in-app scanner. The page does not offer a generic
`otpauth://` link because iOS may open a different app from the one selected. QR codes are generated
locally in the browser from the short-lived setup URI; no external QR service receives the setup
secret.
Then enter the current six-digit code. The server activates the factor only after the code is
verified and returns recovery codes once. Store each recovery code offline; each can be consumed
only once.

An unexpired setup key is reused when the request comes from the same enrollment session and origin,
so reopening setup does not silently invalidate the QR or shorten its expiry. If another session owns
the pending setup, the page reports the conflict. Use **Start over with new key** only when you intend
to rotate it; that explicit action invalidates the previous QR and setup key. The page shows the expiry
and disables QR/code use after it expires. If a QR or setup key appears in a photo or screenshot, treat
it as exposed.
Use **Start over with new key** to rotate it, replace the old Signal Ledger entry in your authenticator
with the new key before entering its code, and do not use the captured QR or old key.

If an authenticator is lost, use one unused recovery code at `/authenticator?mode=recover`. That
session is limited to replacing the factor. Enroll the replacement app and save the newly issued
recovery codes before returning to the workspace. A normal sign-in from another device uses only
GitHub plus the six-digit authenticator code; it does not require Bluetooth, a nearby phone, or
browser passkey support. The retired `/passkey` route redirects to authenticator enrollment and
cannot create or verify a passkey. An existing TOTP account still requires its current TOTP or
recovery-code replacement flow; a fresh GitHub session alone cannot replace the factor.

### Invitation email and host Compose update

An administrator can create an invitation from `/admin` using only the recipient's email address;
there is no need to look up a GitHub username or numeric ID first. The existing numeric-ID
invitation-code flow remains available. Email invitations are single-use and expire. The recipient
must continue through GitHub sign-in. For an email-only invitation, the app checks that the
invited address is among the authenticated account's GitHub addresses marked verified before
binding the invitation to that account's stable numeric GitHub ID. A public profile email or
matching username does not prove identity. If an administrator explicitly supplies a positive
GitHub ID, the invitation remains bound to that numeric ID and the email is only the delivery
destination; an optional username is only a display hint for that ID-bound invitation. After
redemption, the existing TOTP enrollment or verification and per-user workspace ownership checks
still apply.

The email-only GitHub OAuth check uses the least-privilege `user:email` scope and reads the
authenticated account's email records and their `verified` flags. If GitHub does not provide a
verified match, or the lookup fails, email-only redemption fails closed. Address comparison uses
ASCII case-folding only; it does not fold Gmail dots or plus tags. The optional `github_id` and
`github_login` request fields support an explicit ID-bound invitation; they are not required for
an email-only invitation, and the login remains only a display hint. See the
[API reference](../reference/api.md#email-invitation-contract) and GitHub's
[authenticated email-list endpoint](https://docs.github.com/en/rest/users/emails#list-email-addresses-for-the-authenticated-user).

Email delivery submits the generated invitation code to the supplied mailbox when the optional
SMTP settings are fully configured; the code is not included in the HTTP response. The six production
variables and accepted values are listed in [local configuration](../configure/local-configuration.md#production-invitation-email).
Keep SMTP credentials in the operator-controlled production secret path outside the repository.
The client validates the SMTP server certificate and uses `implicit_tls` on port `465` or `2465`,
or `starttls` on port `587`, with a 10-second socket timeout applied to each socket operation. This
is not a total deadline for the entire submission.

A successful email response means only that the configured SMTP server accepted the message for
processing. The returned local submission ID is not a provider receipt and does not confirm
mailbox delivery or reading. SMTP failures do not prove that no message was accepted. Since the
invitation is created before submission, inspect the invitation list before retrying; an unused
code may remain valid until it expires. The `R-ASTRA-104` scoped QA did not exercise a live SMTP
provider, mailbox delivery, or production deployment. R-ASTRA-112 later confirmed delivery of one
operator test message to Gmail's Spam folder; that did not test authenticated HTTP invitation
creation or new-user redemption. R-ASTRA-113 passed its local implementation/QA gate (`796` Python
tests) and was deployed at schema 12 on pushed revision
`4cc5c8502ec93c57947958ee07f891b45e98d870`. Three invitations were submitted using production
service functions over operator SSH, and Resend reported all three delivered; the authenticated
admin HTTP/browser flow was not used. One recipient mailbox classified its invitation as Spam;
placement/read status for the other mailboxes is unavailable. Follow-ups were sent from personal
Gmail in the same thread. One invitee reported access and sanitized logs support redemption, TOTP
enrollment, and private API activity; browser-rendered UI is not established. Another invitee
reported rejection while the invitation remained valid, with verified-email mismatch only inferred.
See the [current evidence](../../MVP-PLAN.md).

### Recovering an invitation email mismatch

With deployed R-ASTRA-118, only an active, unused, unexpired email-only invitation can show a
specific `invitation_email_mismatch` response. This preserves the existing atomic behavior that
leaves the invitation valid after a mismatch. Have the
invitee check or add the invited address under
[GitHub email settings](https://github.com/settings/emails), complete verification, then return to
the same browser and enter the original invitation code again. Do not refresh a callback page.
If the person already has an account, use normal sign-in instead. Used/expired invitations and
numeric-ID invitations retain generic error handling. Focused independent backend/browser QA passed,
as did the full local gate and schema-12 deployment. Production probes and a dummy-callback browser
check showed the recovery guidance; they do not confirm the remaining invitee's sign-in or verified
email. See the [MVP plan](../../MVP-PLAN.md) for the exact evidence and limits.

### Resend sending domain and credential workflow

The Resend free account was created with Google SSO, and `mail.jtmb.cc` was reported verified at
approximately `2026-10-01T14:04Z`. Cloudflare Terraform manages three DNS-only sending records in
`infra/cloudflare/main.tf`; commit `90ad506dc7c39e145734f295f41ac2a4358b7a14` was pushed. Terraform
format/validate, the exact three-record create apply, public DNS resolution, and the post-apply
no-change plan were reported **Pass** for the DNS scope. This does not verify an API key, SMTP
authentication, message acceptance, or mailbox delivery.

The fixed typed controller refreshed the Linode operator SSH rule to `142.198.155.54/32`.
From Linode, `smtp.resend.com:2465` reached the endpoint over TCP and negotiated TLS 1.3. These
are transport checks only; they do not prove that a Resend key exists or that a message can be sent.

The intended credential workflow is the fixed local entry point
`infra/linode/install-resend-smtp-key.sh --api-key-file FILE`, which accepts one private, one-line
Resend API-key file and uses fixed host, Compose, and readiness boundaries. The companion remote
helper sets the fixed Resend SMTP values and recreates the current production app without building
or pulling a new image. Builder and repaired installer QA were observed against local revision
`42cf0f40c98404d55585745b10311354661a5195`; the installer is included in pushed `main` checkpoint
`329fdc595483fa3b112b98c7788d808348638faa`, reported as matching `origin/main` with a clean tree
at that checkpoint.
Builder self-validation reported `11` focused tests, Ruff check/format, `bash -n`, and ShellCheck
**Pass**; initial independent QA found a P1 remote-shell quoting blocker and a P2 incomplete-read
rollback blocker; the repaired QA recheck passed `13` tests, including command parse/probe and
incomplete-read rollback, for its declared local scope. This does not establish production
acceptance or authorize a live key install.

At installer checkpoint `329fdc595483fa3b112b98c7788d808348638faa`, the report said the tree was
clean, matched `origin/main`, and no Resend API key existed at that time. A later operator-side
production observation reported `email_invites_enabled=false`; no timestamp was supplied. That
point-in-time state was still unavailable after a read-only SSH timeout. Local fake-SMTP QA reported
25 passing cases plus invitation-expiry coverage; those checks did not establish live delivery.

R-ASTRA-112 supersedes that earlier production configuration status. The fixed installer enabled
Resend SMTP on `smtp.resend.com:2465` with `implicit_tls`; the existing R-ASTRA-111 application
image and database were preserved. A user-authorized sending-only key remained in the operator's
external private-file path. The operator created an owner-bound invitation using the same service
functions used by the email endpoint. Resend reported delivery and Gmail metadata confirmed
receipt, SPF, and DKIM, but Gmail classified the message as Spam/Updates. The invitation was later
confirmed expired, with no invitation rows deleted. This was not an authenticated browser or HTTP
API test, and new-user onboarding remains unverified. See the [R-ASTRA-112 evidence](../../MVP-PLAN.md).

To install a reviewed change to the host's production Compose file, run the fixed updater from a
clean checkout of the exact reviewed `main` revision. It verifies that local `HEAD` equals the
supplied SHA, the worktree is clean, public `origin/main` has the same revision, and the tracked
Compose file matches the supplied SHA-256. The repository, host, operator account, SSH target, and
remote destination are fixed in the script.

From the repository root, calculate the hash and invoke the updater, replacing the placeholder
with the reviewed 40-character commit SHA:

```bash
reviewed_sha="<reviewed-main-commit-sha>"
compose_sha="$(sha256sum compose.production.yaml | awk '{print $1}')"
./infra/linode/update-host-compose.sh \
  --reviewed-revision "$reviewed_sha" \
  --compose-sha256 "$compose_sha"
```

The operator SSH identity and pinned known-hosts file must exist at the script's local defaults,
or their locations may be supplied through `SIGNAL_LEDGER_OPERATOR_IDENTITY_FILE` and
`SIGNAL_LEDGER_KNOWN_HOSTS_FILE`. They must be regular, private files, and the known-hosts file
must be scoped to the fixed host. Never copy private key contents into the repository.

The updater transfers only the verified Compose bytes and atomically replaces the fixed host file
under the deployment lock. It does not restart the app or tunnel, publish an image, validate a live
SMTP account, or prove email delivery. Production deployment and live mail acceptance are separate
checks.

Terraform's Linode configuration keeps the requested low-resource shape: Ubuntu 24.04,
`g6-nanode-1` (1 GB RAM/25 GB disk), `us-east`, VM Backups, disk encryption, and the existing
firewall imported as `177236117`. Its inbound policy is default-deny with only operator SSH from
the configured `/32`; application ports are not opened, and the Linode and firewall have
`prevent_destroy`. The fixed external source gate runs during plan and again during apply and
requires a clean checkout, exact `origin/main`, the reviewed revision, and checksums for the
bootstrap files. This has been applied to replacement Linode `106817202`; E59 retired legacy Linode
`97934478` after validation-only checks and a guarded execute run. The old instance was labeled
`cardventory` with backups disabled; the replacement is labeled `signal-ledger` with backups enabled
and the same shape/location. The retirement workflow used the local Signal Ledger app as its data
source; no Cardventory-data preservation claim is made. The firewall is attached only to the
replacement host, and the application remains loopback-only.

Cloudflare Terraform defaults to `exposure_mode=closed`: the managed tunnel has a terminal 404
ingress and no DNS record. E58 records the provider-refreshed `public_invited` apply for
`ledger.jtmb.cc`: the owner-canary Access app was deleted and the exposure guard updated, while
the tunnel, DNS record, and cache-settings rule remain managed. The route still targets
`http://127.0.0.1:8000`, the connector is active, and direct port `8000` remains unreachable.
The live boundary returned `303` to local sign-in for `/overview`, `401` for `/api/v1/history`, and
`200` for `/api/v1/auth/status`; each response was `no-store`/`DYNAMIC`. The live IAB showed the
unauthenticated sign-in page but no owner UI session. E59's post-delete probes returned health and
auth `200`, history `401`, and overview `303` to sign-in, with `no-store`/`DYNAMIC`. Functional
owner/invited-user acceptance remains pending.
The earlier provider verification reported Cloudflare HTTP `401` despite functional API/Terraform
operations, so that discrepancy remains an open limitation.

### Build and publish locally

The VM never builds source. A reviewed clean checkout whose `origin/main` matches the exact `HEAD`
builds and publishes the default GitHub Release transport:

```bash
./scripts/publish-production-image.sh
```

The script builds a Linux `amd64` image, creates the revision-named local tag
`signal-ledger-<reviewed-sha>` and release asset `signal-ledger-image-<reviewed-sha>.tar.gz`, scans
the archive for credential-like material, publishes through `gh release create`, then downloads
the asset again and verifies its archive SHA-256, Docker image ID, revision label, platform, and
size. The script treats the revision-named asset as immutable during this workflow, but GitHub
does not enforce asset immutability. Set `SIGNAL_LEDGER_IMAGE_PUBLISH_MODE=ghcr` only for the
explicit compatibility transport; GHCR is not the default. Local-to-GitHub publication is
completed for reviewed revision `3bc85ed6c6b8b56386da32e532e4a79c5f74b6dd`; the verified asset is
`103,116,996` bytes with SHA-256
`586ef74929dd3542930f37f46f9081f56a2c3bdf7a43b5aec32450be69d9ecce` at
`https://github.com/eddiesoz/stock_probs/releases/tag/signal-ledger-3bc85ed6c6b8b56386da32e532e4a79c5f74b6dd`.
That transport receipt remains historical. The current private deployment uses reviewed revision
`f329a4c99bf75d9ff2d365473051580f8eda7f58`, archive SHA-256
`79f4ac15491ccb7d70ab28b0ed44f441f18f0212c54c3a1487dde6a3a267f9a1`, and image ID
`sha256:b324a8f288307ff864b26d4792c54271cfee963cf077d31b16c1fac951f87eca`; remote readiness is
schema `8`. The Linode helper derives the fixed GitHub URL from the reviewed revision and accepts
only the verified archive hash and full image ID. It does not accept mutable tags, arbitrary image
names, remote builds, shell commands, paths, URLs, Compose edits, or Docker-socket operations.

### Prepare the host

The operator's Linode console login uses Google SSO. This web-console identity is separate from
the pinned SSH identity and Terraform/provider credentials; keep those operator-controlled files
outside the repository.

From a clean reviewed checkout, run the static validation and plan the two Terraform roots. Supply
the operator IPv4 `/32`, separate operator/deployment public-key paths, and reviewed commit SHA as
variables; the private keys and provider credentials stay outside the repository. The plan must
show the existing firewall import and the requested `g6-nanode-1` replacement without opening
application ports. Do not remove the existing VM or change the current local app during
preparation. Run Terraform from an operator-owned private working directory with mode `0700`, and
set `umask 077` before creating `.terraform`, local state, saved plans, or backups:

```bash
umask 077
chmod 700 /path/to/private-deployment-workdir
cd /path/to/private-deployment-workdir
```

Before using any existing state, backup, or saved-plan file, verify that it is operator-owned and
mode `0600`; correct each retained file with `chmod 600 /path/to/file` before continuing. This
procedure does not claim that existing state or credential permissions have been checked. Do not
store Terraform state, saved plans, backups, provider credentials, or private keys in a shared or
world-readable directory.

```bash
./infra/linode/validate.sh
terraform -chdir=infra/linode init -backend=false
terraform -chdir=infra/linode plan \
  -var='operator_ipv4_cidr=OPERATOR_IPV4/32' \
  -var='reviewed_revision=REVIEWED_MAIN_SHA'
terraform -chdir=infra/cloudflare init -backend=false
terraform -chdir=infra/cloudflare plan -var='exposure_mode=closed'
```

The first-boot bootstrap installs Docker, Compose, `cloudflared`, the restricted host boundary, and
a disabled `signal-ledger-cloudflared.service`. The service command and host-unit update path are
code-managed, and the fresh bootstrap remains source-gated. The later configuration helper writes
each file atomically under its own lock; the app environment and tunnel token are separate writes,
so the operation is not an all-or-nothing pair. The private replacement host has completed the
scoped bootstrap, configure, seed, and image deployment checks; the recovery rehearsal is recorded
separately below. When the provider steps are complete, install the remotely managed tunnel token at
`/etc/cloudflared/tunnel.token` with mode `0600`. Store production values in
`/etc/signal-ledger/app.env` with mode `0600`: `STOCK_PROBS_ENV=production`,
`STOCK_PROBS_AUTH_MODE=github`, exact `STOCK_PROBS_PUBLIC_ORIGIN`, unique
`STOCK_PROBS_AUTH_SESSION_SECRET`, `STOCK_PROBS_GITHUB_CLIENT_ID`,
`STOCK_PROBS_GITHUB_CLIENT_SECRET`, `STOCK_PROBS_GITHUB_REDIRECT_URI`, and
`STOCK_PROBS_OWNER_GITHUB_ID`. Keep `STOCK_PROBS_AUTH_COOKIE_SECURE=1`, leave the cookie domain
unset for a host-only cookie, and trust proxy headers only from `127.0.0.1`.

### Preserve and migrate existing data

At cutover, take a fresh online SQLite snapshot while the source app is running, verify the signed
`.spbackup` and installation trust key, then transfer the snapshot through the protected operator
SSH route into the private target volume. Preserve mode `0600`; do not copy a live WAL pair by hand,
edit tables, or generate a replacement trust key. Keep the public Tunnel disabled while loading and
verifying the private volume.

The deployment helper is designed to read the existing schema, verify a pre-deploy backup, create
and verify the pre-migration backup when the imported database advances schema, run the
checksum-pinned migrations, verify a current-schema backup, and require readiness with the image's
schema. The historical R-ASTRA-102 candidate advanced the additive auth schema to schema 9. The
deployed R-ASTRA-103 baseline advances it to schema 10 and revokes stored passkeys and old
passkey sessions. Luna's QA covered the local fixture paths; owner TOTP enrollment remains pending.
The
repaired recovery rehearsal passed its declared
scope after restoring a disposable clone, checking the app, database, firewall, SSH, loopback, and
tunnel-disabled boundaries, then deleting the clone and confirming that its API lookup returned
`404`.
reserved legacy owner claim remains the owner of legacy
events/results; every new request derives ownership from the session, so
changing an ID cannot expose another user's history, exports, holdings, watchlists, outcomes, or
reconstructions.

The local rehearsal used the verified read-only `pre-production-20260927.spbackup` schema-6
database hash `2533d3bf96db79610b4616531e047df434ed54b1b2e1243c8a65b4e8401adcfd`. A separate
mode-`0600` online snapshot matched it and passed `PRAGMA integrity_check=ok`; it contained 13
events, 13 runs, 20 results, 6 portfolio holdings, and 3 watchlist items. Disposable schema-6→8
migration verified pre/post backups, and a simulated claim to GitHub ID `86915618` preserved all
records. This is local evidence; take the live snapshot again if data changes before cutover.

### Use the deployment MCP

Run `./scripts/deploy-mcp.sh` locally. The independent E70 official Python SDK stdio client
initialized and listed all eight expected operations and schemas: `inspect`, `plan_deploy`,
`deploy`, `status`, `rollback`, `refresh_operator_access(operator_ipv4_cidr)`, `rehearse_pr_pair`,
and `set_assistant_rollout`. It invoked no tool and passed no target variables. E90 later records
a fresh Codex task discovering all eight names and completing read-only `inspect` and `status`; E105
records a separate later current-root observation with all eight names and one read-only `status`
call. An earlier six-name root/task snapshot remains historical. These are separate discovery and
read-only observations; no mutating-tool execution, deployment, rollback, or rollout acceptance is
inferred.
The default release transport carries
the reviewed revision, archive SHA-256, and full Docker image ID; the optional GHCR compatibility
shape carries its immutable digest. The controller uses the restricted SSH helper and records only
revisions, image identities, schema versions, backups, and safe result codes.
The normal sequence is:

```text
inspect → plan_deploy(main revision, release archive SHA, image ID) → deploy(plan) → status
```

#### Review a PR pair before rehearsal

For the fixed R-ASTRA-120 PR #1 pair, first build and verify the exact clean candidate/recovery
pair. Only then persist its local review pins with:

```bash
python3 scripts/pin_pr_rehearsal_review.py --write
```

The command has no target/path arguments. It checks the current clean PR head and pair manifest
before writing private, nonsensitive pins to `$XDG_CONFIG_HOME/signal-ledger/rehearsal-review.json`
(defaulting under `~/.config`). The paired environment compatibility variables must agree with the
file if both are present; partial or mismatched values fail closed. This is an operator-local
preparation step, not a deployment. The E741 candidate command was not executed, no metadata file
was written, and no PR-pair rehearsal or remote operation is accepted. The latest config text names
eight operations. E767 later passed fresh-task discovery for this configuration; future configuration changes require a fresh Codex task to verify discovery. See [local metadata settings](../configure/local-configuration.md#local-pr-rehearsal-review-metadata)
and [developer testing](../develop/testing.md#exact-pr-pair-review-pins).

`refresh_operator_access(operator_ipv4_cidr)` is a separate maintenance action. It accepts one
canonical IPv4 `/32` and constrains Terraform to the fixed `linode_firewall.signal_ledger` resource
(firewall ID `177236117`) and its `ssh-operator` TCP port-22 rule, using the fixed external private
state and the reviewed clean-tree/source gate. It does not accept a caller-supplied Terraform path,
state, command, or credential. R-ASTRA-106 records a live refresh result with `50.21.67.178/32`
applied to firewall `177236117`; the Linode console login uses Google SSO and SSH material remains
separate.

R-ASTRA-120 remains **In progress**. E827's candidate build failed at a BuildKit library-copy step
on the then-clean pushed head `83e0b0e1cdfbec8502208c48814a592112c022ea`; later source repairs make
that head historical, and no image built from the repaired exact head or PR pair is accepted.
E823/E824 storage and bounded-worker checks passed for their recorded scopes; physical absent-medium
startup and fresh archive-metadata checks remain unavailable. E791/E795 browser and axe evidence are
reusable only for unchanged inputs. E813's guide metadata rebind passed for its unchanged inputs on
83e, but final current-head guide acceptance is not established.
Native/provider, full security, current-image kill, actual combined 1 GB, PR-bound rollback,
current canonical, deployment/canary, and release gates remain open. Production's last recorded
read was `2026-10-08T21:33:44Z` (schema 12 ready, loopback-only; rollout mode unavailable). The
US$15 total cap, existing 1 GB plan, and backups remain unchanged. See the
[R-ASTRA-120 ledger](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on);
no production change, resize, rollout, merge, email, or release is claimed.

The
rehearsal source creates a separate, labelled user-defined bridge for each candidate run, with
Docker's default IPAM and no published ports. Recovery and one-shot CLI containers use `none`.
Cleanup checks the exact network ID, name, ownership and empty endpoints after confirming owned
containers are absent; listing fallback validates bounded full-ID/name rows and compares names
locally. E197 passes synthetic/source verification only; native bridge and PR-bound recovery
acceptance remain open. The
current host-helper source requests `HostConfig.SecurityOpt` and requires exactly
`["no-new-privileges:true"]`. Independent E70 selected profile tests passed 17/17 (32 deselected),
but these are local mocked/helper checks; live Docker or production inspection remains
**Unavailable**. The E19 runtime-verification gap is not evidence that a live container lacks the
setting. The local schema-12-to-13 rehearsal directly checked `no_new_privileges`, app UID/GID
10001, no effective or permitted capabilities, read-only root, and network isolation; this does not
substitute for live inspection. An actual active-search kill passed on earlier schema-13 image
`sha256:37c0c449e62e14ec83afc26163c59a69d17ae6a0a8d77133d180e4d68a3a1fc6`: it cancelled the turn,
left a pending search unexecuted, preserved app readiness/private history and saved records, and
erased worker state with zero OOM events. Current-image kill acceptance remains open; see the current
checkpoint above and the [R-ASTRA-120 ledger](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on). The schema-12-to-13 migration/recovery rehearsal passed for its declared same-disposable-volume scope,
preserved post-migration writes, and recorded `PR_bound=false` and `actual_1GB_Linode=false`; it is
not PR-bound rollback or actual 1 GB host evidence. The E39 model-activation-lock native run
failed after owner 1's approved WebFetch timed out at `dns_lookup_timeout` after 8,963 ms, leaving no
source or final answer; the DNS/network cause is unproven. Later same-image DNS-only comparisons
found host and owned user-defined bridge resolution at 189 ms and 440 ms, while the default bridge
timed out after 3,005 ms (E54). The instrumented guard diagnostic errored internally (E55), then the
unchanged hash-pinned guard resolved in 203 ms with four public addresses and exact cleanup (E56).
Production Compose uses a user-defined bridge; these checks do not establish the native fetch cause.
A later same-image two-owner run passed its bounded native functional workflow over that bridge
(E58), but its local 768 MiB sample peaked at the cap; required 1 GB evidence remains open. Worker
readiness intermittently showed starting/unavailable while app readiness stayed ready; exact cleanup
passed. The initial migration/hash mismatch remains historical (E63); independent pin QA later
passed its selected helper scope (E65), and parent read-only verification confirmed the two actual
manifest pin links (E78). Neither establishes live promotion or production configuration. No live
promotion was attempted. E85's independent PR-helper test command passed 61/61 with two warnings;
cached amd64 recovery-profile transfer and inspection, wrong-digest denial, and cleanup passed for
that scope. Its overall receipt is **Fail closed** because `scripts/pr_rehearsal_seed.py` lacked a
contemporaneous pre-run hash. A matching prior prepared hash and current hash do not replace that
missing baseline. This was a fixed 384 MiB local recovery-profile check, not a full candidate/recovery
pair rehearsal, PR-bound rollback, production inspection, or combined 1 GB test. Production was not
changed. Do not use
candidate operations for production promotion; see the
[plan evidence](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on).

### Ledger assistant help-guide capture pipeline

The candidate includes a renderer for the illustrated HTML and tagged PDF user guide. It only
accepts a capture bundle from the approved independent browser-QA directory, a fixed manifest name,
and the exact reviewed 40-character application revision. After an independent full browser run
passes and records the eight approved synthetic screenshot states, invoke it with explicit inputs:

```bash
node tools/assistant-help/render.mjs \
  --capture-root test-results/r-astra-120-independent-ui-qa-final/browser \
  --manifest test-results/r-astra-120-independent-ui-qa-final/browser/assistant-help-captures.json \
  --revision FULL_REVIEWED_REVISION
```

The eight manifest keys are `desktop_light`, `desktop_dark`, `mobile_light`, `mobile_dark`,
`forecast_sources`, `action_preview`, `action_receipt`, and `history_context`. The first four
desktop/mobile captures and the four state captures use synthetic demonstration data. Each PNG
must have its own SHA-256 and the same reviewed revision; the manifest and independent QA receipt
bind those eight hashes and capture metadata together. Mobile screenshots use browser viewport
emulation and are not physical-phone evidence. The renderer validates the approved root, file types,
image bounds, current revision, receipt status, hashes, privacy labels, and symlink boundary before
building previews. Review both generated formats for image loading, reading order, contrast,
captions, and page layout; renderer tests alone do not establish visual acceptance. Generated guide
previews are local ignored artifacts, not release files.

Historical R-ASTRA-120 guide evidence begins with the first independent eight-capture manifest and QA receipt
passed their declared scope, but trace review confirmed the screenshots used stale staged CSS. A
frontend build/stage subsequently passed and all 48 staged files matched the current build output;
the refreshed staged bundle contains the current composer placeholder rule. A replacement eight-
image set has since passed independent capture-only review with 93 source bindings, all 48 served
files matched to `frontend/out`, and the strict loader passing (E49). An HTML/PDF draft was rendered
with eight screenshots and no external requests (E50). Initial visual review found a broken
section-04 border/split figure and undersized action figures (E52). The repaired draft then rendered
with 8 DOM images and 12 PDF pages (E61), but parent visual review **Failed** because the
action-receipt image and caption were absent from all printed pages (E62). Later standalone guide
HTML QA passed 180 checks across 12 states with raw axe 0/0 (E73), and visual review passed for the
current 13-page PDF (E75). Parent's later structural inspection found 30 `/Strong` structure
elements without a role map and 30 `pdfinfo -struct` wrong-type warnings (E80); PDF/UA and
screen-reader acceptance remain unverified. Final PR-bound guide acceptance is pending. The fresh
150-case browser execution
and independent receipt passed its test scope with 147 passes and 3 expected skips (E59); raw axe
cleanliness **Failed** on incomplete items (E60). The later current-stage full run **Failed** at
145 passed, 2 failed, and 3 expected skips, with zero flaky (E83). Both failures repeated the same
terminal-copy test expectation in desktop and mobile; traces showed the explicit
EOF-without-completion warning and Reconnect control. All 197 source bindings and 48 staged files
matched at run end, and cleanup passed, but guide-capture refresh was **Skipped** because the suite
failed. Raw axe retained one incomplete contrast rule in each of four snapshots, so strict app
accessibility remains **Fail**. A separate focused EOF browser retest passed 2/2 in desktop Chromium
and Pixel 7 emulation (E86); the earlier anchored-selector attempt selected zero tests and is
retained as a setup failure. A separate focused repaired responsive retest passed 3 cases with 1
expected mobile skip (E87), verifying minimize/resume focus and 390×844 modal restoration alongside
the checked-in saved-answer/theme case. These focused results do not change the full-suite failure
or establish guide accessibility. Do not use the earlier stale bundle as current evidence or treat the separate
standalone guide checks as final PR-bound accessibility acceptance.
The earlier dirty-tree review did not establish a reviewed release revision. Do not bind an unreviewed guide to a local tree or send it with an announcement. The latest completed quiet full browser run failed at 145 passed, 2
failed, and 3 skipped (E36); a newer attempt stopped before an aggregate and is **Unavailable**
(E43: 85 passed, 2 failed, 1 interrupted, 2 skipped, 60 unrun; aggregate **Unavailable**). Owned-run
cleanup later **Passed** (E48). Its measured 3.5403:1 dark-placeholder contrast was served from the
old staged CSS confirmed in the trace; it is not the refreshed bundle's current-source result. A fresh full browser run on the
refreshed stage has now passed its test scope (E59), with the raw axe result retained separately in
E60. The independent E70 Python SDK client listed all eight deployment MCP operations and schemas
but invoked none and passed no target variables. An earlier root/current-task metadata snapshot
exposed six; that is a historical snapshot, not the current discovery result. A later fresh Codex
task discovered all eight and completed read-only `inspect` and `status` (E90), and E105 later
observed all eight in the current root and passed a read-only `status` call. These observations do
not establish mutating-tool execution, deployment, or rollout.

The E664 guide bundle was captured at app revision `ee65b40460fa5d5b536ae51169b9c01b6ddc1034`.
Its standalone HTML passed six viewport/theme states; its 14-page PDF passed visual review but
failed tagged-text fidelity because extracted structure text omits spaces present in the HTML.
E670 later changed the tracked renderer, so the E664 finalized files no longer bind the current
renderer. Its initial test review found a P2 gap in structure-boundary checks. A test-only repair
then passed independent source/test review and TAP reported 17/17, but the numeric command exit is
unavailable in that attempt. E673 independently reran the exact command with exit 0 and 17/17.
Fresh capture/render/finalization remain pending. The separate E665 private PDF passed
exact-structure review, but is not output from the current maintained renderer. PDF/UA and actual
assistive-technology results are unavailable;
the prior outputs are not final guide acceptance or release attachments. The full canonical check
at the app revision also failed; see the [R-ASTRA-120 ledger](../../MVP-PLAN.md) for exact scope
and receipts. A static instruction audit at the 30742 checkpoint found that context selection is
all-or-none with the current route always included, email-only invitations require a verified
GitHub email (while a supplied positive account ID restricts redemption to that account), and the
visible cancellation control is labeled “Stop response.” E679's copy/source-contract review and E696/E697's earlier capture are historical. E706–E710 bound a synthetic guide draft to the then-current PR head and passed their declared capture, review, finalization, and render scopes. E714's standalone HTML/PDF draft review found an unnamed cover Figure; E715/E717 repaired and independently checked the Figure name. That repair made the earlier bundle stale, so fresh current-head guide capture/render remains pending. E725's later 194-case browser aggregate failed, and guide capture was skipped. E760 later passed the maintained four-state panel snapshot scope with zero raw axe violations and incompletes; this does not establish full-app accessibility. E722 documentation checks passed at their earlier checkpoint. Physical mobile, actual assistive technology, PDF/UA, final PR-bound guide, native/provider, actual 1 GB, rollback, deployment, and release acceptance remain unavailable or pending. See the [R-ASTRA-120 ledger](../../MVP-PLAN.md) for exact receipts and earlier failures.

### PR-head candidate image build helper

The existing schema-13 rehearsal CLI now contains a fixed-source mode for a private local image
from the exact clean, reviewed head of open PR #1. Set `REVIEWED_PR_HEAD` to that exact lowercase
40-character SHA and `PRIVATE_RECEIPT` to a private output path, then use these mode flags:

```bash
python3 scripts/rehearse_schema13.py \
  --build-pr-candidate \
  --reviewed-pr-head "$REVIEWED_PR_HEAD" \
  --receipt "$PRIVATE_RECEIPT"
```

The helper verifies local `HEAD` and a clean worktree, the fixed PR-1/head/base relationship, and
the reviewed SHA again around the build. It writes a mode-0600 JSON receipt. The local
`linux/amd64` image is not published; every checked build filesystem must have at least 4 GiB free
before build, and the helper stops if free space drops below 1 GiB. E678's original independent process-ownership source review **Failed** and remains preserved.
E683 recorded builder checks; E684 independently passed source/test QA (59/59, exit 0; 149 source
inputs unchanged). No real Docker build, live PR/network check, process-group runtime probe, or
PR-bound rollback ran; image-build and rollback acceptance remain open.

E685's public-marker catalog GET returned HTTP 200 and did not explain the separate no-marker 403.
E687's application refresh found seven eligible catalog rows without a model request. E690
independently passed local catalog QA (7 focused tests and 174 provider tests); its narrower initial
6/6 selection omitted the recovery case. Network/model/provider, Docker and production checks were
not run. The native acceptance probe uses maintained field `zen.native_acceptance_model_id` for the
reviewed SpaceBunny model. E691 builder checks and E692 independent synthetic QA passed the
selector's declared source/test scope (308 probe, 38 kill, 9 attached-model, and 2 driver-binding
tests). No native OpenCode/provider/model/network, Docker, or production action ran; candidate image
build and native acceptance remain pending. Both probe paths must fail closed without exact explicit
selection. This acceptance-run selector does not change the app's normal model choice/default,
policy, or budgets; no model request occurred. See the [R-ASTRA-120 ledger](../../MVP-PLAN.md)
for complete evidence and limits.

The later prebuilt-image rehearsal remains a separate step. It binds an immutable candidate image
ID and context digest to the same reviewed PR head SHA, followed by the existing recovery-image
pair. The production publisher was not changed and still requires a clean revision matching exact
`origin/main`.

For a full local pair rehearsal, the optional boolean `--use-deployed-baseline-image` selects the
centrally pinned deployed schema-12 baseline. Omit it to retain the default verified-archive rebuild.
The helper verifies the pinned immutable ID, `linux/amd64` platform, revision label, and a nonempty
valid retained-tag list. The receipt's `schema12_base_image.mode` distinguishes
`reused_exact_deployed_image` from `locally_rebuilt_from_verified_archive`. The reused protected
image is not a generated cleanup target; remove task-generated tags only after ownership checks and
use `docker image rm --no-prune TAG` to preserve untagged ancestors. See [local testing
guidance](../develop/testing.md) for the cleanup
boundary and the [R-ASTRA-120 ledger](../../MVP-PLAN.md) for current evidence. E718/E719 cover
selected tests only; no pair rehearsal ran with the option.

The R-ASTRA-120 candidate helper runs database presence/schema probes with an explicit Python
entrypoint as UID/GID 10001. This prevents the container supervisor from treating `python -c`
as an application CLI command. Schema inspection opens SQLite read-only and fails closed on
invalid output. Independent helper tests passed for this change (E340); actual container probes
and the PR-bound recovery rehearsal remain pending. The earlier E340 database-probe repair was
local and did not update production. The later R-ASTRA-120 candidate rollback uses the existing typed
`rollback(revision, image_id)` call with the exact recovery image ID recorded in the reviewed PR
pair. It validates the candidate revision, pair/source/migration digests and recovery image, checks
that the existing data volume is already at schema 13 before and after stopping the app, then starts
the recorded Compose snapshot with assistant rollout disabled and requires readiness before it
records the recovered release. It does not restore or replace the database. Independent local helper
QA passed 83 tests; its opt-in Docker case was skipped. Live host/container behavior and the actual
PR-bound rollback rehearsal remain pending, so this candidate is not production rollback acceptance.
See the [MVP plan](../../MVP-PLAN.md) for its exact evidence scope.

Current R-ASTRA-120 release status is summarized above; the complete per-run evidence remains in
the [R-ASTRA-120 ledger](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on).
Keep the existing 1 GB plan and backups within the US$15 monthly total cap; no resize, deployment,
rollout, or release is authorized by this documentation status.

### R-ASTRA-106 operator-access and deployment receipt

The pushed reviewed `main` revision is
`de9f45f2d5c562c34e004c658e7cee118af6ef58`. The fixed host helper's direct plan passed with ID
`475203e37dd969d84e10e7a0839f1a28`; two official-client plan attempts returned the generic
`remote_operation_failed` error and remain a limitation. The installed production Compose file
matched SHA-256 `35b4f09c0696a4873302f1127eeeb2d1468f77ce8c9c25d989e8f30af156f14b`. The immutable
GitHub Release archive SHA-256 is
`0e81c7c227ffe15094c5f7557b024e445e3fe61d72138bb57bacc6f6f99f47a0`, and the image ID is
`sha256:bbb6a35143cda6d38883a8294710b2ee143f383077f4e27d6fad0c746ec5a6f1`.

The fixed MCP deploy passed at `2026-10-01T00:20:13Z`. Status reported the pre-deploy backup
`pre-deploy-de9f45f2d5c562c3-497734d9.spbackup`, schema `10` ready,
`loopback_only: true`, and `failed: null`. HTTPS probes returned health `200` and private history
`401`, with `no-store`/`DYNAMIC` responses. This receipt covers the declared operator-access and
deployment scope. No SMTP provider or mailbox delivery was available for verification; owner TOTP
enrollment, authenticated workspace retrieval, physical-mobile/hardware-authenticator evidence,
and full production acceptance remain **Unavailable**.

### Historical schema-8 passkey canary and recovery receipt

The recovery rehearsal passed before the restricted canary. Cloudflare is now in
`exposure_mode=public_invited` after E58's provider-refreshed plan and apply. The exact hostname is
`ledger.jtmb.cc`; the tunnel routes to `http://127.0.0.1:8000`, and the cache-settings rule bypasses
shared/browser caching. The owner-canary Access app was deleted as part of the apply. The GitHub OAuth application authorization and
Cloudflare one-time-code flow completed successfully in the earlier browser session. The final live
in-app-browser reload with an expired session showed `Sign in first` and `Open sign in` and hid
`Create passkey`; opening sign-in and continuing with GitHub returned to
`/passkey?mode=enroll&next=/overview`, showed `Signed in as jtmb`, and showed `Create passkey`.
No ceremony was completed in this browser tab. A read-only operator SQLite check on `2026-09-28`
(exact query UTC not captured) found `quick_check` `ok`, zero foreign-key violations, owner id `1`
claimed to the configured GitHub account as active admin, one nonrevoked passkey, one current
passkey-verified session, and owner mappings of 13 events, 13 runs, 20 results, 0 outcomes, 6
holdings, and 3 watchlist items. This proves enrollment, a completed passkey verification on another
computer, and persisted owner mappings, but not browser-rendered UI retrieval. A fresh production
tab hit Cloudflare Access login with no transferable session. Later read-only Docker access logs
observed authenticated owner API retrieval and saved-forecast access after the passkey session;
`/overview`, portfolio, watchlist, history, and saved-forecast requests returned `200`. The earlier
callback-blocked observation is retained as historical evidence in E38, and E49 remains the prior
origin-navigation record. Browser-rendered owner content remains **Unavailable**. E56 independently
passes the four two-client isolation scenarios locally—cross-watchlist deletion, member `promote=true`
restore denial, nested outcome export, and two-account invitation reuse/identity binding—while remote
two-user behavior and browser UI remain **Unavailable**. E58 makes the public-invited infrastructure
boundary live, but the live IAB had no owner UI session. E59 records legacy-host retirement. E60
records the historical current-machine GitHub OAuth provisional session at `/passkey?mode=verify`,
the browser error `The browser could not create a passkey` after Verify with passkey, a `403`/denied
sign-out response, and the generic verify-mode error using `create`. E61 records the locally accepted
logout and mode-aware passkey repair with independent QA, and E62 records the passing full local gate.
E63 records the historical schema-8 deployment and a post-deploy read-only SQLite check with `quick_check=ok`,
zero foreign-key violations, 13 search events, 13 forecast runs, 20 forecast results, 6 holdings,
3 watchlist items, 1 passkey, and 1 user. The server-observed owner-verified session on another computer and saved API retrieval
in E52/E55 remain valid. Administrator
fresh-passkey backup/restore, rendered owner workspace, live second-user onboarding, and functional
invited-user acceptance remain pending or **Unavailable**. E64's Astra live read-only review found no
P1/P2; its Terraform/image, IPv6, and old-VM rechecks remain **Unavailable**.

### R-ASTRA-103 authenticator release status

The current follow-on retires the ongoing passkey requirement. The deployed schema 10 migration revokes
stored passkeys and old passkey sessions; the application does not create or accept WebAuthn
credentials. After a
fresh GitHub OAuth sign-in, an account without a TOTP factor goes directly to
`/authenticator?mode=enroll`; the old `/passkey` route redirects to authenticator enrollment. An
existing TOTP account still requires its current TOTP or recovery-code replacement flow, so a fresh
GitHub session alone cannot replace the factor.

Scoped independent QA passed `64` authentication/repository/list checks, `123` API checks, `61`
backup/CLI checks, `10` desktop/mobile-emulated auth-flow cases, `27` frontend checks, Ruff, and
diff checks. Fresh schema-10 creation and schema-9-to-10 migration checks passed; the `61`
backup/CLI check set passed. No schema-10 backup/restore rehearsal is claimed. The
owner API flow returned `303` to `/authenticator?mode=enroll`, required TOTP for protected access,
denied private history without a session, and returned `403` for WebAuthn. Existing TOTP factor
replacement remained guarded. Astra's independent medium source security review reported no P1/P2
finding.

The current local `R-ASTRA-103` gate **Passed** for its declared scope. Receipt
`test-results/local-gates/R-ASTRA-103-20260928T235350Z/evidence.json` reports `707` Python tests
passed, `4` live tests deselected, `85.25%` coverage, frontend build/typecheck and `27` frontend
tests, and documentation coverage. The older schema-9 backup is an offline recovery artifact only.
The reviewed schema-10 image is now deployed. Owner TOTP enrollment, authenticated workspace
retrieval, physical mobile, and second-user acceptance remain **Unavailable**.

The exact remote `main` revision `9cc0751da459e911d285b14e0d57a29320a9f366` matched before
publication. GitHub Release `signal-ledger-9cc0751da459e911d285b14e0d57a29320a9f366` has archive
SHA-256 `d60da545be26a050e305e13d2e8db219a253a0668b32f13f532148069bde188e`; publisher re-download
passed. The Linux/amd64 image is `103143811` bytes with ID
`sha256:3e5f242573044114797b66447e3a8139ed35ca7decc387e6f1ab3ef62db486ff`. Restricted MCP plan
`16c6655376c3b80569694ce400a2381c` passed; deploy returned readiness schema `10`, and status
reported backup `pre-deploy-9cc0751da459e911-20833573.spbackup`,
`deployed_at=2026-09-29T00:21:06.828904+00:00`, `failed: null`, and `loopback_only: true`.
At `2026-09-29T00:22:18Z`–`00:22:19Z`, live HTTPS returned health `200`, anonymous history `401`,
overview `303` to sign-in, and `no-store`/`DYNAMIC` responses. `/passkey?mode=verify` returned
`303` to `/authenticator?mode=enroll&next=%2Foverview`. The IAB showed `Sign in first` for the
revoked old session; fresh GitHub sign-in as `jtmb` rendered `Protect your account`, `Setup needed`,
and `Generate setup key` without a WebAuthn prompt.

### R-ASTRA-107 TOTP enrollment key-reuse repair

`R-ASTRA-107` remains **In progress** for complete authentication acceptance. Its key-reuse repair
is included in the deployed `R-ASTRA-110` image at pushed clean `main` revision
`566baab14c298fb52b5edb3138d64cd3e9123311`. Enrollment reuses an unexpired pending setup only for
the same session, factor generation,
and origin; **Start over with new key** rotates it, and the UI shows expiry and disables expired QR
and code use.

In the production in-app browser, repeated starts across reload reused the same pending setup, with
expiry and rotation controls visible. Public health and auth status returned `200`, anonymous history
returned `401`, and `/overview` redirected to sign-in; responses were `no-store`/`DYNAMIC`. No TOTP
code was entered, so owner enrollment and authenticated workspace access remain **Unavailable**.
Physical iPhone code validation is also **Unavailable**. See the [MVP plan](../../MVP-PLAN.md) for the
final-tree gate, release identity, deployment receipt, and historical attempts. This evidence
does not claim complete auth acceptance.

Application backups remain signed and verified. Linode VM Backups are enabled, and successful
snapshot `385239936` is available. The first disposable restore attempt **Failed**: clone
`106821372` reached offline boot, but a concurrent in-place Bash edit corrupted the running process
and it exited `127` before verification; that guarded clone was deleted and its API lookup returned
`404`. The repaired rehearsal then **Passed**: clone `106825234` was restored, verified against the
declared boundaries, deleted, and confirmed `404`. The failed attempt and the repair findings stay
visible in the root evidence ledger. This release has no independent encrypted off-server backup;
Linode's configured VM Backup retention is the external recovery boundary and remains a limitation.

The following local QA counts and schema-8 readiness observation are historical pre-`R-ASTRA-110`
evidence; the current deployed image is schema 10 at revision
`566baab14c298fb52b5edb3138d64cd3e9123311`. The earlier local run included authentication status
`200`, private history `401` without a session, frontend build/typecheck with `28` tests, pinned Playwright desktop/mobile
`2/2`, Luna auth contract `9/9`, click `2/2`, and simulated passkey-cancellation checks on desktop
and mobile. Astra's source review reported no P1/P2 after its `409` guidance finding was repaired.
Focused API/auth `151` tests, helper/MCP `31` tests, and a private remote deployment with migrated
data counts are also recorded. An earlier Astra source review reported no remaining P1/P2 finding
for the deployment-hardening boundary; a later privacy review
found a P2 because the configured owner email reached an embedded Python process argv. The private
owner-email-file repair is complete, the tracked tree has no literal personal email, `14` canary
fixture tests passed, and the live canary script reran exit `0` with the tunnel active. Luna's final
scoped QA passed the focused checks and Astra's final P1/P2 re-review reported no remaining finding
for this boundary. The earlier owner callback observation is historical; E51 records the final live
sign-in recovery. E52 records operator-side owner enrollment, passkey verification, and persisted
mappings, but does not complete authenticated app retrieval or the invited-user release gate.
A subsequent source fix at
commit `a1d868287a729c75d9b8628f612a856db132374a` handles a stale/expired provisional session that
returned `authenticated:false` and left the passkey page at `Checking your session`; build/typecheck,
`28` frontend tests, and browser `4/4` passed locally. The fix is source-reviewed and included in
the final clean-main image.
Independent Luna QA passed Terraform format/validate, `31` scoped infrastructure tests, and
`git diff --check` at the dirty reviewed revision. The earlier review recorded an import-order
finding in the Terraform test; final scoped QA passed all four Ruff checks, so that finding is
historical. The full Linode validator exits `2` on a deliberately dirty worktree. The earlier
Cloudflare token verification `401` and documentation-coverage **Fail** remain historical evidence.
The OAuth authorization and Access code steps completed in the earlier browser session. The final
live session returned to the signed-in passkey-enrollment page, but no ceremony completed in that
browser tab; owner passkey enrollment is operator-verified. E55 records server-observed
authenticated owner API and saved-forecast retrieval, while browser-rendered content remains
**Unavailable**. E56 passes the local four-scenario two-client QA, and E57 records the passing full
local gate after its initial comment-audit failure. E58 records the public-invited boundary and its
live unauthenticated probes. E59 records retirement of legacy Linode `97934478`; E60 records the
current-machine browser limitation; E61-E62 record the locally accepted repair and gate; E63 records
the current deployment; and E64 records Astra's no-P1/P2 live read-only review. Remote two-user/browser
verification, rendered owner workspace, and functional invited-user acceptance remain pending or
**Unavailable**; the current local application is untouched.
