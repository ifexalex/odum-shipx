locals {
  name_prefix = "${var.project_name}-${var.environment}"
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = "logistics-platform"
    Owner       = "platform-engineering"
  }

  queues = {
    sms = {
      visibility_timeout_seconds = 60
      max_receive_count          = 3
    }
    whatsapp = {
      visibility_timeout_seconds = 60
      max_receive_count          = 3
    }
    email = {
      visibility_timeout_seconds = 60
      max_receive_count          = 3
    }
    metering = {
      visibility_timeout_seconds = 30
      max_receive_count          = 5
    }
  }
}

# ---------------------------------------------------------------------------
# Dead-letter queues — one per channel
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "dlq" {
  for_each = local.queues

  name                      = "${var.project_name}-${each.key}-dlq-${var.environment}"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true

  tags = merge(local.common_tags, { Queue = "${each.key}-dlq" })
}

# ---------------------------------------------------------------------------
# Main queues with redrive policy → DLQ
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "main" {
  for_each = local.queues

  name                       = "${var.project_name}-${each.key}-${var.environment}"
  visibility_timeout_seconds = each.value.visibility_timeout_seconds
  message_retention_seconds  = 345600 # 4 days
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = each.value.max_receive_count
  })

  tags = merge(local.common_tags, { Queue = each.key })
}
