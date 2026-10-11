variable "name_prefix" {
  description = "Resource name prefix (e.g. logistics-dev)."
  type        = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "common_tags" {
  type = map(string)
}

variable "python_version" {
  description = "Python runtime for the Function App (Azure Functions supported version)."
  type        = string
  default     = "3.12"
}

variable "app_insights_connection_string" {
  description = "Application Insights connection string (observability). Optional."
  type        = string
  default     = ""
  sensitive   = true
}

# --- Entra claims-extension config (filled after the manual Entra tenant setup) ---
# These are unknown at first apply (the Entra app/tenant is created by hand), so
# they default to empty; the Function deploys but denies callers until set. Supply
# them via tfvars once the Entra app registration + custom-auth-extension exist.

variable "caller_jwks_url" {
  description = "Tenant JWKS URL used to verify the inbound Entra caller token."
  type        = string
  default     = ""
}

variable "caller_audience" {
  description = "Expected `aud` of the inbound Entra caller token (the extension's API app id)."
  type        = string
  default     = ""
}

variable "caller_issuer" {
  description = "Expected `iss` of the inbound Entra caller token."
  type        = string
  default     = ""
}

variable "tenant_id_attr" {
  description = "Directory extension attribute holding the ShipX tenant id (extension_<appId>_tenant_id)."
  type        = string
  default     = ""
}

variable "role_attr" {
  description = "Directory extension attribute holding the ShipX role (extension_<appId>_role)."
  type        = string
  default     = ""
}

variable "out_tenant_claim" {
  description = "Claim name to emit the tenant id as (must match backend ENTRA_TENANT_ID_CLAIM)."
  type        = string
  default     = "tenant_id"
}

variable "out_role_claim" {
  description = "Claim name to emit the role as (must match backend ENTRA_ROLE_CLAIM)."
  type        = string
  default     = "role"
}

variable "graph_base_url" {
  description = "Microsoft Graph base URL (override for sovereign clouds)."
  type        = string
  default     = "https://graph.microsoft.com/v1.0"
}
