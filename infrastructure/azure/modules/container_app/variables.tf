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
variable "db_user" {
  description = "The OWNER login. Used by the migrate job only — DDL cannot be run by the application role."
  type        = string
}

variable "db_app_user" {
  description = "The role the application connects as (logistics_app) — DML only, no BYPASSRLS, so RLS is enforced."
  type        = string
}

variable "db_app_password" {
  description = "Password for db_app_user. The app containers' DATABASE_PASSWORD and the migrate job's APP_DB_PASSWORD."
  type        = string
  sensitive   = true
}
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

variable "environment_name" {
  description = "Deployment environment (dev/staging/prod/demo) — sets ENVIRONMENT, which the structured logger stamps on every line and the notification recipient guard reads ('production' disables the guard)."
  type        = string
  default     = ""
}

variable "notification_allowlist" {
  description = <<-EOT
    Comma-separated phone numbers / emails that MAY be messaged outside
    production. `shared/notifications.is_recipient_allowed` fails CLOSED: with
    this empty, every non-production notification is suppressed (dev/staging
    databases hold real imported customer contacts, so opt-in is the only safe
    default). Set it to your own test contacts to receive activation/onboarding
    emails in dev. Ignored when ENVIRONMENT=production.
  EOT
  type        = string
  default     = ""
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

variable "entra_authorize_prompt" {
  description = <<-EOT
    OAuth2 `prompt` sent on the authorize request. "select_account" (default)
    shows the account picker so a different user can sign in on a shared
    browser; "login" forces re-authentication; "" omits the parameter and lets
    Entra silently reuse its active SSO session.
  EOT
  type        = string
  default     = "select_account"
}

variable "trusted_proxy_hops" {
  description = <<-EOT
    Number of reverse proxies in front of the app that each append the address they received the
    connection from to X-Forwarded-For (read as TRUSTED_PROXY_HOPS by shared/client_ip.py). The client is
    taken that many entries from the END of the header, because a client can put anything at the front.

    0 means none are configured. That is safe but not useful behind Front Door: with a proxy header and an
    internal peer address the client address is treated as unknown, so per-client rate limits do not apply
    (per-tenant and per-username ones still do) and audit logs record no address. Set it to the VERIFIED hop
    count (likely 2: Front Door, then the Container Apps ingress) after checking a real request's header.
    Too low lumps every user into one client; too high lets a client choose its own address.
  EOT
  type        = number
  default     = 0
}

variable "app_base_url" {
  description = <<-EOT
    Public base URL of the SPA, used to build activation and password links in
    outbound email. Empty falls back to the origin of entra_redirect_uri; if
    BOTH are empty the links render empty and activation email is useless, so
    set this in every environment that sends mail.
  EOT
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

# ---------------------------------------------------------------------------
# Notification channels — SMS and WhatsApp
#
# These were absent from the Azure deployment entirely. Email worked (ACS, via
# acs_sender_address → SES_FROM_ADDRESS) but SMS and WhatsApp had no
# credentials at all, so every send logged "not configured" and returned
# without error. WhatsApp is the primary customer channel here.
# ---------------------------------------------------------------------------

variable "customer_portal_base_url" {
  description = "Override base URL for customer invite links if the customer portal is hosted separately. Falls back to app_base_url."
  type        = string
  default     = ""
}

variable "africastalking_api_key" {
  description = "Africa's Talking API key for SMS. Delivered as a Container App secret; gated on africastalking_username being set."
  type        = string
  default     = ""
  sensitive   = true
}

variable "africastalking_username" {
  description = "Africa's Talking username. Must be the live username in production — the application default is 'sandbox', which accepts messages and delivers nothing. Also gates whether the API key secret is created."
  type        = string
  default     = ""
}

variable "africastalking_sender_id" {
  description = "Africa's Talking sender ID / short code, if one is registered."
  type        = string
  default     = ""
}

variable "meta_whatsapp_access_token" {
  description = "Meta Cloud API access token for WhatsApp Business. Delivered as a Container App secret; gated on meta_whatsapp_phone_id being set."
  type        = string
  default     = ""
  sensitive   = true
}

variable "meta_whatsapp_phone_id" {
  description = "Meta Cloud API phone number ID. Also gates whether the WhatsApp secrets are created."
  type        = string
  default     = ""
}

variable "meta_whatsapp_template_lang" {
  description = "Language code the WhatsApp templates were approved under (e.g. en, en_US, zh_CN). Must match Meta exactly or every send 404s."
  type        = string
  default     = ""
}

variable "whatsapp_verify_token" {
  description = "Shared secret Meta echoes when verifying the WhatsApp webhook subscription."
  type        = string
  default     = ""
  sensitive   = true
}

variable "front_door_id" {
  description = <<-EOT
    This deployment's Front Door id (the profile's resource_guid), sent by Front Door as X-Azure-FDID on every
    request it forwards. The app takes the client's address from Front Door's own stamp (X-Azure-SocketIP) only
    on requests carrying this id, so rate limits and audit logs get the real address without anyone having to
    count proxies. Empty when there is no Front Door: the app then falls back to trusted_proxy_hops.
  EOT
  type        = string
  default     = ""
}

variable "require_front_door" {
  description = <<-EOT
    Refuse API requests that did not come through this deployment's Front Door (403), so nothing can go around
    it by calling the container app's own hostname. Costs nothing. Off by default because anything configured to
    call that hostname directly (a payment or WhatsApp webhook URL, a smoke test) would start failing: point
    those at the Front Door host first, then turn this on. /health stays open for the platform's probes.
  EOT
  type        = bool
  default     = false
}
