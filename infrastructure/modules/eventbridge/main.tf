locals {
  name_prefix = "${var.project_name}-${var.environment}"
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = "logistics-platform"
    Owner       = "platform-engineering"
  }

  # Routing rules: rule name → detail-type list + target SQS queue key
  routing_rules = {
    route-sms = {
      detail_types = ["ShipmentStatusUpdated", "PaymentDue", "ReleaseNoteGenerated"]
      queue_key    = "sms"
    }
    route-whatsapp = {
      detail_types = ["ShipmentStatusUpdated", "PaymentDue", "CBMDisputeResolved", "ReleaseNoteGenerated"]
      queue_key    = "whatsapp"
    }
    route-email = {
      detail_types = ["PackingListApproved", "ReleaseNoteGenerated", "DamageClaimFiled", "TenantOnboarded", "TenantSuspended"]
      queue_key    = "email"
    }
  }

  # Scheduled rules: rule name → schedule expression
  scheduled_rules = {
    storage-fee-accrual     = "cron(0 0 * * ? *)" # midnight UTC daily
    dispute-auto-escalation = "rate(6 hours)"
    sla-breach-check        = "rate(4 hours)"
    storage-reminders       = "cron(0 8 * * ? *)" # 08:00 UTC daily
    tenant-data-cleanup     = "cron(0 2 * * ? *)" # 02:00 UTC daily
    usage-aggregation       = "rate(1 hour)"
    release-note-expiry     = "cron(0 0 * * ? *)" # midnight UTC daily
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
  name = "${local.name_prefix}-eventbridge-sqs-role"

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
      Resource = values(var.sqs_queue_arns)
    }]
  })
}

# ---------------------------------------------------------------------------
# SQS resource policies — allow EventBridge to send to each queue
# ---------------------------------------------------------------------------

resource "aws_sqs_queue_policy" "eventbridge" {
  for_each  = var.sqs_queue_urls
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
# Routing rules on the custom event bus (SMS / WhatsApp / Email)
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "routing" {
  for_each = local.routing_rules

  name           = "${local.name_prefix}-${each.key}"
  event_bus_name = aws_cloudwatch_event_bus.main.name
  state          = "ENABLED"

  event_pattern = jsonencode({
    source      = [{ prefix = "${var.project_name}." }]
    detail-type = each.value.detail_types
  })

  tags = local.common_tags
}

resource "aws_cloudwatch_event_target" "routing_sqs" {
  for_each = local.routing_rules

  rule           = aws_cloudwatch_event_rule.routing[each.key].name
  event_bus_name = aws_cloudwatch_event_bus.main.name
  target_id      = "sqs-${each.value.queue_key}"
  arn            = var.sqs_queue_arns[each.value.queue_key]
  role_arn       = aws_iam_role.eventbridge_sqs.arn
}

# ---------------------------------------------------------------------------
# Metering rule — all events from logistics.* sources
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "route_metering" {
  name           = "${local.name_prefix}-route-metering"
  event_bus_name = aws_cloudwatch_event_bus.main.name
  state          = "ENABLED"

  event_pattern = jsonencode({
    source = [{ prefix = "${var.project_name}." }]
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
