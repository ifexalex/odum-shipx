variable "project_name" {
  description = "Project name used in resource naming and tagging"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "lambda_function_names" {
  description = "List of all Lambda function names (for per-function CloudWatch alarms)"
  type        = list(string)
}

variable "api_id" {
  description = "API Gateway HTTP API ID (for 5xx error alarm)"
  type        = string
}

variable "dlq_names" {
  description = "Map of logical queue name → SQS DLQ queue name (for DLQ depth alarms)"
  type        = map(string)
}

variable "cluster_identifier" {
  description = "Aurora cluster identifier (for database connections alarm)"
  type        = string
}

variable "alerts_email" {
  description = "Email address for SNS alarm notifications (leave empty to skip subscription)"
  type        = string
  default     = ""
}
