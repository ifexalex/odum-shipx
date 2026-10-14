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

# ── Entra auth (dev tenant ifexalexoutlook) — public identifiers, not secrets ──
auth_provider                 = "azure"
oidc_jwks_url                 = "https://ifexalexoutlook.ciamlogin.com/a59c21d1-635f-4308-bb41-2d582350660d/discovery/v2.0/keys"
oidc_audience                 = "9436cda7-a13f-4ef9-a580-6c11c1257c35"
entra_user_domain             = "ifexalexoutlook.onmicrosoft.com"
entra_platform_admin_group_id = "226e2e44-ef7e-4dc6-bf2b-6f39879e8628"
# Native-Entra SPA (ROPC) + backend cookie-refresh:
entra_client_id      = "9436cda7-a13f-4ef9-a580-6c11c1257c35"
entra_token_endpoint = "https://ifexalexoutlook.ciamlogin.com/ifexalexoutlook.onmicrosoft.com/oauth2/v2.0/token"
entra_claims_caller_audience = "api://shipx-dev-entra-claims.niceflower-e336bb33.northeurope.azurecontainerapps.io/1567ba7b-ad78-4d23-9e75-a027fb90abe9"
entra_claims_caller_issuer   = "https://login.microsoftonline.com/a59c21d1-635f-4308-bb41-2d582350660d/v2.0"
entra_claims_caller_jwks_url = "https://login.microsoftonline.com/a59c21d1-635f-4308-bb41-2d582350660d/discovery/v2.0/keys"