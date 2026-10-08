variable "project_name" {
  description = "Project name used in resource naming and tagging"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID for the ElastiCache subnet group and security group"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for ElastiCache (must match Lambda subnets)"
  type        = list(string)
}

variable "lambda_security_group_id" {
  description = "Lambda security group ID — granted inbound access to Redis port"
  type        = string
}

variable "node_type" {
  description = "ElastiCache node type. cache.t4g.micro is the cheapest (~$11.52/month in eu-west-1)"
  type        = string
  default     = "cache.t4g.micro"
}
