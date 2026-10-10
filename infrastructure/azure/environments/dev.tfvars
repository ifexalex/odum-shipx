environment  = "dev"
location     = "northeurope"
api_base_url = "https://api-dev.shipx.example"

# dev targets a Free Trial / Student subscription, which restricts some services:
#   - Front Door is forbidden        → skip the frontend module
#   - classic Azure Cache for Redis is retiring/blocked → skip Redis (cache
#     degrades to DB lookups; still functional)
#   - the OIDC deploy identity is Contributor-only (can't write role assignments)
#     → pull images from ACR with admin creds instead of a managed-identity role
# Flip these back to true once dev runs on a pay-as-you-go subscription.
enable_frontend = false
enable_redis    = false
grant_acr_pull  = false
