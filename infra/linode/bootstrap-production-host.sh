#!/usr/bin/env bash
# Provision only the immutable host boundary; app secrets and tunnel credentials arrive later.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  printf 'This bootstrap must run as root.\n' >&2
  exit 2
fi

: "${SIGNAL_LEDGER_SOURCE_ROOT:?}"
: "${SIGNAL_LEDGER_SOURCE_BASE_URL:?}"
: "${SIGNAL_LEDGER_REVIEWED_REVISION:?}"
: "${SIGNAL_LEDGER_OPERATOR_PUBLIC_KEY_FILE:?}"
: "${SIGNAL_LEDGER_DEPLOY_PUBLIC_KEY_FILE:?}"
: "${SIGNAL_LEDGER_SETUP_SHA256:?}"
: "${SIGNAL_LEDGER_COMPOSE_SHA256:?}"
: "${SIGNAL_LEDGER_HELPER_SHA256:?}"
: "${SIGNAL_LEDGER_UNIT_SHA256:?}"

SOURCE_ROOT="${SIGNAL_LEDGER_SOURCE_ROOT}"
SOURCE_BASE_URL="${SIGNAL_LEDGER_SOURCE_BASE_URL}"
if [[ "$SOURCE_BASE_URL" != */"$SIGNAL_LEDGER_REVIEWED_REVISION" ]]; then
  printf 'The source URL must end at the reviewed commit.\n' >&2
  exit 3
fi
BOOTSTRAP_TMP="$(mktemp -d /var/lib/signal-ledger-bootstrap.XXXXXX)"
trap 'rm -rf -- "$BOOTSTRAP_TMP"' EXIT

for public_key_file in "$SIGNAL_LEDGER_OPERATOR_PUBLIC_KEY_FILE" "$SIGNAL_LEDGER_DEPLOY_PUBLIC_KEY_FILE"; do
  if [[ -L "$public_key_file" || ! -f "$public_key_file" ]]; then
    printf 'SSH public keys must be regular files.\n' >&2
    exit 3
  fi
  if ! ssh-keygen -lf "$public_key_file" >/dev/null 2>&1; then
    printf 'An SSH public key failed validation.\n' >&2
    exit 3
  fi
done
operator_key_fingerprint="$(ssh-keygen -lf "$SIGNAL_LEDGER_OPERATOR_PUBLIC_KEY_FILE" -E sha256 | awk 'NR == 1 { print $2 }')"
deploy_key_fingerprint="$(ssh-keygen -lf "$SIGNAL_LEDGER_DEPLOY_PUBLIC_KEY_FILE" -E sha256 | awk 'NR == 1 { print $2 }')"
if [[ -z "$operator_key_fingerprint" || "$operator_key_fingerprint" == "$deploy_key_fingerprint" ]]; then
  printf 'The operator and deployment SSH public keys must be different.\n' >&2
  exit 3
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg git openssh-server python3 sudo

install -d -m 0755 /etc/apt/keyrings
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
  https://download.docker.com/linux/ubuntu/gpg -o "$BOOTSTRAP_TMP/docker.asc"
install -o root -g root -m 0644 "$BOOTSTRAP_TMP/docker.asc" /etc/apt/keyrings/docker.asc
source /etc/os-release
host_arch="$(dpkg --print-architecture)"
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $host_arch
Signed-By: /etc/apt/keyrings/docker.asc
EOF

install -d -m 0755 /usr/share/keyrings
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
  https://pkg.cloudflare.com/cloudflare-main.gpg \
  -o "$BOOTSTRAP_TMP/cloudflare-main.gpg"
install -o root -g root -m 0644 "$BOOTSTRAP_TMP/cloudflare-main.gpg" \
  /usr/share/keyrings/cloudflare-main.gpg
printf '%s\n' \
  'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
  > /etc/apt/sources.list.d/cloudflared.list

apt-get update
apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin cloudflared
systemctl enable --now docker

# The setup script checks for a regular token path, but the real tunnel credential is supplied
# separately by the operator. An empty root-owned marker lets the public connector stay disabled.
install -d -o root -g root -m 0750 /etc/cloudflared
if [[ ! -e /etc/cloudflared/tunnel.token ]]; then
  install -o root -g root -m 0600 /dev/null /etc/cloudflared/tunnel.token
fi

install -d -m 0750 "$SOURCE_ROOT/scripts" "$SOURCE_ROOT/infra/cloudflare"
download_verified() {
  local relative_path="$1"
  local expected_sha256="$2"
  local destination="$SOURCE_ROOT/$relative_path"
  local temporary
  temporary="$BOOTSTRAP_TMP/$(basename "$relative_path").download"
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    --max-time 60 --output "$temporary" "$SOURCE_BASE_URL/$relative_path"
  if [[ "$(sha256sum "$temporary" | awk '{print $1}')" != "$expected_sha256" ]]; then
    printf 'Reviewed source checksum mismatch: %s\n' "$relative_path" >&2
    exit 4
  fi
  install -o root -g root -m 0644 "$temporary" "$destination"
}

download_verified scripts/setup-production-host.sh "$SIGNAL_LEDGER_SETUP_SHA256"
download_verified compose.production.yaml "$SIGNAL_LEDGER_COMPOSE_SHA256"
download_verified scripts/production-deploy-helper.py "$SIGNAL_LEDGER_HELPER_SHA256"
download_verified infra/cloudflare/signal-ledger-cloudflared.service "$SIGNAL_LEDGER_UNIT_SHA256"
chmod 0750 "$SOURCE_ROOT/scripts/setup-production-host.sh"

if ! id signalops >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash --groups sudo signalops
else
  usermod --shell /bin/bash --groups sudo signalops
fi
install -d -o signalops -g signalops -m 0700 /home/signalops/.ssh
install -o signalops -g signalops -m 0600 "$SIGNAL_LEDGER_OPERATOR_PUBLIC_KEY_FILE" \
  /home/signalops/.ssh/authorized_keys
printf '%s\n' 'signalops ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/signalops
chown root:root /etc/sudoers.d/signalops
chmod 0440 /etc/sudoers.d/signalops
visudo -cf /etc/sudoers.d/signalops >/dev/null

SIGNAL_LEDGER_DEPLOY_PUBLIC_KEY_FILE="$SIGNAL_LEDGER_DEPLOY_PUBLIC_KEY_FILE" \
  bash "$SOURCE_ROOT/scripts/setup-production-host.sh"

install -o root -g root -m 0644 /dev/stdin /etc/ssh/sshd_config.d/99-signal-ledger-hardening.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
EOF
# Cloud-init can reach this check before the SSH service creates its runtime directory.
install -d -o root -g root -m 0755 /run/sshd
sshd -t
if ! systemctl reload ssh; then
  systemctl reload sshd
fi

# The tunnel unit is installed for the later canary but remains stopped and disabled on first boot.
systemctl disable --now signal-ledger-cloudflared.service >/dev/null 2>&1 || true

printf 'Signal Ledger host bootstrap completed; Cloudflare Tunnel remains disabled.\n'
