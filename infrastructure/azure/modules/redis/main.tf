# ---------------------------------------------------------------------------
# Azure Cache for Redis — the analogue of the AWS `elasticache` module (the
# tenant-status distributed cache, shared/distributed_cache.py).
#
# Basic C0 is the cheapest tier (single node, no SLA) — fine for a cache whose
# miss path falls through to the DB. Basic/Standard are public endpoints with a
# mandatory access key over TLS (VNet injection needs Premium), so unlike AWS
# ElastiCache this requires REDIS_PASSWORD + TLS — wired in Phase 3
# (distributed_cache.py gains REDIS_PASSWORD/REDIS_SSL support).
# ---------------------------------------------------------------------------

resource "azurerm_redis_cache" "main" {
  name                = "${var.name_prefix}-redis"
  resource_group_name = var.resource_group_name
  location            = var.location

  capacity = var.capacity
  family   = var.family
  sku_name = var.sku_name

  # TLS-only; Basic/Standard always require the access key.
  non_ssl_port_enabled = false
  minimum_tls_version  = "1.2"
  redis_version        = "6"

  tags = var.common_tags
}
