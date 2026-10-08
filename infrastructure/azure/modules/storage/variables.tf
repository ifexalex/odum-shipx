variable "name_prefix" {
  description = "Resource name prefix (e.g. shipx-prod)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group to create the storage account in."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "container_name" {
  description = "Blob container name — the StorageProvider 'bucket' (BLOB_CONTAINER_NAME)."
  type        = string
  default     = "logistics-assets"
}

variable "common_tags" {
  description = "Tags applied to all resources."
  type        = map(string)
}
