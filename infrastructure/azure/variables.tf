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

variable "entra_user_domain" {
  description = "Entra verified/managed domain for UPNs (e.g. yourtenant.onmicrosoft.com). Empty until Entra is set up."
  type        = string
  default     = ""
}

variable "entra_platform_admin_group_id" {
  description = "Entra platform_admin group object id — the backend maps it to the platform_admin role (ADR-004). Empty until set up."
  type        = string
  default     = ""
}

variable "entra_group_id_map" {
  description = "Optional JSON {guid: canonical role-group name} for extra Entra group-id → role mappings."
  type        = string
  default     = ""
}

variable "auth_provider" {
  description = "Identity authority: 'azure' (Entra) or 'aws' (Cognito bridge — the Azure API validates Cognito JWTs). Defaults to azure."
  type        = string
  default     = "azure"
}

variable "entra_token_endpoint" {
  description = "Entra OAuth2 token endpoint for the backend session-refresh exchange. Empty until Entra is set up."
  type        = string
  default     = ""
}

variable "entra_client_id" {
  description = "Entra app registration client id for the backend session-refresh exchange."
  type        = string
  default     = ""
}

variable "entra_local_accounts" {
  description = "true on an Entra External ID (CIAM) tenant → provision email local accounts (email sign-in); false on workforce → member/UPN accounts (default)."
  type        = bool
  default     = false
}

variable "entra_authorize_endpoint" {
  description = "Entra OAuth2 authorize endpoint for interactive login. Empty → derived from the token endpoint (/token→/authorize)."
  type        = string
  default     = ""
}

variable "entra_redirect_uri" {
  description = "Interactive-login SPA callback URL registered on the app registration. Empty → derived as <frontend_url>/auth/callback."
  type        = string
  default     = ""
}

variable "auth_cookie_samesite" {
  description = "SameSite for auth cookies. Default 'None' — the Azure SPA (Front Door) and API (Container Apps) are different sites, so cross-site cookies are required."
  type        = string
  default     = "None"
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

# --- Entra claims extension (ADR-004) — filled after the manual Entra setup ---
variable "entra_claims_caller_jwks_url" {
  description = "Tenant JWKS URL the claims Function uses to verify Entra's inbound call."
  type        = string
  default     = ""
}

variable "entra_claims_caller_audience" {
  description = "Expected audience of Entra's inbound call to the claims Function (the extension API app id)."
  type        = string
  default     = ""
}

variable "entra_claims_caller_issuer" {
  description = "Expected issuer of Entra's inbound call to the claims Function."
  type        = string
  default     = ""
}

variable "entra_out_tenant_claim" {
  description = "Claim name the Function emits the tenant id as (must match backend ENTRA_TENANT_ID_CLAIM)."
  type        = string
  default     = "tenant_id"
}

variable "entra_out_role_claim" {
  description = "Claim name the Function emits the role as (must match backend ENTRA_ROLE_CLAIM)."
  type        = string
  default     = "role"
}
