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

variable "vnet_id" {
  description = "Virtual network id (for the private DNS zone link)."
  type        = string
}

variable "delegated_subnet_id" {
  description = "Subnet delegated to Microsoft.DBforPostgreSQL/flexibleServers."
  type        = string
}

variable "key_vault_id" {
  description = "Key Vault id to store the generated admin password in."
  type        = string
}

variable "administrator_login" {
  description = "Postgres admin username. 'postgres' is reserved on Azure Flexible Server; use a distinct name."
  type        = string
  default     = "shipxadmin"
}

variable "database_name" {
  description = "Application database name — matches the AWS side so migrations run unchanged."
  type        = string
  default     = "logistics"
}

variable "sku_name" {
  description = "Flexible Server SKU. Burstable B1ms is the cheapest; use GP_Standard_* for prod."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "storage_mb" {
  description = "Storage in MB (32768 = 32 GiB minimum)."
  type        = number
  default     = 32768
}

variable "backup_retention_days" {
  description = "Automated backup retention in days."
  type        = number
  default     = 7
}
