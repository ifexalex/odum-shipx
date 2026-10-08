variable "name_prefix" {
  description = "Resource name prefix (e.g. shipx-prod)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group to create the vault in."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "extra_object_ids" {
  description = "Additional AAD object IDs granted key wrap/unwrap + secret read (e.g. the app's managed identity)."
  type        = list(string)
  default     = []
}

variable "common_tags" {
  description = "Tags applied to all resources."
  type        = map(string)
}
