output "frontend_url" {
  description = "Public HTTPS URL of the SPA (Front Door default endpoint)."
  value       = one(module.frontend[*].frontend_url)
}

output "frontend_storage_account" {
  description = "Storage account name — CI uploads the built dist/ into its $web container."
  value       = one(module.frontend[*].storage_account_name)
}

output "frontend_frontdoor_profile" {
  description = "Front Door profile name — used by CI to purge the endpoint after a deploy."
  value       = one(module.frontend[*].frontdoor_profile_name)
}

output "frontend_frontdoor_endpoint" {
  description = "Front Door endpoint name — used by CI for cache purge."
  value       = one(module.frontend[*].frontdoor_endpoint_name)
}

output "resource_group" {
  description = "Resource group holding the Azure stack."
  value       = azurerm_resource_group.main.name
}

# ─── Backend adapter env values (feed shared/providers/azure/*) ─────────────

output "blob_container_name" {
  description = "Set as BLOB_CONTAINER_NAME for the BlobStorageProvider."
  value       = module.storage.container_name
}

output "storage_connection_string" {
  description = "Set as AZURE_STORAGE_CONNECTION_STRING for the BlobStorageProvider. Read with: terraform output -raw storage_connection_string"
  value       = module.storage.connection_string
  sensitive   = true
}

output "key_vault_url" {
  description = "Set as AZURE_KEY_VAULT_URL for the KeyVaultSecretsProvider."
  value       = module.keyvault.vault_uri
}

output "encryption_key_vault_key_id" {
  description = "Set as ENCRYPTION_KEY_VAULT_KEY_ID for the KeyVaultKeyProvider."
  value       = module.keyvault.encryption_key_id
}

output "smoke_secret_name" {
  description = "Secret name (value 'ok') for verifying the SecretsProvider."
  value       = module.keyvault.smoke_secret_name
}

# ─── Data + messaging adapter env values (Phase 2) ──────────────────────────
# These map 1:1 to the env vars the app/adapters read; Phase-3 Container Apps
# wires them (secrets from Key Vault / module outputs). Read a sensitive one
# with e.g. `terraform output -raw database_password`.

output "database_host" {
  description = "DATABASE_HOST — Postgres Flexible Server FQDN."
  value       = module.postgres.host
}

output "database_port" {
  description = "DATABASE_PORT."
  value       = module.postgres.port
}

output "database_name" {
  description = "DATABASE_NAME."
  value       = module.postgres.database_name
}

output "database_user" {
  description = "DATABASE_USER."
  value       = module.postgres.administrator_login
}

output "database_password" {
  description = "DATABASE_PASSWORD (also in Key Vault secret `postgres-admin-password`)."
  value       = module.postgres.administrator_password
  sensitive   = true
}

output "redis_host" {
  description = "REDIS_HOST."
  value       = one(module.redis[*].hostname)
}

output "redis_port" {
  description = "REDIS_PORT (TLS — requires REDIS_SSL=true)."
  value       = one(module.redis[*].ssl_port)
}

output "redis_password" {
  description = "REDIS_PASSWORD — Redis access key."
  value       = one(module.redis[*].primary_access_key)
  sensitive   = true
}

output "service_bus_connection_string" {
  description = "AZURE_SERVICE_BUS_CONNECTION_STRING."
  value       = module.servicebus.connection_string
  sensitive   = true
}

output "service_bus_queue_names" {
  description = "Channel → queue name map (set as SQS_SMS/WHATSAPP/EMAIL/METERING_QUEUE_URL)."
  value       = module.servicebus.queue_names
}

output "event_grid_endpoint" {
  description = "AZURE_EVENT_GRID_ENDPOINT."
  value       = module.eventgrid.endpoint
}

output "event_grid_key" {
  description = "AZURE_EVENT_GRID_KEY."
  value       = module.eventgrid.primary_access_key
  sensitive   = true
}

output "acs_connection_string" {
  description = "AZURE_COMMUNICATION_CONNECTION_STRING."
  value       = module.acs.connection_string
  sensitive   = true
}

output "acs_sender_address" {
  description = "Managed-domain sender address — wire as the notification from-address."
  value       = module.acs.sender_address
}

output "log_analytics_workspace_id" {
  description = "Log Analytics workspace id (Container Apps Environment log sink)."
  value       = module.monitoring.workspace_id
}

output "app_insights_connection_string" {
  description = "APPLICATIONINSIGHTS_CONNECTION_STRING."
  value       = module.monitoring.app_insights_connection_string
  sensitive   = true
}

# ─── Compute (Phase 3) ──────────────────────────────────────────────────────

output "api_url" {
  description = "Public HTTPS base URL of the API Container App — point the frontend + smoke tests here."
  value       = module.container_app.api_url
}

output "api_fqdn" {
  description = "API Container App ingress FQDN."
  value       = module.container_app.api_fqdn
}

output "acr_login_server" {
  description = "ACR login server — the deploy workflow tags/pushes the backend image here."
  value       = module.container_app.acr_login_server
}

output "acr_name" {
  description = "ACR name (for `az acr login` and image updates)."
  value       = module.container_app.acr_name
}

output "api_app_name" {
  description = "API Container App name (for `az containerapp update --image`)."
  value       = module.container_app.api_app_name
}

output "migrate_job_name" {
  description = "Migration Container App Job name (`az containerapp job start`)."
  value       = module.container_app.migrate_job_name
}

output "entra_claims_function_name" {
  description = "Entra claims-provider Function App name (CI zip-deploys services/entra_token_claims/ to it)."
  value       = module.entra_claims_function.function_app_name
}

output "entra_claims_endpoint_url" {
  description = "Register this URL as the Entra custom authentication extension target."
  value       = module.entra_claims_function.endpoint_url
}

output "entra_claims_principal_id" {
  description = "Claims Function managed-identity object id — grant it Graph User.Read.All (manual)."
  value       = module.entra_claims_function.principal_id
}
