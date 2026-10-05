variable "project_name" {
  description = "Project name used in resource naming"
  type        = string
}

variable "permissions_boundary_arn" {
  description = "IAM permissions boundary ARN to attach to the EventBridge delivery role"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "sqs_queue_arns" {
  description = "Map of queue name → SQS ARN for routing rule targets"
  type        = map(string)
}

variable "sqs_queue_urls" {
  description = "Map of queue name → SQS URL for resource policies"
  type        = map(string)
}
