"""Scheduled-job runner — the entry point for Azure Container App Jobs (cron).

On AWS each scheduled job is a Lambda invoked by an EventBridge rule. Azure
Container App Jobs run a container on a cron schedule instead, so this runner
invokes the matching job's ``lambda_handler`` once and exits with its status.
One mapping here mirrors the EventBridge rule → Lambda wiring.

Run as::

    python -m services.scheduled.run --job release_expiry

Exit code 0 on success, 1 if the job handler raises — so the Container App Job
is marked failed and alerting fires, exactly as a failed Lambda would.
"""

import argparse
import importlib
import logging
import sys

from shared.logging_config import bind_log_context, clear_log_context, setup_logging

setup_logging()
logger = logging.getLogger("shipx_scheduled")

# job name → module exposing lambda_handler(event, context). Mirrors the
# EventBridge rules in infrastructure/aws/modules/eventbridge.
JOBS: tuple[str, ...] = (
    "data_cleanup",
    "dispute_escalation",
    "offboarding_export",
    "release_expiry",
    "sla_check",
    "storage_fee",
    "storage_reminders",
    "usage_aggregation",
)


def run_job(job: str) -> int:
    """Invoke one scheduled job's handler. Returns a process exit code."""
    if job not in JOBS:
        raise ValueError(f"Unknown job '{job}'; expected one of {list(JOBS)}")

    module = importlib.import_module(f"services.scheduled.{job}")
    handler = module.lambda_handler

    clear_log_context()
    bind_log_context(request_id=f"cron:{job}")
    logger.info("Scheduled job starting: %s", job)
    try:
        handler({"source": "cron", "job": job}, {})
    except Exception:
        logger.exception("Scheduled job failed: %s", job)
        return 1
    logger.info("Scheduled job finished: %s", job)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ShipX scheduled-job runner")
    parser.add_argument("--job", required=True, choices=list(JOBS), help="Which scheduled job to run")
    args = parser.parse_args(argv)
    return run_job(args.job)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
