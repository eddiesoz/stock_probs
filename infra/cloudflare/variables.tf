variable "account_id" {
  description = "Cloudflare account that owns the remote-managed tunnel."
  type        = string
  default     = "f4c09c14a6618297f411e9ee75305013"

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.account_id))
    error_message = "account_id must be a 32-character lowercase Cloudflare account ID."
  }
}

variable "zone_id" {
  description = "Cloudflare zone ID for jtmb.cc."
  type        = string
  default     = "53092409b9e2a417c3af37656b48ce64"

  validation {
    condition     = var.zone_id == "53092409b9e2a417c3af37656b48ce64"
    error_message = "zone_id must be the reviewed jtmb.cc Cloudflare zone ID."
  }
}

variable "zone_name" {
  description = "DNS zone containing the canary hostname."
  type        = string
  default     = "jtmb.cc"

  validation {
    condition     = lower(var.zone_name) == "jtmb.cc"
    error_message = "zone_name is fixed to jtmb.cc for this deployment."
  }
}

variable "tunnel_name" {
  description = "Stable name of the remotely managed Cloudflare Tunnel."
  type        = string
  default     = "signal-ledger"

  validation {
    condition     = var.tunnel_name == "signal-ledger"
    error_message = "tunnel_name is fixed to signal-ledger for this deployment."
  }
}

variable "hostname" {
  description = "Exact hostname used by the owner-only canary and post-canary invite-only route."
  type        = string
  default     = "ledger.jtmb.cc"

  validation {
    condition = (
      lower(var.hostname) == "ledger.jtmb.cc" &&
      !strcontains(var.hostname, "*") &&
      !strcontains(var.hostname, "/") &&
      !strcontains(var.hostname, ":")
    )
    error_message = "hostname is fixed to the exact ledger.jtmb.cc hostname; wildcards and URLs are not allowed."
  }
}

variable "owner_email" {
  description = "Single owner email allowed by Cloudflare Access in closed and canary modes."
  type        = string
  default     = ""

  validation {
    condition = (
      trimspace(var.owner_email) == "" ||
      can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.owner_email))
    )
    error_message = "owner_email must be a valid single email address when provided."
  }
}

variable "exposure_mode" {
  description = "Ingress lifecycle: closed, owner-only canary, or the explicit post-canary invite-only public route."
  type        = string
  default     = "closed"

  validation {
    condition     = contains(["closed", "canary", "public_invited"], var.exposure_mode)
    error_message = "exposure_mode must be closed, canary, or public_invited."
  }
}

variable "public_invited_confirmation" {
  description = "Exact acknowledgement required to remove Cloudflare Access and rely on the app's invite-only authentication."
  type        = string
  default     = ""
}
