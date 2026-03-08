variable "project_name" {
  description = "Project name used in resource naming"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID where Aurora and RDS Proxy reside"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for Aurora and RDS Proxy"
  type        = list(string)
}

variable "db_subnet_group_name" {
  description = "Name of the DB subnet group for Aurora"
  type        = string
}

variable "aurora_security_group_id" {
  description = "Security group ID for the Aurora cluster"
  type        = string
}

variable "rds_proxy_security_group_id" {
  description = "Security group ID for the RDS Proxy"
  type        = string
}

variable "min_acu" {
  description = "Minimum Aurora Capacity Units for Serverless v2 scaling"
  type        = number
  default     = 0.5
}

variable "max_acu" {
  description = "Maximum Aurora Capacity Units for Serverless v2 scaling"
  type        = number
  default     = 4
}

variable "deletion_protection" {
  description = "Enables deletion protection on the Aurora cluster (set true for prod)"
  type        = bool
  default     = false
}
