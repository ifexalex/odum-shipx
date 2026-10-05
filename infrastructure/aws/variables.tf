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

# ---------------------------------------------------------------------------
# Frontend (CloudFront + S3) variables
# ---------------------------------------------------------------------------

variable "domain_name" {
  description = "Root domain for the frontend (e.g. shipx.co). CloudFront serves both the apex and *.{domain_name} for tenant subdomains."
  type        = string
  default     = "shipx.co"
}

variable "route53_zone_id" {
  description = "Route 53 hosted zone ID for the domain. Must exist before applying."
  type        = string
  default     = ""
}

variable "frontend_price_class" {
  description = "CloudFront price class. PriceClass_100 (US/EU edges) is cheapest and covers the logistics ops audience."
  type        = string
  default     = "PriceClass_100"
}

# paystack_secret_key removed (2026-07-19) — multi-tenant Paystack: each
# tenant connects their own key via PUT /v1/tenant/config/paystack, encrypted
# in tenant_config. There is no platform-wide key to provision via Terraform
# anymore. See services/payment_release/paystack.py's module docstring.
