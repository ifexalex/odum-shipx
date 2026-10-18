environment  = "demo"
location     = "northeurope"
api_base_url = "https://api-demo.shipx.example"
# test contacts belong here. Match is an exact, case-insensitive compare and
# phones are stored E.164 (shared/phone.py), so use the +234 form.
notification_allowlist = "ifexalex2@gmail.com,ifexanda@gmail.com,ifexalex@gmail.com,ifexalex@outlook.com,djangotestmail1593@gmail.com,ndnicksonm@gmail.com,+2348169760253,+447778569025,+2347066071386"

# ── Entra auth — NOT YET PROVISIONED ────────────────────────────────────────
# auth_provider defaults to "azure", so `terraform plan` for demo now FAILS
# on the auth_config_guard in ../main.tf until the block below is filled in.
# That failure is deliberate: without these values the stack deploys healthy
# and every single sign-in fails, which is far more expensive to diagnose.
#
# To fill it in, run these against the Entra tenant that will own demo users
# (a tenant SEPARATE from dev's, so a demo test cannot touch dev identities):
#   az login --tenant <demo CIAM tenant id> --allow-no-subscriptions
#   ENTRA_TENANT_ID=<id> ../../../scripts/setup_entra_auth.sh
#   ../../../scripts/setup_entra_claims_provider.sh
#   ../../../scripts/setup_entra_platform_admin.sh
# Each script prints the exact values to paste here. Do NOT hand-assemble the
# issuer or JWKS URL — copy what setup_entra_claims_provider.sh reports, which
# it reads from the tenant's OIDC discovery document. A guessed issuer host is
# what produced AADSTS1100001 in dev.
#
# entra_local_accounts = true
# auth_cookie_samesite = "Lax"
# oidc_jwks_url                 = ""   # discovery: jwks_uri
# oidc_audience                 = ""   # SPA app registration client id
# entra_client_id               = ""   # same SPA client id
# entra_token_endpoint          = ""
# entra_redirect_uri            = ""   # https://<frontdoor-host>/auth/callback
# app_base_url                  = ""   # https://<frontdoor-host>
# entra_user_domain             = ""
# entra_platform_admin_group_id = ""   # setup_entra_platform_admin.sh
# entra_claims_caller_audience  = ""
# entra_claims_caller_issuer    = ""   # discovery: issuer (tenant-GUID host on CIAM)
# entra_claims_caller_jwks_url  = ""
# entra_graph_tenant_id         = ""
# entra_graph_client_id         = ""   # setup_entra_auth.sh
# ENTRA_GRAPH_CLIENT_SECRET is a GitHub Environment secret, never a tfvar.
