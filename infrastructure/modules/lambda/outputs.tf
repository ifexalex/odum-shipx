output "api_lambda_arns" {
  description = "Map of API Gateway service key → Lambda ARN (passed to api_gateway module as lambda_arns)"
  # Constructed from static locals + data sources so keys/values are known at plan time,
  # allowing api_gateway module to use this map in for_each without "known after apply" errors.
  value = merge(
    {
      for k, v in local.vpc_api_configs :
      k => "arn:aws:lambda:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:function:${var.project_name}-${v.name}-${var.environment}"
    },
    {
      # Dual-mode SQS/HTTP Lambda — serves GET /v1/platform/tenants/{id}/usage.
      metering = "arn:aws:lambda:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:function:${var.project_name}-${local.metering_config.name}-${var.environment}"
    },
    {
      for k, v in local.non_vpc_api_configs :
      k => "arn:aws:lambda:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:function:${var.project_name}-${v.name}-${var.environment}"
    },
  )
}

output "all_function_names" {
  description = "List of all Lambda function names (used by monitoring module for alarms)"
  # Use the static local (computed from variables, not resource attributes) so monitoring
  # module can use this list in for_each without "known after apply" errors.
  value = local.all_function_names
}

output "shared_layer_arn" {
  description = "ARN of the shared Lambda Layer version"
  value       = aws_lambda_layer_version.shared.arn
}
