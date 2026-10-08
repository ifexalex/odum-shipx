variable "project_name" {
  description = "Project name used in resource naming"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "callback_urls" {
  description = "Allowed OAuth callback URLs for the app client"
  type        = list(string)
  default     = ["http://localhost:3000/callback"]
}

variable "logout_urls" {
  description = "Allowed OAuth logout URLs for the app client"
  type        = list(string)
  default     = ["http://localhost:3000/logout"]
}
