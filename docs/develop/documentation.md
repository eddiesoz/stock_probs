---
title: "Documentation"
description: "Repository rules for authored pages, authoritative root records, generated exports, taxonomy links, and deterministic audits."
---

# Documentation

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

Codex discovers repository skills in `.agents/skills/`. Seven relative symlinks point to the
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

### Local deployment MCP boundary

Both `.codex/config.toml` and `opencode.json` declare the enabled local
`signal-ledger-deploy` MCP with `./scripts/deploy-mcp.sh`. The wrapper runs the separate,
locked `tools/deploy_mcp` project over stdio; Codex allows a 30-second startup and 1,800-second
tool deadline, while OpenCode declares the same catalog and execution limits. This is a static
configuration contract. It does not prove that a running parent loaded the server or that an SSH
target is configured.

The server exposes six typed tools: `inspect`, `plan_deploy`, `deploy`, `status`, `rollback`, and
`refresh_operator_access(operator_ipv4_cidr)`. The default release shape accepts a 40-character reviewed commit, a 64-hex archive
SHA-256, and a full `sha256:<64-hex>` Docker image ID; the publisher derives the GitHub Release
tag and asset URL from that commit. The controller reads one fixed target and SSH identity from
its process environment, then sends bounded JSON through `ssh -T` to the fixed remote command
`signal-ledger-deploy-helper`. Tool requests cannot provide shell text, arbitrary host or
filesystem paths, URLs, Compose edits, registry names, mutable tags, or Docker-socket operations.
The helper verifies the fixed release asset bytes before loading the image, then checks image ID,
platform, revision, Compose bytes, schema, backup, and readiness before promotion. An explicit
`SIGNAL_LEDGER_IMAGE_PUBLISH_MODE=ghcr` remains a compatibility transport for already staged
GHCR plans; it is not the default. Rollback is schema-compatible and responses are bounded and
credential-free.

The `refresh_operator_access(operator_ipv4_cidr)` operation is constrained to one canonical IPv4
`/32` and the fixed `linode_firewall.signal_ledger` operator SSH rule. It uses the fixed external
private Terraform state and the existing clean-tree, exact-`origin/main`, reviewed-revision source
gate; it accepts no caller-supplied command, path, state, or credential. A successful local QA
discovery of six tools does not establish a live firewall refresh or deployment.

The current `.codex/config.toml` supplies the fixed target through a nonsecret `env` table:
the host, restricted deployment user, and operator-owned paths for the SSH identity and known-host
file. The key and known-host bytes remain outside the repository; no credential value belongs in
the configuration or authored documentation. Static discovery in a fresh CLI task found the
server and its typed tools (the task ID was not supplied). The locked stdio discovery check
initialized the fixed-target server, listed exactly six typed tools, and completed read-only
`inspect` with `is_error=False` and bounded text content; credential bytes were not printed. A fresh
Codex client invocation remains **Unavailable** because the current host approval
policy is `never`, so that client result does not replace the protocol-client pass or establish
deploy/rollback acceptance.

After changing either MCP configuration, `scripts/deploy-mcp.sh`, `tools/deploy_mcp/**`, or its
lock, restart the parent process and open a fresh Codex/OpenCode task to verify that the server
appears in the tool catalog and that its typed tools are discoverable. A configuration parse,
file-presence check, or the editing session is not runtime discovery evidence. With
`OPENCODE_DISABLE_PROJECT_CONFIG=1`, project MCP discovery is **Pending**/**Unavailable** and no
deployment or provider acceptance may be inferred.

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
`opencode.json`. The seven approved directory-based definitions are governance entries only. Their
`metadata.json` files,
`alwaysApply: false`, `.opencode/SKILL-INDEX.md`, the allow-list in `scripts/validate_docs.py`,
and `.opencode/skill-history/learnings.md` support static consistency and history; none is native
loader/discovery proof. Native runtime skill discovery is **Unavailable** in this harness because
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

The approved project governance set contains seven directory-based skill definitions:
`documentation`, `development-conventions`, `stock-probability-skill-maintenance`,
`local-gate-evidence`, `browser-qa`, `database-conventions`, and `security-audit`. This static
definition count is not native loader or runtime discovery acceptance. The current `R-ASTRA-98`
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
route is not the current setup flow. The current deployment is `R-ASTRA-110`, schema 10; the
R-ASTRA-102 checks and release details below remain historical evidence. `R-ASTRA-111` tracks a
source-only schema-11 OAuth admission change, including clearing OAuth transaction rows, a verified
schema-10 pre-migration backup, and production Compose ingress attribution installed through the
existing reviewed host-Compose updater. The scoped Sol security review and independent Luna Docker
bridge regression passed. The first full local gate failed on four stale schema-10 test expectations;
the corrected full gate passed, and parent integrated review found no blocker for the declared local
scope. The change is not deployed; production remains schema 10.
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
skill in that historical catalog, and fresh discovery was recorded as **Pass**. The current
reconciliation records seven approved directory-based skill definitions/governance entries after
Ponytail retirement; this static governance wording does not establish native loader/discovery
acceptance. Skill/profile activation still requires a parent OpenCode restart and independent
post-restart discovery; implementation presence does not create that gate effect.

The validator checks heading anchors, high-confidence credential patterns, duplicate taxonomy
links, exact description parity between the skill frontmatter, project catalog metadata, and
skill index, and the active skill's 500-line limit. Prose duplication is a manual review rather
than a validator heuristic. These are static governance checks; metadata, the index, the
allow-list, and `SKILL.md` frontmatter do not establish that a native loader discovered a skill.
Native V2's directory-based auto-discovery is the loader boundary, and runtime discovery remains
**Unavailable** in this harness.
