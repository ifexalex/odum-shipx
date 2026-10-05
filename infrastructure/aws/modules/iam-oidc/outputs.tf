output "deploy_role_arns" {
  description = "Map of environment → GitHub Actions IAM deploy role ARN. Set each as AWS_DEPLOY_ROLE_ARN in the matching GitHub Environment secret."
  value       = { for env, role in aws_iam_role.deploy : env => role.arn }
}

output "deploy_role_names" {
  description = "Map of environment → IAM role name"
  value       = { for env, role in aws_iam_role.deploy : env => role.name }
}

output "oidc_provider_arn" {
  description = "GitHub Actions OIDC provider ARN"
  value       = aws_iam_openid_connect_provider.github.arn
}

output "permissions_boundary_arn" {
  description = "Lambda permissions boundary policy ARN — attach to all Lambda execution roles created by Terraform modules"
  value       = aws_iam_policy.permissions_boundary.arn
}
