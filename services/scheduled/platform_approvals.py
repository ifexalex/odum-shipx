"""Platform approvals — runs every 15 minutes (platform audit Phase 1, decision D4).

Runs the sole-admin offboardings whose 24-hour wait is over (unless cancelled meanwhile), and expires two-person
requests that nobody approved or rejected within 24 hours. The decision logic lives in
``services/tenant_management/approvals.py``; this is the timer.
"""

import logging
from typing import Any

from shared.job_runs import tracked_job
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.observability import init_tracing, record_failure

setup_logging()
init_tracing()

logger = logging.getLogger(__name__)


@tracked_job("platform_approvals")
def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Run due scheduled approvals and expire stale pending ones; return the counts."""
    from services.tenant_management import approvals

    clear_log_context()
    bind_log_context(request_id=getattr(context, "aws_request_id", None) or "cron:platform_approvals")
    result = approvals.run_due()
    if result["failed"]:
        record_failure("scheduled_job_step")
    logger.info(
        "Platform approvals job done: executed=%d failed=%d expired=%d",
        result["executed"],
        result["failed"],
        result["expired"],
    )
    return result
