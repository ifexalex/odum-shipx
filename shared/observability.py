"""Tracing initialization and failure counters, behind a cloud-neutral shim.

Tracing: on AWS this instruments boto3 / psycopg2 / requests for X-Ray (`patch_all`); on any other cloud it is a
no-op, since tracing there is wired at the platform level (e.g. Azure Application Insights auto-instrumentation)
rather than in-process. Call once at module load, next to `setup_logging()`.

Failure counters (audit OPS-04): invoice generation, notification enqueueing, audit writes and the per-tenant steps of
scheduled jobs catch errors, log them and carry on, which keeps a request alive but alerts nobody. Each of those catch
sites calls `record_failure(operation)`. The count is one structured log line in CloudWatch's Embedded Metric Format:
on AWS, CloudWatch turns it into the metric ``ShipX / Failures`` (dimensions ``Environment``, ``Operation``) with no
API call; on Azure the same line lands in Log Analytics, where the alert rules query it. Alarms on both:
``infrastructure/aws/modules/monitoring`` and ``infrastructure/azure/modules/monitoring``. Response steps:
``docs/runbook.md``, "Failure alarms".
"""

import logging
import os
import re
import time

from shared.providers import CLOUD_PROVIDER

#: CloudWatch namespace for the counters. Alarms name it too.
METRIC_NAMESPACE = "ShipX"

#: The operations that are counted. A name is a metric dimension, so the set must stay small and fixed: never build
#: one from data (a tenant id or an error message would create a metric per value, each billed).
OPERATIONS = frozenset(
    {
        "invoice_generation",
        "notification_enqueue",
        "notification_send",
        "audit_write",
        "scheduled_job_step",
        "tenant_deletion_refused",
    }
)

_metrics_logger = logging.getLogger("shipx.metrics")
# Counted even where LOG_LEVEL hides INFO: a metric that depends on the log level is a metric that silently stops.
_metrics_logger.setLevel(logging.INFO)

_IDENTIFIER = re.compile(r"^[a-z_]+$")


def init_tracing() -> None:
    """Instrument the runtime for distributed tracing on the active cloud."""
    if CLOUD_PROVIDER != "aws":
        return
    from aws_xray_sdk.core import patch_all

    patch_all()


def record_failure(operation: str) -> None:
    """Count one failure of ``operation`` that was caught and not re-raised. Never raises.

    Call it next to the log line in the ``except`` block; the log line carries the detail, this carries the count.
    """
    _emit(operation, {"Failures": 1})


def record_outcome(operation: str, *, failed: bool) -> None:
    """Count one attempt of ``operation`` and whether it failed, for alarms on a failure rate. Never raises."""
    _emit(operation, {"Attempts": 1, "Failures": 1 if failed else 0})


def _emit(operation: str, values: dict[str, int]) -> None:
    if operation not in OPERATIONS or not _IDENTIFIER.match(operation):
        # A programming error, but counting must never break the operation being counted.
        _metrics_logger.error("Not a counted operation: %r", operation[:60])
        return
    try:
        _metrics_logger.info(
            "metric %s",
            operation,
            extra={
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": METRIC_NAMESPACE,
                            "Dimensions": [["Environment", "Operation"]],
                            "Metrics": [{"Name": name, "Unit": "Count"} for name in values],
                        }
                    ],
                },
                "Environment": os.environ.get("ENVIRONMENT", "unknown"),
                "Operation": operation,
                **values,
            },
        )
    except Exception:
        logging.getLogger(__name__).warning("Could not record a %s metric", operation, exc_info=True)
