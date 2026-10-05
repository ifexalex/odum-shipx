variable "project_name" {
  description = "Project name — used in resource naming (e.g. logistics)"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository in OWNER/REPO format for OIDC trust policy (e.g. ifexalex/odum-shipx)"
  type        = string
}
