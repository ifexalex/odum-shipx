"""Migration Lambda — runs Alembic upgrade head against Aurora via RDS Proxy.

Invoked synchronously by the deploy pipeline before any service code is deployed.
Raises on failure so the pipeline step exits non-zero and aborts the deploy.

Environment variables (injected by Terraform, same as all VPC Lambdas):
    DATABASE_HOST     RDS Proxy endpoint
    DATABASE_NAME     Database name (logistics)
    DATABASE_USER     DB user — the OWNER (postgres); DDL needs owner rights
    DATABASE_PORT     DB port (default 5432)
    DB_SECRET_ARN     Secrets Manager ARN for the owner's password
    APP_DB_SECRET_ARN Secrets Manager ARN for the logistics_app password, which
                      migration 060 sets on the role (optional; unset leaves the
                      role NOLOGIN and the switchover incomplete)
"""

import json
import logging
import os

from alembic import command
from alembic.config import Config

from shared.logging_config import setup_logging
from shared.providers import get_secrets_provider

# Module-level init (runs once on cold start)
setup_logging()

logger = logging.getLogger(__name__)


def lambda_handler(event: dict[str, object], context: object) -> dict[str, object]:
    """Fetch DB credentials and run alembic upgrade head.

    Args:
        event: Ignored — Lambda is invoked with empty payload {}.
        context: Lambda context (unused).

    Returns:
        dict with status and revision.

    Raises:
        Exception: Re-raises any alembic error so Lambda exits non-zero.
    """
    _inject_db_password()
    _inject_app_db_password()

    cfg = Config("migrations/alembic.ini")
    command.upgrade(cfg, "head")

    logger.info("Migrations complete")
    return {"status": "ok"}


def _inject_db_password() -> None:
    """Fetch the owner's DB password from Secrets Manager and set DATABASE_PASSWORD.

    Migrations connect as the table owner: DDL cannot be run by the application
    role, which holds only DML (migration 059).
    """
    secret_str = get_secrets_provider().get_secret(os.environ["DB_SECRET_ARN"])
    secret = json.loads(secret_str)
    os.environ["DATABASE_PASSWORD"] = secret["password"]


def _inject_app_db_password() -> None:
    """Expose the `logistics_app` password to migration 060 as APP_DB_PASSWORD.

    060 sets that password on the role, completing the RLS credential
    switchover. Fetched here rather than passed as a Lambda environment
    variable so the plaintext never sits in the function configuration or in
    Terraform state.

    A missing `APP_DB_SECRET_ARN` is not an error: 060 is written to log a
    notice and leave the role NOLOGIN, so an environment that has not been
    provisioned yet still migrates cleanly instead of blocking its own deploy.
    Never logged — the value is a live credential.
    """
    secret_arn = os.environ.get("APP_DB_SECRET_ARN")
    if not secret_arn:
        logger.info("APP_DB_SECRET_ARN not set — migration 060 will leave logistics_app NOLOGIN")
        return

    secret = json.loads(get_secrets_provider().get_secret(secret_arn))
    os.environ["APP_DB_PASSWORD"] = secret["password"]
    logger.info("Application DB credential loaded for the role migration")
