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

  # Content-Security-Policy for the SPA — mirrors the AWS CloudFront module's
  # policy: only this origin's scripts, plus connect-src to the API and the
  # Entra (Azure AD) identity endpoints.
  content_security_policy = join("; ", [
    "default-src 'self'",
    "script-src 'self'",
    # 'unsafe-inline' stays for the inline style attributes the app sets at runtime.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    # Fonts are self-hosted (frontend/src/design/fonts.css, audit FD-06).
    "font-src 'self'",
    "connect-src 'self' ${var.api_base_url} https://*.azurecontainerapps.io https://login.microsoftonline.com https://*.ciamlogin.com",
    "frame-ancestors 'none'",
    "base-uri 'self'",
  ])
}
