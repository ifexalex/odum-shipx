variable "name_prefix" {
  description = "Resource name prefix (project-environment)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group to create resources in."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "common_tags" {
  description = "Tags applied to all resources."
  type        = map(string)
}

variable "content_security_policy" {
  description = "CSP header value for the SPA."
  type        = string
}

variable "api_origin_host" {
  description = "API Container App ingress FQDN. When set, Front Door serves /v1/* and /health from it so the API is same-origin with the SPA (first-party auth cookies, no CORS). Empty disables the API route."
  type        = string
  default     = ""
}

variable "frontdoor_profile_id" {
  description = "Resource id of the Front Door profile (created at the root; see the note in main.tf)."
  type        = string
}

variable "frontdoor_profile_name" {
  description = "Name of that Front Door profile, re-exported for the CI cache purge."
  type        = string
}
