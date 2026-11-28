"""SQL for the platform admin directory (``platform_user``) and two-person approvals (``platform_approval``).

Platform scope throughout: both tables are platform-only under RLS (migration 076). Every write returns a row so a
zero-row update is visible to the caller (CLAUDE.md, ``RETURNING`` on writes).
"""

from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.tenant_context import PLATFORM_TENANT_ID

_ADMIN_COLUMNS = """
    pu.id, pu.email, pu.name, pu.role, pu.status, pu.last_seen_at, pu.disabled_at, pu.created_at, pu.updated_at,
    pu.subject, inviter.name AS invited_by_name
"""

_APPROVAL_COLUMNS = """
    pa.id, pa.action, pa.target_tenant_id, pa.target_label, pa.payload, pa.payload_hash, pa.reason, pa.status,
    pa.requested_by, requester.name AS requested_by_name, pa.requested_at,
    pa.decided_by, decider.name AS decided_by_name, pa.decided_at, pa.decision_note,
    pa.expires_at, pa.execute_after, pa.executed_at, pa.error, t.company_name AS target_tenant_name
"""

_APPROVAL_FROM = """
    FROM platform_approval pa
    JOIN platform_user requester ON requester.id = pa.requested_by
    LEFT JOIN platform_user decider ON decider.id = pa.decided_by
    LEFT JOIN tenant t ON t.id = pa.target_tenant_id
"""


# ---------------------------------------------------------------------------
# Directory
# ---------------------------------------------------------------------------


def list_platform_users() -> list[dict[str, Any]]:
    """Every platform admin, owners first, then by name."""
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        f"""
        SELECT {_ADMIN_COLUMNS}
        FROM platform_user pu
        LEFT JOIN platform_user inviter ON inviter.id = pu.invited_by
        ORDER BY CASE pu.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 WHEN 'support' THEN 2 ELSE 3 END, pu.name
        """,
    )


def get_platform_user(platform_user_id: str) -> dict[str, Any] | None:
    """One platform admin by id, or None."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        f"""
        SELECT {_ADMIN_COLUMNS}
        FROM platform_user pu
        LEFT JOIN platform_user inviter ON inviter.id = pu.invited_by
        WHERE pu.id = %(id)s
        """,
        {"id": platform_user_id},
    )
    return rows[0] if rows else None


def get_platform_user_by_email(email: str) -> dict[str, Any] | None:
    """One platform admin by email (case-insensitive), or None."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT id, status FROM platform_user WHERE lower(email) = lower(%(email)s)",
        {"email": email},
    )
    return rows[0] if rows else None


def insert_platform_user(subject: str | None, email: str, name: str, role: str, invited_by: str | None) -> dict[str, Any]:
    """Create an ``invited`` platform admin and return the row."""
    row = execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        INSERT INTO platform_user (subject, email, name, role, status, invited_by)
        VALUES (%(subject)s, %(email)s, %(name)s, %(role)s, 'invited', %(invited_by)s)
        RETURNING id
        """,
        {"subject": subject, "email": email, "name": name, "role": role, "invited_by": invited_by},
    )
    if row is None:
        raise RuntimeError("insert_platform_user returned no row")
    created = get_platform_user(str(row["id"]))
    if created is None:
        raise RuntimeError("inserted platform_user row is not readable")
    return created


def update_platform_user(platform_user_id: str, **fields: Any) -> dict[str, Any] | None:
    """Set ``role`` and/or ``status`` (stamping ``disabled_at``) on one admin; None when no row matched."""
    allowed = {"role", "status"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"update_platform_user cannot set {sorted(unknown)}")
    if not fields:
        raise ValueError("update_platform_user needs at least one field")
    params: dict[str, Any] = {"id": platform_user_id, "role": fields.get("role"), "status": fields.get("status")}
    row = execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        UPDATE platform_user
        SET role        = COALESCE(%(role)s, role),
            status      = COALESCE(%(status)s, status),
            disabled_at = CASE WHEN %(status)s = 'disabled' THEN NOW()
                               WHEN %(status)s IS NOT NULL THEN NULL
                               ELSE disabled_at END,
            updated_at  = NOW()
        WHERE id = %(id)s
        RETURNING id
        """,
        params,
    )
    return get_platform_user(str(row["id"])) if row else None


def count_active_owners() -> int:
    """How many owners can still sign in."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT COUNT(*) AS cnt FROM platform_user WHERE role = 'owner' AND status = 'active'",
    )
    return int(rows[0]["cnt"]) if rows else 0


def list_active_users_with_roles(roles: list[str]) -> list[dict[str, Any]]:
    """Active admins holding one of ``roles`` (id, email, name, role)."""
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT id, email, name, role FROM platform_user WHERE status = 'active' AND role = ANY(%(roles)s)",
        {"roles": roles},
    )


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


def insert_approval(values: dict[str, Any]) -> dict[str, Any]:
    """Create an approval request and return it with names joined."""
    row = execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        INSERT INTO platform_approval
            (action, target_tenant_id, target_label, payload, secret_payload, payload_hash, reason, status,
             requested_by, expires_at, execute_after)
        VALUES (%(action)s, %(target_tenant_id)s, %(target_label)s, %(payload)s::jsonb, %(secret_payload)s,
                %(payload_hash)s, %(reason)s, %(status)s, %(requested_by)s, %(expires_at)s, %(execute_after)s)
        RETURNING id
        """,
        values,
    )
    if row is None:
        raise RuntimeError("insert_approval returned no row")
    created = get_approval(str(row["id"]))
    if created is None:
        raise RuntimeError("inserted platform_approval row is not readable")
    return created


def get_approval(approval_id: str, *, with_secret: bool = False) -> dict[str, Any] | None:
    """One approval by id; ``with_secret`` adds the encrypted ``secret_payload`` (for execution only)."""
    secret = ", pa.secret_payload" if with_secret else ""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        f"SELECT {_APPROVAL_COLUMNS}{secret} {_APPROVAL_FROM} WHERE pa.id = %(id)s",
        {"id": approval_id},
    )
    return rows[0] if rows else None


def find_open_approval(action: str, target_label: str) -> dict[str, Any] | None:
    """The pending or scheduled request for this action and target, if one is open."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        f"""
        SELECT {_APPROVAL_COLUMNS} {_APPROVAL_FROM}
        WHERE pa.action = %(action)s AND pa.target_label = %(target_label)s AND pa.status IN ('pending', 'scheduled')
        """,
        {"action": action, "target_label": target_label},
    )
    return rows[0] if rows else None


def list_approvals(status: str | None, limit: int) -> list[dict[str, Any]]:
    """Approvals newest first; ``status='open'`` means pending or scheduled."""
    where = ""
    params: dict[str, Any] = {"limit": limit}
    if status == "open":
        where = "WHERE pa.status IN ('pending', 'scheduled')"
    elif status:
        where = "WHERE pa.status = %(status)s"
        params["status"] = status
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        f"SELECT {_APPROVAL_COLUMNS} {_APPROVAL_FROM} {where} ORDER BY pa.requested_at DESC LIMIT %(limit)s",
        params,
    )


def transition_approval(approval_id: str, from_statuses: list[str], to_status: str, **fields: Any) -> dict[str, Any] | None:
    """Move an approval from one of ``from_statuses`` to ``to_status``; None when it was not in one of them.

    The status guard in the WHERE clause is what stops two admins deciding the same request, or a request being
    executed twice: only one UPDATE can match.
    """
    allowed = {"decided_by", "decision_note", "error", "executed", "decided"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"transition_approval cannot set {sorted(unknown)}")
    row = execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        UPDATE platform_approval
        SET status        = %(to_status)s,
            decided_by    = COALESCE(%(decided_by)s, decided_by),
            decision_note = COALESCE(%(decision_note)s, decision_note),
            decided_at    = CASE WHEN %(decided)s THEN NOW() ELSE decided_at END,
            executed_at   = CASE WHEN %(executed)s THEN NOW() ELSE executed_at END,
            error         = %(error)s
        WHERE id = %(id)s AND status = ANY(%(from_statuses)s)
        RETURNING id
        """,
        {
            "id": approval_id,
            "from_statuses": from_statuses,
            "to_status": to_status,
            "decided_by": fields.get("decided_by"),
            "decision_note": fields.get("decision_note"),
            "decided": bool(fields.get("decided")),
            "executed": bool(fields.get("executed")),
            "error": fields.get("error"),
        },
    )
    return get_approval(str(row["id"])) if row else None


def list_due_scheduled_approvals() -> list[dict[str, Any]]:
    """Scheduled requests whose waiting period is over (single-admin offboarding, decision D4)."""
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        f"""
        SELECT {_APPROVAL_COLUMNS} {_APPROVAL_FROM}
        WHERE pa.status = 'scheduled' AND pa.execute_after <= NOW()
        ORDER BY pa.execute_after
        """,
    )


def list_expired_pending_approvals() -> list[dict[str, Any]]:
    """Pending requests nobody decided in time."""
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        f"""
        SELECT {_APPROVAL_COLUMNS} {_APPROVAL_FROM}
        WHERE pa.status = 'pending' AND pa.expires_at <= NOW()
        """,
    )
