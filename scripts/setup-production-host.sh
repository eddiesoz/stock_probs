#!/usr/bin/env bash
# Install the fixed Signal Ledger host boundary; credentials and Cloudflare tunnel state are
# supplied separately by the operator and are never generated or printed by this script.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  printf 'This script must run as root.\n' >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_USER="signal-ledger-deploy"
DEPLOY_GROUP="signal-ledger-deploy"
APP_ROOT="/opt/signal-ledger"
STATE_ROOT="/var/lib/signal-ledger"
DEPLOY_PUBLIC_KEY_FILE="${SIGNAL_LEDGER_DEPLOY_PUBLIC_KEY_FILE:-}"
AUTHORIZED_KEYS_DIR="$STATE_ROOT/.ssh"
AUTHORIZED_KEYS="$AUTHORIZED_KEYS_DIR/authorized_keys"
CONFIG_ROOT="/etc/signal-ledger"
LOG_ROOT="/var/log/signal-ledger"
SSH_DROPIN="/etc/ssh/sshd_config.d/signal-ledger-deploy.conf"
HELPER="/usr/local/libexec/signal-ledger-deploy-helper"
WRAPPER="/usr/local/bin/signal-ledger-deploy-helper"
SUDOERS="/etc/sudoers.d/signal-ledger-deploy"
SYSTEMD_UNIT="/etc/systemd/system/signal-ledger-cloudflared.service"

for command in docker git python3 curl install systemctl visudo sshd ssh-keygen getent awk wc grep; do
  command -v "$command" >/dev/null || {
    printf 'Required host command is unavailable: %s\n' "$command" >&2
    exit 3
  }
done

# The deployment account must have one operator-supplied public key before this script makes
# any host changes.  The path is deliberately supplied out-of-band so a private key is never
# needed on the server and an omitted/ambiguous key cannot leave a non-functional SSH boundary.
if [[ -z "$DEPLOY_PUBLIC_KEY_FILE" ]]; then
  printf 'Set SIGNAL_LEDGER_DEPLOY_PUBLIC_KEY_FILE to one public SSH key file.\n' >&2
  exit 4
fi
if [[ -L "$DEPLOY_PUBLIC_KEY_FILE" || ! -f "$DEPLOY_PUBLIC_KEY_FILE" ]]; then
  printf 'SIGNAL_LEDGER_DEPLOY_PUBLIC_KEY_FILE must be a regular, non-symlink file.\n' >&2
  exit 4
fi
KEY_BYTES="$(wc -c < "$DEPLOY_PUBLIC_KEY_FILE")"
if (( KEY_BYTES < 8 || KEY_BYTES > 16 * 1024 )); then
  printf 'The deployment public key file must be between 8 bytes and 16 KiB.\n' >&2
  exit 4
fi
if LC_ALL=C grep -q $'\r' "$DEPLOY_PUBLIC_KEY_FILE"; then
  printf 'The deployment public key file must use Unix line endings.\n' >&2
  exit 4
fi
if [[ "$(awk 'NF { count++ } END { print count + 0 }' "$DEPLOY_PUBLIC_KEY_FILE")" != "1" ]]; then
  printf 'The deployment public key file must contain exactly one key.\n' >&2
  exit 4
fi
read -r DEPLOY_KEY_TYPE DEPLOY_KEY_BLOB _ < "$DEPLOY_PUBLIC_KEY_FILE" || true
if [[ ! "$DEPLOY_KEY_TYPE" =~ ^[[:alnum:]@._+-]+$ || ! "$DEPLOY_KEY_BLOB" =~ ^[A-Za-z0-9+/]+={0,2}$ ]]; then
  printf 'The deployment public key file is not an OpenSSH public key.\n' >&2
  exit 4
fi
if ! ssh-keygen -lf "$DEPLOY_PUBLIC_KEY_FILE" >/dev/null 2>&1; then
  printf 'The deployment public key file failed SSH key validation.\n' >&2
  exit 4
fi
if [[ ! -x /usr/bin/cloudflared ]]; then
  printf 'Install the official cloudflared binary at /usr/bin/cloudflared before setup.\n' >&2
  exit 3
fi
if ! /usr/bin/cloudflared tunnel run --help 2>&1 | grep -q -- '--token-file'; then
  printf 'cloudflared must support remotely managed tunnel token files.\n' >&2
  exit 3
fi

# Publish the operator key only with a fixed command and SSH's restrictive key options.  This
# remains a defense-in-depth boundary if setup stops before the Match block can be reloaded.
publish_restricted_authorized_key() {
  install -o "$DEPLOY_USER" -g "$DEPLOY_GROUP" -m 0600 /dev/stdin "$AUTHORIZED_KEYS" <<EOF
restrict,command="$WRAPPER" $DEPLOY_KEY_TYPE $DEPLOY_KEY_BLOB
EOF
}

if ! getent group "$DEPLOY_GROUP" >/dev/null; then
  groupadd --system "$DEPLOY_GROUP"
fi
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  # sshd must start a real shell before applying ForceCommand; the Match block below still
  # denies an interactive shell, PTY, forwarding, and user-supplied command text.
  useradd --system --home-dir "$STATE_ROOT" --create-home --shell /bin/sh \
    --gid "$DEPLOY_GROUP" "$DEPLOY_USER"
fi
DEPLOY_HOME="$(getent passwd "$DEPLOY_USER" | awk -F: 'NR == 1 { print $6 }')"
if [[ "$DEPLOY_HOME" != "$STATE_ROOT" ]]; then
  printf 'The deployment account has an unexpected home directory.\n' >&2
  exit 3
fi
if ! id cloudflared >/dev/null 2>&1; then
  useradd --system --no-create-home --home-dir /var/lib/cloudflared \
    --shell /usr/sbin/nologin cloudflared
fi

install -d -o root -g "$DEPLOY_GROUP" -m 0750 "$STATE_ROOT"
if [[ -L "$AUTHORIZED_KEYS_DIR" || -L "$AUTHORIZED_KEYS" ]]; then
  printf 'The deployment account SSH authorization path must not be a symlink.\n' >&2
  exit 3
fi
install -d -o "$DEPLOY_USER" -g "$DEPLOY_GROUP" -m 0700 "$AUTHORIZED_KEYS_DIR"
if [[ -L "$AUTHORIZED_KEYS_DIR" || -L "$AUTHORIZED_KEYS" ]]; then
  printf 'The deployment account SSH authorization path must not be a symlink.\n' >&2
  exit 3
fi
# An earlier interrupted setup may have left a bare key. Harden it before any further operation.
if [[ -e "$AUTHORIZED_KEYS" ]]; then
  publish_restricted_authorized_key
fi
usermod --shell /bin/sh "$DEPLOY_USER"
install -d -o root -g "$DEPLOY_GROUP" -m 0750 "$APP_ROOT" "$STATE_ROOT/releases" \
  "$STATE_ROOT/plans" "$CONFIG_ROOT" "$LOG_ROOT" /usr/local/libexec /etc/cloudflared /var/lib/cloudflared
install -o root -g root -m 0644 "$ROOT/compose.production.yaml" "$APP_ROOT/compose.production.yaml"
install -o root -g root -m 0750 "$ROOT/scripts/production-deploy-helper.py" "$HELPER"

# The SSH command is intentionally argument-free.  The Python helper reads one bounded JSON
# request from stdin and sudo permits exactly this executable, avoiding a general shell account.
install -o root -g root -m 0755 /dev/stdin "$WRAPPER" <<'EOF'
#!/bin/sh
set -eu
exec /usr/bin/sudo -n -- /usr/local/libexec/signal-ledger-deploy-helper
EOF
install -o root -g root -m 0440 /dev/stdin "$SUDOERS" <<EOF
$DEPLOY_USER ALL=(root) NOPASSWD: $HELPER ""
EOF
visudo -cf "$SUDOERS" >/dev/null

install -o root -g root -m 0644 /dev/stdin "$SSH_DROPIN" <<EOF
Match User $DEPLOY_USER
    ForceCommand $WRAPPER
    AuthorizedKeysFile $AUTHORIZED_KEYS
    PubkeyAuthentication yes
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AuthenticationMethods publickey
    AllowTcpForwarding no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTunnel no
    PermitTTY no
    PermitUserEnvironment no
    PermitUserRC no
EOF
sshd -t
# On a new host this is the first key publication, and it is already restricted even if reload
# fails. The daemon configuration is syntax-checked before the key is made available to sshd.
publish_restricted_authorized_key
# Activate the Match/ForceCommand boundary after the restricted deployment key is installed.
# A reload keeps existing SSH sessions alive; setup fails closed if neither service exists.
if ! systemctl reload ssh; then
  systemctl reload sshd
fi

if [[ ! -e "$CONFIG_ROOT/app.env" ]]; then
  install -o root -g root -m 0600 /dev/null "$CONFIG_ROOT/app.env"
  printf 'Created %s; populate the production OAuth/origin/session values before deployment.\n' \
    "$CONFIG_ROOT/app.env" >&2
fi
if [[ -L /etc/cloudflared/tunnel.token ]]; then
  printf '/etc/cloudflared/tunnel.token must not be a symlink.\n' >&2
  exit 3
elif [[ ! -e /etc/cloudflared/tunnel.token ]]; then
  printf 'Install the remotely managed tunnel token at /etc/cloudflared/tunnel.token before enabling it.\n' >&2
else
  if [[ ! -f /etc/cloudflared/tunnel.token ]]; then
    printf '/etc/cloudflared/tunnel.token must be a regular file.\n' >&2
    exit 3
  fi
  chmod 0600 /etc/cloudflared/tunnel.token
fi
chown -R cloudflared:cloudflared /etc/cloudflared /var/lib/cloudflared
chmod 0750 /etc/cloudflared /var/lib/cloudflared
if [[ -e /etc/cloudflared/tunnel.token ]]; then
  chmod 0600 /etc/cloudflared/tunnel.token
fi

install -o root -g root -m 0644 /dev/stdin "$SYSTEMD_UNIT" <<'EOF'
[Unit]
Description=Signal Ledger Cloudflare Tunnel
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
User=cloudflared
ExecStart=/usr/bin/cloudflared tunnel run --no-autoupdate --token-file /etc/cloudflared/tunnel.token
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/cloudflared
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
# Keep the public hostname closed until the application and security gates are accepted.
systemctl disable --now signal-ledger-cloudflared.service >/dev/null 2>&1 || true

chown -R root:"$DEPLOY_GROUP" "$STATE_ROOT" "$CONFIG_ROOT" "$LOG_ROOT"
chmod 0750 "$STATE_ROOT" "$STATE_ROOT/releases" "$STATE_ROOT/plans" "$CONFIG_ROOT" "$LOG_ROOT"
chmod 0600 "$CONFIG_ROOT/app.env"
chown "$DEPLOY_USER:$DEPLOY_GROUP" "$AUTHORIZED_KEYS_DIR" "$AUTHORIZED_KEYS"
chmod 0700 "$AUTHORIZED_KEYS_DIR"
chmod 0600 "$AUTHORIZED_KEYS"

printf 'Installed fixed deployment helper and loopback-only production Compose boundary.\n'
printf 'Populate %s and the token file, then enable the tunnel after the security gates.\n' \
  "$CONFIG_ROOT/app.env"
