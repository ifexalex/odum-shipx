# ---------------------------------------------------------------------------
# Event Grid custom topic — the Azure analogue of the AWS `eventbridge` custom
# bus. Feeds shared/providers/azure/eventgrid.py (EventGridProvider): the app
# publishes domain events to this topic's endpoint with its access key.
#
# AWS EventBridge also routes events to SQS + runs the scheduled rules; on Azure
# those are separate concerns — Service Bus is a distinct namespace, and the
# scheduled jobs run as Container App Jobs (Phase 3), not Event Grid.
# ---------------------------------------------------------------------------

resource "azurerm_eventgrid_topic" "main" {
  name                = "${var.name_prefix}-events"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.common_tags
}
