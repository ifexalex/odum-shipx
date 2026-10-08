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

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from shared.providers import get_event_provider

logger = logging.getLogger(__name__)


def publish_event(
    source: str,
    detail_type: str,
    tenant_id: str,
    payload: dict[str, Any],
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
    occurred_at = datetime.now(UTC).isoformat()

    detail = {
        "tenant_id": tenant_id,
        "event_id": event_id,
        "occurred_at": occurred_at,
        "request_id": request_id,
        "payload": payload,
    }

    bus_name = os.environ.get("EVENT_BUS_NAME", "logistics-events")

    try:
        get_event_provider().publish(source=source, detail_type=detail_type, detail=detail, bus_name=bus_name)
    except Exception as exc:
        logger.error(
            "Event publish failed",
            extra={
                "event_id": event_id,
                "source": source,
                "detail_type": detail_type,
                "error_message": str(exc),
            },
        )
        raise

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
