output "vpc_id" {
  description = "The ID of the VPC"
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "IDs of the private subnets (for Aurora + VPC-attached Lambdas)"
  value       = aws_subnet.private[*].id
}

output "public_subnet_ids" {
  description = "IDs of the public subnets (for future NAT or ALB)"
  value       = aws_subnet.public[*].id
}

output "lambda_security_group_id" {
  description = "Security group ID to attach to VPC-connected Lambda functions"
  value       = aws_security_group.lambda.id
}

output "aurora_security_group_id" {
  description = "Security group ID for the Aurora cluster"
  value       = aws_security_group.aurora.id
}

output "rds_proxy_security_group_id" {
  description = "Security group ID for the RDS Proxy"
  value       = aws_security_group.rds_proxy.id
}

output "db_subnet_group_name" {
  description = "Name of the DB subnet group for Aurora"
  value       = aws_db_subnet_group.aurora.name
}
