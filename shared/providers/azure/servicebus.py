"""Azure Service Bus queue provider — the Azure analogue of `aws/sqs.py`.

Implements the `QueueProvider` port against Azure Service Bus so
`shared/notifications.py` and the notification service enqueue unchanged when
`CLOUD_PROVIDER=azure`. `destination` is a Service Bus **queue name** (on AWS the
same port parameter is an SQS queue URL); the per-channel `SQS_*_QUEUE_URL` env
vars hold queue names on Azure.

Auth: `AZURE_SERVICE_BUS_CONNECTION_STRING` (namespace-level, or the
`UseDevelopmentEmulator=true` string for the local Service Bus emulator). A
managed-identity path would construct `ServiceBusClient(fully_qualified_namespace,
credential=DefaultAzureCredential())` — wired alongside the Terraform module.
"""
import os
from typing import Any


class ServiceBusQueueProvider:
    """QueueProvider backed by Azure Service Bus `send_messages`."""

    def __init__(self) -> None:
        self._conn = os.environ.get("AZURE_SERVICE_BUS_CONNECTION_STRING", "")
        self._namespace = os.environ.get("AZURE_SERVICE_BUS_NAMESPACE", "")
        self._client: Any = None

    def _service_bus(self) -> Any:
        if self._client is None:
            from azure.servicebus import ServiceBusClient

            if self._conn:
                self._client = ServiceBusClient.from_connection_string(self._conn)
            else:
                from azure.identity import DefaultAzureCredential

                self._client = ServiceBusClient(self._namespace, credential=DefaultAzureCredential())
        return self._client

    def send(self, *, destination: str, body: str) -> None:
        from azure.servicebus import ServiceBusMessage

        with self._service_bus().get_queue_sender(destination) as sender:
            sender.send_messages(ServiceBusMessage(body))
