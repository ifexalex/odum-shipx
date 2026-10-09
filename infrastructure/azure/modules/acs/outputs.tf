output "connection_string" {
  description = "Communication Services connection string — set as AZURE_COMMUNICATION_CONNECTION_STRING."
  value       = azurerm_communication_service.main.primary_connection_string
  sensitive   = true
}

output "sender_address" {
  description = "Managed-domain sender address (DoNotReply@<domain>) — wire as the notification from-address."
  value       = "DoNotReply@${azurerm_email_communication_service_domain.managed.from_sender_domain}"
}

output "mail_from_domain" {
  description = "The Azure-managed sending domain."
  value       = azurerm_email_communication_service_domain.managed.from_sender_domain
}
