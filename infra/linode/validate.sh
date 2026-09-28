#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TF_BIN="${TERRAFORM_BIN:-$HOME/.cache/signal-ledger-terraform/terraform}"
if [[ ! -x "$TF_BIN" ]]; then
  TF_BIN="$(command -v terraform)"
fi

cd "$ROOT/infra/linode"
"$TF_BIN" fmt -check -diff
"$TF_BIN" init -backend=false -input=false -upgrade=false
"$TF_BIN" validate
bash -n bootstrap-production-host.sh
bash -n retire-legacy-linode.sh

grep -Eq 'type[[:space:]]*=[[:space:]]*"g6-nanode-1"' main.tf
grep -Eq 'image[[:space:]]*=[[:space:]]*"linode/ubuntu24.04"' main.tf
grep -Eq 'region[[:space:]]*=[[:space:]]*"us-east"' main.tf
grep -Eq 'backups_enabled[[:space:]]*=[[:space:]]*true' main.tf
grep -Eq 'disk_encryption[[:space:]]*=[[:space:]]*"enabled"' main.tf
grep -Eq 'inbound_policy[[:space:]]*=[[:space:]]*"DROP"' main.tf
grep -Eq 'outbound_policy[[:space:]]*=[[:space:]]*"ACCEPT"' main.tf
grep -Eq 'ports[[:space:]]*=[[:space:]]*"22"' main.tf
if grep -Eq 'ports[[:space:]]*=[[:space:]]*"(80|443|8000)"' main.tf; then
  printf 'Application ports must not be opened by the host firewall.\n' >&2
  exit 1
fi
grep -Fq 'prevent_destroy = true' main.tf
grep -Fq 'user_data = base64encode(templatefile' main.tf
grep -Fq 'ignore_changes = [metadata[0].user_data]' main.tf
if grep -Fq 'ignore_changes = [metadata]' main.tf; then
  printf 'Only first-boot metadata.user_data may be ignored after instance creation.\n' >&2
  exit 1
fi
grep -Fq 'authorized_keys = [local.operator_public_key]' main.tf
grep -Fq 'deploy_public_key_path' variables.tf
grep -Fq 'local.operator_public_key != local.deploy_public_key' main.tf
grep -Fq 'hashicorp/external' versions.tf
grep -Fq 'version = "= 4.5.0"' versions.tf
grep -Fq 'version = "= 2.4.2"' versions.tf
grep -Fq 'data "external" "source_gate"' source-gate.tf
grep -Fq 'data "external" "source_gate_apply"' source-gate.tf
grep -Fq 'apply_nonce       = timestamp()' source-gate.tf
grep -Fq 'verify-source.sh' source-gate.tf
grep -Fq 'https://raw.githubusercontent.com/eddiesoz/stock_probs/' locals.tf
[[ "$(grep -Fc 'depends_on      = [data.external.source_gate, data.external.source_gate_apply]' main.tf)" -eq 2 ]]
if grep -Fq 'variable "public_repository"' variables.tf; then
  printf 'The deployment repository must be fixed to eddiesoz/stock_probs.\n' >&2
  exit 1
fi
grep -Fq 'SIGNAL_LEDGER_DEPLOY_PUBLIC_KEY_FILE=/var/lib/signal-ledger/deploy.pub' cloud-init.yaml.tftpl
grep -Fq 'SIGNAL_LEDGER_UNIT_SHA256=${unit_sha256}' cloud-init.yaml.tftpl
grep -Fq 'The operator and deployment SSH public keys must be different.' bootstrap-production-host.sh
if grep -Fq 'root_pass' main.tf; then
  printf 'The instance must not use a root password.\n' >&2
  exit 1
fi

operator_key_path="${SIGNAL_LEDGER_OPERATOR_PUBLIC_KEY_PATH:-$HOME/.ssh/signal-ledger-operator-2026.pub}"
deploy_key_path="${SIGNAL_LEDGER_DEPLOY_PUBLIC_KEY_PATH:-$HOME/.ssh/signal-ledger-deploy-2026.pub}"
if [[ -f "$operator_key_path" && -f "$deploy_key_path" ]]; then
  operator_key_fingerprint="$(ssh-keygen -lf "$operator_key_path" -E sha256 | awk 'NR == 1 { print $2 }')"
  deploy_key_fingerprint="$(ssh-keygen -lf "$deploy_key_path" -E sha256 | awk 'NR == 1 { print $2 }')"
  if [[ -z "$operator_key_fingerprint" || "$operator_key_fingerprint" == "$deploy_key_fingerprint" ]]; then
    printf 'The operator and deployment SSH public keys must be different.\n' >&2
    exit 1
  fi
fi
grep -Fq 'cloudflared' bootstrap-production-host.sh
grep -Fq 'SIGNAL_LEDGER_UNIT_SHA256' bootstrap-production-host.sh
grep -Fq 'download_verified infra/cloudflare/signal-ledger-cloudflared.service "$SIGNAL_LEDGER_UNIT_SHA256"' bootstrap-production-host.sh
grep -Fq '"infra/cloudflare/signal-ledger-cloudflared.service"' locals.tf
grep -Fq 'systemctl disable --now signal-ledger-cloudflared.service' bootstrap-production-host.sh
grep -Fq 'PermitRootLogin no' bootstrap-production-host.sh
grep -Fq 'PasswordAuthentication no' bootstrap-production-host.sh
grep -Fq 'OLD_INSTANCE_ID=97934478' retire-legacy-linode.sh
grep -Fq 'DELETE-LEGACY-97934478' retire-legacy-linode.sh
grep -Fq 'backup_recovery' retire-legacy-linode.sh
grep -Fq 'data_migration' retire-legacy-linode.sh
grep -Fq 'owner_canary' retire-legacy-linode.sh
grep -Fq 'if [[ "$EXECUTE" != true ]]' retire-legacy-linode.sh
grep -Fq '"$API_ROOT/$OLD_INSTANCE_ID"' retire-legacy-linode.sh
grep -Fq 'LINODE_TOKEN must be a bounded single-line token' retire-legacy-linode.sh
if grep -Fq -- '--location' retire-legacy-linode.sh; then
  printf 'Fixed Linode API calls must not follow redirects.\n' >&2
  exit 1
fi

grep -Fq 'EXPECTED_REPOSITORY="https://github.com/eddiesoz/stock_probs.git"' verify-source.sh
grep -Fq 'status --porcelain --untracked-files=normal' verify-source.sh
grep -Fq 'ls-remote --exit-code --refs "$EXPECTED_REPOSITORY" refs/heads/main' verify-source.sh
grep -Fq 'reviewed_revision" == "$head_revision"' verify-source.sh
grep -Fq 'query must contain reviewed_revision and optional apply_nonce' verify-source.sh
grep -Fq 'apply_nonce must be an RFC3339 timestamp' verify-source.sh
grep -Fq 'source_unit_sha256' verify-source.sh

head_revision="$(git -C "$ROOT" rev-parse --verify HEAD)"
if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=normal)" ]]; then
  printf 'The source tree must be clean before validating deployment inputs.\n' >&2
  exit 2
fi
remote_main="$(git -C "$ROOT" ls-remote origin refs/heads/main | awk 'NR == 1 { print $1 }')"
if [[ ! "$head_revision" =~ ^[0-9a-f]{40}$ || "$remote_main" != "$head_revision" ]]; then
  printf 'HEAD must be an exact match for origin/main before deployment validation.\n' >&2
  exit 2
fi
reviewed_revision="${SIGNAL_LEDGER_REVIEWED_REVISION:-}"
if [[ ! "$reviewed_revision" =~ ^[0-9a-f]{40}$ || "$reviewed_revision" != "$head_revision" ]]; then
  printf 'Set SIGNAL_LEDGER_REVIEWED_REVISION to the clean HEAD SHA before apply.\n' >&2
  exit 2
fi
for relative_path in scripts/setup-production-host.sh compose.production.yaml scripts/production-deploy-helper.py infra/cloudflare/signal-ledger-cloudflared.service; do
  source_path="$ROOT/$relative_path"
  [[ -f "$source_path" && ! -L "$source_path" ]]
  source_sha256="$(sha256sum "$source_path" | awk '{print $1}')"
  [[ "$source_sha256" =~ ^[0-9a-f]{64}$ ]]
done
printf 'Terraform and bootstrap static checks passed.\n'
