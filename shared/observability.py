"""Distributed-tracing initialization behind a cloud-neutral shim.

On AWS this instruments boto3 / psycopg2 / requests for X-Ray (`patch_all`); on
any other cloud it is a no-op, since tracing there is wired at the platform level
(e.g. Azure Application Insights auto-instrumentation) rather than in-process.
Call once at module load, next to `setup_logging()`.
"""

from shared.providers import CLOUD_PROVIDER


def init_tracing() -> None:
    """Instrument the runtime for distributed tracing on the active cloud."""
    if CLOUD_PROVIDER != "aws":
        return
    from aws_xray_sdk.core import patch_all

    patch_all()
