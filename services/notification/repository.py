"""Database access layer for the notification_log table.

PII policy: phone numbers stored as last-4 digits masked (e.g. ****6789);
email addresses stored as first-2 chars + *** + @domain (e.g. ng***@gmail.com).
Neither form can be used to reconstruct the original — see 00_CROSS_CUTTING_STANDARDS.md §6.
"""

import logging
import re
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.pagination import build_paginated_query, extract_page

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PII masking helpers
# ---------------------------------------------------------------------------


def mask_phone(phone: str) -> str:
    """Return a masked phone: last 4 digits visible, rest replaced with ****."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 4:
        return "****"
    return f"****{digits[-4:]}"


def mask_email(email: str) -> str:
    """Return a masked email: first 2 chars + *** + @domain."""
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    prefix = local[:2] if len(local) >= 2 else local
    return f"{prefix}***@{domain}"


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def insert_log(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Insert a new notification_log row and return it."""
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO notification_log (
            tenant_id, event_type, channel, recipient_masked,
            recipient_name, customer_id, status, provider,
            provider_message_id, gateway_response, error_detail,
            retry_of, template_data, message_body, locale
        ) VALUES (
            %(tenant_id)s, %(event_type)s, %(channel)s, %(recipient_masked)s,
            %(recipient_name)s, %(customer_id)s, %(status)s, %(provider)s,
            %(provider_message_id)s, %(gateway_response)s::jsonb, %(error_detail)s,
            %(retry_of)s, %(template_data)s::jsonb, %(message_body)s, %(locale)s
        ) RETURNING *
        """,
        {**data, "message_body": data.get("message_body"), "locale": data.get("locale")},
    )


def mark_sent(
    tenant_id: str,
    log_id: str,
    provider: str,
    provider_message_id: str,
    gateway_response: str,
) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE notification_log
        SET status = 'sent',
            provider = %(provider)s,
            provider_message_id = %(provider_message_id)s,
            gateway_response = %(gateway_response)s::jsonb,
            updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "id": log_id,
            "provider": provider,
            "provider_message_id": provider_message_id,
            "gateway_response": gateway_response,
        },
    )


def mark_failed(
    tenant_id: str,
    log_id: str,
    error_detail: str,
    gateway_response: str | None = None,
) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE notification_log
        SET status = 'failed',
            error_detail = %(error_detail)s,
            gateway_response = COALESCE(%(gateway_response)s::jsonb, gateway_response),
            updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "id": log_id,
            "error_detail": error_detail,
            "gateway_response": gateway_response,
        },
    )


def update_delivery_status(
    provider_message_id: str,
    new_status: str,
    gateway_response: str | None = None,
) -> None:
    """Update delivery status by provider_message_id. No-op if not found.

    Uses PLATFORM scope because this is called from the webhook handler which
    doesn't carry tenant context — notification_log RLS is set, so we need
    a platform-scope bypass to update cross-tenant rows by provider_message_id.
    """
    from shared.tenant_context import PLATFORM_TENANT_ID

    execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        UPDATE notification_log
        SET status = %(status)s,
            gateway_response = COALESCE(%(gateway_response)s::jsonb, gateway_response),
            updated_at = NOW()
        WHERE provider_message_id = %(provider_message_id)s
        RETURNING id
        """,
        {
            "provider_message_id": provider_message_id,
            "status": new_status,
            "gateway_response": gateway_response,
        },
    )


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def get_log_by_id(tenant_id: str, log_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM notification_log WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, log_id),
    )
    return rows[0] if rows else None


def list_logs(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int = 20,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    conditions = ["tenant_id = %(tenant_id)s"]
    extra: dict[str, Any] = {"tenant_id": tenant_id}

    for col in ("channel", "status", "event_type"):
        if filters.get(col):
            conditions.append(f"{col} = %({col})s")
            extra[col] = filters[col]

    if filters.get("customer_id"):
        conditions.append("customer_id = %(customer_id)s")
        extra["customer_id"] = filters["customer_id"]
    if filters.get("created_after"):
        conditions.append("created_at >= %(created_after)s")
        extra["created_after"] = filters["created_after"]
    if filters.get("created_before"):
        conditions.append("created_at <= %(created_before)s")
        extra["created_before"] = filters["created_before"]

    base = f"SELECT * FROM notification_log WHERE {' AND '.join(conditions)}"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def get_log_for_fallback(tenant_id: str, log_id: str) -> dict[str, Any] | None:
    """Fetch the fields an SMS fallback needs from a WhatsApp notification_log row."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT id, event_type, customer_id, recipient_name, template_data, locale
        FROM notification_log
        WHERE tenant_id = %s AND id = %s
        LIMIT 1
        """,
        (tenant_id, log_id),
    )
    return rows[0] if rows else None


def fallback_already_sent(tenant_id: str, whatsapp_log_id: str) -> bool:
    """True when an SMS has already been queued for this WhatsApp log row.

    Both the immediate-rejection path and the delivery-status webhook can fire
    for the same message, so without this a customer with no WhatsApp account
    would receive two texts.
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT 1 FROM notification_log
        WHERE tenant_id = %s AND channel = 'sms' AND retry_of = %s
        LIMIT 1
        """,
        (tenant_id, whatsapp_log_id),
    )
    return bool(rows)


def get_customer_phone(tenant_id: str, customer_id: str) -> str | None:
    """Read a customer's phone for an SMS fallback.

    notification_log stores only a masked contact by design (no PII in logs),
    so the real number is read back from the customer record instead.
    """
    rows = execute_with_tenant(
        tenant_id,
        "SELECT phone FROM customer WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, customer_id),
    )
    return (rows[0].get("phone") if rows else None) or None


# ---------------------------------------------------------------------------
# Staff notifications (in-app bell — migration 046)
# ---------------------------------------------------------------------------

# "Visible to me": targeted directly at me, or broadcast to my role (with no
# specific target_user_id), or broadcast to everyone (both columns NULL).
_STAFF_NOTIFICATION_VISIBILITY = """
    (sn.target_user_id = %(user_id)s)
    OR (sn.target_user_id IS NULL AND sn.target_role = %(role)s)
    OR (sn.target_user_id IS NULL AND sn.target_role IS NULL)
"""


def list_staff_notifications(
    tenant_id: str,
    user_id: str,
    role: str,
    limit: int = 20,
    cursor: dict[str, Any] | None = None,
    unread_only: bool = False,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Notifications visible to this user, newest first, with `is_read`
    resolved per-viewer via a LEFT JOIN against staff_notification_read —
    a role-broadcast notification can be read by one recipient without
    affecting what any other recipient sees."""
    from shared.pagination import build_paginated_query, extract_page

    unread_clause = " AND r.notification_id IS NULL" if unread_only else ""
    base = f"""
        SELECT sn.*, (r.notification_id IS NOT NULL) AS is_read
        FROM staff_notification sn
        LEFT JOIN staff_notification_read r
            ON r.notification_id = sn.id AND r.user_id = %(user_id)s AND r.tenant_id = sn.tenant_id
        WHERE sn.tenant_id = %(tenant_id)s AND ({_STAFF_NOTIFICATION_VISIBILITY})
            AND r.dismissed_at IS NULL{unread_clause}
    """
    query, params = build_paginated_query(base, cursor, limit, sort_field="sn.created_at", sort_direction="DESC")
    params.update({"tenant_id": tenant_id, "user_id": user_id, "role": role})
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def count_unread_staff_notifications(tenant_id: str, user_id: str, role: str) -> int:
    rows = execute_with_tenant(
        tenant_id,
        f"""
        SELECT COUNT(*) AS cnt
        FROM staff_notification sn
        LEFT JOIN staff_notification_read r
            ON r.notification_id = sn.id AND r.user_id = %(user_id)s AND r.tenant_id = sn.tenant_id
        WHERE sn.tenant_id = %(tenant_id)s AND ({_STAFF_NOTIFICATION_VISIBILITY})
            AND r.notification_id IS NULL
        """,
        {"tenant_id": tenant_id, "user_id": user_id, "role": role},
    )
    return int(rows[0]["cnt"]) if rows else 0


def create_staff_notification(
    tenant_id: str,
    event_type: str,
    entity_type: str,
    title: str,
    body: str | None = None,
    entity_id: str | None = None,
    target_role: str | None = None,
    target_user_id: str | None = None,
    announcement_group_id: str | None = None,
    banner_active: bool = False,
) -> dict[str, Any] | None:
    """Direct, error-propagating insert for a staff_notification row.

    Distinct from shared.staff_notifications.notify_staff(), which is
    deliberately silent-safe for side-effect notifications fired alongside
    an unrelated business action (a failed write there must never fail the
    action that triggered it). An announcement IS the whole action — the
    person composing it needs a real success/failure response, not a silent
    no-op — so this raises on failure like any other write in this codebase.

    `announcement_group_id`/`banner_active` are only ever set for
    entity_type="announcement" rows — see migration 049.
    """
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO staff_notification (
            tenant_id, target_role, target_user_id, event_type,
            entity_type, entity_id, title, body, announcement_group_id, banner_active
        ) VALUES (
            %(tenant_id)s, %(target_role)s, %(target_user_id)s, %(event_type)s,
            %(entity_type)s, %(entity_id)s, %(title)s, %(body)s,
            %(announcement_group_id)s, %(banner_active)s
        )
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "target_role": target_role,
            "target_user_id": target_user_id,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "title": title,
            "body": body,
            "announcement_group_id": announcement_group_id,
            "banner_active": banner_active,
        },
    )


def get_staff_notification_by_id(tenant_id: str, notification_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM staff_notification WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, notification_id),
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Announcement banners (migration 049)
# ---------------------------------------------------------------------------


def deactivate_active_banners_for_roles(tenant_id: str, target_roles: list[str]) -> int:
    """Turns off every currently-active banner targeting any of these roles
    (a plain list — `= ANY(%(target_roles)s)`, never string-interpolated).
    Called immediately before inserting a new banner-eligible announcement
    group so "only one can be visible per time" holds for that audience."""
    from shared.db import execute_write_with_tenant_many

    rows = execute_write_with_tenant_many(
        tenant_id,
        """
        UPDATE staff_notification
        SET banner_active = FALSE
        WHERE tenant_id = %(tenant_id)s AND target_role = ANY(%(target_roles)s) AND banner_active = TRUE
        RETURNING id
        """,
        {"tenant_id": tenant_id, "target_roles": target_roles},
    )
    return len(rows)


def get_active_banner(tenant_id: str, user_id: str, role: str) -> dict[str, Any] | None:
    """The single announcement (if any) this viewer should currently see as
    a page banner — same visibility scoping as the bell feed."""
    rows = execute_with_tenant(
        tenant_id,
        f"""
        SELECT sn.* FROM staff_notification sn
        WHERE sn.tenant_id = %(tenant_id)s AND sn.event_type = 'announcement' AND sn.banner_active = TRUE
            AND ({_STAFF_NOTIFICATION_VISIBILITY})
        ORDER BY sn.created_at DESC
        LIMIT 1
        """,
        {"tenant_id": tenant_id, "user_id": user_id, "role": role},
    )
    return rows[0] if rows else None


def list_announcement_groups(tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """One row per announcement *send* (not per targeted role) for the
    tenant_admin management list — an "all_staff" send fans out to 4
    staff_notification rows sharing one announcement_group_id; this
    collapses them back to one entry, newest send first."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT DISTINCT ON (announcement_group_id)
            id, announcement_group_id, title, body, target_role, banner_active, created_at
        FROM staff_notification
        WHERE tenant_id = %(tenant_id)s AND event_type = 'announcement'
            AND announcement_group_id IS NOT NULL
        ORDER BY announcement_group_id, created_at DESC
        """,
        {"tenant_id": tenant_id},
    )
    return sorted(rows, key=lambda r: r["created_at"], reverse=True)[:limit]


def set_banner_active_for_group(tenant_id: str, announcement_group_id: str, active: bool) -> int:
    """Flips banner_active for every row in one announcement's group at
    once, so enabling/disabling an "all_staff" send affects all 4 targeted
    roles together rather than just the one row an id happened to name."""
    from shared.db import execute_write_with_tenant_many

    rows = execute_write_with_tenant_many(
        tenant_id,
        """
        UPDATE staff_notification
        SET banner_active = %(active)s
        WHERE tenant_id = %(tenant_id)s AND announcement_group_id = %(group_id)s
        RETURNING id
        """,
        {"tenant_id": tenant_id, "group_id": announcement_group_id, "active": active},
    )
    return len(rows)


def get_announcement_group_target_roles(tenant_id: str, announcement_group_id: str) -> list[str]:
    """The distinct target_role values in one announcement's group — used to
    scope the "only one active per audience" dedup when re-activating a
    historical announcement."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT DISTINCT target_role FROM staff_notification
        WHERE tenant_id = %(tenant_id)s AND announcement_group_id = %(group_id)s AND target_role IS NOT NULL
        """,
        {"tenant_id": tenant_id, "group_id": announcement_group_id},
    )
    return [r["target_role"] for r in rows]


def mark_staff_notification_read(tenant_id: str, notification_id: str, user_id: str) -> dict[str, Any] | None:
    """Idempotent — re-marking an already-read notification just returns the
    existing read row rather than erroring."""
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO staff_notification_read (tenant_id, notification_id, user_id, read_at)
        VALUES (%(tenant_id)s, %(notification_id)s, %(user_id)s, NOW())
        ON CONFLICT (notification_id, user_id) DO UPDATE SET read_at = staff_notification_read.read_at
        RETURNING *
        """,
        {"tenant_id": tenant_id, "notification_id": notification_id, "user_id": user_id},
    )


def mark_all_staff_notifications_read(tenant_id: str, user_id: str, role: str) -> int:
    """Marks every currently-unread notification visible to this user as
    read. Returns the number of rows newly marked."""
    from shared.db import execute_write_with_tenant_many

    rows = execute_write_with_tenant_many(
        tenant_id,
        f"""
        INSERT INTO staff_notification_read (tenant_id, notification_id, user_id, read_at)
        SELECT sn.tenant_id, sn.id, %(user_id)s, NOW()
        FROM staff_notification sn
        LEFT JOIN staff_notification_read r
            ON r.notification_id = sn.id AND r.user_id = %(user_id)s AND r.tenant_id = sn.tenant_id
        WHERE sn.tenant_id = %(tenant_id)s AND ({_STAFF_NOTIFICATION_VISIBILITY})
            AND r.notification_id IS NULL
        ON CONFLICT (notification_id, user_id) DO NOTHING
        RETURNING notification_id
        """,
        {"tenant_id": tenant_id, "user_id": user_id, "role": role},
    )
    return len(rows)


def mark_staff_notification_dismissed(tenant_id: str, notification_id: str, user_id: str) -> dict[str, Any] | None:
    """Clear (dismiss) one notification for this viewer only — removes it
    from their own list without touching any other recipient's copy of a
    role-broadcast notification. Implies read: `read_at` is set alongside
    `dismissed_at` if it wasn't already, since a cleared notification was by
    definition seen. Idempotent, same as mark_staff_notification_read."""
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO staff_notification_read (tenant_id, notification_id, user_id, read_at, dismissed_at)
        VALUES (%(tenant_id)s, %(notification_id)s, %(user_id)s, NOW(), NOW())
        ON CONFLICT (notification_id, user_id) DO UPDATE
            SET dismissed_at = COALESCE(staff_notification_read.dismissed_at, NOW()),
                read_at = COALESCE(staff_notification_read.read_at, NOW())
        RETURNING *
        """,
        {"tenant_id": tenant_id, "notification_id": notification_id, "user_id": user_id},
    )


def dismiss_all_staff_notifications(tenant_id: str, user_id: str, role: str) -> int:
    """Clears every notification currently visible to this user (that isn't
    already cleared). Returns the number of rows newly dismissed."""
    from shared.db import execute_write_with_tenant_many

    rows = execute_write_with_tenant_many(
        tenant_id,
        f"""
        INSERT INTO staff_notification_read (tenant_id, notification_id, user_id, read_at, dismissed_at)
        SELECT sn.tenant_id, sn.id, %(user_id)s, NOW(), NOW()
        FROM staff_notification sn
        LEFT JOIN staff_notification_read r
            ON r.notification_id = sn.id AND r.user_id = %(user_id)s AND r.tenant_id = sn.tenant_id
        WHERE sn.tenant_id = %(tenant_id)s AND ({_STAFF_NOTIFICATION_VISIBILITY})
            AND r.dismissed_at IS NULL
        ON CONFLICT (notification_id, user_id) DO UPDATE
            SET dismissed_at = COALESCE(staff_notification_read.dismissed_at, NOW()),
                read_at = COALESCE(staff_notification_read.read_at, NOW())
        RETURNING notification_id
        """,
        {"tenant_id": tenant_id, "user_id": user_id, "role": role},
    )
    return len(rows)


# ---------------------------------------------------------------------------
# Announcement requests (staff-composed customer announcements pending
# tenant_admin approval — migration 048)
# ---------------------------------------------------------------------------


def create_announcement_request(
    tenant_id: str,
    title: str,
    body: str | None,
    audience: str,
    requested_by: str,
) -> dict[str, Any] | None:
    """A nigeria_office_staff-composed announcement, held for tenant_admin
    review before any `staff_notification` row is created — so a compromised
    staff account cannot broadcast misinformation straight to customers."""
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO announcement_request (tenant_id, title, body, audience, requested_by)
        VALUES (%(tenant_id)s, %(title)s, %(body)s, %(audience)s, %(requested_by)s)
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "title": title,
            "body": body,
            "audience": audience,
            "requested_by": requested_by,
        },
    )


def get_announcement_request_by_id(tenant_id: str, request_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM announcement_request WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, request_id),
    )
    return rows[0] if rows else None


def list_pending_announcement_requests(
    tenant_id: str,
    limit: int = 20,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """The tenant_admin review queue, oldest-first (submitted-earliest is
    reviewed first, same triage order as every other approval queue in this
    codebase)."""
    base = """
        SELECT * FROM announcement_request
        WHERE tenant_id = %(tenant_id)s AND status = 'pending'
    """
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at", sort_direction="ASC")
    params["tenant_id"] = tenant_id
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def mark_announcement_request_reviewed(
    tenant_id: str,
    request_id: str,
    status: str,
    reviewed_by: str,
    rejection_reason: str | None = None,
) -> dict[str, Any] | None:
    """Transitions a pending request to approved/rejected — the `status =
    'pending'` guard in the WHERE clause makes double-review impossible: a
    second approve/reject call on an already-reviewed row matches zero rows
    and returns None, which the service layer turns into a 409."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE announcement_request
        SET status = %(status)s, reviewed_by = %(reviewed_by)s, reviewed_at = NOW(),
            rejection_reason = %(rejection_reason)s
        WHERE tenant_id = %(tenant_id)s AND id = %(request_id)s AND status = 'pending'
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "request_id": request_id,
            "status": status,
            "reviewed_by": reviewed_by,
            "rejection_reason": rejection_reason,
        },
    )


def list_my_announcement_requests(tenant_id: str, requested_by: str) -> list[dict[str, Any]]:
    """A staff member's own submissions, every status — the dedicated
    Announcements page's "My announcements" section, so a submitter can see
    a rejection reason or track a still-pending request without waiting on
    a bell notification."""
    return execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM announcement_request
        WHERE tenant_id = %(tenant_id)s AND requested_by = %(requested_by)s
        ORDER BY created_at DESC
        """,
        {"tenant_id": tenant_id, "requested_by": requested_by},
    )


def update_announcement_request(
    tenant_id: str,
    request_id: str,
    requested_by: str,
    title: str,
    body: str | None,
) -> dict[str, Any] | None:
    """Edits a still-pending request's title/body — scoped to the original
    requester and to `status = 'pending'` so a request already reviewed (or
    someone else's) can't be edited out from under a reviewer."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE announcement_request
        SET title = %(title)s, body = %(body)s
        WHERE tenant_id = %(tenant_id)s AND id = %(request_id)s
            AND requested_by = %(requested_by)s AND status = 'pending'
        RETURNING *
        """,
        {"tenant_id": tenant_id, "request_id": request_id, "requested_by": requested_by, "title": title, "body": body},
    )


def delete_announcement_request(tenant_id: str, request_id: str, requested_by: str) -> int:
    """Withdraws a still-pending request — same ownership + status guard as
    update_announcement_request. Returns the number of rows deleted (0 or 1)."""
    from shared.db import execute_write_with_tenant_many

    rows = execute_write_with_tenant_many(
        tenant_id,
        """
        DELETE FROM announcement_request
        WHERE tenant_id = %(tenant_id)s AND id = %(request_id)s
            AND requested_by = %(requested_by)s AND status = 'pending'
        RETURNING id
        """,
        {"tenant_id": tenant_id, "request_id": request_id, "requested_by": requested_by},
    )
    return len(rows)


def update_announcement_group(tenant_id: str, announcement_group_id: str, title: str, body: str | None) -> int:
    """Edits every row in an already-sent announcement's group at once (e.g.
    an all_staff send's 4 role rows) — tenant_admin only, enforced in the
    service/handler layer. Returns the number of rows updated."""
    from shared.db import execute_write_with_tenant_many

    rows = execute_write_with_tenant_many(
        tenant_id,
        """
        UPDATE staff_notification
        SET title = %(title)s, body = %(body)s
        WHERE tenant_id = %(tenant_id)s AND announcement_group_id = %(group_id)s
        RETURNING id
        """,
        {"tenant_id": tenant_id, "group_id": announcement_group_id, "title": title, "body": body},
    )
    return len(rows)


def delete_announcement_group(tenant_id: str, announcement_group_id: str) -> int:
    """Permanently removes every row in an announcement's group — unlike
    deactivating a banner, this also removes it from every recipient's bell
    history (staff_notification_read cascades via its FK). tenant_admin
    only. Returns the number of rows deleted."""
    from shared.db import execute_write_with_tenant_many

    rows = execute_write_with_tenant_many(
        tenant_id,
        """
        DELETE FROM staff_notification
        WHERE tenant_id = %(tenant_id)s AND announcement_group_id = %(group_id)s
        RETURNING id
        """,
        {"tenant_id": tenant_id, "group_id": announcement_group_id},
    )
    return len(rows)


def get_log_by_provider_message_id(provider_message_id: str) -> dict[str, Any] | None:
    """Find a notification_log row by the provider's message id.

    Platform-scoped: Meta's delivery webhook is unauthenticated and carries no
    tenant, so the row must be located before its tenant is known — the same
    bypass update_delivery_status already uses.
    """
    from shared.tenant_context import PLATFORM_TENANT_ID

    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        """
        SELECT id, tenant_id FROM notification_log
        WHERE provider_message_id = %s
        LIMIT 1
        """,
        (provider_message_id,),
    )
    return rows[0] if rows else None
