output "hostname" {
  description = "Redis hostname — set as REDIS_HOST."
  value       = azurerm_redis_cache.main.hostname
}

output "ssl_port" {
  description = "TLS port — set as REDIS_PORT (6380). Requires REDIS_SSL=true."
  value       = azurerm_redis_cache.main.ssl_port
}

output "primary_access_key" {
  description = "Access key — set as REDIS_PASSWORD."
  value       = azurerm_redis_cache.main.primary_access_key
  sensitive   = true
}
