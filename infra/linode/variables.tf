variable "instance_label" {
  description = "Stable Linode label for the Signal Ledger host."
  type        = string
  default     = "signal-ledger"

  validation {
    condition = can(regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$", var.instance_label)) && !strcontains(
      lower(var.instance_label),
      "cardventory",
    )
    error_message = "instance_label must be a short Linode-safe label and must not be cardventory."
  }
}

variable "operator_public_key_path" {
  description = "Path to the existing operator SSH public key used for initial access."
  type        = string
  default     = "~/.ssh/signal-ledger-operator-2026.pub"
}

variable "deploy_public_key_path" {
  description = "Path to the separate SSH public key restricted to the deployment helper."
  type        = string
  default     = "~/.ssh/signal-ledger-deploy-2026.pub"
}

variable "operator_ipv4_cidr" {
  description = "The operator's current public IPv4 address as a single /32 for SSH ingress."
  type        = string

  validation {
    condition     = can(cidrhost(var.operator_ipv4_cidr, 0)) && can(regex("/32$", var.operator_ipv4_cidr))
    error_message = "operator_ipv4_cidr must be one IPv4 address expressed as a /32 CIDR."
  }
}

variable "firewall_id" {
  description = "Existing Linode Cloud Firewall to import and manage."
  type        = number
  default     = 177236117

  validation {
    condition     = var.firewall_id > 0 && floor(var.firewall_id) == var.firewall_id
    error_message = "firewall_id must be a positive integer."
  }
}

variable "firewall_label" {
  description = "Expected label of the existing managed firewall."
  type        = string
  default     = "signal-ledger-fw"
}

variable "reviewed_revision" {
  description = "Reviewed public main commit whose host files are fetched during first boot."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.reviewed_revision))
    error_message = "reviewed_revision must be a 40-character lowercase Git commit SHA."
  }
}
