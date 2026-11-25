# ---------------------------------------------------------------------------
# App object storage — the Azure analogue of the S3 assets bucket, and the
# target of shared/providers/azure/blob.py (BlobStorageProvider).
#
# Free/cheap sizing: StandardV2, LRS, Hot. A fresh free account's 12-month
# Blob grant covers test volumes. The container is the StorageProvider's
# "bucket" (BLOB_CONTAINER_NAME).
# ---------------------------------------------------------------------------

locals {
  # Storage account names: 3–24 chars, lowercase alphanumeric, globally unique.
  sa_base = substr(lower(replace("${var.name_prefix}assets", "-", "")), 0, 16)
}

resource "random_string" "sa_suffix" {
  length  = 6
  lower   = true
  upper   = false
  numeric = true
  special = false
}

resource "azurerm_storage_account" "assets" {
  name                     = "${local.sa_base}${random_string.sa_suffix.result}"
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  access_tier              = "Hot"

  # Security posture: HTTPS-only, TLS1.2 floor, no public blob access
  # (the app issues SAS URLs; blobs are never anonymously readable).
  https_traffic_only_enabled      = true
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false

  blob_properties {
    # GDPR erasure (delete_prefix) deletes immediately; keep a short soft-delete
    # window as a safety net without defeating the purge intent.
    delete_retention_policy {
      days = 7
    }

    # CORS for browser presigned-SAS PUT uploads (logos, claim evidence,
    # container documents, packing-list imports). Without this rule, Azure Blob
    # rejects the OPTIONS preflight triggered by Content-Type + x-ms-blob-type.
    dynamic "cors_rule" {
      for_each = length(var.cors_allowed_origins) > 0 ? [1] : []
      content {
        allowed_headers    = ["*"]
        allowed_methods    = ["GET", "HEAD", "OPTIONS", "PUT"]
        allowed_origins    = var.cors_allowed_origins
        exposed_headers    = ["ETag", "x-ms-request-id"]
        max_age_in_seconds = 3600
      }
    }
  }

  tags = var.common_tags
}

resource "azurerm_storage_container" "assets" {
  name                  = var.container_name
  storage_account_id    = azurerm_storage_account.assets.id
  container_access_type = "private"
}
