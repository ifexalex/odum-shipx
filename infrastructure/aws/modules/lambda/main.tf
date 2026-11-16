data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

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
    search            = { name = "search", memory = 256, timeout = 15, handler = "search.handler.lambda_handler" }

    # Notification HTTP surface (2026-09-23). The delivery log, staff/customer
    # in-app bells and announcements all read/write Aurora, and announcing
    # enqueues via SQS (interface endpoint) — so they belong in the VPC, not on
    # the non-VPC SQS consumers below. Previously no Lambda served these routes
    # at all. The WhatsApp webhook writes notification_log status updates, so
    # it is VPC-attached for the same reason.
    notification_api     = { name = "notif-api", memory = 256, timeout = 30, handler = "notification.handler.http_handler" }
    notification_webhook = { name = "notif-webhook", memory = 256, timeout = 15, handler = "notification.handler.webhook_handler" }
  }

  # Non-VPC notification SQS consumers (external provider APIs — Africa's
  # Talking, Meta, SES). Each channel has its own entry point in
  # services/notification/handler.py; there is no `lambda_handler` in that
  # module, so the previous shared "notification.handler.lambda_handler" would
  # have failed every invocation with Runtime.HandlerNotFound.
  #
  # KNOWN GAP (needs an architecture decision — see docs/runbook.md): these
  # write notification_log rows (log_queued/log_sent/log_failed, best-effort)
  # and meter usage, which need Aurora, but this VPC has no NAT ("no NAT in
  # v1") and the design keeps them off the VPC to reach the providers. Sends
  # still work; the log/metering writes fail after connect_timeout=5s each.
  notification_configs = {
    notif_sms      = { name = "notif-sms", memory = 256, timeout = 60, queue_key = "sms", handler = "notification.handler.sms_handler" }
    notif_whatsapp = { name = "notif-whatsapp", memory = 256, timeout = 60, queue_key = "whatsapp", handler = "notification.handler.whatsapp_handler" }
    notif_email    = { name = "notif-email", memory = 256, timeout = 60, queue_key = "email", handler = "notification.handler.email_handler" }
  }

  # Non-VPC API Lambda (API Gateway trigger, Cognito-only calls — no DB needed).
  # Kept off the VPC on purpose: it never queries Aurora, and skipping the ENI
  # attach avoids the cold-start penalty on a path that's on the critical
  # render path of every page load (silent session restore).
  non_vpc_api_configs = {
    auth = { name = "auth", memory = 256, timeout = 15, handler = "auth.handler.lambda_handler" }
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
    local.non_vpc_api_configs,
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
    [for k, v in local.non_vpc_api_configs : "${var.project_name}-${v.name}-${var.environment}"],
  )

  # Common environment variables injected into every Lambda function.
  # local_env_overrides (empty by default) allows LocalStack runs to override
  # DATABASE_HOST, DB_SECRET_ARN, DATABASE_PASSWORD, etc. without touching CI/CD.
  common_env_vars = merge(
    {
      DATABASE_HOST = var.rds_proxy_endpoint
      DATABASE_NAME = var.db_name
      # PHASE 1 of the RLS credential switchover: still the master user.
      #
      # Flipping these two to logistics_app / db_app_secret_arn is phase 2, and
      # must not be bundled with phase 1. On AWS the env flip and the migration
      # live in SEPARATE pipelines — terraform.yml applies infrastructure,
      # deploy.yml runs migrations and then deploys code — so a Terraform apply
      # on its own would repoint every Lambda at a role migration 060 has not
      # yet given a password to, with no migration anywhere in that pipeline to
      # fix it.
      #
      # Phase 1 provisions the credential: the migrate Lambda below receives
      # APP_DB_SECRET_ARN, so 060 sets the role's password on the next deploy.
      # Phase 2 then flips these two lines against a role that already works.
      DATABASE_USER         = "postgres"
      DB_SECRET_ARN         = var.db_secret_arn
      S3_BUCKET             = var.bucket_name
      EVENT_BUS_NAME        = var.event_bus_name
      COGNITO_USER_POOL_ID  = var.cognito_user_pool_id
      ENVIRONMENT           = var.environment
      ENCRYPTION_KMS_KEY_ID = var.encryption_kms_key_arn
      REDIS_HOST            = var.redis_host

      # shared/notifications.py reads these to enqueue; unset, it logs
      # "Queue URL env var not set — notification dropped" and returns False.
      SQS_SMS_QUEUE_URL      = lookup(var.sqs_queue_urls, "sms", "")
      SQS_WHATSAPP_QUEUE_URL = lookup(var.sqs_queue_urls, "whatsapp", "")
      SQS_EMAIL_QUEUE_URL    = lookup(var.sqs_queue_urls, "email", "")

      # Absolute base URL for links in notifications — account activation
      # (/activate/{token}) and customer invites (/invite/{token}).
      # shared/app_urls.py refuses to build a relative link, so leaving these
      # empty means those notifications are not sent at all (and say so in the
      # log) rather than arriving with a dead link, which is what used to
      # happen: neither variable was set here, so every invite carried the bare
      # path "/invite/<token>".
      APP_BASE_URL             = var.app_base_url
      CUSTOMER_PORTAL_BASE_URL = var.customer_portal_base_url

      # Origins allowed to call the cookie-authenticated /v1/auth/* endpoints, comma-separated.
      # shared/origin_guard.py refuses any other Origin, and also trusts the origins of the two
      # URLs above. With none of them set it refuses every request, so this must not be dropped.
      ALLOWED_ORIGINS = join(",", var.cors_allow_origins)

      # Email — SES. The sender must be a verified identity in this account's
      # SES region, or every send is rejected.
      SES_FROM_ADDRESS = var.ses_from_address

      # SMS — Africa's Talking. AFRICASTALKING_USERNAME must be the live
      # username in production: the code's default is "sandbox", which accepts
      # messages and delivers nothing.
      AFRICASTALKING_API_KEY   = var.africastalking_api_key
      AFRICASTALKING_USERNAME  = var.africastalking_username
      AFRICASTALKING_SENDER_ID = var.africastalking_sender_id

      # WhatsApp — Meta Cloud API. Templates must be pre-approved by Meta under
      # the names in WA_TEMPLATE_MAP (services/notification/service.py), and
      # META_WHATSAPP_TEMPLATE_LANG must match the locale those templates were
      # approved in, or Meta 404s the send.
      META_WHATSAPP_ACCESS_TOKEN  = var.meta_whatsapp_access_token
      META_WHATSAPP_PHONE_ID      = var.meta_whatsapp_phone_id
      META_WHATSAPP_TEMPLATE_LANG = var.meta_whatsapp_template_lang
      WHATSAPP_VERIFY_TOKEN       = var.whatsapp_verify_token

      # Outside production nothing is messaged unless the contact is listed
      # here — dev and staging databases hold real imported customer contacts.
      # See shared/notifications.py::is_recipient_allowed.
      NOTIFICATION_ALLOWLIST = var.notification_allowlist
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
  compatible_runtimes = ["python3.13"]
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
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        # PHASE 1: the master secret, matching DATABASE_USER above. Phase 2
        # narrows this to var.db_app_secret_arn alone — the service Lambdas have
        # no business reading the master credential once they stop using it.
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
        # Used by services/tenant_management/cognito_client.py but previously
        # ungranted: role changes, profile sync, password reset/resend-invite,
        # forced sign-out on deactivation, per-tenant group creation.
        "cognito-idp:AdminRemoveUserFromGroup",
        "cognito-idp:AdminUpdateUserAttributes",
        "cognito-idp:AdminResetUserPassword",
        "cognito-idp:AdminSetUserPassword",
        "cognito-idp:AdminUserGlobalSignOut",
        "cognito-idp:CreateGroup",
      ]
      Resource = [var.cognito_user_pool_arn]
    }]
  })
}

# auth — refresh-token exchange + revoke for the httpOnly-cookie session flow.
# Deliberately narrower than tenant_management's cognito_admin policy above:
# InitiateAuth/RevokeToken are the non-admin, non-destructive Cognito APIs —
# this Lambda can refresh or kill one session, never create/disable/delete a
# user or read the user directory.
resource "aws_iam_role_policy" "cognito_refresh" {
  name = "${local.name_prefix}-auth-cognito-refresh"
  role = aws_iam_role.lambda["auth"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "cognito-idp:InitiateAuth",
        "cognito-idp:RevokeToken",
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

# tracking / payment_release / manifest / excel — presigned S3 uploads and
# downloads (container documents, payment-claim evidence, manifest evidence,
# import/export files). A presigned URL is authorised as the role that signed
# it, so the role needs the underlying object permissions; only `claims` had
# them. Tenant-prefix isolation is enforced in application code (every key is
# validated to start with "{tenant_id}/") — same posture as s3_claims above.
resource "aws_iam_role_policy" "s3_documents" {
  for_each = toset(["tracking", "payment_release", "manifest", "excel"])
  name     = "${local.name_prefix}-${local.vpc_api_configs[each.key].name}-s3"
  role     = aws_iam_role.lambda[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:PutObject", "s3:GetObject"]
      Resource = ["arn:aws:s3:::${var.bucket_name}/*"]
    }]
  })
}

# data_cleanup — irreversible tenant offboarding: purge the tenant's S3 prefix
# (current + versioned objects) and delete its Cognito users.
resource "aws_iam_role_policy" "data_cleanup_purge" {
  name = "${local.name_prefix}-data-cleanup-purge"
  role = aws_iam_role.lambda["data_cleanup"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:ListBucketVersions"]
        Resource = ["arn:aws:s3:::${var.bucket_name}"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:DeleteObject", "s3:DeleteObjectVersion"]
        Resource = ["arn:aws:s3:::${var.bucket_name}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["cognito-idp:ListUsers", "cognito-idp:AdminDeleteUser"]
        Resource = [var.cognito_user_pool_arn]
      },
    ]
  })
}

# Producers — enqueue SMS/WhatsApp/email notifications (shared/notifications.py).
# No Lambda role could send to SQS before, so every enqueue would have raised
# AccessDenied. The WhatsApp consumer is included: it falls back to the SMS
# queue when a WhatsApp send fails.
resource "aws_iam_role_policy" "sqs_send_notifications" {
  for_each = merge(local.vpc_api_configs, local.scheduled_configs, local.notification_configs)
  name     = "${var.project_name}-${each.value.name}-sqs-send-${var.environment}"
  role     = aws_iam_role.lambda[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:SendMessage"]
      Resource = [for q in ["sms", "whatsapp", "email"] : var.sqs_queue_arns[q]]
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

# payment_release + refunds + tenant_management — KMS field-level encryption
# (passport IDs, bank account details, per-tenant Paystack secret keys)
resource "aws_iam_role_policy" "kms_field_encryption" {
  for_each = {
    payment_release   = local.vpc_api_configs["payment_release"]
    refunds           = local.vpc_api_configs["refunds"]
    tenant_management = local.vpc_api_configs["tenant_management"] # encrypts each tenant's Paystack secret key
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

# notification Lambdas — consume from their respective SQS queues
resource "aws_iam_role_policy" "sqs_notification" {
  for_each = local.notification_configs
  name     = "${local.name_prefix}-${each.value.name}-sqs"
  role     = aws_iam_role.lambda[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      Resource = [var.sqs_queue_arns[each.value.queue_key]]
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
  runtime          = "python3.13"
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
    # Multi-tenant Paystack (2026-07-19): each tenant connects their own
    # secret key via PUT /v1/tenant/config/paystack (encrypted in
    # tenant_config using ENCRYPTION_KMS_KEY_ID above) — there is no
    # platform-wide Paystack key to inject here anymore. See
    # services/payment_release/paystack.py's module docstring.
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
  runtime          = "python3.13"
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
# Lambda Functions — Notification SQS consumers (non-VPC, SQS trigger)
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "notification" {
  for_each         = local.notification_configs
  function_name    = "${var.project_name}-${each.value.name}-${var.environment}"
  role             = aws_iam_role.lambda[each.key].arn
  runtime          = "python3.13"
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
# Lambda Function — Auth session (non-VPC, API Gateway trigger)
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "non_vpc_api" {
  for_each         = local.non_vpc_api_configs
  function_name    = "${var.project_name}-${each.value.name}-${var.environment}"
  role             = aws_iam_role.lambda[each.key].arn
  runtime          = "python3.13"
  handler          = each.value.handler
  memory_size      = each.value.memory
  timeout          = each.value.timeout
  filename         = data.archive_file.services_code.output_path
  source_code_hash = data.archive_file.services_code.output_base64sha256
  layers           = [aws_lambda_layer_version.shared.arn]

  # No vpc_config — calls Cognito only, never touches Aurora.

  environment {
    variables = merge(local.common_env_vars, {
      COGNITO_CLIENT_ID = var.cognito_client_id

      # Outside the VPC this function cannot reach ElastiCache, and trying would only add a connection
      # timeout to every request. Its public routes (/v1/auth/*) are throttled per route at API Gateway
      # instead — see public_route_throttles in modules/api-gateway/main.tf. shared/rate_limit.py.
      RATE_LIMIT_ENABLED = "false"
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
  runtime          = "python3.13"
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

  # 1, not 10: these Lambdas are outside the VPC but still try to write
  # notification_log/metering to Aurora (see the KNOWN GAP note on
  # notification_configs), and each failed attempt costs connect_timeout=5s.
  # A batch of 10 can exceed the 60s timeout, and SQS then redelivers messages
  # that were already sent — duplicate SMS/WhatsApp. Raise this back to 10 once
  # the consumers have working DB access.
  batch_size = 1
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

# The metering Lambda is dual-mode (SQS batch or API Gateway event —
# services/metering/handler.py) and serves GET /v1/platform/tenants/{id}/usage,
# but had no invoke permission and no entry in api_lambda_arns, so that route
# was silently dropped by api-gateway's `active_routes` filter.
resource "aws_lambda_permission" "apigw_metering" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.metering.function_name
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

# ---------------------------------------------------------------------------
# Migration Lambda — runs Alembic upgrade head, invoked by the deploy pipeline
# before service code is deployed. No API Gateway or EventBridge trigger.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "migrate" {
  name              = "/aws/lambda/${var.project_name}-migrate-${var.environment}"
  retention_in_days = local.log_retention_days
  tags              = local.common_tags
}

resource "aws_iam_role" "migrate" {
  name                 = "${var.project_name}-migrate-role-${var.environment}"
  assume_role_policy   = data.aws_iam_policy_document.lambda_assume.json
  permissions_boundary = var.permissions_boundary_arn
  tags                 = local.common_tags
}

resource "aws_iam_role_policy_attachment" "migrate_basic_execution" {
  role       = aws_iam_role.migrate.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "migrate_vpc_access" {
  role       = aws_iam_role.migrate.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "migrate_db_access" {
  name = "${var.project_name}-migrate-db-${var.environment}"
  role = aws_iam_role.migrate.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        # Both: the master credential to run DDL as the owner, and the
        # application credential because migration 060 sets it on the
        # logistics_app role (handler injects it as APP_DB_PASSWORD).
        Resource = [var.db_secret_arn, var.db_app_secret_arn]
      },
      {
        Effect   = "Allow"
        Action   = ["rds-db:connect"]
        Resource = ["${var.cluster_arn}/*"]
      },
    ]
  })
}

resource "aws_lambda_function" "migrate" {
  function_name = "${var.project_name}-migrate-${var.environment}"
  role          = aws_iam_role.migrate.arn
  runtime       = "python3.13"
  handler       = "handler.lambda_handler"
  memory_size   = 256
  timeout       = 300

  # Placeholder package — the deploy pipeline overwrites with update-function-code
  # on every deploy run. The package must exist at creation time for Terraform apply.
  filename         = data.archive_file.services_code.output_path
  source_code_hash = data.archive_file.services_code.output_base64sha256

  layers = [aws_lambda_layer_version.shared.arn]

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [var.lambda_security_group_id]
  }

  environment {
    variables = {
      DATABASE_HOST = var.rds_proxy_endpoint
      DATABASE_NAME = var.db_name
      # Migrations run as the OWNER by design: DDL cannot be run by
      # logistics_app, which holds only DML (migration 059).
      DATABASE_USER = "postgres"
      DATABASE_PORT = "5432"
      DB_SECRET_ARN = var.db_secret_arn
      # Migration 060 reads APP_DB_PASSWORD to set logistics_app's password.
      # Passed as an ARN, not a value: the handler fetches it at runtime, so the
      # plaintext never enters a Lambda environment variable or Terraform state.
      APP_DB_SECRET_ARN = var.db_app_secret_arn
      ENVIRONMENT       = var.environment
    }
  }

  depends_on = [aws_cloudwatch_log_group.migrate]

  tags = local.common_tags
}
