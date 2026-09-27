import {
  to = linode_firewall.signal_ledger
  id = tostring(var.firewall_id)
}

resource "linode_firewall" "signal_ledger" {
  label           = var.firewall_label
  inbound_policy  = "DROP"
  outbound_policy = "ACCEPT"
  depends_on      = [data.external.source_gate, data.external.source_gate_apply]

  inbound {
    label    = "ssh-operator"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = "22"
    ipv4     = [var.operator_ipv4_cidr]
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "linode_instance" "signal_ledger" {
  label           = var.instance_label
  image           = "linode/ubuntu24.04"
  region          = "us-east"
  type            = "g6-nanode-1"
  backups_enabled = true
  disk_encryption = "enabled"
  authorized_keys = [local.operator_public_key]
  booted          = true
  firewall_id     = linode_firewall.signal_ledger.id
  depends_on      = [data.external.source_gate, data.external.source_gate_apply]

  metadata {
    user_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
      bootstrap_script_b64 = base64encode(file("${path.module}/bootstrap-production-host.sh"))
      operator_public_key  = local.operator_public_key
      deploy_public_key    = local.deploy_public_key
      reviewed_revision    = var.reviewed_revision
      source_base_url      = local.source_base_url
      setup_sha256         = local.reviewed_source_files["scripts/setup-production-host.sh"]
      compose_sha256       = local.reviewed_source_files["compose.production.yaml"]
      helper_sha256        = local.reviewed_source_files["scripts/production-deploy-helper.py"]
    }))
  }

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = local.operator_public_key != local.deploy_public_key
      error_message = "operator_public_key_path and deploy_public_key_path must contain different SSH public keys."
    }
  }
}
