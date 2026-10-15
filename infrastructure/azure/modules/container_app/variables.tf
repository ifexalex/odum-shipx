variable "name_prefix" {
  description = "Resource name prefix (e.g. shipx-prod)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "common_tags" {
  description = "Tags applied to all resources."
  type        = map(string)
}

# ─── Identity + network + observability (from other modules) ────────────────
variable "identity_id" {
  description = "User-assigned managed identity resource id (ACR pull + Key Vault access)."
  type        = string
}

variable "identity_principal_id" {
  description = "Managed identity principal id (for the AcrPull role assignment)."
  type        = string
}

variable "subnet_id" {
  description = "Container Apps Environment infrastructure subnet (delegated to Microsoft.App/environments)."
  type        = string
}

variable "log_analytics_workspace_id" {
  description = "Log Analytics workspace the environment streams logs to."
  type        = string
}

# ─── Image ───────────────────────────────────────────────────────────────────
variable "container_image" {
  description = "Image to run. Defaults to a public placeholder so the first apply succeeds before the real image is pushed to ACR; the deploy workflow updates it (Terraform ignores image drift)."
  type        = string
  default     = "mcr.microsoft.com/k8se/quickstart:latest"
}

variable "acr_sku" {
  description = "Container Registry SKU."
  type        = string
  default     = "Basic"
}

variable "grant_acr_pull" {
  description = "true: managed-identity pull + AcrPull role assignment (needs role-assignment rights). false: ACR admin creds (for Contributor-only / restricted deploy identities)."
  type        = bool
  default     = true
}

variable "enable_redis" {
  description = "Whether Redis is provisioned. When false, the redis-password secret + REDIS_PASSWORD env are omitted and the cache degrades to DB lookups."
  type        = bool
  default     = true
}

# ─── Data + messaging values (from the Phase-2 modules) ─────────────────────
variable "db_host" { type = string }
variable "db_port" { type = number }
variable "db_name" { type = string }
variable "db_user" { type = string }
variable "db_password" {
  type      = string
  sensitive = true
}
variable "redis_host" { type = string }
variable "redis_port" { type = number }
variable "redis_password" {
  type      = string
  sensitive = true
}
variable "service_bus_connection_string" {
  type      = string
  sensitive = true
}
variable "queue_names" {
  description = "Channel → Service Bus queue name map."
  type        = map(string)
}
variable "event_grid_endpoint" { type = string }
variable "event_grid_key" {
  type      = string
  sensitive = true
}
variable "acs_connection_string" {
  type      = string
  sensitive = true
}
variable "acs_sender_address" { type = string }
variable "blob_container_name" { type = string }
variable "storage_connection_string" {
  type      = string
  sensitive = true
}
variable "key_vault_url" { type = string }
variable "encryption_key_id" { type = string }
variable "app_insights_connection_string" {
  type      = string
  sensitive = true
}

# ─── Auth (Entra, Phase 4 — empty until then) ───────────────────────────────
variable "oidc_jwks_url" {
  description = "OIDC JWKS endpoint for token verification (Entra; set in Phase 4)."
  type        = string
  default     = ""
}

variable "oidc_audience" {
  description = "OIDC token audience (Entra app client id; set in Phase 4)."
  type        = string
  default     = ""
}

variable "entra_platform_admin_group_id" {
  description = "Entra platform_admin group object id → mapped to the platform_admin role by the backend."
  type        = string
  default     = ""
}

variable "entra_group_id_map" {
  description = "Optional JSON {guid: canonical role-group name} for additional group-id → role mappings."
  type        = string
  default     = ""
}

variable "entra_user_domain" {
  description = "Entra verified/managed domain for UPNs (EntraIdentityProvider). Empty until Entra is set up."
  type        = string
  default     = ""
}

variable "entra_local_accounts" {
  description = "true on an Entra External ID (CIAM) tenant → provision email local accounts (email sign-in); false on workforce → member/UPN accounts."
  type        = bool
  default     = false
}

variable "auth_provider" {
  description = "Identity authority: 'azure' (Entra) or 'aws' (Cognito bridge — validate Cognito JWTs while running on Azure). Defaults to azure to match the infra cloud."
  type        = string
  default     = "azure"
}

variable "cors_allow_origins" {
  description = "Comma-separated browser origins allowed to call the API (e.g. the frontend URL). Empty = same-origin only."
  type        = string
  default     = ""
}

variable "entra_token_endpoint" {
  description = "Entra OAuth2 token endpoint — the backend's httpOnly-cookie session refresh uses it when AUTH_PROVIDER=azure. Empty until Entra is set up."
  type        = string
  default     = ""
}

variable "entra_client_id" {
  description = "Entra app registration client id for the backend refresh exchange."
  type        = string
  default     = ""
}

variable "entra_scope" {
  description = "OAuth2 scopes for the Entra refresh exchange."
  type        = string
  default     = "openid profile offline_access"
}

variable "entra_graph_tenant_id" {
  description = "Tenant id of the directory the EntraIdentityProvider provisions users into (the CIAM tenant). Empty → DefaultAzureCredential (managed identity)."
  type        = string
  default     = ""
}

variable "entra_graph_client_id" {
  description = "App-registration client id (in entra_graph_tenant_id) with Graph application permissions to create users/groups. Empty disables client-credentials (falls back to the managed identity)."
  type        = string
  default     = ""
}

variable "entra_graph_client_secret" {
  description = "Client secret for entra_graph_client_id. Supplied at apply time via TF_VAR_entra_graph_client_secret (a GitHub secret) — never committed."
  type        = string
  default     = ""
  sensitive   = true
}

variable "entra_authorize_endpoint" {
  description = "Entra OAuth2 authorize endpoint for interactive login. Empty → derived from the token endpoint."
  type        = string
  default     = ""
}

variable "entra_redirect_uri" {
  description = "SPA callback URL registered on the app registration (e.g. https://<frontend>/auth/callback)."
  type        = string
  default     = ""
}

variable "auth_cookie_samesite" {
  description = "SameSite for the auth cookies. 'None' for cross-site (Azure FrontDoor↔ContainerApps); 'Strict' when SPA+API share a site."
  type        = string
  default     = "Strict"
}

# ─── Sizing ───────────────────────────────────────────────────────────────────
variable "api_cpu" {
  type    = number
  default = 0.5
}
variable "api_memory" {
  type    = string
  default = "1Gi"
}
variable "api_min_replicas" {
  type    = number
  default = 1
}
variable "api_max_replicas" {
  type    = number
  default = 3
}
variable "worker_cpu" {
  type    = number
  default = 0.25
}
variable "worker_memory" {
  type    = string
  default = "0.5Gi"
}
variable "worker_max_replicas" {
  type    = number
  default = 5
}
variable "job_cpu" {
  type    = number
  default = 0.5
}
variable "job_memory" {
  type    = string
  default = "1Gi"
}
variable "job_timeout_seconds" {
  type    = number
  default = 600
}

# --- Entra claims provider (ADR-004) — runs as its own Container App on the
# shared image (docker-entrypoint.sh `claims`). Config filled after the manual
# Entra tenant setup; empty values just mean the endpoint denies callers. ---
variable "claims_caller_jwks_url" {
  type    = string
  default = ""
}
variable "claims_caller_audience" {
  type    = string
  default = ""
}
variable "claims_caller_issuer" {
  type    = string
  default = ""
}
variable "claims_out_tenant_claim" {
  type    = string
  default = "tenant_id"
}
variable "claims_out_role_claim" {
  type    = string
  default = "role"
}
variable "claims_cpu" {
  type    = number
  default = 0.25
}
variable "claims_memory" {
  type    = string
  default = "0.5Gi"
}
variable "claims_min_replicas" {
  description = "Keep >=1: Entra's token-issuance call times out ~2s, so the claims path must stay warm."
  type        = number
  default     = 1
}
variable "claims_max_replicas" {
  type    = number
  default = 2
}
