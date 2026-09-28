"""Terraform contracts keep first boot immutable without replacing the host."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINODE = ROOT / "infra" / "linode"


def test_instance_ignores_only_first_boot_user_data_after_create() -> None:
    """A reviewed revision change must not recreate the stateful instance."""

    main = (LINODE / "main.tf").read_text()
    instance = main.split('resource "linode_instance" "signal_ledger" {', maxsplit=1)[1]

    assert "metadata {" in instance
    assert "user_data = base64encode(templatefile" in instance
    assert "ignore_changes = [metadata[0].user_data]" in instance
    assert "prevent_destroy = true" in instance
    assert "ignore_changes = [metadata]" not in instance


def test_firewall_remains_terraform_managed_and_protected() -> None:
    """Firewall rules stay mutable while accidental destruction remains blocked."""

    main = (LINODE / "main.tf").read_text()
    firewall, instance = main.split(
        'resource "linode_instance" "signal_ledger" {', maxsplit=1
    )

    assert 'resource "linode_firewall" "signal_ledger" {' in firewall
    assert "prevent_destroy = true" in firewall
    assert "ignore_changes" not in firewall
    assert "firewall_id" in instance
    assert "linode_firewall.signal_ledger.id" in instance


def test_validation_keeps_source_gate_and_first_boot_contract_explicit() -> None:
    """Static validation must retain source gates and reject broad metadata ignores."""

    validate = (LINODE / "validate.sh").read_text()

    assert "grep -Fq 'ignore_changes = [metadata[0].user_data]' main.tf" in validate
    assert "grep -Fq 'user_data = base64encode(templatefile' main.tf" in validate
    assert 'grep -Fq \'data "external" "source_gate"\' source-gate.tf' in validate
    assert 'grep -Fq \'data "external" "source_gate_apply"\' source-gate.tf' in validate


def test_first_boot_source_gate_delivers_the_reviewed_cloudflare_unit() -> None:
    """The setup script's tracked tunnel unit must be present in fresh-host source."""

    bootstrap = (LINODE / "bootstrap-production-host.sh").read_text()
    cloud_init = (LINODE / "cloud-init.yaml.tftpl").read_text()
    locals_tf = (LINODE / "locals.tf").read_text()
    main = (LINODE / "main.tf").read_text()
    verify = (LINODE / "verify-source.sh").read_text()
    validate = (LINODE / "validate.sh").read_text()

    assert 'install -d -m 0750 "$SOURCE_ROOT/scripts" "$SOURCE_ROOT/infra/cloudflare"' in bootstrap
    assert (
        'download_verified infra/cloudflare/signal-ledger-cloudflared.service '
        '"$SIGNAL_LEDGER_UNIT_SHA256"'
    ) in bootstrap
    assert 'SIGNAL_LEDGER_UNIT_SHA256=${unit_sha256}' in cloud_init
    assert 'source_unit_sha256' in verify
    assert '"infra/cloudflare/signal-ledger-cloudflared.service"' in locals_tf
    assert 'unit_sha256          = local.reviewed_source_files[' in main
    assert 'SIGNAL_LEDGER_UNIT_SHA256' in validate
