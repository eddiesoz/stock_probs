locals {
  operator_public_key = trimspace(file(pathexpand(var.operator_public_key_path)))
  deploy_public_key   = trimspace(file(pathexpand(var.deploy_public_key_path)))

  # The external source gate verifies the checkout, remote main, reviewed revision, and these
  # exact files before Terraform can plan or apply. Its results are used directly in cloud-init.
  reviewed_source_files = {
    "scripts/setup-production-host.sh"                   = data.external.source_gate.result["source_setup_sha256"]
    "compose.production.yaml"                            = data.external.source_gate.result["source_compose_sha256"]
    "scripts/production-deploy-helper.py"                = data.external.source_gate.result["source_helper_sha256"]
    "infra/cloudflare/signal-ledger-cloudflared.service" = data.external.source_gate.result["source_unit_sha256"]
  }

  source_base_url = "https://raw.githubusercontent.com/eddiesoz/stock_probs/${var.reviewed_revision}"
}
