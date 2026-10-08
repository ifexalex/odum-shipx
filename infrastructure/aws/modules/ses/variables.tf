variable "project_name" {
  description = "Project name used in resource naming"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "from_email" {
  description = "Email address to verify with SES for outbound notifications"
  type        = string
}
