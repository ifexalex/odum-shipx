output "api_endpoint" {
  description = "Base invoke URL for the $default stage (e.g. https://{id}.execute-api.{region}.amazonaws.com)"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "api_id" {
  description = "API Gateway HTTP API ID"
  value       = aws_apigatewayv2_api.main.id
}

output "execution_arn" {
  description = "API Gateway execution ARN — used to grant Lambda invoke permissions"
  value       = aws_apigatewayv2_api.main.execution_arn
}
