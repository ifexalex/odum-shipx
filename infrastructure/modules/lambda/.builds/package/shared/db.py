"""Database connection management for Lambda functions.

Uses psycopg2 with a module-level connection that is reused across warm
Lambda invocations (connection reuse pattern). Automatically sets the
PostgreSQL session variable `app.current_tenant_id` before every query
to activate Row-Level Security policies.

The database password is fetched from AWS Secrets Manager on cold start
and cached in-process for the Lambda container lifetime.

See 00_CROSS_CUTTING_STANDARDS.md §2.2 for SQL injection prevention rules.
"""

import json
import logging
import os
from typing import Any

import boto3
import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

# Module-level connection reused across warm Lambda invocations
_connection: psycopg2.extensions.connection | None = None

# Cached DB password — fetched from Secrets Manager once per cold start
_cached_password: str | None = None


def _get_db_password() -> str:
    """Fetch the DB password, caching the result.

    In production: reads from Secrets Manager using DB_SECRET_ARN.
    Locally: falls back to DATABASE_PASSWORD env var when DB_SECRET_ARN is unset.
    """
    global _cached_password
    if _cached_password:
        return _cached_password

    secret_arn = os.environ.get("DB_SECRET_ARN", "")
    if not secret_arn:
        # Local / test mode — read password directly from env
        _cached_password = os.environ["DATABASE_PASSWORD"]
        logger.debug("DB password read from DATABASE_PASSWORD env var (local mode)")
        return _cached_password

    region = os.environ.get("AWS_REGION", "eu-west-1")
    client = boto3.client("secretsmanager", region_name=region)
    secret = client.get_secret_value(SecretId=secret_arn)
    _cached_password = json.loads(secret["SecretString"])["password"]
    logger.debug("DB password fetched from Secrets Manager")
    return _cached_password


def get_connection() -> psycopg2.extensions.connection:
    """Return a database connection, creating one if necessary.

    Reuses the module-level connection across warm Lambda invocations.
    Recreates if the connection has been closed.
    """
    global _connection

    if _connection is None or _connection.closed:
        logger.debug("Creating new database connection")
        _connection = psycopg2.connect(
            host=os.environ["DATABASE_HOST"],
            port=int(os.environ.get("DATABASE_PORT", "5432")),
            dbname=os.environ["DATABASE_NAME"],
            user=os.environ["DATABASE_USER"],
            password=_get_db_password(),
            connect_timeout=5,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        _connection.autocommit = False

    return _connection


def _set_tenant(cursor: psycopg2.extensions.cursor, tenant_id: str) -> None:
    """Set the RLS session variable for the current transaction.

    Uses parameterized query — never string formatting — per §2.2.
    """
    cursor.execute("SET LOCAL app.current_tenant_id = %s", (tenant_id,))


def _rows_to_dicts(cursor: psycopg2.extensions.cursor) -> list[dict]:
    """Convert cursor results to plain dicts."""
    rows = cursor.fetchall()
    if rows is None:
        return []
    return [dict(row) for row in rows]


def execute_with_tenant(
    tenant_id: str,
    query: str,
    params: Any = None,
) -> list[dict]:
    """Execute a SELECT query within a tenant scope.

    Sets `app.current_tenant_id` session variable before executing, which
    activates PostgreSQL RLS policies scoped to the tenant.

    Args:
        tenant_id: The tenant UUID (or PLATFORM for admin queries).
        query: Parameterized SQL string using %s placeholders.
        params: Query parameters (tuple, list, or dict).

    Returns:
        List of result rows as plain dicts.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            _set_tenant(cur, tenant_id)
            cur.execute(query, params)
            return _rows_to_dicts(cur)
    except Exception:
        conn.rollback()
        raise


def execute_write_with_tenant(
    tenant_id: str,
    query: str,
    params: Any = None,
) -> dict | None:
    """Execute an INSERT/UPDATE/DELETE query within a tenant scope.

    Appends `RETURNING *` expectation — the caller's query should include it.
    Commits the transaction on success.

    Returns:
        The first returned row as a dict, or None if nothing was returned.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            _set_tenant(cur, tenant_id)
            cur.execute(query, params)
            rows = _rows_to_dicts(cur)
            conn.commit()
            return rows[0] if rows else None
    except Exception:
        conn.rollback()
        raise


def execute_transaction(
    tenant_id: str,
    queries: list[tuple[str, Any]],
) -> list[dict | None]:
    """Execute multiple queries in a single transaction within a tenant scope.

    Sets the tenant RLS variable once, then runs all queries. Commits on
    success; rolls back the entire transaction on any failure.

    Args:
        tenant_id: The tenant UUID (or PLATFORM).
        queries: List of (query_string, params) tuples. Each query that
                 includes RETURNING will have its first row captured.

    Returns:
        List of result rows (one per query, None for queries without RETURNING).
    """
    conn = get_connection()
    results: list[dict | None] = []
    try:
        with conn.cursor() as cur:
            _set_tenant(cur, tenant_id)
            for query, params in queries:
                cur.execute(query, params)
                if cur.description:
                    rows = _rows_to_dicts(cur)
                    results.append(rows[0] if rows else None)
                else:
                    results.append(None)
        conn.commit()
        return results
    except Exception:
        conn.rollback()
        raise
