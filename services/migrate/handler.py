"""Migration Lambda — runs Alembic upgrade head against Aurora via RDS Proxy.

Invoked synchronously by the deploy pipeline before any service code is deployed.
Raises on failure so the pipeline step exits non-zero and aborts the deploy.

Environment variables (injected by Terraform, same as all VPC Lambdas):
    DATABASE_HOST     RDS Proxy endpoint
    DATABASE_NAME     Database name (logistics)
    DATABASE_USER     DB user (postgres)
    DATABASE_PORT     DB port (default 5432)
    DB_SECRET_ARN     Secrets Manager ARN for the DB password
"""
import json
import logging
import os

import boto3
from alembic import command
from alembic.config import Config

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

    cfg = Config("migrations/alembic.ini")
    command.upgrade(cfg, "head")

    logger.info("Migrations complete")
    return {"status": "ok"}


def _inject_db_password() -> None:
    """Fetch the DB password from Secrets Manager and set DATABASE_PASSWORD."""
    sm = boto3.client("secretsmanager")
    secret_str = sm.get_secret_value(SecretId=os.environ["DB_SECRET_ARN"])["SecretString"]
    secret = json.loads(secret_str)
    os.environ["DATABASE_PASSWORD"] = secret["password"]
