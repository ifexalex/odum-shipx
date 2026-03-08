output "redis_host" {
  description = "ElastiCache Redis primary endpoint hostname (injected as REDIS_HOST into Lambda)"
  value       = aws_elasticache_cluster.tenant_status.cache_nodes[0].address
}

output "redis_port" {
  description = "ElastiCache Redis port (always 6379)"
  value       = aws_elasticache_cluster.tenant_status.port
}

output "elasticache_security_group_id" {
  description = "Security group ID for the ElastiCache cluster"
  value       = aws_security_group.elasticache.id
}
