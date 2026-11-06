"""AWS EventBridge event provider."""

import json
import os
from typing import Any

from shared.exceptions import ExternalServiceError


class EventBridgeProvider:
    """EventProvider backed by AWS EventBridge `put_events`."""

    def __init__(self, region: str | None = None) -> None:
        self._region = region or os.environ.get("AWS_REGION", "eu-west-1")
        self._client: Any = None

    def _events(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("events", region_name=self._region)
        return self._client

    def publish(self, *, source: str, detail_type: str, detail: dict[str, Any], bus_name: str) -> None:
        entry = {
            "Source": source,
            "DetailType": detail_type,
            "Detail": json.dumps(detail, default=str),
            "EventBusName": bus_name,
        }
        response = self._events().put_events(Entries=[entry])
        if response.get("FailedEntryCount", 0):
            failed = response["Entries"][0]
            error_code = failed.get("ErrorCode", "Unknown")
            error_msg = failed.get("ErrorMessage", "")
            raise ExternalServiceError("EventBridge", f"{error_code}: {error_msg}")
