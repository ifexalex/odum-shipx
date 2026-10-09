environment  = "prod"
location     = "northeurope"
api_base_url = "https://api.shipx.example"

# Production sizing (override the cheap test-tier module defaults). General
# Purpose Postgres + Standard Redis. dev/staging/demo use the Burstable/Basic
# defaults; raise staging to match prod before a production cutover.
postgres_sku_name   = "GP_Standard_D2s_v3"
postgres_storage_mb = 65536
redis_sku_name      = "Standard"
