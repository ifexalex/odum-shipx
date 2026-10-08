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
