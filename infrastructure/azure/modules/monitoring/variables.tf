variable "name_prefix" {
  description = "Resource name prefix (e.g. shipx-prod)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group."
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

variable "retention_in_days" {
  description = "Log Analytics retention."
  type        = number
  default     = 30
}
