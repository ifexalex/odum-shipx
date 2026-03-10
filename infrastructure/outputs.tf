# ---------------------------------------------------------------------------
# Task 04a outputs — networking + database
# ---------------------------------------------------------------------------

output "vpc_id" {
  description = "VPC ID"
  value       = module.networking.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs (for Lambda + Aurora)"
  value       = module.networking.private_subnet_ids
}

output "lambda_security_group_id" {
  description = "Security group ID to attach to VPC-connected Lambdas"
  value       = module.networking.lambda_security_group_id
}

output "rds_proxy_endpoint" {
  description = "RDS Proxy endpoint — used by Lambda as DATABASE_HOST"
  value       = module.aurora.rds_proxy_endpoint
}

output "db_secret_arn" {
  description = "Secrets Manager ARN for Aurora DB credentials"
  value       = module.aurora.db_secret_arn
  sensitive   = true
}

output "db_name" {
  description = "Aurora database name"
  value       = module.aurora.db_name
}

output "cluster_arn" {
  description = "Aurora cluster ARN"
  value       = module.aurora.cluster_arn
}

output "user_pool_id" {
  description = "Cognito User Pool ID"
  value       = module.cognito.user_pool_id
}

output "user_pool_arn" {
  description = "Cognito User Pool ARN"
  value       = module.cognito.user_pool_arn
}

output "cognito_client_id" {
  description = "Cognito User Pool App Client ID"
  value       = module.cognito.client_id
}

output "user_pool_domain" {
  description = "Cognito hosted UI domain prefix"
  value       = module.cognito.user_pool_domain
}

output "api_endpoint" {
  description = "API Gateway invoke URL ($default stage)"
  value       = module.api_gateway.api_endpoint
}

output "api_id" {
  description = "API Gateway HTTP API ID"
  value       = module.api_gateway.api_id
}

output "api_execution_arn" {
  description = "API Gateway execution ARN (used for Lambda invoke permissions)"
  value       = module.api_gateway.execution_arn
}

output "assets_bucket_name" {
  description = "S3 assets bucket name"
  value       = module.s3.bucket_name
}

output "assets_bucket_arn" {
  description = "S3 assets bucket ARN"
  value       = module.s3.bucket_arn
}

output "sqs_queue_urls" {
  description = "Map of SQS queue name → URL (sms, whatsapp, email, metering)"
  value       = module.sqs.queue_urls
}

output "sqs_queue_arns" {
  description = "Map of SQS queue name → ARN (sms, whatsapp, email, metering)"
  value       = module.sqs.queue_arns
}

output "event_bus_name" {
  description = "Custom EventBridge event bus name"
  value       = module.eventbridge.event_bus_name
}

output "event_bus_arn" {
  description = "Custom EventBridge event bus ARN"
  value       = module.eventbridge.event_bus_arn
}

output "ses_identity_arn" {
  description = "SES email identity ARN"
  value       = module.ses.ses_identity_arn
}

output "lambda_arns" {
  description = "Map of API service key → Lambda ARN"
  value       = module.lambda.api_lambda_arns
}

output "alerts_topic_arn" {
  description = "SNS topic ARN for CloudWatch alarm notifications"
  value       = module.monitoring.alerts_topic_arn
}

output "deploy_role_arns" {
  description = "GitHub Actions IAM deploy role ARNs — set each as AWS_DEPLOY_ROLE_ARN in the matching GitHub Environment secret"
  value       = module.iam_oidc.deploy_role_arns
}

output "oidc_provider_arn" {
  description = "GitHub Actions OIDC provider ARN"
  value       = module.iam_oidc.oidc_provider_arn
}

output "permissions_boundary_arn" {
  description = "Lambda permissions boundary policy ARN"
  value       = module.iam_oidc.permissions_boundary_arn
}
