output "user_pool_id" {
  description = "Cognito User Pool ID"
  value       = aws_cognito_user_pool.main.id
}

output "user_pool_arn" {
  description = "Cognito User Pool ARN"
  value       = aws_cognito_user_pool.main.arn
}

output "client_id" {
  description = "Cognito User Pool App Client ID"
  value       = aws_cognito_user_pool_client.web.id
}

output "user_pool_domain" {
  description = "Cognito hosted UI domain prefix"
  value       = aws_cognito_user_pool_domain.main.domain
}

output "platform_user_pool_id" {
  description = "Platform admins' Cognito User Pool ID (MFA required; platform audit Phase 1b)"
  value       = aws_cognito_user_pool.platform.id
}

output "platform_user_pool_arn" {
  description = "Platform admins' Cognito User Pool ARN"
  value       = aws_cognito_user_pool.platform.arn
}

output "platform_client_id" {
  description = "Platform admins' public app client ID"
  value       = aws_cognito_user_pool_client.platform_web.id
}
