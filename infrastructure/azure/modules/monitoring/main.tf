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
