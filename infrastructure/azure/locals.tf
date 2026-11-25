# Shared naming + tagging comes from ../common/naming (same module the AWS root
# uses) so tag keys and the name prefix stay consistent across clouds.
module "naming" {
  source       = "../common/naming"
  project_name = var.project_name
  environment  = var.environment
  cloud        = "azure"
}

locals {
  common_tags = module.naming.common_tags
  name_prefix = module.naming.name_prefix

  # Assets Blob Storage host for browser presigned PUT uploads and logo/evidence display.
  storage_blob_origin = "https://${module.storage.storage_account_name}.blob.core.windows.net"

  # Browser origins allowed to PUT/GET presigned blobs directly from the SPA.
  # Derived from explicit app_base_url / entra_redirect_uri rather than module.frontend
  # to avoid a dependency cycle (frontend → container_app → storage).
  _spa_origin = trimsuffix(
    var.app_base_url != ""
    ? var.app_base_url
    : try(regex("^https?://[^/]+", var.entra_redirect_uri), ""),
    "/",
  )
  storage_cors_origins = local._spa_origin != "" ? [local._spa_origin] : []

  # Content-Security-Policy for the SPA — mirrors the AWS CloudFront module's
  # policy: only this origin's scripts, plus img-src/connect-src to the assets
  # storage account (presigned uploads and tenant logos) and the Entra identity endpoints.
  content_security_policy = join("; ", [
    "default-src 'self'",
    "script-src 'self'",
    # 'unsafe-inline' stays for the inline style attributes the app sets at runtime.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: ${local.storage_blob_origin}",
    # Fonts are self-hosted (frontend/src/design/fonts.css, audit FD-06).
    "font-src 'self'",
    "connect-src 'self' ${var.api_base_url} https://*.azurecontainerapps.io ${local.storage_blob_origin} https://login.microsoftonline.com https://*.ciamlogin.com",
    "frame-ancestors 'none'",
    "base-uri 'self'",
  ])
}
