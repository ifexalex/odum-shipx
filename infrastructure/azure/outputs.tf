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

# Entra SPA values for the frontend build (public identifiers, not secrets) — so
# the Azure frontend deploy reads them from Terraform instead of extra secrets.
output "frontend_auth_provider" {
  description = "Auth provider the SPA should build with (entra when auth_provider=azure)."
  value       = var.auth_provider == "azure" ? "entra" : "cognito"
}

output "entra_client_id" {
  description = "Entra SPA app (client) id — VITE_ENTRA_CLIENT_ID."
  value       = var.entra_client_id
}

output "entra_token_endpoint" {
  description = "Entra OAuth2 token endpoint — VITE_ENTRA_TOKEN_ENDPOINT."
  value       = var.entra_token_endpoint
}

output "entra_platform_admin_group_id" {
  description = <<-EOT
    Entra platform_admin group object id — VITE_ENTRA_PLATFORM_ADMIN_GROUP_ID.
    The SPA maps this GUID (carried in the token's `groups` claim) back to the
    canonical `platform_admin` name and derives tenant_id=PLATFORM, mirroring the
    backend EntraClaimsMapper. A public identifier, not a secret.
  EOT
  value       = var.entra_platform_admin_group_id
}

output "entra_group_id_map" {
  description = <<-EOT
    JSON {<group guid>: <canonical name>} for tenant-scoped Entra groups —
    VITE_ENTRA_GROUP_ID_MAP. Usually empty (tenant users' tenant_id/role come
    from the DB claims extension); here for parity with the backend mapper.
  EOT
  value       = var.entra_group_id_map
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

output "entra_claims_app_name" {
  description = "Entra claims-provider Container App name (rolled by the deploy's `az containerapp update` loop)."
  value       = module.container_app.claims_app_name
}

output "entra_claims_endpoint_url" {
  description = "Register this URL as the Entra custom authentication extension target."
  value       = "https://${module.container_app.claims_app_fqdn}/token-claims"
}

output "entra_claims_principal_id" {
  description = "Shared app managed-identity object id — grant it Graph User.Read.All (manual)."
  value       = azurerm_user_assigned_identity.app.principal_id
}
