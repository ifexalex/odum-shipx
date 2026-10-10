# ---------------------------------------------------------------------------
# Service Bus — the Azure analogue of the AWS `sqs` module. One namespace with
# the same four queues (sms, whatsapp, email, metering). Service Bus has
# built-in dead-lettering (no separate DLQ resource): max_delivery_count +
# dead_lettering_on_message_expiration give the SQS redrive behaviour.
#
# Feeds shared/providers/azure/servicebus.py (producer) and
# services/queue_worker (consumer): AZURE_SERVICE_BUS_CONNECTION_STRING +
# the per-channel queue names (set as SQS_*_QUEUE_URL — the port's opaque queue
# reference holds a queue *name* on Azure).
# ---------------------------------------------------------------------------

locals {
  # name → max_delivery_count, mirroring the SQS max_receive_count per channel.
  queues = {
    sms      = { max_delivery_count = 3, lock_duration = "PT1M" }
    whatsapp = { max_delivery_count = 3, lock_duration = "PT1M" }
    email    = { max_delivery_count = 3, lock_duration = "PT1M" }
    metering = { max_delivery_count = 5, lock_duration = "PT5M" }
  }
}

resource "azurerm_servicebus_namespace" "main" {
  # Azure reserves the -sb and -mgmt suffixes for namespace names, so use -bus.
  name                = "${var.name_prefix}-bus"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = var.sku
  tags                = var.common_tags
}

resource "azurerm_servicebus_queue" "channel" {
  for_each = local.queues

  name         = "${var.name_prefix}-${each.key}"
  namespace_id = azurerm_servicebus_namespace.main.id

  max_delivery_count                   = each.value.max_delivery_count
  lock_duration                        = each.value.lock_duration
  dead_lettering_on_message_expiration = true
  # 4-day message TTL, matching the SQS main-queue retention.
  default_message_ttl = "P4D"
}
