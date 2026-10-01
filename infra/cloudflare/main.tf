locals {
  origin_service     = "http://127.0.0.1:8000"
  cache_ruleset_name = "Signal Ledger cache bypass"

  # Cloudflare requires a terminal ingress rule. The terminal 404 is kept in
  # closed mode so an unmatched request cannot fall through to the origin.
  default_ingress = {
    hostname       = null
    path           = null
    service        = "http_status:404"
    origin_request = null
  }

  canary_ingress = {
    hostname       = var.hostname
    path           = null
    service        = local.origin_service
    origin_request = null
  }

  tunnel_ingress = var.exposure_mode == "closed" ? [local.default_ingress] : [local.canary_ingress, local.default_ingress]
}

# Cloudflare allows one zone entrypoint ruleset for each phase. Read the live
# list before planning so an unrelated cache-settings ruleset cannot be
# replaced accidentally. The returned list intentionally omits rule bodies;
# an existing ruleset with the managed name must be imported and reviewed
# before the first apply rather than being treated as equivalent by name.
data "cloudflare_rulesets" "zone" {
  zone_id   = var.zone_id
  max_items = 1000
}

locals {
  conflicting_cache_rulesets = [
    for ruleset in data.cloudflare_rulesets.zone.rulesets : ruleset
    if ruleset.kind == "zone" &&
    ruleset.phase == "http_request_cache_settings" &&
    ruleset.name != local.cache_ruleset_name
  ]
}

resource "terraform_data" "cache_ruleset_guard" {
  # Include the IDs so a newly discovered live conflict invalidates the
  # planned graph and cannot be hidden by a stable Terraform input.
  input = join(",", sort([for ruleset in local.conflicting_cache_rulesets : ruleset.id]))

  lifecycle {
    precondition {
      condition     = length(local.conflicting_cache_rulesets) == 0
      error_message = "The zone already has an unrelated http_request_cache_settings ruleset; import/reconcile it before enabling Signal Ledger cache bypass."
    }
  }
}

resource "cloudflare_ruleset" "signal_ledger_cache_bypass" {
  zone_id     = var.zone_id
  name        = local.cache_ruleset_name
  description = "Bypass shared and browser caching for Signal Ledger HTML and authenticated API responses."
  kind        = "zone"
  phase       = "http_request_cache_settings"

  # This is the sole rule in the zone cache-settings entrypoint. The stable
  # ref makes its precedence explicit if more rules are added later.
  rules = [{
    action = "set_cache_settings"
    action_parameters = {
      cache = false
      browser_ttl = {
        mode = "bypass"
      }
    }
    description = "Bypass cache for the exact Signal Ledger hostname."
    enabled     = true
    expression  = "(http.host eq \"${var.hostname}\")"
    ref         = "signal-ledger-cache-bypass"
  }]

  depends_on = [terraform_data.cache_ruleset_guard]
}

resource "terraform_data" "exposure_guard" {
  # Keeping one guard in every mode makes every exposure transition explicit in
  # the dependency graph, including the protected closed state.
  count = 1

  input = var.exposure_mode

  lifecycle {
    precondition {
      condition = (
        var.exposure_mode == "public_invited" || trimspace(var.owner_email) != ""
      )
      error_message = "closed and canary modes require owner_email for the protective Access policy."
    }

    precondition {
      condition = (
        var.exposure_mode != "public_invited" ||
        var.public_invited_confirmation == "I_UNDERSTAND_APP_INVITE_ONLY_AUTH"
      )
      error_message = "public_invited requires public_invited_confirmation=I_UNDERSTAND_APP_INVITE_ONLY_AUTH to remove Cloudflare Access."
    }
  }
}

resource "cloudflare_zero_trust_tunnel_cloudflared" "signal_ledger" {
  account_id = var.account_id
  name       = var.tunnel_name
  config_src = "cloudflare"

  lifecycle {
    prevent_destroy = true
  }
}

resource "cloudflare_zero_trust_tunnel_cloudflared_config" "signal_ledger" {
  account_id = var.account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.signal_ledger.id
  source     = "cloudflare"

  config = {
    ingress = local.tunnel_ingress
  }

  depends_on = [
    terraform_data.exposure_guard,
    terraform_data.cache_ruleset_guard,
    cloudflare_ruleset.signal_ledger_cache_bypass,
    cloudflare_zero_trust_access_application.canary,
  ]
}

resource "cloudflare_zero_trust_access_application" "canary" {
  # The closed state deliberately retains the owner-only Access application
  # while DNS and tunnel ingress are disabled. This makes the later public
  # transition start from a protected, non-routable state.
  count = var.exposure_mode == "public_invited" ? 0 : 1

  zone_id                    = var.zone_id
  name                       = "Signal Ledger owner canary"
  domain                     = var.hostname
  type                       = "self_hosted"
  session_duration           = "12h"
  enable_binding_cookie      = true
  http_only_cookie_attribute = true
  # GitHub's OAuth callback is a cross-site top-level GET. Lax keeps the Access
  # session on that redirect while still withholding it from cross-site POSTs.
  same_site_cookie_attribute = "lax"
  destinations = [{
    type = "public"
    uri  = var.hostname
  }]
  policies = [{
    decision   = "allow"
    name       = "Signal Ledger owner"
    precedence = 1
    include = [{
      email = {
        email = var.owner_email
      }
    }]
  }]

  depends_on = [
    terraform_data.exposure_guard,
  ]
}

resource "cloudflare_dns_record" "canary" {
  count = var.exposure_mode == "closed" ? 0 : 1

  zone_id = var.zone_id
  name    = var.hostname
  type    = "CNAME"
  ttl     = 1
  content = "${cloudflare_zero_trust_tunnel_cloudflared.signal_ledger.id}.cfargotunnel.com"
  proxied = true

  depends_on = [
    terraform_data.exposure_guard,
    terraform_data.cache_ruleset_guard,
    cloudflare_ruleset.signal_ledger_cache_bypass,
    cloudflare_zero_trust_access_application.canary,
    cloudflare_zero_trust_tunnel_cloudflared_config.signal_ledger,
  ]
}

# Resend outbound sending-domain records use automatic TTL and DNS-only mode.
# No inbound mail records are managed here.
resource "cloudflare_dns_record" "resend_dkim" {
  zone_id = var.zone_id
  name    = "resend._domainkey.mail.jtmb.cc"
  type    = "TXT"
  ttl     = 1
  content = "p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCqC7+bnHbClSkSEa0aQHOCFiq36lBMxzF8mheD9T7hDhEJ7AyWrTQ95NIysLGxOepwWPpAMnb4xXQ+XDvM4A4Kz0C0jxYJ2dd9Rhw3C4aavfsFnDJHjg8U6jM0lasnkPdo9rbYTzrPG/Qt9UZ3qRgICJkQxWnr/1zyoikHuDg3aQIDAQAB"
  proxied = false
}

resource "cloudflare_dns_record" "resend_return_path" {
  zone_id = var.zone_id
  name    = "rsend.mail.jtmb.cc"
  type    = "CNAME"
  ttl     = 1
  content = "rsend.forge.rmta.net"
  proxied = false
}

resource "cloudflare_dns_record" "resend_tracking" {
  zone_id = var.zone_id
  name    = "send.mail.jtmb.cc"
  type    = "CNAME"
  ttl     = 1
  content = "send.forge.rmta.net"
  proxied = false
}
