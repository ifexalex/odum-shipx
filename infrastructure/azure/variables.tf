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

variable "notification_allowlist" {
  description = <<-EOT
    Comma-separated phone numbers / emails that MAY be messaged outside
    production. The recipient guard (`shared/notifications.is_recipient_allowed`)
    fails CLOSED: empty means every non-production notification is suppressed,
    because dev/staging databases hold real imported customer contacts. Set this
    to your own test contacts to actually receive activation/onboarding emails in
    dev. Ignored when environment = "prod"/production.
  EOT
  type        = string
  default     = ""
}

variable "entra_graph_tenant_id" {
  description = "Tenant id of the directory the backend provisions users into (the CIAM tenant). Empty → managed identity (only works when that directory is the compute's home tenant)."
  type        = string
  default     = ""
}

variable "entra_graph_client_id" {
  description = "App-registration client id (in the CIAM tenant) holding Graph application permissions (User.ReadWrite.All, Group.ReadWrite.All) to provision tenant users. Empty disables client-credentials."
  type        = string
  default     = ""
}

variable "entra_graph_client_secret" {
  description = "Client secret for entra_graph_client_id — set via TF_VAR_entra_graph_client_secret (a GitHub Actions secret), never committed to tfvars."
  type        = string
  default     = ""
  sensitive   = true
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

variable "entra_authorize_prompt" {
  description = "OAuth2 `prompt` on the authorize request. 'select_account' shows the account picker (so a second user can sign in on a shared browser); 'login' forces re-auth; '' lets Entra silently reuse its SSO session."
  type        = string
  default     = "select_account"
}

variable "require_front_door" {
  description = "Refuse API requests that did not come through Front Door (403). Free. Off until every webhook URL and smoke test uses the Front Door host; see modules/container_app/variables.tf."
  type        = bool
  default     = false
}

variable "trusted_proxy_hops" {
  description = "Fallback only: reverse proxies that append to X-Forwarded-For for requests that did NOT come through Front Door. Leave 0 (address unknown) unless there is no Front Door; see modules/container_app/variables.tf."
  type        = number
  default     = 0
}

variable "app_base_url" {
  description = <<-EOT
    Public SPA base URL used to build activation/password links in outbound
    email. Set it explicitly for the same reason as entra_redirect_uri: the
    frontend module depends on container_app's api_fqdn, so referencing
    module.frontend here would create a cycle. Empty falls back to the origin
    of entra_redirect_uri — and if both are empty, activation emails ship an
    empty link.
  EOT
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

# ---------------------------------------------------------------------------
# Notification channels — SMS and WhatsApp.
# Passed through to modules/container_app, which documents each one.
# ---------------------------------------------------------------------------

variable "customer_portal_base_url" {
  description = "Override base URL for customer invite links if the customer portal is hosted separately. Falls back to app_base_url."
  type        = string
  default     = ""
}

variable "africastalking_api_key" {
  description = "Africa's Talking API key for SMS."
  type        = string
  default     = ""
  sensitive   = true
}

variable "africastalking_username" {
  description = "Africa's Talking username — the live one in production, not 'sandbox'."
  type        = string
  default     = ""
}

variable "africastalking_sender_id" {
  description = "Africa's Talking sender ID / short code, if registered."
  type        = string
  default     = ""
}

variable "meta_whatsapp_access_token" {
  description = "Meta Cloud API access token for WhatsApp Business."
  type        = string
  default     = ""
  sensitive   = true
}

variable "meta_whatsapp_phone_id" {
  description = "Meta Cloud API phone number ID for WhatsApp Business."
  type        = string
  default     = ""
}

variable "meta_whatsapp_template_lang" {
  description = "Language code the WhatsApp templates were approved under. Must match Meta exactly."
  type        = string
  default     = ""
}

variable "whatsapp_verify_token" {
  description = "Shared secret Meta echoes when verifying the WhatsApp webhook subscription."
  type        = string
  default     = ""
  sensitive   = true
}

variable "alerts_email" {
  description = "Email for failure alerts (audit OPS-04). Empty skips the alert rules entirely (no cost)."
  type        = string
  default     = ""
}
