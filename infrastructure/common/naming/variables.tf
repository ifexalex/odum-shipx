variable "project_name" {
  description = "Project name — first segment of every resource name."
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev / staging / prod / demo)."
  type        = string
}

variable "cloud" {
  description = "Cloud provider, added as a `Cloud` tag (e.g. aws / azure). Empty = omit the tag."
  type        = string
  default     = ""
}
