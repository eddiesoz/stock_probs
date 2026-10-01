# Agent Rules

## Codex project workflow

Codex uses this root `AGENTS.md` for repository policy. Its project configuration is
`.codex/config.toml`, its three scoped subagents are `.codex/agents/luna-build.toml`,
`luna-qa.toml`, and `luna-docs.toml`, and its repository skills are in `.agents/skills/`.
The seven shared skill directories there are relative symlinks to the maintained
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
OpenCode evidence only.

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
  The seven approved directory-based definitions are governance entries, not native loader proof.
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
- The documentation map is a fail-closed gate. Workflow/config/profile/plugin/command
  changes require `docs/develop/documentation.md` and the additional `AGENTS.md` policy
  coverage. `.githooks/pre-push` runs `scripts/check-doc-coverage.py`; the completeness,
  change-aware, and isolated self-test commands are read-only. This reconciliation does not
  install hooks, edit Git history, or edit `SESSION-EXPORT.md`.
- Evidence remains architecture-specific: native x86_64, emulated ARM64, and physical
  ARM64 are separate labels. Emulated ARM64 can support package/runtime/functional/build/tool
  claims, not ARM64 performance. Physical mobile, actual screen-reader, true-zoom, native
  ARM64, provider, and project-profile evidence remain **Unavailable** unless directly run.

### Current reconciliation evidence

The approved project governance set contains seven directory-based skill definitions:
`documentation`, `development-conventions`, `stock-probability-skill-maintenance`,
`local-gate-evidence`, `browser-qa`, `database-conventions`, and `security-audit`. Ponytail is
not one of them. This is a static definition/governance count, not native loader or runtime
discovery acceptance. In this harness, native runtime skill discovery remains **Unavailable**
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

`R-ASTRA-103` is the current authenticator-only authentication follow-on. `R-ASTRA-101` and
`R-ASTRA-102` are historical passkey/TOTP deployment records and are not current auth guidance.
The local implementation has schema 10, and the current local gate passed for its declared scope.
The reviewed schema-10 image is now deployed and the live passkey retirement redirect is verified;
owner TOTP enrollment and authenticated workspace retrieval remain **Unavailable**. Physical mobile
and hardware authenticator-device evidence remain **Unavailable**.
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
  fixed controller applied operator SSH `142.198.155.54/32`. No API key exists, no host installation
  has been observed, and no live send or mailbox delivery is verified.
- `R-ASTRA-106-E14` records the local commit
  `42cf0f40c98404d55585745b10311354661a5195` (not pushed) containing
  `infra/linode/install-resend-smtp-key.sh`, `infra/linode/smtp-credential-installer.py`, and
  `tests/test_linode_smtp_credentials.py`; builder checks reported `11` focused tests, Ruff
  check/format, `bash -n`, and ShellCheck **Pass** as self-validation. `R-ASTRA-106-E15` retains
  the initial independent QA P1 remote-shell quoting blocker and P2 incomplete-read rollback
  blocker. `R-ASTRA-106-E16` records the repaired independent QA recheck: `13` tests passed,
  including command parse/probe and incomplete-read rollback, for its declared local scope. No API
  key, host installation, live send, mailbox delivery, or production acceptance is evidenced.
- `R-ASTRA-106-E17` records the final authored-documentation checks **Pass** on native x86_64 at
  `2026-10-01T14:55:29Z`–`14:56:27Z`, dirty `HEAD`
  `42cf0f40c98404d55585745b10311354661a5195`: `.dev-venv/bin/python scripts/validate_docs.py`
  reported `9` categories, `13` topics, and `7` governance entries; documentation tests passed
  `57` with one warning; coverage checked `133` mapped files; the coverage self-test passed `26`
  cases; and scoped `git diff --check -- AGENTS.md README.md MVP-PLAN.md MVP-ROADMAP.md docs`
  exited `0`. Reviewer `LUNA MAX docs`; these checks do not establish installer, host, SMTP,
  mailbox, or production acceptance.
- The intended Resend installer accepts only one operator-owned private, one-line API-key file
  through `infra/linode/install-resend-smtp-key.sh --api-key-file FILE`; host, SSH account, remote
  paths, Compose file, image behavior, and readiness URL remain fixed. The API key must stay outside
  the repository, logs, exports, and evidence. Browser action-time confirmation is still required
  to create the key; no credential-bearing run is authorized or evidenced by this follow-on.

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

### Current authenticator-only follow-on (`R-ASTRA-103`)

- Production retains invite-only GitHub OAuth and the numeric GitHub account ID as the stable
  identity. The sole application second factor is a six-digit TOTP code from an authenticator app.
  The deployed schema-10 migration revokes stored passkeys and old passkey sessions; the application
  does not create or accept WebAuthn credentials.
- After a fresh GitHub OAuth sign-in, an account without a TOTP factor goes directly to
  `/authenticator?mode=enroll`; the old `/passkey` route redirects to that authenticator flow. An
  existing TOTP account still requires its current TOTP or recovery-code replacement flow; a
  fresh GitHub session alone cannot replace the factor.
- Enrollment is short-lived and origin-bound. The setup page provides a manual secret and an
  `otpauth://` link, then returns recovery codes exactly once after a valid code. Recovery codes are
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
  checks. The current catalog has seven skills and no Ponytail package, skill, or gate; current
  documentation validation is recorded in the reconciliation evidence above.
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
