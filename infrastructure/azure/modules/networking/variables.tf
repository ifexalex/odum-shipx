variable "name_prefix" {
  description = "Resource name prefix (e.g. shipx-prod)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group to create networking in."
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

variable "vnet_cidr" {
  description = "VNet address space. 10.1.0.0/16 (AWS uses 10.0.0.0/16; kept distinct for clarity)."
  type        = string
  default     = "10.1.0.0/16"
}

variable "container_apps_subnet_cidr" {
  description = "Subnet for the Container Apps Environment (delegated). /23 minimum."
  type        = string
  default     = "10.1.0.0/23"
}

variable "postgres_subnet_cidr" {
  description = "Subnet delegated to Postgres Flexible Server for VNet integration."
  type        = string
  default     = "10.1.4.0/24"
}

variable "private_endpoints_subnet_cidr" {
  description = "Subnet for private endpoints (Redis/Service Bus/etc.)."
  type        = string
  default     = "10.1.5.0/24"
}
