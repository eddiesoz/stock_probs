output "instance_id" {
  description = "Replacement Signal Ledger Linode ID."
  value       = linode_instance.signal_ledger.id
}

output "instance_ipv4" {
  description = "Replacement Signal Ledger Linode public IPv4 address."
  value       = tolist(linode_instance.signal_ledger.ipv4)[0]
}

output "firewall_id" {
  description = "Managed Signal Ledger firewall ID."
  value       = linode_firewall.signal_ledger.id
}

output "reviewed_revision" {
  description = "Reviewed source revision used by first-boot provisioning."
  value       = var.reviewed_revision
}
