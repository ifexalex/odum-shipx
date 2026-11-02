provider "azurerm" {
  features {}

  # subscription_id is read from ARM_SUBSCRIPTION_ID (or the `az login` context).
  # This root is applied ONCE PER SUBSCRIPTION — make sure the variable points at
  # the subscription you intend to change before applying.
}
