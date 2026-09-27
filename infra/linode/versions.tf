terraform {
  required_version = ">= 1.16.0, < 2.0.0"

  required_providers {
    linode = {
      source  = "linode/linode"
      version = "= 4.5.0"
    }
    external = {
      source  = "hashicorp/external"
      version = "= 2.4.2"
    }
  }
}

provider "linode" {}
