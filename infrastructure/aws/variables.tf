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

# ---------------------------------------------------------------------------
# Notification channels — email, SMS, WhatsApp
# Passed through to modules/lambda, which documents each one.
# ---------------------------------------------------------------------------

variable "app_base_url" {
  description = "Absolute base URL of the web app, for activation and invite links (e.g. https://app.example.com)."
  type        = string
  default     = ""
}

variable "customer_portal_base_url" {
  description = "Override base URL for customer invite links if the customer portal is hosted separately. Falls back to app_base_url."
  type        = string
  default     = ""
}

variable "ses_from_address" {
  description = "Verified SES sender address for outbound notification email."
  type        = string
  default     = ""
}

variable "africastalking_api_key" {
  description = "Africa's Talking API key for SMS."
  type        = string
  default     = ""
  sensitive   = true
}

variable "africastalking_username" {
  description = "Africa's Talking username — the live one in production, not 'sandbox'."
  type        = string
  default     = ""
}

variable "africastalking_sender_id" {
  description = "Africa's Talking sender ID / short code, if registered."
  type        = string
  default     = ""
}

variable "meta_whatsapp_access_token" {
  description = "Meta Cloud API access token for WhatsApp Business."
  type        = string
  default     = ""
  sensitive   = true
}

variable "meta_whatsapp_phone_id" {
  description = "Meta Cloud API phone number ID for WhatsApp Business."
  type        = string
  default     = ""
}

variable "meta_whatsapp_template_lang" {
  description = "Language code the WhatsApp templates were approved under. Must match Meta exactly."
  type        = string
  default     = ""
}

variable "whatsapp_verify_token" {
  description = "Shared secret Meta echoes when verifying the WhatsApp webhook subscription."
  type        = string
  default     = ""
  sensitive   = true
}

variable "notification_allowlist" {
  description = "Comma-separated phones/emails messageable OUTSIDE production. Empty = nothing sent outside production."
  type        = string
  default     = ""
}
