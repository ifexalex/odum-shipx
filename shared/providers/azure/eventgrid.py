"""Azure Event Grid event provider — the Azure analogue of `aws/eventbridge.py`.

Implements the `EventProvider` port by publishing one `EventGridEvent` to a
custom topic. The envelope (event_id / occurred_at / tenant_id / payload) is
still built in `shared/events.py`; this adapter only delivers. The EventBridge
`detail_type` maps to the Event Grid `event_type` and `source` to the `subject`
(`bus_name` selects the topic, which is the publisher endpoint). Raises
`ExternalServiceError` on failure, matching the port contract.

Auth: `AZURE_EVENT_GRID_ENDPOINT` + `AZURE_EVENT_GRID_KEY` (access-key), or the
endpoint alone with `DefaultAzureCredential` (keyless/managed identity).
"""
import os
from typing import Any

from shared.exceptions import ExternalServiceError


class EventGridProvider:
    """EventProvider backed by Azure Event Grid (`EventGridPublisherClient`)."""

    def __init__(self) -> None:
        self._endpoint = os.environ.get("AZURE_EVENT_GRID_ENDPOINT", "")
        self._key = os.environ.get("AZURE_EVENT_GRID_KEY", "")
        self._client: Any = None

    def _publisher(self) -> Any:
        if self._client is None:
            from azure.eventgrid import EventGridPublisherClient

            if self._key:
                from azure.core.credentials import AzureKeyCredential

                self._client = EventGridPublisherClient(self._endpoint, AzureKeyCredential(self._key))
            else:
                from azure.identity import DefaultAzureCredential

                self._client = EventGridPublisherClient(self._endpoint, DefaultAzureCredential())
        return self._client

    def publish(self, *, source: str, detail_type: str, detail: dict[str, Any], bus_name: str) -> None:
        from azure.eventgrid import EventGridEvent

        event = EventGridEvent(
            subject=source,
            event_type=detail_type,
            data=detail,
            data_version="1.0",
        )
        try:
            self._publisher().send(event)
        except Exception as exc:  # noqa: BLE001 — normalize any SDK/transport error to the port contract
            raise ExternalServiceError("EventGrid", str(exc)) from exc
