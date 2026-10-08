output "queue_urls" {
  description = "Map of queue name → SQS URL for main queues"
  value       = { for k, v in aws_sqs_queue.main : k => v.url }
}

output "queue_arns" {
  description = "Map of queue name → SQS ARN for main queues"
  value       = { for k, v in aws_sqs_queue.main : k => v.arn }
}

output "dlq_urls" {
  description = "Map of queue name → SQS URL for dead-letter queues"
  value       = { for k, v in aws_sqs_queue.dlq : k => v.url }
}

output "dlq_arns" {
  description = "Map of queue name → SQS ARN for dead-letter queues"
  value       = { for k, v in aws_sqs_queue.dlq : k => v.arn }
}
