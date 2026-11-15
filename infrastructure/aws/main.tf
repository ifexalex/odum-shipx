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

  # Notification channels — see modules/lambda/variables.tf. Empty values mean
  # that channel simply does not send; the notification_config_guard below
  # fails the plan rather than letting production deploy that way.
  app_base_url                = var.app_base_url
  customer_portal_base_url    = var.customer_portal_base_url
  cors_allow_origins          = var.cors_allow_origins
  ses_from_address            = var.ses_from_address
  africastalking_api_key      = var.africastalking_api_key
  africastalking_username     = var.africastalking_username
  africastalking_sender_id    = var.africastalking_sender_id
  meta_whatsapp_access_token  = var.meta_whatsapp_access_token
  meta_whatsapp_phone_id      = var.meta_whatsapp_phone_id
  meta_whatsapp_template_lang = var.meta_whatsapp_template_lang
  whatsapp_verify_token       = var.whatsapp_verify_token
  notification_allowlist      = var.notification_allowlist
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

# ---------------------------------------------------------------------------
# Notification channel guard
#
# Production is the only environment where these must be complete, and the only
# one where getting it wrong is invisible: every send path logs "not configured"
# and returns, so a deploy is healthy, the API returns 200, notification_log
# fills with failures nobody reads, and customers are never told anything. This
# fails the PLAN instead.
#
# Invite and activation links are checked in every environment, because a
# notification with a relative link is worse than none — it consumes a
# single-use token and tells staff the customer was contacted.
# ---------------------------------------------------------------------------
resource "terraform_data" "notification_config_guard" {
  input = var.environment

  lifecycle {
    precondition {
      condition     = var.app_base_url != "" || var.customer_portal_base_url != ""
      error_message = <<-EOT
        app_base_url and customer_portal_base_url are both empty for
        environment "${var.environment}". Account activation
        (/activate/{token}) and customer invite (/invite/{token}) links are
        built from these, and shared/app_urls.py refuses to emit a relative
        URL — so those notifications will not be sent at all.
      EOT
    }

    precondition {
      condition     = var.environment != "prod" || var.ses_from_address != ""
      error_message = <<-EOT
        ses_from_address is empty for prod. The application default is
        notifications@logistics.example.com, which SES will reject as an
        unverified identity — every notification email would fail.
      EOT
    }

    precondition {
      condition = var.environment != "prod" || alltrue([
        var.africastalking_api_key != "",
        var.africastalking_username != "",
      ])
      error_message = <<-EOT
        Africa's Talking SMS is not configured for prod
        (africastalking_api_key / africastalking_username). With the key empty,
        send_sms logs a warning and returns False — no SMS is ever delivered
        and nothing fails. Note the username must be the LIVE one: the
        application default is "sandbox", which accepts messages and delivers
        nothing.
      EOT
    }

    precondition {
      condition = var.environment != "prod" || alltrue([
        var.meta_whatsapp_access_token != "",
        var.meta_whatsapp_phone_id != "",
        var.meta_whatsapp_template_lang != "",
      ])
      error_message = <<-EOT
        WhatsApp is not configured for prod (meta_whatsapp_access_token /
        meta_whatsapp_phone_id / meta_whatsapp_template_lang). WhatsApp is the
        PRIMARY customer channel here — SMS is only its fallback — so an
        unconfigured token means the main way customers are contacted is dead.
        meta_whatsapp_template_lang must match the language the templates in
        WA_TEMPLATE_MAP were approved under, or Meta 404s every send.
      EOT
    }
  }
}
