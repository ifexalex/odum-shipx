variable "name_prefix" {
  description = "Resource name prefix (e.g. shipx-prod)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group."
  type        = string
}

variable "common_tags" {
  description = "Tags applied to all resources."
  type        = map(string)
}

variable "data_location" {
  description = "ACS data residency region (e.g. Europe, United States). Not the deployment region."
  type        = string
  default     = "Europe"
}
