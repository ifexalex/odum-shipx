locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

# ---------------------------------------------------------------------------
# DB Master Password — stored in Secrets Manager (never hardcoded per §8.1)
# ---------------------------------------------------------------------------

resource "random_password" "db_master" {
  length           = 24
  special          = false # psycopg2 DSN is sensitive to some special chars
  override_special = ""
}

resource "aws_secretsmanager_secret" "db_password" {
  name        = "${local.name_prefix}-db-password"
  description = "Aurora master password for the ${var.environment} logistics database. 90-day rotation recommended via AWS Secrets Manager rotation Lambda."

  tags = {
    Name = "${local.name_prefix}-db-password"
  }
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id = aws_secretsmanager_secret.db_password.id
  secret_string = jsonencode({
    username = "postgres"
    password = random_password.db_master.result
  })
}

# ---------------------------------------------------------------------------
# Aurora Serverless v2 Cluster
# ---------------------------------------------------------------------------

resource "aws_rds_cluster" "main" {
  cluster_identifier = "${local.name_prefix}-aurora"
  engine             = "aurora-postgresql"
  engine_version     = "15.4"
  engine_mode        = "provisioned" # required for Serverless v2

  serverlessv2_scaling_configuration {
    min_capacity = var.min_acu
    max_capacity = var.max_acu
  }

  database_name   = "logistics"
  master_username = "postgres"
  master_password = random_password.db_master.result

  db_subnet_group_name   = var.db_subnet_group_name
  vpc_security_group_ids = [var.aurora_security_group_id]

  storage_encrypted   = true
  deletion_protection = var.deletion_protection

  backup_retention_period      = 7
  preferred_backup_window      = "03:00-04:00"
  preferred_maintenance_window = "sun:05:00-sun:06:00"

  # Skip final snapshot in dev/staging; take one in prod
  skip_final_snapshot       = !var.deletion_protection
  final_snapshot_identifier = var.deletion_protection ? "${local.name_prefix}-aurora-final-snapshot" : null

  tags = {
    Name = "${local.name_prefix}-aurora"
  }
}

resource "aws_rds_cluster_instance" "main" {
  identifier         = "${local.name_prefix}-aurora-instance-1"
  cluster_identifier = aws_rds_cluster.main.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.main.engine
  engine_version     = aws_rds_cluster.main.engine_version

  tags = {
    Name = "${local.name_prefix}-aurora-instance-1"
  }
}

# ---------------------------------------------------------------------------
# IAM Role for RDS Proxy — allows proxy to read the DB secret
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "rds_proxy_assume" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["rds.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "rds_proxy" {
  name                 = "${local.name_prefix}-rds-proxy-role"
  assume_role_policy   = data.aws_iam_policy_document.rds_proxy_assume.json
  permissions_boundary = var.permissions_boundary_arn

  tags = {
    Name = "${local.name_prefix}-rds-proxy-role"
  }
}

data "aws_iam_policy_document" "rds_proxy_secrets" {
  statement {
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.db_password.arn]
  }
}

resource "aws_iam_role_policy" "rds_proxy_secrets" {
  name   = "${local.name_prefix}-rds-proxy-secrets-policy"
  role   = aws_iam_role.rds_proxy.id
  policy = data.aws_iam_policy_document.rds_proxy_secrets.json
}

# ---------------------------------------------------------------------------
# RDS Proxy
# ---------------------------------------------------------------------------

resource "aws_db_proxy" "main" {
  name                   = "${local.name_prefix}-rds-proxy"
  debug_logging          = false
  engine_family          = "POSTGRESQL"
  idle_client_timeout    = 1800 # 30 minutes
  require_tls            = true
  role_arn               = aws_iam_role.rds_proxy.arn
  vpc_security_group_ids = [var.rds_proxy_security_group_id]
  vpc_subnet_ids         = var.private_subnet_ids

  auth {
    auth_scheme = "SECRETS"
    description = "Aurora master password"
    iam_auth    = "DISABLED"
    secret_arn  = aws_secretsmanager_secret.db_password.arn
  }

  tags = {
    Name = "${local.name_prefix}-rds-proxy"
  }
}

resource "aws_db_proxy_default_target_group" "main" {
  db_proxy_name = aws_db_proxy.main.name

  connection_pool_config {
    connection_borrow_timeout    = 120
    max_connections_percent      = 80
    max_idle_connections_percent = 50
  }
}

resource "aws_db_proxy_target" "main" {
  db_cluster_identifier = aws_rds_cluster.main.cluster_identifier
  db_proxy_name         = aws_db_proxy.main.name
  target_group_name     = aws_db_proxy_default_target_group.main.name
}
