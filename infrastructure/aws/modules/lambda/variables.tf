variable "project_name" {
  description = "Project name used in resource naming and tagging"
  type        = string
}

variable "permissions_boundary_arn" {
  description = "IAM permissions boundary ARN to attach to all Lambda execution roles"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for VPC-attached Lambda functions"
  type        = list(string)
}

variable "lambda_security_group_id" {
  description = "Security group ID to attach to VPC-connected Lambdas"
  type        = string
}

variable "rds_proxy_endpoint" {
  description = "RDS Proxy endpoint used as DATABASE_HOST by VPC Lambdas"
  type        = string
}

variable "db_name" {
  description = "Aurora database name"
  type        = string
}

variable "db_secret_arn" {
  description = "Secrets Manager ARN for Aurora DB credentials"
  type        = string
}

variable "cluster_arn" {
  description = "Aurora cluster ARN (used in rds-db:connect IAM policy)"
  type        = string
}

variable "bucket_name" {
  description = "S3 assets bucket name"
  type        = string
}

variable "event_bus_name" {
  description = "Custom EventBridge event bus name"
  type        = string
}

variable "cognito_user_pool_id" {
  description = "Cognito User Pool ID"
  type        = string
}

variable "cognito_user_pool_arn" {
  description = "Cognito User Pool ARN (for tenant_management IAM policy)"
  type        = string
}

variable "cognito_client_id" {
  description = "Cognito App Client ID (public client, no secret — for the auth Lambda's refresh-token exchange)"
  type        = string
}

variable "sqs_queue_arns" {
  description = "Map of queue name → SQS ARN (sms, whatsapp, email, metering)"
  type        = map(string)
}

variable "sqs_queue_urls" {
  description = "Map of queue name → SQS URL (sms, whatsapp, email, metering). Injected as SQS_*_QUEUE_URL env vars for the notification producers."
  type        = map(string)
  default     = {}
}

variable "ses_identity_arn" {
  description = "SES email identity ARN (for notification-email IAM policy)"
  type        = string
}

variable "scheduled_rule_arns" {
  description = "Map of scheduled rule name → ARN (from eventbridge module)"
  type        = map(string)
}

variable "api_execution_arn" {
  description = "API Gateway execution ARN (used for Lambda invoke permissions)"
  type        = string
}

variable "encryption_kms_key_arn" {
  description = "KMS key ARN for field-level PII encryption (id_number, account_number, account_name)"
  type        = string
}

variable "redis_host" {
  description = "ElastiCache Redis endpoint hostname — injected as REDIS_HOST into all Lambda functions"
  type        = string
}

variable "local_env_overrides" {
  description = "Extra/override env vars merged into every Lambda (used for LocalStack local testing)"
  type        = map(string)
  default     = {}
}
