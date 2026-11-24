# ---------------------------------------------------------------------------
# Observability — the Azure analogue of the AWS `monitoring` module. Log
# Analytics is the CloudWatch Logs equivalent and the sink the Container Apps
# Environment (Phase 3) streams stdout/stderr to; Application Insights is the
# APM/telemetry backbone (shared/observability.py wires tracing at the platform
# level on Azure rather than in-process X-Ray).
#
# Metric alert rules are added in Phase 3 once their target resources (Container
# Apps, Postgres) exist, mirroring the AWS CloudWatch alarms.
# ---------------------------------------------------------------------------

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.name_prefix}-logs"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = var.retention_in_days
  tags                = var.common_tags
}

resource "azurerm_application_insights" "main" {
  name                = "${var.name_prefix}-appinsights"
  resource_group_name = var.resource_group_name
  location            = var.location
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  tags                = var.common_tags
}

# ---------------------------------------------------------------------------
# Swallowed failures (audit OPS-04) — the Azure side of the AWS failure alarms.
#
# shared/observability.py writes each counted failure as one JSON log line (Embedded Metric Format, which on Azure is
# just a log line): {"Operation": "...", "Failures": 1, ...}. Container Apps stream stdout/stderr to this workspace's
# ContainerAppConsoleLogs_CL table; these rules query it every 15 minutes, the cheapest log-alert frequency (about
# USD 0.50 per rule a month). Off unless alerts_email is set, so an environment without an inbox costs nothing.
# Runbook: "Failure alarms".
# ---------------------------------------------------------------------------

locals {
  alerts_enabled = var.alerts_email != ""

  # One summarised number per rule; the rule fires when it is above the threshold.
  failure_queries = {
    invoice-generation = { operation = "invoice_generation", window = "PT15M", threshold = 0 }
    audit-write        = { operation = "audit_write", window = "PT15M", threshold = 0 }
    scheduled-job-step = { operation = "scheduled_job_step", window = "PT1H", threshold = 0 }
  }
}

resource "azurerm_monitor_action_group" "alerts" {
  count               = local.alerts_enabled ? 1 : 0
  name                = "${var.name_prefix}-alerts"
  resource_group_name = var.resource_group_name
  short_name          = "shipxalert"
  tags                = var.common_tags

  email_receiver {
    name                    = "ops"
    email_address           = var.alerts_email
    use_common_alert_schema = true
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "failures" {
  for_each = local.alerts_enabled ? local.failure_queries : {}

  name                 = "${var.name_prefix}-${each.key}-failures"
  resource_group_name  = var.resource_group_name
  location             = var.location
  scopes               = [azurerm_log_analytics_workspace.main.id]
  evaluation_frequency = "PT15M"
  window_duration      = each.value.window
  severity             = 2
  description          = "Swallowed ${each.value.operation} failures (audit OPS-04). Runbook: Failure alarms."
  tags                 = var.common_tags

  criteria {
    query                   = <<-KQL
      ContainerAppConsoleLogs_CL
      | where Log_s has "${each.value.operation}" and Log_s has "Failures"
      | extend entry = parse_json(Log_s)
      | where tostring(entry.Operation) == "${each.value.operation}"
      | summarize failures = sum(toint(entry.Failures))
    KQL
    time_aggregation_method = "Total"
    metric_measure_column   = "failures"
    operator                = "GreaterThan"
    threshold               = each.value.threshold

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.alerts[0].id]
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "notification_failure_rate" {
  count = local.alerts_enabled ? 1 : 0

  name                 = "${var.name_prefix}-notification-failure-rate"
  resource_group_name  = var.resource_group_name
  location             = var.location
  scopes               = [azurerm_log_analytics_workspace.main.id]
  evaluation_frequency = "PT15M"
  window_duration      = "PT15M"
  severity             = 2
  description          = "More than ${var.notification_failure_rate_percent}% of notification sends failed (audit OPS-04)."
  tags                 = var.common_tags

  criteria {
    query                   = <<-KQL
      ContainerAppConsoleLogs_CL
      | where Log_s has "notification_send" and Log_s has "Attempts"
      | extend entry = parse_json(Log_s)
      | where tostring(entry.Operation) == "notification_send"
      | summarize attempts = sum(toint(entry.Attempts)), failures = sum(toint(entry.Failures))
      | extend failure_percent = iff(attempts >= ${var.notification_rate_min_attempts}, 100.0 * failures / attempts, 0.0)
    KQL
    time_aggregation_method = "Maximum"
    metric_measure_column   = "failure_percent"
    operator                = "GreaterThan"
    threshold               = var.notification_failure_rate_percent

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.alerts[0].id]
  }
}
