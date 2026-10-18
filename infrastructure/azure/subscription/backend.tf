terraform {
  backend "azurerm" {
    # Configured per subscription via
    #   -backend-config=environments/{dev,hardened}.backend.hcl
    # State lives in the same bootstrap account as the per-environment roots but
    # under a distinct key, because this root owns SUBSCRIPTION-scoped settings
    # and must never share state with an environment stack.
    #   resource_group_name  = "shipx-tfstate-rg"
    #   storage_account_name = "shipxtfstate<suffix>"
    #   container_name       = "tfstate"
    #   key                  = "azure/subscription/{name}/terraform.tfstate"
    #   use_azuread_auth     = true
  }
}
