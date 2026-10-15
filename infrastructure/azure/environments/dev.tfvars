environment  = "dev"
location     = "northeurope"
api_base_url = "https://api-dev.shipx.example"

# dev runs on a Pay-As-You-Go subscription (upgraded from Free Trial — keeps the
# $200 credit). Front Door + RBAC now work, so the frontend is enabled.
#   - enable_frontend=true  → Blob static site + Front Door (the prod design)
#   - enable_redis=false    → classic Azure Cache for Redis is retiring platform-
#                             wide; the cache degrades to DB lookups. Switch to
#                             Azure Managed Redis later if a real cache is needed.
#   - grant_acr_pull=false  → pull from ACR with admin creds. Flip to true only
#                             after granting the deploy identity User Access
#                             Administrator (Contributor alone can't assign roles).
# PREREQUISITE: upgrade the subscription to PAYG before the next apply, or the
# Front Door create will 400 again ("Free Trial forbidden").
enable_frontend = true
enable_redis    = false
grant_acr_pull  = false

# ── Entra auth (dev = External ID / CIAM tenant "Shipx Customer") ─────────────
# Public identifiers, not secrets. Tenant 062cb98d-8990-4947-81c4-223cb1e9b8f3,
# domain shipxcustomer.onmicrosoft.com. Email+password local accounts
# (entra_local_accounts=true) — users sign in with their real email.
auth_provider        = "azure"
entra_local_accounts = true
# API is served same-origin with the SPA (Front Door /v1/* → API container), so
# auth cookies are first-party; Lax survives the Entra redirect back.
auth_cookie_samesite = "Lax"
# Explicit (the frontend module now depends on the API fqdn, so this can't be
# derived from the Front Door URL without a cycle). Must match the SPA redirect
# URI registered on the app registration in the CIAM tenant.
entra_redirect_uri = "https://shipx-dev-fde-a3d7cufpbwgwcgc2.z03.azurefd.net/auth/callback"
oidc_jwks_url      = "https://shipxcustomer.ciamlogin.com/062cb98d-8990-4947-81c4-223cb1e9b8f3/discovery/v2.0/keys"
oidc_audience      = "c6d0fc93-1fb5-43c5-9621-513abf93c5d6"
entra_user_domain  = "shipxcustomer.onmicrosoft.com"
# platform_admin GROUP object id in the CIAM tenant (fallback that resolves the
# admin to platform_admin when the token has no tenant_id/role claim).
entra_platform_admin_group_id = "7eec8dba-c70f-4043-b84d-5c3a82b86c37"
# Interactive auth-code + PKCE SPA app (created by the setup scripts in 062cb98d):
entra_client_id              = "c6d0fc93-1fb5-43c5-9621-513abf93c5d6"
entra_token_endpoint         = "https://shipxcustomer.ciamlogin.com/shipxcustomer.onmicrosoft.com/oauth2/v2.0/token"
entra_claims_caller_audience = "bc01467b-2122-41be-ae25-c678d9248c16" # the custom-extension resourceId
# NB: the issuer host is the tenant GUID, not the tenant name — this is what the
# CIAM tenant actually stamps on tokens (confirmed via the OIDC discovery doc's
# `issuer`). Using the shipxcustomer.* host here 401'd the claims extension and
# failed token issuance (AADSTS1100001/1003002). The JWKS host below may use
# either form (signature verification resolves the key by kid).
entra_claims_caller_issuer   = "https://062cb98d-8990-4947-81c4-223cb1e9b8f3.ciamlogin.com/062cb98d-8990-4947-81c4-223cb1e9b8f3/v2.0"
entra_claims_caller_jwks_url = "https://shipxcustomer.ciamlogin.com/062cb98d-8990-4947-81c4-223cb1e9b8f3/discovery/v2.0/keys"
# Graph client-credentials used by EntraIdentityProvider to provision tenant
# users INTO the CIAM tenant (the Container App's managed identity can't — it is
# single-tenant). Create a confidential app registration in 062cb98d with Graph
# APPLICATION permissions User.ReadWrite.All + Group.ReadWrite.All (admin-consented),
# put its client id below, and set its secret as the GitHub Environment secret
# ENTRA_GRAPH_CLIENT_SECRET (injected via TF_VAR at apply — never in tfvars).
# Empty client id → managed-identity fallback (provisioning stays disabled).
entra_graph_tenant_id = "062cb98d-8990-4947-81c4-223cb1e9b8f3"
entra_graph_client_id = "37c40cbe-5995-4b37-9d2a-0d6a02624426" # shipx-graph-provisioner (User.ReadWrite.All + Group.ReadWrite.All)