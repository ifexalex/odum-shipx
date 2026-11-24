data "aws_region" "current" {}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  region      = data.aws_region.current.name
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = "logistics-platform"
    Owner       = "platform-engineering"
  }
}

# ---------------------------------------------------------------------------
# SNS Topic for alarm notifications
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
  tags = local.common_tags
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alerts_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alerts_email
}

# ---------------------------------------------------------------------------
# CloudWatch Metric Alarms
# ---------------------------------------------------------------------------

# 1. Lambda Errors > 5 in any 5-minute window (one alarm per function)
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = toset(var.lambda_function_names)

  alarm_name          = "${each.value}-errors"
  alarm_description   = "Lambda function ${each.value} has more than 5 errors in 5 minutes"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = each.value }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = local.common_tags
}

# 2. API Gateway 5xx error rate > 1% (count-based, 1-minute window)
resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name        = "${local.name_prefix}-api-5xx"
  alarm_description = "API Gateway 5xx error rate exceeded 1% threshold"
  namespace         = "AWS/ApiGateway"
  metric_name       = "5XXError"
  dimensions = {
    ApiId = var.api_id
    Stage = "$default"
  }
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0.01
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = local.common_tags
}

# 3. Aurora database connections > 40 (proxy pool approaching limit)
resource "aws_cloudwatch_metric_alarm" "aurora_connections" {
  alarm_name          = "${local.name_prefix}-aurora-connections"
  alarm_description   = "Aurora database connections exceeded 40 (>80% of proxy pool)"
  namespace           = "AWS/RDS"
  metric_name         = "DatabaseConnections"
  dimensions          = { DBClusterIdentifier = var.cluster_identifier }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 40
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = local.common_tags
}

# 4. SQS DLQ messages visible > 0 (any failed message warrants investigation)
resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  for_each = var.dlq_names

  alarm_name          = "${local.name_prefix}-dlq-${each.key}-messages"
  alarm_description   = "Dead-letter queue ${each.value} has visible messages (processing failures)"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = local.common_tags
}

# 5. Lambda p95 duration > 5000ms (latency SLA breach)
resource "aws_cloudwatch_metric_alarm" "lambda_duration_p95" {
  for_each = toset(var.lambda_function_names)

  alarm_name          = "${each.value}-duration-p95"
  alarm_description   = "Lambda function ${each.value} p95 duration exceeded 5000ms"
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  dimensions          = { FunctionName = each.value }
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = local.common_tags
}

# ---------------------------------------------------------------------------
# Swallowed failures (audit OPS-04)
#
# Invoice generation, notification enqueueing, audit writes and scheduled jobs' per-tenant steps catch errors and
# carry on, so Lambda "Errors" never sees them. shared/observability.py counts each one as an Embedded Metric Format
# log line: namespace ShipX, metric Failures (and Attempts for notification sends), dimensions Environment and
# Operation. CloudWatch builds the metrics from the logs; no data means nothing failed. Runbook: "Failure alarms".
# Cost: one custom metric per operation (about USD 0.30 each a month) and USD 0.10 per alarm.
# ---------------------------------------------------------------------------

locals {
  failure_alarms = {
    invoice-generation = {
      operation   = "invoice_generation"
      period      = 300
      description = "A customer on a cleared container was not invoiced (generation raised). They are not billed until someone generates it again."
    }
    audit-write = {
      operation   = "audit_write"
      period      = 300
      description = "An audit record (tenant or platform) could not be written; the action itself went ahead without one."
    }
    scheduled-job-step = {
      operation   = "scheduled_job_step"
      period      = 3600
      description = "A scheduled job failed for a tenant or a record (storage fees, reminders, escalations, expiry, usage, cleanup, offboarding export) and moved on."
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "failures" {
  for_each = local.failure_alarms

  alarm_name          = "${local.name_prefix}-${each.key}-failures"
  alarm_description   = each.value.description
  namespace           = var.metric_namespace
  metric_name         = "Failures"
  dimensions          = { Environment = var.environment, Operation = each.value.operation }
  statistic           = "Sum"
  period              = each.value.period
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = local.common_tags
}

# Notifications fail for reasons outside the app (a gateway down, credit exhausted), so a single failure is noise; a
# rate is the signal. Only judged once there are enough sends in the window to mean something.
resource "aws_cloudwatch_metric_alarm" "notification_failure_rate" {
  alarm_name          = "${local.name_prefix}-notification-failure-rate"
  alarm_description   = "More than ${var.notification_failure_rate_percent}% of notification sends failed in 15 minutes (at least ${var.notification_rate_min_attempts} sends)."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = var.notification_failure_rate_percent
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = local.common_tags

  metric_query {
    id = "attempts"
    metric {
      namespace   = var.metric_namespace
      metric_name = "Attempts"
      dimensions  = { Environment = var.environment, Operation = "notification_send" }
      period      = 900
      stat        = "Sum"
    }
  }

  metric_query {
    id = "failures"
    metric {
      namespace   = var.metric_namespace
      metric_name = "Failures"
      dimensions  = { Environment = var.environment, Operation = "notification_send" }
      period      = 900
      stat        = "Sum"
    }
  }

  metric_query {
    id          = "rate"
    expression  = "IF(attempts >= ${var.notification_rate_min_attempts}, 100 * failures / attempts, 0)"
    label       = "Notification send failure %"
    return_data = true
  }
}

# ---------------------------------------------------------------------------
# CloudWatch Dashboard
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${local.name_prefix}-overview"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title       = "Lambda Errors (all functions)"
          view        = "timeSeries"
          period      = 300
          region      = local.region
          annotations = { horizontal = [] }
          metrics = [
            for fn in var.lambda_function_names : ["AWS/Lambda", "Errors", "FunctionName", fn, { stat = "Sum" }]
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title       = "API Gateway — Requests & 5xx Errors"
          view        = "timeSeries"
          period      = 60
          region      = local.region
          annotations = { horizontal = [] }
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiId", var.api_id, "Stage", "$default", { stat = "Sum", label = "Requests" }],
            ["AWS/ApiGateway", "5XXError", "ApiId", var.api_id, "Stage", "$default", { stat = "Sum", label = "5xx Errors" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title       = "Lambda p95 Duration (all functions)"
          view        = "timeSeries"
          period      = 300
          region      = local.region
          annotations = { horizontal = [] }
          metrics = [
            for fn in var.lambda_function_names : ["AWS/Lambda", "Duration", "FunctionName", fn, { stat = "p95" }]
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title       = "Aurora — Database Connections"
          view        = "timeSeries"
          period      = 60
          region      = local.region
          annotations = { horizontal = [] }
          metrics = [
            ["AWS/RDS", "DatabaseConnections", "DBClusterIdentifier", var.cluster_identifier, { stat = "Maximum" }]
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 24
        height = 6
        properties = {
          title       = "SQS DLQ — Messages Visible"
          view        = "timeSeries"
          period      = 60
          region      = local.region
          annotations = { horizontal = [] }
          metrics = [
            for name, queue_name in var.dlq_names : ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", queue_name, { stat = "Maximum", label = name }]
          ]
        }
      },
    ]
  })
}
