# ---------------------------------------------------------------------------
# Azure Communication Services (Email) — the analogue of the AWS `ses` module.
# Feeds shared/providers/azure/acs_email.py (AcsEmailProvider) via
# AZURE_COMMUNICATION_CONNECTION_STRING. Uses an Azure-managed email domain
# (DoNotReply@<guid>.azurecomm.net) so sending works immediately without DNS
# verification — the analogue of an SES sandbox identity; swap for a custom
# verified domain in prod.
# ---------------------------------------------------------------------------

resource "azurerm_email_communication_service" "main" {
  name                = "${var.name_prefix}-email"
  resource_group_name = var.resource_group_name
  data_location       = var.data_location
  tags                = var.common_tags
}

resource "azurerm_email_communication_service_domain" "managed" {
  name              = "AzureManagedDomain"
  email_service_id  = azurerm_email_communication_service.main.id
  domain_management = "AzureManaged"
  tags              = var.common_tags
}

resource "azurerm_communication_service" "main" {
  name                = "${var.name_prefix}-acs"
  resource_group_name = var.resource_group_name
  data_location       = var.data_location
  tags                = var.common_tags
}

# Link the managed email domain to the Communication Service so it can send.
resource "azurerm_communication_service_email_domain_association" "main" {
  communication_service_id = azurerm_communication_service.main.id
  email_service_domain_id  = azurerm_email_communication_service_domain.managed.id
}
