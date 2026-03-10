variable "project_name" {
  description = "Project name used in resource naming and tagging"
  type        = string
  default     = "logistics"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod"
  }
}

variable "aws_region" {
  description = "AWS region for resource deployment"
  type        = string
  default     = "eu-west-1"
}

variable "availability_zones" {
  description = "List of AZs to deploy subnets into (2 required)"
  type        = list(string)
  default     = ["eu-west-1a", "eu-west-1b"]
}

variable "min_acu" {
  description = "Minimum Aurora Capacity Units for Serverless v2 scaling"
  type        = number
  default     = 0.5
}

variable "max_acu" {
  description = "Maximum Aurora Capacity Units for Serverless v2 scaling"
  type        = number
  default     = 4
}

variable "deletion_protection" {
  description = "Enables deletion protection on Aurora cluster (true in prod)"
  type        = bool
  default     = false
}

variable "cors_allow_origins" {
  description = "CORS allowed origins for API Gateway"
  type        = list(string)
  default     = ["http://localhost:3000"]
}

variable "ses_from_email" {
  description = "Email address to verify with SES for sending notifications"
  type        = string
  default     = "noreply@logistics.example.com"
}

variable "alerts_email" {
  description = "Email address for CloudWatch alarm SNS notifications (leave empty to skip subscription)"
  type        = string
  default     = ""
}

variable "elasticache_node_type" {
  description = "ElastiCache node type for the tenant-status Redis cluster. cache.t4g.micro is cheapest (~$11.52/month in eu-west-1)"
  type        = string
  default     = "cache.t4g.micro"
}

variable "local_env_overrides" {
  description = "Extra/override Lambda env vars for local/LocalStack testing (empty in real environments)"
  type        = map(string)
  default     = {}
}

variable "github_repo" {
  description = "GitHub repository in OWNER/REPO format for OIDC trust policy (e.g. ifexalex/odum-shipx)"
  type        = string
}
