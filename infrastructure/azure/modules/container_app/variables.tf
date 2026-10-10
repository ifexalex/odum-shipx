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
