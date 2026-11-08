output "cluster_endpoint" {
  description = "Writer endpoint for the Aurora cluster (direct connection)"
  value       = aws_rds_cluster.main.endpoint
}

output "reader_endpoint" {
  description = "Reader endpoint for the Aurora cluster"
  value       = aws_rds_cluster.main.reader_endpoint
}

output "rds_proxy_endpoint" {
  description = "RDS Proxy endpoint — use this in Lambda functions (not the cluster endpoint)"
  value       = aws_db_proxy.main.endpoint
}

output "db_name" {
  description = "Name of the application database"
  value       = aws_rds_cluster.main.database_name
}

output "db_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the MASTER (owner) DB credentials — migrations and admin only"
  value       = aws_secretsmanager_secret.db_password.arn
}

output "db_app_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the logistics_app credentials — what the application connects with (subject to RLS)"
  value       = aws_secretsmanager_secret.db_app_password.arn
}

output "cluster_arn" {
  description = "ARN of the Aurora cluster"
  value       = aws_rds_cluster.main.arn
}
