terraform {
  backend "azurerm" {
    # Configured per environment via -backend-config=environments/{env}.backend.hcl.
    # Uses Entra (AAD) auth — the CI deploy identity (OIDC federated creds) needs
    # "Storage Blob Data Contributor" on the tfstate container. One-time bootstrap
    # of the state storage account is documented in README.md → "Terraform state".
    #   resource_group_name  = "shipx-tfstate-rg"
    #   storage_account_name = "shipxtfstate<suffix>"
    #   container_name       = "tfstate"
    #   key                  = "azure/{environment}/terraform.tfstate"
    #   use_azuread_auth     = true
  }
}
