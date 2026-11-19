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
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import psycopg2
import psycopg2.extras

from shared.providers import get_secrets_provider

logger = logging.getLogger(__name__)

# Module-level connection reused across warm Lambda invocations
_connection: psycopg2.extensions.connection | None = None

# Cached DB password — fetched from Secrets Manager once per cold start
_cached_password: str | None = None

# The cursor and tenant scope of the `tenant_transaction` currently open in this
# context, if any. While one is open, every `execute_*` helper below runs on that
# cursor and leaves committing to the transaction, so existing repository
# functions compose into one atomic unit without being rewritten.
_active_transaction: ContextVar[tuple[str, Any] | None] = ContextVar("active_tenant_transaction", default=None)


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

    _cached_password = json.loads(get_secrets_provider().get_secret(secret_arn))["password"]
    logger.debug("DB password fetched from the secrets provider")
    return _cached_password


def get_connection() -> psycopg2.extensions.connection:
    """Return a database connection, creating one if necessary.

    Reuses the module-level connection across warm Lambda invocations.
    Recreates if the connection has been closed.
    """
    global _connection

    if _connection is None or _connection.closed:
        logger.debug("Creating new database connection")
        # sslmode: an explicit DATABASE_SSLMODE wins (set 'require' on Azure,
        # whose Postgres Flexible Server mandates TLS). Otherwise it defaults to
        # 'require' in AWS production (DB_SECRET_ARN set) and 'prefer' locally so
        # plain-TCP Aurora Serverless local Docker works without a cert bundle.
        _ssl_mode = os.environ.get("DATABASE_SSLMODE") or ("require" if os.environ.get("DB_SECRET_ARN") else "prefer")
        _connection = psycopg2.connect(
            host=os.environ["DATABASE_HOST"],
            port=int(os.environ.get("DATABASE_PORT", "5432")),
            dbname=os.environ["DATABASE_NAME"],
            user=os.environ["DATABASE_USER"],
            password=_get_db_password(),
            connect_timeout=5,
            sslmode=_ssl_mode,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        _connection.autocommit = False
    elif _connection.get_transaction_status() == psycopg2.extensions.TRANSACTION_STATUS_INERROR:
        # Self-heal a connection left in a failed transaction by an earlier
        # caller that raised past its own rollback (a raw get_connection()
        # user outside execute_with_tenant/execute_write_with_tenant, or any
        # future code path that doesn't roll back on error). Found live: a
        # duplicate-key race in shared/metering.py's record_usage() under
        # rapid concurrent-ish requests left every *subsequent* unrelated
        # request on this warm container failing with
        # "current transaction is aborted, commands ignored until end of
        # transaction block" — not just the request that actually hit the
        # constraint violation. In production this is a warm Lambda
        # container reusing this same module-level connection across
        # invocations, so one unrolled-back failure would otherwise break
        # every request on that container until AWS recycles it.
        logger.warning(
            "Reused connection was left in a failed transaction — rolling back "
            "before use. This means some earlier caller raised past an error "
            "without rolling back; that call site should be fixed too."
        )
        _connection.rollback()

    return _connection


def _set_tenant(cursor: psycopg2.extensions.cursor, tenant_id: str) -> None:
    """Set the RLS session variable for the current transaction.

    Uses parameterized query — never string formatting — per §2.2.
    """
    cursor.execute("SET LOCAL app.current_tenant_id = %s", (tenant_id,))


def _transaction_cursor(tenant_id: str) -> psycopg2.extensions.cursor | None:
    """The open transaction's cursor if one is active for this tenant scope, else None.

    A query for a *different* scope inside an open transaction raises. The RLS
    variable is set with `SET LOCAL`, which lasts until the transaction ends, so
    letting a PLATFORM-scoped read (or an audit write) slip in would silently
    widen the scope for every statement after it. Do such reads before opening the
    transaction, and audit/publish after it commits.
    """
    active = _active_transaction.get()
    if active is None:
        return None
    scope, cursor = active
    if scope != tenant_id:
        raise RuntimeError(
            f"query scoped to {tenant_id!r} issued inside a transaction scoped to {scope!r}; "
            "do cross-scope reads before the transaction and audit/publish after it"
        )
    return cursor


def _rows_to_dicts(cursor: psycopg2.extensions.cursor) -> list[dict[str, Any]]:
    """Convert cursor results to plain dicts."""
    if cursor.description is None:
        return []
    rows = cursor.fetchall()
    if rows is None:
        return []
    return [dict(row) for row in rows]


def execute_with_tenant(
    tenant_id: str,
    query: str,
    params: Any = None,
) -> list[dict[str, Any]]:
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
    joined = _transaction_cursor(tenant_id)
    if joined is not None:
        joined.execute(query, params)
        return _rows_to_dicts(joined)
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
) -> dict[str, Any] | None:
    """Execute an INSERT/UPDATE/DELETE query within a tenant scope.

    Appends `RETURNING *` expectation — the caller's query should include it.
    Commits the transaction on success.

    Returns:
        The first returned row as a dict, or None if nothing was returned.
    """
    joined = _transaction_cursor(tenant_id)
    if joined is not None:
        joined.execute(query, params)
        rows = _rows_to_dicts(joined)
        return rows[0] if rows else None
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


def execute_write_with_tenant_many(
    tenant_id: str,
    query: str,
    params: Any = None,
) -> list[dict[str, Any]]:
    """Execute a multi-row INSERT/UPDATE/DELETE within a tenant scope.

    Like `execute_write_with_tenant`, but for writes that affect (and
    RETURN) more than one row, e.g. a bulk `UPDATE ... WHERE id = ANY(...)`.
    Commits the transaction on success.

    Returns:
        All returned rows as dicts.
    """
    joined = _transaction_cursor(tenant_id)
    if joined is not None:
        joined.execute(query, params)
        return _rows_to_dicts(joined)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            _set_tenant(cur, tenant_id)
            cur.execute(query, params)
            rows = _rows_to_dicts(cur)
            conn.commit()
            return rows
    except Exception:
        conn.rollback()
        raise


def execute_transaction(
    tenant_id: str,
    queries: list[tuple[str, Any]],
) -> list[dict[str, Any] | None]:
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
    results: list[dict[str, Any] | None] = []
    joined = _transaction_cursor(tenant_id)
    if joined is not None:
        for query, params in queries:
            joined.execute(query, params)
            rows = _rows_to_dicts(joined) if joined.description else []
            results.append(rows[0] if rows else None)
        return results
    conn = get_connection()
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


@contextmanager
def tenant_transaction(tenant_id: str) -> Iterator[psycopg2.extensions.cursor]:
    """Run a multi-statement unit of work atomically within a tenant scope.

    The tenant RLS variable is set once; the transaction commits when the block
    exits normally and rolls back entirely if it raises. Nothing is visible to
    other requests until it commits.

    While the block is open, every `execute_with_tenant`, `execute_write_with_tenant`
    and `execute_transaction` call for the same tenant runs inside it, so existing
    repository functions can simply be called from within the block and will
    commit or roll back together::

        with tenant_transaction(tenant_id):
            refund = repo.create_refund_request(tenant_id, data)
            repo.link_refund_to_missing_item(tenant_id, item_id, refund["id"])

    The yielded cursor is there for statements that need a value from an earlier
    one (dict-like rows)::

        with tenant_transaction(tenant_id) as cur:
            cur.execute("UPDATE billing ... RETURNING *", params)
            billing = cur.fetchone()

    Rules:
      * Keep the block to the money-state writes. Do `log_audit`, `publish_event`
        and notifications AFTER it: `log_audit` swallows its own errors, and a
        failed statement inside a transaction aborts every statement after it.
      * Do not catch and swallow a database error inside the block for the same
        reason; let it propagate so the whole unit rolls back.
      * Reads scoped to another tenant (PLATFORM lookups) raise inside the block.
        Do them first.
      * Do not call `commit()` or `rollback()` on the connection inside the block.
      * A nested block for the same tenant joins the outer one and commits with it.
    """
    active = _active_transaction.get()
    if active is not None:
        scope, cursor = active
        if scope != tenant_id:
            raise RuntimeError(f"cannot open a {tenant_id!r} transaction inside one scoped to {scope!r}")
        yield cursor
        return

    conn = get_connection()
    token = None
    try:
        with conn.cursor() as cur:
            _set_tenant(cur, tenant_id)
            token = _active_transaction.set((tenant_id, cur))
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if token is not None:
            _active_transaction.reset(token)


def next_tenant_counter(cursor: psycopg2.extensions.cursor, tenant_id: str, name: str) -> int:
    """Atomically take the next value of a per-tenant named counter.

    Replaces the `SELECT COUNT(*) + 1` pattern, which hands the same number to
    two requests that run at the same moment. The upsert takes a row lock on the
    counter, so concurrent callers are serialised and each receives a distinct
    value. Call it inside `tenant_transaction` so a failed insert rolls the
    increment back and leaves no gap.

    Args:
        cursor: The cursor yielded by `tenant_transaction`.
        tenant_id: The tenant UUID the counter belongs to.
        name: Counter name, for example ``invoice`` or ``receipt``.

    Returns:
        The new counter value, starting at 1 for a counter that did not exist.
    """
    cursor.execute(
        """
        INSERT INTO tenant_counter (tenant_id, name, last_value)
        VALUES (%s, %s, 1)
        ON CONFLICT (tenant_id, name)
        DO UPDATE SET last_value = tenant_counter.last_value + 1
        RETURNING last_value
        """,
        (tenant_id, name),
    )
    row = cursor.fetchone()
    return int(row["last_value"])


def take_tenant_counter(tenant_id: str, name: str) -> int:
    """Take the next value of a per-tenant counter in its own transaction.

    Use when the number is needed before the row that will carry it exists and the
    two cannot share a transaction. Concurrent callers always receive distinct
    values. If whatever uses the number then fails, that number is skipped, so this
    gives uniqueness, not gap-free numbering; use `next_tenant_counter` inside the
    inserting transaction when gaps matter. Inside an open `tenant_transaction` it
    joins that transaction instead.
    """
    with tenant_transaction(tenant_id) as cur:
        return next_tenant_counter(cur, tenant_id, name)
