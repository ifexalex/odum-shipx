output "api_lambda_arns" {
  description = "Map of API Gateway service key → Lambda ARN (passed to api_gateway module as lambda_arns)"
  value = merge(
    { for k, v in aws_lambda_function.vpc_api : k => v.arn },
    # notif_whatsapp handles the GET/POST /v1/webhooks/whatsapp public routes
    { notification = aws_lambda_function.notification["notif_whatsapp"].arn },
  )
}

output "all_function_names" {
  description = "List of all Lambda function names (used by monitoring module for alarms)"
  value = concat(
    [for v in aws_lambda_function.vpc_api : v.function_name],
    [aws_lambda_function.metering.function_name],
    [for v in aws_lambda_function.notification : v.function_name],
    [for v in aws_lambda_function.scheduled_job : v.function_name],
  )
}

output "shared_layer_arn" {
  description = "ARN of the shared Lambda Layer version"
  value       = aws_lambda_layer_version.shared.arn
}
