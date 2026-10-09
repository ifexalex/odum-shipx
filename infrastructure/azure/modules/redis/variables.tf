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

variable "capacity" {
  description = "Cache size. For Basic/Standard (family C): 0 = C0 (250 MB, cheapest)."
  type        = number
  default     = 0
}

variable "family" {
  description = "SKU family: C (Basic/Standard) or P (Premium)."
  type        = string
  default     = "C"
}

variable "sku_name" {
  description = "Redis SKU: Basic / Standard / Premium."
  type        = string
  default     = "Basic"
}
