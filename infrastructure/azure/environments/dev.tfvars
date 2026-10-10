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
