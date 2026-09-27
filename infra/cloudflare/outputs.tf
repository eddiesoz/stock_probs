output "tunnel_id" {
  description = "Remote-managed Cloudflare Tunnel UUID. Use this with fetch-tunnel-token.sh after an approved apply."
  value       = cloudflare_zero_trust_tunnel_cloudflared.signal_ledger.id
}

output "tunnel_name" {
  description = "Remote-managed Cloudflare Tunnel name."
  value       = cloudflare_zero_trust_tunnel_cloudflared.signal_ledger.name
}

output "cache_ruleset_id" {
  description = "Zone cache-settings ruleset that bypasses shared and browser caching for the exact hostname."
  value       = cloudflare_ruleset.signal_ledger_cache_bypass.id
}

output "exposure_mode" {
  description = "Declared ingress lifecycle mode."
  value       = var.exposure_mode
}

output "public_hostname" {
  description = "Exact public hostname, or null while the route is closed."
  value       = var.exposure_mode == "closed" ? null : var.hostname
}
