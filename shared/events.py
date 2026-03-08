"""EventBridge event publisher.

All domain events carry a tenant_id and are published to the bus configured
via the EVENT_BUS_NAME environment variable.

Event envelope format (§ task 02):
  {
    "source": "logistics.{service_name}",
    "detail-type": "{EventName}",
    "detail": {
      "tenant_id": "uuid",
      "event_id": "uuid",
      "occurred_at": "ISO 8601",
      "payload": { ... }
    }
  }
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3

logger = logging.getLogger(__name__)

# Module-level client reused across warm Lambda invocations
_events_client = None


def _get_client():
    global _events_client
    if _events_client is None:
        _events_client = boto3.client("events", region_name=os.environ.get("AWS_REGION", "eu-west-1"))
    return _events_client


def publish_event(
    source: str,
    detail_type: str,
    tenant_id: str,
    payload: dict,
    request_id: str = "",
) -> str:
    """Publish a domain event to EventBridge.

    Args:
        source: Event source string, e.g. "logistics.packing_list".
        detail_type: Human-readable event name, e.g. "PackingListApproved".
        tenant_id: Tenant UUID — included in the event envelope for routing.
        payload: Arbitrary event payload dict.
        request_id: Correlation ID propagated from the originating request.

    Returns:
        The generated event_id (UUID v4 string).
    """
    event_id = str(uuid.uuid4())
    occurred_at = datetime.now(timezone.utc).isoformat()

    detail = {
        "tenant_id": tenant_id,
        "event_id": event_id,
        "occurred_at": occurred_at,
        "request_id": request_id,
        "payload": payload,
    }

    bus_name = os.environ.get("EVENT_BUS_NAME", "logistics-events")

    entry = {
        "Source": source,
        "DetailType": detail_type,
        "Detail": json.dumps(detail, default=str),
        "EventBusName": bus_name,
    }

    client = _get_client()
    response = client.put_events(Entries=[entry])

    failed = response.get("FailedEntryCount", 0)
    if failed:
        error_code = response["Entries"][0].get("ErrorCode", "Unknown")
        error_msg = response["Entries"][0].get("ErrorMessage", "")
        logger.error(
            "EventBridge publish failed",
            extra={
                "event_id": event_id,
                "source": source,
                "detail_type": detail_type,
                "error_code": error_code,
                "error_message": error_msg,
            },
        )
        from shared.exceptions import ExternalServiceError
        raise ExternalServiceError("EventBridge", f"{error_code}: {error_msg}")

    logger.info(
        "Event published",
        extra={
            "event_id": event_id,
            "source": source,
            "detail_type": detail_type,
            "tenant_id": tenant_id,
        },
    )
    return event_id
