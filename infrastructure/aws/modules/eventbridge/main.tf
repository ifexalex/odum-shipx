locals {
  name_prefix = "${var.project_name}-${var.environment}"
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = "logistics-platform"
    Owner       = "platform-engineering"
  }

  # No rule targets the sms, whatsapp or email queues (audit BE-09, 2026-11-17). Their consumers read the message
  # that shared/notifications.py enqueues ({tenant_id, event_type, recipient, template_data, ...}); a raw EventBridge
  # event has no recipient, so every one routed there was skipped with a warning: wasted invocations, log noise, and
  # a duplicate message the day a consumer is taught to read them. Services enqueue notifications directly. The
  # metering queue is the only EventBridge target, and the only queue EventBridge may send to.
  eventbridge_queue_keys = ["metering"]

  # Scheduled rules: rule name → schedule expression
  scheduled_rules = {
    storage-fee-accrual     = "cron(0 0 * * ? *)" # midnight UTC daily
    dispute-auto-escalation = "rate(6 hours)"
    sla-breach-check        = "rate(4 hours)"
    storage-reminders       = "cron(0 8 * * ? *)" # 08:00 UTC daily
    tenant-data-cleanup     = "cron(0 2 * * ? *)" # 02:00 UTC daily
    usage-aggregation       = "rate(1 hour)"
    release-note-expiry     = "cron(0 0 * * ? *)" # midnight UTC daily
    offboarding-export      = "rate(1 hour)"      # writes queued tenant data exports (audit BE-10)
    platform-approvals      = "rate(15 minutes)"  # due sole-admin offboardings, expired approvals (platform Phase 1)
  }
}

# ---------------------------------------------------------------------------
# Custom event bus
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_bus" "main" {
  name = "${var.project_name}-events-${var.environment}"
  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# IAM role for EventBridge → SQS delivery
# ---------------------------------------------------------------------------

resource "aws_iam_role" "eventbridge_sqs" {
  name                 = "${local.name_prefix}-eventbridge-sqs-role"
  permissions_boundary = var.permissions_boundary_arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "eventbridge_sqs" {
  name = "${local.name_prefix}-eventbridge-sqs-policy"
  role = aws_iam_role.eventbridge_sqs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sqs:SendMessage"
      Resource = [for key in local.eventbridge_queue_keys : var.sqs_queue_arns[key]]
    }]
  })
}

# ---------------------------------------------------------------------------
# SQS resource policies — allow EventBridge to send to the queues it targets
# ---------------------------------------------------------------------------

resource "aws_sqs_queue_policy" "eventbridge" {
  for_each  = { for key in local.eventbridge_queue_keys : key => var.sqs_queue_urls[key] }
  queue_url = each.value

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowEventBridge"
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = var.sqs_queue_arns[each.key]
      Condition = {
        ArnEquals = {
          "aws:SourceArn" = aws_cloudwatch_event_bus.main.arn
        }
      }
    }]
  })
}

# ---------------------------------------------------------------------------
# Metering rule — all events from logistics.* sources
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "route_metering" {
  name           = "${local.name_prefix}-route-metering"
  event_bus_name = aws_cloudwatch_event_bus.main.name
  state          = "ENABLED"

  event_pattern = jsonencode({
    source      = [{ prefix = "${var.project_name}." }]
    detail-type = ["UsageRecorded"]
  })

  tags = local.common_tags
}

resource "aws_cloudwatch_event_target" "route_metering_sqs" {
  rule           = aws_cloudwatch_event_rule.route_metering.name
  event_bus_name = aws_cloudwatch_event_bus.main.name
  target_id      = "sqs-metering"
  arn            = var.sqs_queue_arns["metering"]
  role_arn       = aws_iam_role.eventbridge_sqs.arn
}

# ---------------------------------------------------------------------------
# Scheduled rules on the default event bus (targets added in Task 16)
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "scheduled" {
  for_each = local.scheduled_rules

  name                = "${local.name_prefix}-${each.key}"
  schedule_expression = each.value
  state               = "ENABLED"

  tags = local.common_tags
}
