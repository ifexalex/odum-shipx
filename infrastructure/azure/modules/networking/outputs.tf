output "vnet_id" {
  description = "Virtual network id."
  value       = azurerm_virtual_network.main.id
}

output "vnet_name" {
  description = "Virtual network name."
  value       = azurerm_virtual_network.main.name
}

output "container_apps_subnet_id" {
  description = "Subnet id for the Container Apps Environment (Phase 3)."
  value       = azurerm_subnet.container_apps.id
}

output "postgres_subnet_id" {
  description = "Delegated subnet id for the Postgres Flexible Server."
  value       = azurerm_subnet.postgres.id
}

output "private_endpoints_subnet_id" {
  description = "Subnet id for private endpoints."
  value       = azurerm_subnet.private_endpoints.id
}
