variable "project_name" {
  description = "Project name used in resource naming"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "cors_allow_origins" {
  description = "Allowed CORS origins for presigned upload requests"
  type        = list(string)
  default     = ["http://localhost:3000"]
}
