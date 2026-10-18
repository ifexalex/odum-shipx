resource_group_name  = "shipx-tfstate-rg"
storage_account_name = "shipxtfstate01" # set to your bootstrap account (see ../../README.md)
container_name       = "tfstate"
key                  = "azure/subscription/hardened/terraform.tfstate"
use_azuread_auth     = true
