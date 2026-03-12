"""Migration Lambda — runs Alembic upgrade head against Aurora via RDS Proxy.

Invoked synchronously by the deploy pipeline before any service code is deployed.
Returns a non-zero returncode to cause the pipeline step to fail and abort the deploy.

Environment variables (injected by Terraform, same as all VPC Lambdas):
    DATABASE_HOST     RDS Proxy endpoint
    DATABASE_NAME     Database name (logistics)
    DATABASE_USER     DB user (postgres)
    DATABASE_PORT     DB port (default 5432)
    DB_SECRET_ARN     Secrets Manager ARN for the DB password
"""
import json
import os
import subprocess
import sys

import boto3


def lambda_handler(event: dict[str, object], context: object) -> dict[str, object]:
    """Fetch DB credentials and run alembic upgrade head.

    Args:
        event: Ignored — Lambda is invoked with empty payload {}.
        context: Lambda context (unused).

    Returns:
        dict with status, returncode, stdout, stderr.
    """
    _inject_db_password()

    cmd = [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", "upgrade", "head"]
    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603

    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)

    return {
        "status": "ok" if result.returncode == 0 else "error",
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _inject_db_password() -> None:
    """Fetch the DB password from Secrets Manager and set DATABASE_PASSWORD."""
    sm = boto3.client("secretsmanager")
    secret_str = sm.get_secret_value(SecretId=os.environ["DB_SECRET_ARN"])["SecretString"]
    secret = json.loads(secret_str)
    os.environ["DATABASE_PASSWORD"] = secret["password"]
