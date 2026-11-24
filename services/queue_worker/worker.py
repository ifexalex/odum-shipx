"""Service Bus queue worker — the Azure analogue of AWS's SQS → Lambda
event-source mappings.

On AWS each notification/metering queue has its own Lambda wired as an SQS event
source (see ``infrastructure/aws/modules/lambda`` — ``notif_sms``,
``notif_whatsapp``, ``notif_email``, ``metering``). Azure Container Apps has no
event-source mapping, so this long-running worker plays that role: it receives
messages from one Service Bus queue and invokes the *same* handler with an
SQS-shaped event (``{"Records": [{"messageId", "body"}]}``), so the handler code
is byte-identical across clouds.

One worker consumes one queue (``--queue sms|whatsapp|email|metering``), mirroring
AWS's one-Lambda-per-queue model and letting each queue scale independently under
a KEDA Service Bus scaler.

Run as::

    python -m services.queue_worker.worker --queue sms

Environment:
  AZURE_SERVICE_BUS_CONNECTION_STRING  — namespace connection string.
  SQS_SMS_QUEUE_URL / SQS_WHATSAPP_QUEUE_URL / SQS_EMAIL_QUEUE_URL /
  SQS_METERING_QUEUE_URL                — hold the Service Bus *queue name* on Azure
                                          (the port's "opaque queue reference").
"""

import argparse
import logging
import os
import sys
from collections.abc import Callable
from typing import Any, cast

from shared.logging_config import bind_log_context, clear_log_context, setup_logging

setup_logging()
logger = logging.getLogger("shipx_queue_worker")

# queue key → (handler import path, queue-name env var). Imported lazily so the
# worker for one queue never imports the others' handlers or the Azure SDK at
# module load (keeps unit tests SDK-free).
_QUEUE_CONFIG: dict[str, tuple[str, str]] = {
    "sms": ("services.notification.handler:sms_handler", "SQS_SMS_QUEUE_URL"),
    "whatsapp": ("services.notification.handler:whatsapp_handler", "SQS_WHATSAPP_QUEUE_URL"),
    "email": ("services.notification.handler:email_handler", "SQS_EMAIL_QUEUE_URL"),
    "metering": ("services.metering.handler:lambda_handler", "SQS_METERING_QUEUE_URL"),
}


def _load_handler(ref: str) -> Callable[[dict[str, Any], Any], Any]:
    """Resolve a ``module.path:function`` reference to the callable."""
    module_path, _, func_name = ref.partition(":")
    import importlib

    module = importlib.import_module(module_path)
    return cast(Callable[[dict[str, Any], Any], Any], getattr(module, func_name))


def process_message(
    handler: Callable[[dict[str, Any], Any], Any],
    body: str,
    message_id: str,
) -> None:
    """Invoke ``handler`` with a single-record SQS-shaped event.

    Raises whatever the handler raises; the caller decides whether to complete or
    abandon the Service Bus message based on success/failure.
    """
    event = {
        "Records": [
            {
                "messageId": message_id,
                "eventSource": "aws:sqs",
                "body": body,
            }
        ]
    }
    result = handler(event, {})
    if isinstance(result, dict) and result.get("batchItemFailures"):
        raise RuntimeError(f"Handler reported batchItemFailures for message {message_id}: {result['batchItemFailures']}")


def run_worker(queue_key: str, max_wait_seconds: int = 5) -> None:  # pragma: no cover - needs live SDK
    """Receive from the Service Bus queue for ``queue_key`` until interrupted.

    Completes each message the handler processes without raising; abandons
    (for redelivery) any message whose handler raises, so Service Bus retry +
    dead-lettering apply exactly as SQS redrive does on AWS.
    """
    if queue_key not in _QUEUE_CONFIG:
        raise ValueError(f"Unknown queue key '{queue_key}'; expected one of {sorted(_QUEUE_CONFIG)}")

    handler_ref, queue_env = _QUEUE_CONFIG[queue_key]
    queue_name = os.environ.get(queue_env, "")
    conn_str = os.environ.get("AZURE_SERVICE_BUS_CONNECTION_STRING", "")
    if not queue_name:
        raise RuntimeError(f"{queue_env} is not set — cannot determine Service Bus queue name")
    if not conn_str:
        raise RuntimeError("AZURE_SERVICE_BUS_CONNECTION_STRING is not set")

    handler = _load_handler(handler_ref)

    from azure.servicebus import ServiceBusClient

    logger.info("Queue worker starting: queue_key=%s queue_name=%s", queue_key, queue_name)
    with ServiceBusClient.from_connection_string(conn_str) as client:
        receiver = client.get_queue_receiver(queue_name=queue_name, max_wait_time=max_wait_seconds)
        with receiver:
            for message in receiver:
                message_id = str(getattr(message, "message_id", "") or "unknown")
                clear_log_context()
                bind_log_context(request_id=message_id)
                try:
                    process_message(handler, str(message), message_id)
                    receiver.complete_message(message)
                except Exception:
                    logger.exception("Handler failed for message %s — abandoning for retry", message_id)
                    receiver.abandon_message(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ShipX Service Bus queue worker")
    parser.add_argument(
        "--queue",
        required=True,
        choices=sorted(_QUEUE_CONFIG),
        help="Which queue this worker consumes",
    )
    args = parser.parse_args(argv)
    run_worker(args.queue)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
