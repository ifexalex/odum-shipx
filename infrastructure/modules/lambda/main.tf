locals {
  name_prefix        = "${var.project_name}-${var.environment}"
  log_retention_days = var.environment == "prod" ? 90 : 30
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = "logistics-platform"
    Owner       = "platform-engineering"
  }

  # ---------------------------------------------------------------------------
  # Lambda function configuration maps
  # ---------------------------------------------------------------------------

  # VPC-attached API Lambdas (API Gateway trigger, need DB access)
  vpc_api_configs = {
    tenant_management = { name = "tenant-mgmt", memory = 512, timeout = 30, handler = "tenant_management.handler.lambda_handler" }
    packing_list      = { name = "packing-list", memory = 256, timeout = 30, handler = "packing_list.handler.lambda_handler" }
    manifest          = { name = "manifest", memory = 256, timeout = 30, handler = "manifest.handler.lambda_handler" }
    tracking          = { name = "tracking", memory = 256, timeout = 30, handler = "tracking.handler.lambda_handler" }
    billing           = { name = "billing", memory = 512, timeout = 30, handler = "billing.handler.lambda_handler" }
    claims            = { name = "claims", memory = 256, timeout = 30, handler = "claims.handler.lambda_handler" }
    payment_release   = { name = "payment-release", memory = 256, timeout = 30, handler = "payment_release.handler.lambda_handler" }
    refunds           = { name = "refunds", memory = 256, timeout = 30, handler = "refunds.handler.lambda_handler" }
    excel             = { name = "excel", memory = 256, timeout = 60, handler = "excel.handler.lambda_handler" }
  }

  # Non-VPC notification Lambdas (SQS trigger, external API calls — no DB needed)
  notification_configs = {
    notif_sms      = { name = "notif-sms", memory = 256, timeout = 60, queue_key = "sms", handler = "notification.handler.lambda_handler" }
    notif_whatsapp = { name = "notif-whatsapp", memory = 256, timeout = 60, queue_key = "whatsapp", handler = "notification.handler.lambda_handler" }
    notif_email    = { name = "notif-email", memory = 256, timeout = 60, queue_key = "email", handler = "notification.handler.lambda_handler" }
  }

  # VPC-attached scheduled Lambdas (EventBridge cron triggers)
  scheduled_configs = {
    storage_fee        = { name = "storage-fee", memory = 256, timeout = 300, handler = "scheduled.storage_fee.lambda_handler", rule_key = "storage-fee-accrual" }
    dispute_escalation = { name = "dispute-escalation", memory = 256, timeout = 300, handler = "scheduled.dispute_escalation.lambda_handler", rule_key = "dispute-auto-escalation" }
    sla_check          = { name = "sla-check", memory = 256, timeout = 300, handler = "scheduled.sla_check.lambda_handler", rule_key = "sla-breach-check" }
    storage_reminders  = { name = "storage-reminders", memory = 256, timeout = 300, handler = "scheduled.storage_reminders.lambda_handler", rule_key = "storage-reminders" }
    data_cleanup       = { name = "data-cleanup", memory = 256, timeout = 300, handler = "scheduled.data_cleanup.lambda_handler", rule_key = "tenant-data-cleanup" }
    usage_aggregation  = { name = "usage-aggregation", memory = 256, timeout = 300, handler = "scheduled.usage_aggregation.lambda_handler", rule_key = "usage-aggregation" }
    release_expiry     = { name = "release-expiry", memory = 256, timeout = 300, handler = "scheduled.release_expiry.lambda_handler", rule_key = "release-note-expiry" }
  }

  # VPC SQS Lambda (metering queue consumer, needs DB)
  metering_config = { name = "metering", memory = 256, timeout = 60, handler = "metering.handler.lambda_handler", queue_key = "metering" }

  # Merged key set — used for shared IAM role creation (one role per Lambda)
  all_lambda_keys = merge(
    local.vpc_api_configs,
    { metering = local.metering_config },
    local.notification_configs,
    local.scheduled_configs,
  )

  # VPC lambda keys (need AWSLambdaVPCAccessExecutionRole + DB IAM policy)
  vpc_lambda_keys = merge(
    local.vpc_api_configs,
    { metering = local.metering_config },
    local.scheduled_configs,
  )

  # All function names computed upfront (for log group creation without circular refs)
  all_function_names = concat(
    [for k, v in local.vpc_api_configs : "${var.project_name}-${v.name}-${var.environment}"],
    ["${var.project_name}-${local.metering_config.name}-${var.environment}"],
    [for k, v in local.notification_configs : "${var.project_name}-${v.name}-${var.environment}"],
    [for k, v in local.scheduled_configs : "${var.project_name}-${v.name}-${var.environment}"],
  )

  # Common environment variables injected into every Lambda function.
  # local_env_overrides (empty by default) allows LocalStack runs to override
  # DATABASE_HOST, DB_SECRET_ARN, DATABASE_PASSWORD, etc. without touching CI/CD.
  common_env_vars = merge(
    {
      DATABASE_HOST          = var.rds_proxy_endpoint
      DATABASE_NAME          = var.db_name
      DATABASE_USER          = "postgres"
      DB_SECRET_ARN          = var.db_secret_arn
      S3_BUCKET              = var.bucket_name
      EVENT_BUS_NAME         = var.event_bus_name
      COGNITO_USER_POOL_ID   = var.cognito_user_pool_id
      ENVIRONMENT            = var.environment
      ENCRYPTION_KMS_KEY_ID  = var.encryption_kms_key_arn
      REDIS_HOST             = var.redis_host
    },
    var.local_env_overrides,
  )

  # Use a pre-built package dir (created by scripts/build_lambda_zip.sh) when it
  # exists; otherwise fall back to the raw source tree (CI/CD pre-builds the ZIP).
  lambda_source_dir = fileexists("${path.module}/.builds/package/shared/__init__.py") ? "${path.module}/.builds/package" : "${path.module}/../../../services"
}

# ---------------------------------------------------------------------------
# Code packaging — archive the services/ and shared/ directories
# ---------------------------------------------------------------------------

# Single zip containing services + shared + pip dependencies.
# For local/LocalStack runs: scripts/build_lambda_zip.sh pre-builds .builds/package/
#   which includes all pip deps; local.lambda_source_dir points there automatically.
# For CI/CD: source_dir falls back to services/ and CI pre-builds a proper ZIP.
data "archive_file" "services_code" {
  type        = "zip"
  source_dir  = local.lambda_source_dir
  output_path = "${path.module}/.builds/services.zip"
}

# Shared utilities layer — when using the pre-built package dir, shared/ is already
# bundled inside services.zip above. This layer is only used for pure-AWS deploys.
data "archive_file" "shared_layer_code" {
  type        = "zip"
  source_dir  = "${path.module}/../../../shared"
  output_path = "${path.module}/.builds/shared-layer.zip"
}

# ---------------------------------------------------------------------------
# Shared Lambda Layer
# ---------------------------------------------------------------------------

resource "aws_lambda_layer_version" "shared" {
  layer_name          = "${local.name_prefix}-shared"
  filename            = data.archive_file.shared_layer_code.output_path
  source_code_hash    = data.archive_file.shared_layer_code.output_base64sha256
  compatible_runtimes = ["python3.12"]
}

# ---------------------------------------------------------------------------
# CloudWatch Log Groups (pre-created to enforce retention policy)
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = toset(local.all_function_names)
  name              = "/aws/lambda/${each.value}"
  retention_in_days = local.log_retention_days
  tags              = local.common_tags
}

# ---------------------------------------------------------------------------
# IAM — one role per Lambda (least-privilege pattern)
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  for_each             = local.all_lambda_keys
  name                 = "${var.project_name}-${each.value.name}-role-${var.environment}"
  assume_role_policy   = data.aws_iam_policy_document.lambda_assume.json
  permissions_boundary = var.permissions_boundary_arn
  tags                 = local.common_tags
}

# All Lambdas — CloudWatch Logs (basic execution)
resource "aws_iam_role_policy_attachment" "basic_execution" {
  for_each   = local.all_lambda_keys
  role       = aws_iam_role.lambda[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# VPC Lambdas — create/describe/delete ENIs in the VPC
resource "aws_iam_role_policy_attachment" "vpc_access" {
  for_each   = local.vpc_lambda_keys
  role       = aws_iam_role.lambda[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# VPC Lambdas — read DB credentials + connect via RDS Proxy
resource "aws_iam_role_policy" "db_access" {
  for_each = local.vpc_lambda_keys
  name     = "${var.project_name}-${each.value.name}-db-${var.environment}"
  role     = aws_iam_role.lambda[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [var.db_secret_arn]
      },
      {
        Effect   = "Allow"
        Action   = ["rds-db:connect"]
        Resource = ["${var.cluster_arn}/*"]
      },
    ]
  })
}

# API Lambdas — emit domain events to EventBridge
resource "aws_iam_role_policy" "eventbridge_put" {
  for_each = local.vpc_api_configs
  name     = "${var.project_name}-${each.value.name}-eb-${var.environment}"
  role     = aws_iam_role.lambda[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["events:PutEvents"]
      Resource = ["*"]
    }]
  })
}

# tenant_management — Cognito user administration
resource "aws_iam_role_policy" "cognito_admin" {
  name = "${local.name_prefix}-tenant-mgmt-cognito"
  role = aws_iam_role.lambda["tenant_management"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "cognito-idp:AdminCreateUser",
        "cognito-idp:AdminAddUserToGroup",
        "cognito-idp:AdminDisableUser",
        "cognito-idp:AdminEnableUser",
        "cognito-idp:AdminDeleteUser",
        "cognito-idp:AdminListGroupsForUser",
        "cognito-idp:ListUsers",
      ]
      Resource = [var.cognito_user_pool_arn]
    }]
  })
}

# claims — S3 presigned URLs for damage-claim attachments
resource "aws_iam_role_policy" "s3_claims" {
  name = "${local.name_prefix}-claims-s3"
  role = aws_iam_role.lambda["claims"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:PutObject", "s3:GetObject"]
      Resource = ["arn:aws:s3:::${var.bucket_name}/*"]
    }]
  })
}

# notif_email — send transactional email via SES
resource "aws_iam_role_policy" "ses_send" {
  name = "${local.name_prefix}-notif-email-ses"
  role = aws_iam_role.lambda["notif_email"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ses:SendEmail", "ses:SendRawEmail"]
      Resource = [var.ses_identity_arn]
    }]
  })
}

# payment_release + refunds — KMS field-level encryption (passport IDs, bank account details)
resource "aws_iam_role_policy" "kms_field_encryption" {
  for_each = {
    payment_release = local.vpc_api_configs["payment_release"]
    refunds         = local.vpc_api_configs["refunds"]
  }
  name = "${var.project_name}-${each.value.name}-kms-${var.environment}"
  role = aws_iam_role.lambda[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "kms:GenerateDataKey",
        "kms:Decrypt",
      ]
      Resource = [var.encryption_kms_key_arn]
    }]
  })
}

# metering — consume from metering SQS queue
resource "aws_iam_role_policy" "sqs_metering" {
  name = "${local.name_prefix}-metering-sqs"
  role = aws_iam_role.lambda["metering"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      Resource = [var.sqs_queue_arns["metering"]]
    }]
  })
}

# ---------------------------------------------------------------------------
# Lambda Functions — VPC API Lambdas (9, API Gateway trigger)
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "vpc_api" {
  for_each         = local.vpc_api_configs
  function_name    = "${var.project_name}-${each.value.name}-${var.environment}"
  role             = aws_iam_role.lambda[each.key].arn
  runtime          = "python3.12"
  handler          = each.value.handler
  memory_size      = each.value.memory
  timeout          = each.value.timeout
  filename         = data.archive_file.services_code.output_path
  source_code_hash = data.archive_file.services_code.output_base64sha256
  layers           = [aws_lambda_layer_version.shared.arn]

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [var.lambda_security_group_id]
  }

  environment {
    variables = local.common_env_vars
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# Lambda Function — Metering (VPC, SQS trigger)
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "metering" {
  function_name    = "${var.project_name}-${local.metering_config.name}-${var.environment}"
  role             = aws_iam_role.lambda["metering"].arn
  runtime          = "python3.12"
  handler          = local.metering_config.handler
  memory_size      = local.metering_config.memory
  timeout          = local.metering_config.timeout
  filename         = data.archive_file.services_code.output_path
  source_code_hash = data.archive_file.services_code.output_base64sha256
  layers           = [aws_lambda_layer_version.shared.arn]

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [var.lambda_security_group_id]
  }

  environment {
    variables = local.common_env_vars
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# Lambda Functions — Notification (non-VPC, SQS trigger + webhook handler)
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "notification" {
  for_each         = local.notification_configs
  function_name    = "${var.project_name}-${each.value.name}-${var.environment}"
  role             = aws_iam_role.lambda[each.key].arn
  runtime          = "python3.12"
  handler          = each.value.handler
  memory_size      = each.value.memory
  timeout          = each.value.timeout
  filename         = data.archive_file.services_code.output_path
  source_code_hash = data.archive_file.services_code.output_base64sha256
  layers           = [aws_lambda_layer_version.shared.arn]

  # No vpc_config — these Lambdas call external APIs (Africa's Talking, Meta, SES)

  environment {
    variables = merge(local.common_env_vars, {
      NOTIFICATION_CHANNEL = each.value.queue_key
    })
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# Lambda Functions — Scheduled Jobs (VPC, EventBridge cron triggers)
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "scheduled_job" {
  for_each         = local.scheduled_configs
  function_name    = "${var.project_name}-${each.value.name}-${var.environment}"
  role             = aws_iam_role.lambda[each.key].arn
  runtime          = "python3.12"
  handler          = each.value.handler
  memory_size      = each.value.memory
  timeout          = each.value.timeout
  filename         = data.archive_file.services_code.output_path
  source_code_hash = data.archive_file.services_code.output_base64sha256
  layers           = [aws_lambda_layer_version.shared.arn]

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [var.lambda_security_group_id]
  }

  environment {
    variables = local.common_env_vars
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# SQS Event Source Mappings
# ---------------------------------------------------------------------------

resource "aws_lambda_event_source_mapping" "notification" {
  for_each         = local.notification_configs
  event_source_arn = var.sqs_queue_arns[each.value.queue_key]
  function_name    = aws_lambda_function.notification[each.key].arn
  batch_size       = 10
}

resource "aws_lambda_event_source_mapping" "metering" {
  event_source_arn = var.sqs_queue_arns["metering"]
  function_name    = aws_lambda_function.metering.arn
  batch_size       = 10
}

# ---------------------------------------------------------------------------
# API Gateway invoke permissions
# (Owned by lambda module to avoid circular dependency with api_gateway module)
# ---------------------------------------------------------------------------

resource "aws_lambda_permission" "apigw_vpc_api" {
  for_each      = local.vpc_api_configs
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.vpc_api[each.key].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${var.api_execution_arn}/*/*"
}

# notif_whatsapp handles the GET/POST /v1/webhooks/whatsapp public routes
resource "aws_lambda_permission" "apigw_notification_webhook" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.notification["notif_whatsapp"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${var.api_execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# EventBridge targets + permissions for scheduled Lambdas
# Scheduled rules were created in the eventbridge module; targets are wired here.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_target" "scheduled" {
  for_each = local.scheduled_configs
  # rule attribute expects the rule name, not the full ARN
  rule      = element(split("/", var.scheduled_rule_arns[each.value.rule_key]), length(split("/", var.scheduled_rule_arns[each.value.rule_key])) - 1)
  target_id = "${local.name_prefix}-${each.value.name}"
  arn       = aws_lambda_function.scheduled_job[each.key].arn
}

resource "aws_lambda_permission" "scheduled_eventbridge" {
  for_each      = local.scheduled_configs
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduled_job[each.key].function_name
  principal     = "events.amazonaws.com"
  source_arn    = var.scheduled_rule_arns[each.value.rule_key]
}
