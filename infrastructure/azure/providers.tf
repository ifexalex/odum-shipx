provider "azurerm" {
  features {}

  # subscription_id is read from ARM_SUBSCRIPTION_ID (or `az login` context).
  # Set via env: ARM_SUBSCRIPTION_ID / ARM_TENANT_ID / ARM_CLIENT_ID / ARM_CLIENT_SECRET
  # (service principal) or `az login` for local use.
}
