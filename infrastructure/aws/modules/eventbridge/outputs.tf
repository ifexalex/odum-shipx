output "event_bus_name" {
  description = "Custom EventBridge event bus name"
  value       = aws_cloudwatch_event_bus.main.name
}

output "event_bus_arn" {
  description = "Custom EventBridge event bus ARN"
  value       = aws_cloudwatch_event_bus.main.arn
}

output "scheduled_rule_arns" {
  description = "Map of scheduled rule name → ARN (used by Task 16 to attach Lambda targets)"
  value       = { for k, v in aws_cloudwatch_event_rule.scheduled : k => v.arn }
}
