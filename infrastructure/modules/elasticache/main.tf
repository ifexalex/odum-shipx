locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

# ---------------------------------------------------------------------------
# Subnet group — ElastiCache must be in the same private subnets as Lambda
# ---------------------------------------------------------------------------

resource "aws_elasticache_subnet_group" "main" {
  name       = "${local.name_prefix}-elasticache-subnet-group"
  subnet_ids = var.private_subnet_ids

  tags = {
    Name = "${local.name_prefix}-elasticache-subnet-group"
  }
}

# ---------------------------------------------------------------------------
# Security group — allows inbound Redis (6379) from Lambda SG only
# ---------------------------------------------------------------------------

resource "aws_security_group" "elasticache" {
  name        = "${local.name_prefix}-sg-elasticache"
  description = "Allows inbound Redis from Lambda security group only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Redis from Lambda"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [var.lambda_security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name = "${local.name_prefix}-sg-elasticache"
  }
}

# ---------------------------------------------------------------------------
# Lambda -> ElastiCache egress rule (cross-SG, declared here to avoid cycle)
# ---------------------------------------------------------------------------

resource "aws_security_group_rule" "lambda_egress_elasticache" {
  type                     = "egress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  security_group_id        = var.lambda_security_group_id
  source_security_group_id = aws_security_group.elasticache.id
  description              = "Redis to ElastiCache"
}

# ---------------------------------------------------------------------------
# ElastiCache cluster — single-node Redis 7, cache.t4g.micro (cheapest)
# Upgrade to aws_elasticache_replication_group for Multi-AZ prod when ready.
# ---------------------------------------------------------------------------

resource "aws_elasticache_cluster" "tenant_status" {
  cluster_id           = "${local.name_prefix}-tenant-status"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.node_type
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.main.name
  security_group_ids   = [aws_security_group.elasticache.id]

  # Maintenance window — off-peak for eu-west-1 (Sunday 03:00-04:00 UTC)
  maintenance_window = "sun:03:00-sun:04:00"

  tags = {
    Name        = "${local.name_prefix}-elasticache-tenant-status"
    Purpose     = "tenant-status-cache"
    ManagedBy   = "terraform"
    Environment = var.environment
  }
}
