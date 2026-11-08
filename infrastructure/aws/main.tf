# ---------------------------------------------------------------------------
# Task 04a: Networking + Aurora modules
# ---------------------------------------------------------------------------

module "networking" {
  source = "./modules/networking"

  project_name       = var.project_name
  environment        = var.environment
  availability_zones = var.availability_zones
}

module "aurora" {
  source = "./modules/aurora"

  project_name                = var.project_name
  environment                 = var.environment
  vpc_id                      = module.networking.vpc_id
  private_subnet_ids          = module.networking.private_subnet_ids
  db_subnet_group_name        = module.networking.db_subnet_group_name
  aurora_security_group_id    = module.networking.aurora_security_group_id
  rds_proxy_security_group_id = module.networking.rds_proxy_security_group_id
  min_acu                     = var.min_acu
  max_acu                     = var.max_acu
  deletion_protection         = var.deletion_protection
  permissions_boundary_arn    = module.iam_oidc.permissions_boundary_arn
}

module "cognito" {
  source       = "./modules/cognito"
  project_name = var.project_name
  environment  = var.environment
}

module "api_gateway" {
  source = "./modules/api-gateway"

  project_name         = var.project_name
  environment          = var.environment
  cognito_user_pool_id = module.cognito.user_pool_id
  cognito_client_id    = module.cognito.client_id
  cognito_issuer_url   = "https://cognito-idp.${var.aws_region}.amazonaws.com/${module.cognito.user_pool_id}"
  lambda_arns          = module.lambda.api_lambda_arns
  cors_allow_origins   = var.cors_allow_origins
}

module "s3" {
  source             = "./modules/s3"
  project_name       = var.project_name
  environment        = var.environment
  cors_allow_origins = var.cors_allow_origins
}

module "kms" {
  source       = "./modules/kms"
  project_name = var.project_name
  environment  = var.environment
}

module "sqs" {
  source       = "./modules/sqs"
  project_name = var.project_name
  environment  = var.environment
}

module "eventbridge" {
  source                   = "./modules/eventbridge"
  project_name             = var.project_name
  environment              = var.environment
  sqs_queue_arns           = module.sqs.queue_arns
  sqs_queue_urls           = module.sqs.queue_urls
  permissions_boundary_arn = module.iam_oidc.permissions_boundary_arn
}

module "ses" {
  source       = "./modules/ses"
  project_name = var.project_name
  environment  = var.environment
  from_email   = var.ses_from_email
}

# ---------------------------------------------------------------------------
# ElastiCache (Redis) — distributed tenant-status cache shared across all
# Lambda instances. Replaces per-instance in-memory cache to ensure
# consistent tenant suspension/offboarding enforcement across the fleet.
# Cheapest option: cache.t4g.micro (~$11.52/month in eu-west-1).
# ---------------------------------------------------------------------------

module "elasticache" {
  source = "./modules/elasticache"

  project_name             = var.project_name
  environment              = var.environment
  vpc_id                   = module.networking.vpc_id
  private_subnet_ids       = module.networking.private_subnet_ids
  lambda_security_group_id = module.networking.lambda_security_group_id
  node_type                = var.elasticache_node_type
}

module "lambda" {
  source = "./modules/lambda"

  project_name             = var.project_name
  environment              = var.environment
  private_subnet_ids       = module.networking.private_subnet_ids
  lambda_security_group_id = module.networking.lambda_security_group_id
  rds_proxy_endpoint       = module.aurora.rds_proxy_endpoint
  db_name                  = module.aurora.db_name
  db_secret_arn            = module.aurora.db_secret_arn
  db_app_secret_arn        = module.aurora.db_app_secret_arn
  cluster_arn              = module.aurora.cluster_arn
  bucket_name              = module.s3.bucket_name
  event_bus_name           = module.eventbridge.event_bus_name
  cognito_user_pool_id     = module.cognito.user_pool_id
  cognito_user_pool_arn    = module.cognito.user_pool_arn
  cognito_client_id        = module.cognito.client_id
  sqs_queue_arns           = module.sqs.queue_arns
  sqs_queue_urls           = module.sqs.queue_urls
  ses_identity_arn         = module.ses.ses_identity_arn
  scheduled_rule_arns      = module.eventbridge.scheduled_rule_arns
  api_execution_arn        = module.api_gateway.execution_arn
  encryption_kms_key_arn   = module.kms.field_encryption_key_arn
  redis_host               = module.elasticache.redis_host
  local_env_overrides      = var.local_env_overrides
  permissions_boundary_arn = module.iam_oidc.permissions_boundary_arn
}

module "monitoring" {
  source = "./modules/monitoring"

  project_name          = var.project_name
  environment           = var.environment
  lambda_function_names = module.lambda.all_function_names
  api_id                = module.api_gateway.api_id
  dlq_names             = { for k, v in module.sqs.dlq_arns : k => "${var.project_name}-${k}-dlq-${var.environment}" }
  cluster_identifier    = "${var.project_name}-${var.environment}-aurora"
  alerts_email          = var.alerts_email
}

# ---------------------------------------------------------------------------
# GitHub Actions OIDC — deploy roles + permissions boundary
# bootstrap_aws.sh creates these on first boot; run `terraform import` after
# the first apply to hand ownership to Terraform (see 18_cicd_pipeline.md).
# ---------------------------------------------------------------------------
module "iam_oidc" {
  source       = "./modules/iam-oidc"
  project_name = var.project_name
  environment  = var.environment
  github_repo  = var.github_repo
}

# ---------------------------------------------------------------------------
# Frontend hosting — S3 + CloudFront (Task FE-13)
# Only deployed when route53_zone_id is provided; skipped for local dev.
# ---------------------------------------------------------------------------
module "cloudfront" {
  count  = var.route53_zone_id != "" ? 1 : 0
  source = "./modules/cloudfront"

  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }

  project_name    = var.project_name
  environment     = var.environment
  common_tags     = local.common_tags
  domain_name     = var.domain_name
  route53_zone_id = var.route53_zone_id
  price_class     = var.frontend_price_class

  # API Gateway domain for CSP connect-src — strip https:// prefix
  api_gateway_domain = trimprefix(module.api_gateway.api_endpoint, "https://")
  # Cognito domain pattern for CSP
  cognito_domain = "cognito-idp.${var.aws_region}.amazonaws.com"
}
