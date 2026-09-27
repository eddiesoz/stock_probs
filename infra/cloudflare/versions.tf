terraform {
  required_version = ">= 1.4.0, < 2.0.0"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

provider "cloudflare" {
  # Terraform reads CLOUDFLARE_API_TOKEN from the environment. Keeping the
  # token out of this configuration prevents it from being written to state.
}
