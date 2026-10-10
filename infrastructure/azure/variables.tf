variable "project_name" {
  description = "Project name, used as the resource name prefix."
  type        = string
  default     = "shipx"
}

variable "environment" {
  description = "Deployment environment (dev / staging / prod / demo)."
  type        = string
  default     = "prod"
}

variable "location" {
  description = "Azure region. North/West Europe mirror the AWS eu-west-1 deployment."
  type        = string
  default     = "northeurope"
}

variable "api_base_url" {
  description = "Public base URL of the backend API, used in the SPA's CSP connect-src (e.g. https://api.shipx.example). Leave as the placeholder until the backend stack exists."
  type        = string
  default     = "https://api.invalid"
}

# ─── Data layer sizing (Phase 2) — defaults are cheapest/test-tier ──────────

variable "postgres_sku_name" {
  description = "Postgres Flexible Server SKU. Burstable B1ms is cheapest; use GP_Standard_D2s_v3 (or larger) for prod."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "postgres_storage_mb" {
  description = "Postgres storage in MB (32768 = 32 GiB minimum)."
  type        = number
  default     = 32768
}

variable "redis_sku_name" {
  description = "Azure Cache for Redis SKU: Basic (cheapest) / Standard / Premium."
  type        = string
  default     = "Basic"
}

variable "acs_data_location" {
  description = "ACS data residency region (Europe / United States / ...). Not the deployment region."
  type        = string
  default     = "Europe"
}

# ─── Compute (Phase 3) ──────────────────────────────────────────────────────

variable "container_image" {
  description = "Backend image for the Container Apps. Defaults to a public placeholder so the first apply succeeds before the real image is in ACR; the deploy workflow pushes + updates it."
  type        = string
  default     = "mcr.microsoft.com/k8se/quickstart:latest"
}

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

variable "api_cpu" {
  description = "API container vCPU."
  type        = number
  default     = 0.5
}

variable "api_memory" {
  description = "API container memory (e.g. 1Gi)."
  type        = string
  default     = "1Gi"
}

variable "api_min_replicas" {
  description = "API minimum replicas (1 keeps it warm; raise for prod)."
  type        = number
  default     = 1
}

variable "api_max_replicas" {
  description = "API maximum replicas."
  type        = number
  default     = 3
}

# ─── Subscription-capability toggles (set false on Free Trial/Student) ──────

variable "enable_frontend" {
  description = "Provision the Blob + Front Door frontend. Front Door is forbidden on Free Trial/Student subscriptions — set false there (backend-only deploy)."
  type        = bool
  default     = true
}

variable "enable_redis" {
  description = "Provision Azure Cache for Redis. Classic Redis is retiring/blocked on some subscriptions — set false to run without it (the cache degrades to DB lookups)."
  type        = bool
  default     = true
}

variable "grant_acr_pull" {
  description = "true: managed-identity ACR pull + role assignment (needs role-assignment rights). false: ACR admin creds — set false when the deploy identity is Contributor-only."
  type        = bool
  default     = true
}
