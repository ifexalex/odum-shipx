variable "project_name" {
  description = "Project name, used as the resource name prefix."
  type        = string
  default     = "shipx"
}

variable "environment" {
  description = "Deployment environment (dev / staging / prod / demo)."
  type        = string
  default     = "prod"
}

variable "location" {
  description = "Azure region. North/West Europe mirror the AWS eu-west-1 deployment."
  type        = string
  default     = "northeurope"
}

variable "api_base_url" {
  description = "Public base URL of the backend API, used in the SPA's CSP connect-src (e.g. https://api.shipx.example). Leave as the placeholder until the backend stack exists."
  type        = string
  default     = "https://api.invalid"
}
