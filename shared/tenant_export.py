"""The record of a tenant's offboarding export (``tenant_offboarding_export``, migration 067).

Offboarding queues an export; the hourly job (``services/scheduled/offboarding_export.py``) claims and writes it;
platform admins read its status and get a short-lived link (``services/tenant_management``); the 90-day cleanup
refuses to delete a tenant until one has completed. All reads and writes are PLATFORM scope: the table is only ever
touched on the platform's behalf.
"""

import json
import re
from datetime import datetime
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant, execute_write_with_tenant_many
from shared.tenant_context import PLATFORM_TENANT_ID

#: An export that failed this many times stops being retried; a platform admin can queue a new one.
MAX_ATTEMPTS = 3

#: A ``running`` export older than this is taken to have died with its worker and is claimed again.
STALE_AFTER_MINUTES = 60

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def export_prefix(tenant_id: str) -> str:
    """Where a tenant's offboarding archives are kept: inside its own storage prefix, so they go when it goes."""
    if not _UUID.match(tenant_id):
        raise ValueError("tenant_id must be a UUID")
    return f"{tenant_id}/exports/offboarding/"


def object_key(tenant_id: str, export_id: str) -> str:
    """The archive's key for one export."""
    if not _UUID.match(export_id):
        raise ValueError("export_id must be a UUID")
    return f"{export_prefix(tenant_id)}{export_id}.zip"


def queue_export(tenant_id: str, requested_by: str | None) -> dict[str, Any] | None:
    """Queue an export for ``tenant_id``, or return ``None`` if one is already pending or running.

    Joins a surrounding ``tenant_transaction(PLATFORM_TENANT_ID)``, so offboarding and its export commit together.
    """
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        INSERT INTO tenant_offboarding_export (tenant_id, requested_by)
        VALUES (%(tenant_id)s, %(requested_by)s)
        ON CONFLICT (tenant_id) WHERE status IN ('pending', 'running') DO NOTHING
        RETURNING *
        """,
        {"tenant_id": tenant_id, "requested_by": requested_by},
    )


def latest_export(tenant_id: str) -> dict[str, Any] | None:
    """The tenant's most recent export, whatever its status."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        """
        SELECT * FROM tenant_offboarding_export
         WHERE tenant_id = %s
         ORDER BY requested_at DESC, id DESC
         LIMIT 1
        """,
        (tenant_id,),
    )
    return rows[0] if rows else None


def has_completed_export(tenant_id: str, since: datetime) -> bool:
    """Whether an export requested at or after ``since`` (the tenant's latest offboarding) has completed.

    The cleanup deletes nothing without one. An export from an earlier offboarding does not count: a tenant that was
    reactivated and offboarded again has data the old archive does not hold. Offboarding queues its export in the
    same transaction, so the two timestamps are equal.
    """
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        """
        SELECT 1 FROM tenant_offboarding_export
         WHERE tenant_id = %s AND status = 'completed' AND requested_at >= %s
         LIMIT 1
        """,
        (tenant_id, since),
    )
    return bool(rows)


def claim_next() -> dict[str, Any] | None:
    """Take the oldest export that needs doing and mark it ``running``, or return ``None``.

    Needs doing: ``pending``; ``failed`` with attempts left; or ``running`` for longer than
    ``STALE_AFTER_MINUTES`` (its worker died). ``SKIP LOCKED`` lets two workers run without taking the same export.
    """
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        UPDATE tenant_offboarding_export e
           SET status = 'running', started_at = NOW(), attempts = e.attempts + 1, updated_at = NOW()
         WHERE e.id = (
                SELECT id FROM tenant_offboarding_export
                 WHERE status = 'pending'
                    OR (status = 'failed' AND attempts < %(max_attempts)s)
                    OR (status = 'running' AND started_at < NOW() - make_interval(mins => %(stale_minutes)s))
                 ORDER BY requested_at
                 LIMIT 1
                 FOR UPDATE SKIP LOCKED
               )
        RETURNING e.*
        """,
        {"max_attempts": MAX_ATTEMPTS, "stale_minutes": STALE_AFTER_MINUTES},
    )


def mark_completed(
    export_id: str,
    *,
    key: str,
    size_bytes: int,
    sha256: str,
    row_counts: dict[str, int],
    completed_at: datetime,
) -> dict[str, Any] | None:
    """Record a written archive. Only a ``running`` export can complete."""
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        UPDATE tenant_offboarding_export
           SET status = 'completed', object_key = %(key)s, size_bytes = %(size)s, sha256 = %(sha256)s,
               row_counts = %(row_counts)s::jsonb, completed_at = %(completed_at)s, last_error = NULL,
               updated_at = NOW()
         WHERE id = %(id)s AND status = 'running'
        RETURNING *
        """,
        {
            "id": export_id,
            "key": key,
            "size": size_bytes,
            "sha256": sha256,
            "row_counts": json.dumps(row_counts),
            "completed_at": completed_at,
        },
    )


def mark_failed(export_id: str, error: str) -> dict[str, Any] | None:
    """Record a failed attempt. ``error`` is the exception's type name: never a message that could hold data."""
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        UPDATE tenant_offboarding_export
           SET status = 'failed', last_error = %(error)s, updated_at = NOW()
         WHERE id = %(id)s AND status = 'running'
        RETURNING *
        """,
        {"id": export_id, "error": error[:200]},
    )


def cancel_open_exports(tenant_id: str) -> list[dict[str, Any]]:
    """Cancel the tenant's exports that have not completed (reactivation: there is nothing to hand over)."""
    return execute_write_with_tenant_many(
        PLATFORM_TENANT_ID,
        """
        UPDATE tenant_offboarding_export
           SET status = 'cancelled', updated_at = NOW()
         WHERE tenant_id = %s AND status IN ('pending', 'running', 'failed')
        RETURNING id
        """,
        (tenant_id,),
    )


def mark_cancelled(export_id: str) -> dict[str, Any] | None:
    """Drop an export whose tenant is no longer offboarded (reactivated before it ran)."""
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        UPDATE tenant_offboarding_export
           SET status = 'cancelled', updated_at = NOW()
         WHERE id = %(id)s AND status IN ('pending', 'running', 'failed')
        RETURNING *
        """,
        {"id": export_id},
    )
