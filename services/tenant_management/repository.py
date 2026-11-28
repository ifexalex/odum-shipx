"""Database access layer for the Tenant Management service.

Pure SQL — no business logic, no Cognito calls.
All queries use parameterized statements (%s / %(name)s) — never f-strings.

Scope rules:
  - PLATFORM scope (PLATFORM_TENANT_ID): tenant table reads, dashboard, platform audit
  - Tenant scope (tenant_id): tenant_user, customer, charge_type, tenant_config
"""

import json
import logging
from typing import Any

from shared.db import execute_transaction, execute_with_tenant, execute_write_with_tenant
from shared.platform_audit import (
    insert_platform_audit as insert_platform_audit,  # re-exported: callers use repo.insert_platform_audit
)
from shared.seats import staff_seat_condition
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Allowed field sets for dynamic UPDATE (SQL-injection prevention §2.2)
# ---------------------------------------------------------------------------

_TENANT_UPDATE_FIELDS = frozenset(
    {
        "company_name",
        "primary_contact_email",
        "primary_contact_phone",
        "origin_country",
        "destination_country",
        "subscription_tier",
        "branding_config",
        "notification_preferences",
    }
)

_USER_UPDATE_FIELDS = frozenset(
    {
        "full_name",
        "locale",
    }
)
# NOTE: "role" is deliberately excluded — primary role changes must go through
# set_user_roles() (which also mirrors into tenant_user.role transactionally)
# so identity-group membership stays in sync via IdentityProvider.sync_user_groups().
# A bare `role` key here would let a role change bypass that sync.

_SUPPORTED_LOCALES: frozenset[str] = frozenset({"en", "zh"})

_CUSTOMER_UPDATE_FIELDS = frozenset(
    {
        "name",
        "phone",
        "email",
        "whatsapp",
        "address",
        "delivery_address",
        "contract_details",
        "notification_consent",  # GDPR Art. 6 — channel opt-in list (e.g. ['sms', 'email'])
        "consent_given_at",  # Timestamp of explicit consent
        "locale",  # Notification language (migration 029) — read by tracking→notification flow
    }
)
# Internal-only fields never writable directly from raw HTTP API payloads:
#   - user_id: linked only by invite acceptance / self-registration
_CUSTOMER_INTERNAL_UPDATE_FIELDS = _CUSTOMER_UPDATE_FIELDS | frozenset({"user_id"})

_CHARGE_TYPE_UPDATE_FIELDS = frozenset(
    {
        "name",
        "description",
        "default_amount_ngn",
        "is_active",
    }
)

_WAREHOUSE_UPDATE_FIELDS = frozenset(
    {
        "name",
        "address",
        "city",
        "state",
        "phone",
        "is_default",
        "is_active",
    }
)

# Aggregates every assigned role for a tenant_user into a `roles` array
# column, falling back to the primary `role` column for rows without any
# tenant_user_role entries (defensive — the migration 039 backfill should
# make that impossible, but a fallback here costs nothing).
_ROLES_AGG_SELECT = """
    COALESCE(
        (SELECT array_agg(tur.role ORDER BY tur.role)
         FROM tenant_user_role tur
         WHERE tur.tenant_user_id = tu.id AND tur.tenant_id = tu.tenant_id),
        ARRAY[tu.role]
    ) AS roles
"""


def _build_set_clause(updates: dict[str, Any], allowed: frozenset[str]) -> tuple[str, dict[str, Any]]:
    """Build a safe SET clause from an updates dict filtered by an allowlist.

    Returns (set_clause_string, filtered_params_dict).
    """
    filtered = {k: v for k, v in updates.items() if k in allowed and v is not None}
    if not filtered:
        raise ValueError("No valid update fields provided")
    set_clause = ", ".join(f"{k} = %({k})s" for k in filtered)
    return set_clause, filtered


# ---------------------------------------------------------------------------
# Tenant operations — PLATFORM scope (bypass RLS)
# ---------------------------------------------------------------------------


def create_tenant(data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        INSERT INTO tenant (
            company_name, primary_contact_email, primary_contact_phone,
            origin_country, destination_country, subscription_tier, status, slug
        ) VALUES (
            %(company_name)s, %(primary_contact_email)s, %(primary_contact_phone)s,
            %(origin_country)s, %(destination_country)s, %(subscription_tier)s, 'active', %(slug)s
        ) RETURNING *
        """,
        data,
    )


def get_tenant_by_slug(slug: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT * FROM tenant WHERE slug = %s LIMIT 1",
        (slug,),
    )
    return rows[0] if rows else None


def get_tenant_by_custom_domain(custom_domain: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT * FROM tenant WHERE custom_domain = %s LIMIT 1",
        (custom_domain,),
    )
    return rows[0] if rows else None


def get_tenant_by_id(tenant_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT * FROM tenant WHERE id = %s LIMIT 1",
        (tenant_id,),
    )
    return rows[0] if rows else None


def _like_pattern(text: str) -> str:
    """``%text%`` for ``ILIKE ... ESCAPE '\\'``, with the user's own ``%``, ``_`` and ``\\`` matched literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _tenant_list_filters(status: str | None, tier: str | None, q: str | None) -> tuple[str, dict[str, Any]]:
    """WHERE conditions (on alias ``t``) and their parameters for the platform tenant list and its count."""
    conditions = ""
    params: dict[str, Any] = {}
    if status:
        conditions += " AND t.status = %(status)s"
        params["status"] = status
    if tier:
        conditions += " AND t.subscription_tier = %(tier)s"
        params["tier"] = tier
    if q:
        conditions += (
            " AND (t.company_name ILIKE %(q)s ESCAPE '\\' OR t.slug ILIKE %(q)s ESCAPE '\\'"
            " OR t.primary_contact_email ILIKE %(q)s ESCAPE '\\' OR t.id::text ILIKE %(q)s ESCAPE '\\')"
        )
        params["q"] = _like_pattern(q)
    return conditions, params


def list_tenants(
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
    status: str | None = None,
    tier: str | None = None,
    q: str | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool, int]:
    """One page of tenants, newest first, with each tenant's staff-seat count.

    Returns:
        ``(page, next_cursor, has_more, total_count)``; ``total_count`` counts every tenant matching the filters.
    """
    from shared.pagination import build_paginated_query, extract_page

    conditions, extra = _tenant_list_filters(status, tier, q)
    # user_count uses the same seat rule as the quota check (shared.seats), so "users x/limit" on the platform list
    # matches what the tenant sees on its own plan page (audit PA-03).
    inner = f"""
        SELECT t.*, u.user_count
        FROM tenant t
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS user_count
            FROM tenant_user tu
            WHERE tu.tenant_id = t.id AND {staff_seat_condition("tu")}
        ) u ON TRUE
        WHERE 1=1{conditions}
    """
    # Wrapped so the pagination cursor compares unambiguous outer columns.
    base = f"SELECT * FROM ({inner}) AS paged WHERE 1=1"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(PLATFORM_TENANT_ID, query, params)
    page, next_cursor, has_more = extract_page(rows, limit)

    count_rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        f"SELECT COUNT(*) AS cnt FROM tenant t WHERE 1=1{conditions}",
        extra,
    )
    total = int(count_rows[0]["cnt"]) if count_rows else 0
    return page, next_cursor, has_more, total


def update_tenant(tenant_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    prepared = dict(updates)
    for json_col in ("branding_config", "notification_preferences"):
        if json_col in prepared and isinstance(prepared[json_col], (dict, list)):
            prepared[json_col] = json.dumps(prepared[json_col])
    set_clause, params = _build_set_clause(prepared, _TENANT_UPDATE_FIELDS)
    params["updated_at"] = "NOW()"
    params["id"] = tenant_id
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        f"UPDATE tenant SET {set_clause}, updated_at = NOW() WHERE id = %(id)s RETURNING *",
        params,
    )


def count_non_offboarded_tenants() -> int:
    """Count tenants that are not offboarded (used to enforce platform max_tenants)."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT COUNT(*)::int AS cnt FROM tenant WHERE status <> 'offboarded'",
    )
    return int(rows[0]["cnt"]) if rows else 0


def set_tenant_status(tenant_id: str, status: str) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        UPDATE tenant
        SET   status                = %(status)s,
              updated_at            = NOW(),
              offboarded_at         = CASE WHEN %(status)s = 'offboarded'
                                          THEN NOW() ELSE offboarded_at END,
              deletion_scheduled_at = CASE WHEN %(status)s = 'offboarded'
                                          THEN NOW() + INTERVAL '90 days'
                                          ELSE deletion_scheduled_at END
        WHERE id = %(id)s
        RETURNING *
        """,
        {"status": status, "id": tenant_id},
    )


def reactivate_tenant(tenant_id: str) -> dict[str, Any] | None:
    """Set tenant back to active after offboarding.

    Clears deletion_scheduled_at (purge no longer applies) and stamps
    reactivated_at for GDPR audit — marks the boundary of the new agreement.
    """
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        UPDATE tenant
        SET   status                = 'active',
              reactivated_at        = NOW(),
              updated_at            = NOW(),
              deletion_scheduled_at = NULL
        WHERE id = %(id)s
        RETURNING *
        """,
        {"id": tenant_id},
    )


# ---------------------------------------------------------------------------
# Tenant config — tenant RLS scope
# ---------------------------------------------------------------------------


def get_all_configs(tenant_id: str) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        "SELECT config_key, config_value, updated_at FROM tenant_config WHERE tenant_id = %s",
        (tenant_id,),
    )


def upsert_config(tenant_id: str, key: str, value: dict[str, Any], updated_by: str | None = None) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO tenant_config (tenant_id, config_key, config_value, updated_by)
        VALUES (%(tenant_id)s, %(key)s, %(value)s::jsonb, %(updated_by)s)
        ON CONFLICT (tenant_id, config_key)
        DO UPDATE SET config_value = EXCLUDED.config_value,
                      updated_by   = EXCLUDED.updated_by,
                      updated_at   = NOW()
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "key": key,
            "value": json.dumps(value),
            "updated_by": updated_by,
        },
    )


def delete_config(tenant_id: str, key: str) -> dict[str, Any] | None:
    """Remove a tenant_config row entirely (e.g. unconfiguring Paystack)."""
    return execute_write_with_tenant(
        tenant_id,
        "DELETE FROM tenant_config WHERE tenant_id = %(tenant_id)s AND config_key = %(key)s RETURNING *",
        {"tenant_id": tenant_id, "key": key},
    )


# ---------------------------------------------------------------------------
# Tenant user operations — tenant RLS scope
# ---------------------------------------------------------------------------


def create_tenant_user(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    # id is set explicitly to cognito_sub (always a UUID) rather than left to
    # gen_random_uuid() — every created_by/approved_by/rejected_by FK points
    # at tenant_user(id), and shared/auth.py's TenantContext.user_id is the
    # raw Cognito sub straight off the JWT, with no separate resolution step.
    # If id != cognito_sub, every write by a real (non-seeded) user 500s with
    # an FK violation. customer.user_id is also set to tenant_user.id
    # (see link_customer_user) so this keeps that chain consistent too.
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO tenant_user (
            id, tenant_id, cognito_sub, email, full_name, role, status, created_by
        ) VALUES (
            %(cognito_sub)s, %(tenant_id)s, %(cognito_sub)s, %(email)s, %(full_name)s,
            %(role)s, 'active', %(created_by)s
        ) RETURNING *
        """,
        data,
    )


def get_user_by_id(tenant_id: str, user_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        f"SELECT tu.*, {_ROLES_AGG_SELECT} FROM tenant_user tu WHERE tu.tenant_id = %s AND tu.id = %s LIMIT 1",
        (tenant_id, user_id),
    )
    return rows[0] if rows else None


def get_user_by_cognito_sub(tenant_id: str, cognito_sub: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM tenant_user WHERE tenant_id = %s AND cognito_sub = %s LIMIT 1",
        (tenant_id, cognito_sub),
    )
    return rows[0] if rows else None


def get_user_by_email(tenant_id: str, email: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM tenant_user WHERE tenant_id = %s AND LOWER(email) = LOWER(%s) LIMIT 1",
        (tenant_id, email),
    )
    return rows[0] if rows else None


def find_user_across_tenants(email: str | None = None, user_id: str | None = None) -> dict[str, Any] | None:
    """Find a tenant_user by email or id across ALL tenants (PLATFORM scope).

    `tenant_user.id` IS the IdP subject/oid, so one identity can belong to exactly
    one tenant. Provisioning uses this to reject a reused admin email up front with
    a clear conflict instead of hitting a `tenant_user_pkey` violation mid-create.
    """
    if user_id:
        rows = execute_with_tenant(
            PLATFORM_TENANT_ID,
            "SELECT * FROM tenant_user WHERE id = %s LIMIT 1",
            (user_id,),
        )
    elif email:
        rows = execute_with_tenant(
            PLATFORM_TENANT_ID,
            "SELECT * FROM tenant_user WHERE LOWER(email) = LOWER(%s) LIMIT 1",
            (email,),
        )
    else:
        return None
    return rows[0] if rows else None


def list_users(tenant_id: str) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        f"""
        SELECT tu.*, {_ROLES_AGG_SELECT}
        FROM tenant_user tu
        WHERE tu.tenant_id = %s
        ORDER BY tu.created_at DESC
        """,
        (tenant_id,),
    )


def update_user(tenant_id: str, user_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    set_clause, params = _build_set_clause(updates, _USER_UPDATE_FIELDS)
    params["tenant_id"] = tenant_id
    params["id"] = user_id
    return execute_write_with_tenant(
        tenant_id,
        f"UPDATE tenant_user SET {set_clause}, updated_at = NOW() WHERE tenant_id = %(tenant_id)s AND id = %(id)s RETURNING *",
        params,
    )


def get_user_roles(tenant_id: str, user_id: str) -> list[str]:
    """Return every role assigned to a user, primary role first."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT role FROM tenant_user_role
        WHERE tenant_id = %s AND tenant_user_id = %s
        ORDER BY is_primary DESC, role
        """,
        (tenant_id, user_id),
    )
    return [row["role"] for row in rows]


def set_user_roles(
    tenant_id: str,
    user_id: str,
    roles: list[str],
    primary_role: str,
    assigned_by: str | None = None,
) -> dict[str, Any] | None:
    """Transactionally replace a user's `tenant_user_role` rows and mirror
    `primary_role` into `tenant_user.role`.

    `tenant_user.role` stays the single source of truth for every existing
    query that reads it directly (reports, staff-detail summary, badges) —
    this keeps it in sync on every role change instead of letting it drift
    from the now-authoritative `tenant_user_role` table.

    Returns the updated tenant_user row, or None if the user doesn't exist.
    """
    delete_query = (
        "DELETE FROM tenant_user_role WHERE tenant_id = %(tenant_id)s AND tenant_user_id = %(user_id)s",
        {"tenant_id": tenant_id, "user_id": user_id},
    )
    insert_queries = [
        (
            """
            INSERT INTO tenant_user_role (tenant_user_id, tenant_id, role, is_primary, assigned_by)
            VALUES (%(user_id)s, %(tenant_id)s, %(role)s, %(is_primary)s, %(assigned_by)s)
            """,
            {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "role": role,
                "is_primary": role == primary_role,
                "assigned_by": assigned_by,
            },
        )
        for role in roles
    ]
    update_query = (
        """
        UPDATE tenant_user SET role = %(role)s, updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(user_id)s
        RETURNING *
        """,
        {"role": primary_role, "tenant_id": tenant_id, "user_id": user_id},
    )
    results = execute_transaction(tenant_id, [delete_query, *insert_queries, update_query])
    updated = results[-1]
    if updated is not None:
        updated["roles"] = sorted(roles)
    return updated


def set_user_status(tenant_id: str, user_id: str, status: str) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE tenant_user SET status = %(status)s, updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {"status": status, "tenant_id": tenant_id, "id": user_id},
    )


def count_active_users(tenant_id: str) -> int:
    """Count the tenant's staff seats (``shared.seats``: customer portal accounts excluded)."""
    rows = execute_with_tenant(
        tenant_id,
        f"SELECT COUNT(*) AS cnt FROM tenant_user WHERE tenant_id = %s AND {staff_seat_condition()}",
        (tenant_id,),
    )
    return int(rows[0]["cnt"]) if rows else 0


def count_active_tenant_admins(tenant_id: str, exclude_user_id: str | None = None) -> int:
    """Count active users holding the `tenant_admin` role (primary or secondary)."""
    if exclude_user_id:
        rows = execute_with_tenant(
            tenant_id,
            """
            SELECT COUNT(DISTINCT tu.id)::int AS cnt
            FROM tenant_user tu
            LEFT JOIN tenant_user_role tur ON tur.tenant_user_id = tu.id AND tur.tenant_id = tu.tenant_id
            WHERE tu.tenant_id = %s
              AND tu.status = 'active'
              AND tu.id <> %s
              AND (tu.role = 'tenant_admin' OR tur.role = 'tenant_admin')
            """,
            (tenant_id, exclude_user_id),
        )
    else:
        rows = execute_with_tenant(
            tenant_id,
            """
            SELECT COUNT(DISTINCT tu.id)::int AS cnt
            FROM tenant_user tu
            LEFT JOIN tenant_user_role tur ON tur.tenant_user_id = tu.id AND tur.tenant_id = tu.tenant_id
            WHERE tu.tenant_id = %s
              AND tu.status = 'active'
              AND (tu.role = 'tenant_admin' OR tur.role = 'tenant_admin')
            """,
            (tenant_id,),
        )
    return int(rows[0]["cnt"]) if rows else 0


def ensure_primary_user_role(tenant_id: str, user_id: str, role: str, assigned_by: str | None = None) -> None:
    """Ensure the user's primary role exists in `tenant_user_role` (idempotent)."""
    execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO tenant_user_role (tenant_user_id, tenant_id, role, is_primary, assigned_by)
        VALUES (%(user_id)s, %(tenant_id)s, %(role)s, TRUE, %(assigned_by)s)
        ON CONFLICT (tenant_user_id, role) DO NOTHING
        RETURNING tenant_user_id
        """,
        {"user_id": user_id, "tenant_id": tenant_id, "role": role, "assigned_by": assigned_by},
    )


def count_containers_this_month(tenant_id: str) -> int:
    """Count containers created in the current calendar month."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COUNT(*) AS cnt
        FROM container
        WHERE tenant_id = %s
          AND date_trunc('month', created_at) = date_trunc('month', NOW())
        """,
        (tenant_id,),
    )
    return int(rows[0]["cnt"]) if rows else 0


def get_subscription_tier(tenant_id: str) -> str:
    """Return the tenant's current subscription_tier (default 'starter')."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT subscription_tier FROM tenant WHERE id = %s LIMIT 1",
        (tenant_id,),
    )
    if rows and rows[0].get("subscription_tier"):
        return str(rows[0]["subscription_tier"])
    return "starter"


# ---------------------------------------------------------------------------
# Customer operations — tenant RLS scope
# ---------------------------------------------------------------------------


def create_customer(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO customer (
            tenant_id, name, phone, email, whatsapp, address, delivery_address,
            contract_details, notification_consent, consent_given_at, user_id
        )
        VALUES (
            %(tenant_id)s, %(name)s, %(phone)s, %(email)s, %(whatsapp)s, %(address)s,
            %(delivery_address)s::jsonb, %(contract_details)s,
            %(notification_consent)s, %(consent_given_at)s, %(user_id)s
        )
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "name": data.get("name"),
            "phone": data.get("phone"),
            "email": data.get("email"),
            "whatsapp": data.get("whatsapp"),
            "address": data.get("address"),
            "delivery_address": json.dumps(data["delivery_address"]) if data.get("delivery_address") else None,
            "contract_details": data.get("contract_details"),
            "notification_consent": data.get("notification_consent", []),
            "consent_given_at": data.get("consent_given_at"),
            "user_id": data.get("user_id"),
        },
    )


# Correlated subquery for the account-status indicator (AdminCustomerList /
# AdminCustomerDetail): the expiry of this customer's current unconsumed
# invite, if any — lets staff tell "no login" apart from "invited, expires
# …" apart from "active" (has user_id) without a separate round trip.
_PENDING_INVITE_EXPIRES_AT = """
    (SELECT ci.expires_at FROM customer_invite ci
     WHERE ci.customer_id = c.id AND ci.tenant_id = c.tenant_id
       AND ci.consumed_at IS NULL AND ci.expires_at > NOW()
     ORDER BY ci.created_at DESC LIMIT 1) AS pending_invite_expires_at
"""


def get_customer_by_id(tenant_id: str, customer_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        f"SELECT c.*, {_PENDING_INVITE_EXPIRES_AT} FROM customer c WHERE c.tenant_id = %s AND c.id = %s LIMIT 1",
        (tenant_id, customer_id),
    )
    return rows[0] if rows else None


def get_customer_by_user_id(tenant_id: str, user_id: str) -> dict[str, Any] | None:
    """Resolve a customer record from the portal account's Cognito sub."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM customer WHERE tenant_id = %s AND user_id = %s LIMIT 1",
        (tenant_id, user_id),
    )
    return rows[0] if rows else None


def get_customer_stats(tenant_id: str) -> dict[str, int]:
    """Tenant-wide customer aggregates for the list stats row — SQL-computed so
    the figures stay correct at scale (the frontend previously counted only the
    loaded page). `shipments` is the tenant's total packing-list count, matching
    how list_customers derives per-customer shipment_count."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT
            COUNT(*)                                                 AS total,
            COUNT(*) FILTER (WHERE anonymised_at IS NOT NULL)        AS anonymised,
            COUNT(*) FILTER (WHERE anonymised_at IS NULL)            AS active,
            COUNT(*) FILTER (WHERE 'whatsapp' = ANY(notification_consent)) AS with_whatsapp
        FROM customer
        WHERE tenant_id = %s
        """,
        (tenant_id,),
    )
    shipments = execute_with_tenant(
        tenant_id,
        "SELECT COUNT(*) AS n FROM packing_list WHERE tenant_id = %s",
        (tenant_id,),
    )
    row = rows[0] if rows else {}
    result = {k: int(row.get(k) or 0) for k in ("total", "anonymised", "active", "with_whatsapp")}
    result["shipments"] = int((shipments[0] if shipments else {}).get("n") or 0)
    return result


def list_customers(
    tenant_id: str,
    q: str | None = None,
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    from shared.pagination import build_paginated_query, extract_page

    # shipment_count = lifetime packing lists for the customer (one PL = one
    # customer's cargo on one container = one shipment). Correlated subquery is
    # wrapped below so the pagination cursor references unambiguous outer columns.
    shipment_count = (
        "(SELECT COUNT(*) FROM packing_list pl WHERE pl.customer_id = c.id AND pl.tenant_id = c.tenant_id) AS shipment_count"
    )
    if q:
        pattern = f"%{q}%"
        inner = (
            f"SELECT c.*, {shipment_count}, {_PENDING_INVITE_EXPIRES_AT} FROM customer c"
            " WHERE c.tenant_id = %(tenant_id)s"
            " AND (c.name ILIKE %(q)s OR c.phone ILIKE %(q)s OR c.email ILIKE %(q)s)"
        )
        extra: dict[str, Any] = {"tenant_id": tenant_id, "q": pattern}
    else:
        inner = f"SELECT c.*, {shipment_count}, {_PENDING_INVITE_EXPIRES_AT} FROM customer c WHERE c.tenant_id = %(tenant_id)s"
        extra = {"tenant_id": tenant_id}

    base = f"SELECT * FROM ({inner}) AS t WHERE 1=1"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def update_customer(
    tenant_id: str,
    customer_id: str,
    updates: dict[str, Any],
    *,
    allow_internal: bool = False,
) -> dict[str, Any] | None:
    prepared = dict(updates)
    for json_col in ("delivery_address",):
        if json_col in prepared and isinstance(prepared[json_col], (dict, list)):
            prepared[json_col] = json.dumps(prepared[json_col])
    allowed_fields = _CUSTOMER_INTERNAL_UPDATE_FIELDS if allow_internal else _CUSTOMER_UPDATE_FIELDS
    set_clause, params = _build_set_clause(prepared, allowed_fields)
    params["tenant_id"] = tenant_id
    params["id"] = customer_id
    return execute_write_with_tenant(
        tenant_id,
        f"UPDATE customer SET {set_clause}, updated_at = NOW() WHERE tenant_id = %(tenant_id)s AND id = %(id)s RETURNING *",
        params,
    )


def customer_has_unpaid_balance(tenant_id: str, customer_id: str) -> bool:
    """True when the customer still owes money on a non-cancelled/non-waived invoice."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT 1 FROM billing
        WHERE tenant_id = %s
          AND customer_id = %s
          AND status NOT IN ('cancelled', 'waived', 'paid', 'overpaid')
          AND balance_ngn > 0.01
        LIMIT 1
        """,
        (tenant_id, customer_id),
    )
    return bool(rows)


def get_customer_credit_exposure(tenant_id: str, customer_id: str) -> dict[str, Any]:
    """Return open unpaid invoice balance and open carryover balance for a customer."""
    billing_rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(SUM(GREATEST(balance_ngn, 0)), 0) AS unpaid_billing_ngn
        FROM billing
        WHERE tenant_id = %s
          AND customer_id = %s
          AND status NOT IN ('cancelled', 'waived', 'paid', 'overpaid')
        """,
        (tenant_id, customer_id),
    )
    carryover_rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(SUM(carryover_amount_ngn), 0) AS active_carryover_ngn
        FROM carryover_ledger
        WHERE tenant_id = %s
          AND customer_id = %s
          AND status = 'outstanding'
        """,
        (tenant_id, customer_id),
    )
    return {
        "unpaid_billing_ngn": (billing_rows[0]["unpaid_billing_ngn"] if billing_rows else 0) or 0,
        "active_carryover_ngn": (carryover_rows[0]["active_carryover_ngn"] if carryover_rows else 0) or 0,
    }


def update_customer_credit_terms(
    tenant_id: str,
    customer_id: str,
    *,
    credit_limit_ngn: Any,
    credit_terms_days: int | None,
) -> dict[str, Any] | None:
    """Update a customer's per-customer credit limit and payment terms (nullable to reset to tenant defaults)."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE customer
        SET credit_limit_ngn  = %(credit_limit_ngn)s,
            credit_terms_days = %(credit_terms_days)s,
            updated_at        = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "id": customer_id,
            "credit_limit_ngn": credit_limit_ngn,
            "credit_terms_days": credit_terms_days,
        },
    )


def delete_unconsumed_invites_for_customer(tenant_id: str, customer_id: str) -> None:
    """Remove any pending customer_invite rows so an anonymised customer can never be resurrected."""
    execute_write_with_tenant(
        tenant_id,
        """
        DELETE FROM customer_invite
        WHERE tenant_id = %s AND customer_id = %s AND consumed_at IS NULL
        RETURNING id
        """,
        (tenant_id, customer_id),
    )


def anonymise_tenant_user(tenant_id: str, user_id: str) -> dict[str, Any] | None:
    """Erase the personal data on a portal login (GDPR Art. 17), keeping the row for FK integrity.

    `email` is NOT NULL and unique per tenant, so it becomes a per-user placeholder on a reserved
    domain; the row is left `deactivated`. Cognito/Entra hold their own copy, which the caller deletes.
    """
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE tenant_user
        SET email = %(placeholder)s, full_name = 'Anonymised', cognito_sub = NULL,
            status = 'deactivated', updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING id
        """,
        {"tenant_id": tenant_id, "id": user_id, "placeholder": f"erased-{user_id}@erased.invalid"},
    )


def anonymise_customer_record(tenant_id: str, customer_id: str) -> None:
    """Erase personal data from a customer record (GDPR Art. 17).

    Retains the UUID row for FK integrity but nulls all PII fields (including
    `delivery_address` and consent state) and timestamps `anonymised_at`.
    """
    execute_write_with_tenant(
        tenant_id,
        """
        UPDATE customer
        SET name                 = 'Anonymised',
            email                = NULL,
            phone                = NULL,
            whatsapp             = NULL,
            address              = NULL,
            delivery_address     = NULL,
            contract_details     = NULL,
            notification_consent = '{}'::text[],
            consent_given_at     = NULL,
            user_id              = NULL,
            anonymised_at        = NOW(),
            updated_at           = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING id
        """,
        {"tenant_id": tenant_id, "id": customer_id},
    )


def get_customer_full_export_data(tenant_id: str, customer_id: str) -> dict[str, Any]:
    """Return all data held for a customer across related tables (GDPR Art. 20).

    Used by the data portability export endpoint.
    """
    customer_rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM customer WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, customer_id),
    )
    customer: dict[str, Any] = customer_rows[0] if customer_rows else {}

    billing_rows = execute_with_tenant(
        tenant_id,
        """
        SELECT b.id, b.invoice_number, c.container_number,
               b.total_ngn, b.balance_ngn, b.status, b.created_at
        FROM billing b
        LEFT JOIN container c ON b.container_id = c.id
        WHERE b.tenant_id = %s AND b.customer_id = %s
        ORDER BY b.created_at DESC
        """,
        (tenant_id, customer_id),
    )

    shipment_rows = execute_with_tenant(
        tenant_id,
        """
        SELECT st.id, st.tracking_code, st.status, st.created_at
        FROM shipment_tracking st
        JOIN packing_list_item pli ON st.packing_list_item_id = pli.id
        JOIN packing_list pl ON pli.packing_list_id = pl.id
        WHERE st.tenant_id = %s AND pl.customer_id = %s
        ORDER BY st.created_at DESC
        """,
        (tenant_id, customer_id),
    )

    claim_rows = execute_with_tenant(
        tenant_id,
        """
        SELECT id, status, claimed_amount_ngn, created_at
        FROM damage_claim
        WHERE tenant_id = %s AND customer_id = %s
        ORDER BY created_at DESC
        """,
        (tenant_id, customer_id),
    )

    return {
        "customer": customer,
        "billing": list(billing_rows),
        "shipments": list(shipment_rows),
        "claims": list(claim_rows),
    }


def get_customer_by_email(tenant_id: str, email: str) -> dict[str, Any] | None:
    """Return `{id, name}` of the live customer with this email, ignoring case, or None."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id, name FROM customer WHERE tenant_id = %s AND LOWER(email) = LOWER(%s) AND anonymised_at IS NULL LIMIT 1",
        (tenant_id, email),
    )
    return rows[0] if rows else None


def get_customer_by_phone(tenant_id: str, phone: str) -> dict[str, Any] | None:
    """Look up a customer by normalised phone within one tenant.

    Needed because `idx_customer_tenant_phone_unique` enforces one customer per
    phone per tenant, and self-registration checked only the email. A returning
    customer who used a different email therefore hit a raw
    `psycopg2.UniqueViolation`, surfacing as an unexplained 500.
    """
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM customer WHERE tenant_id = %s AND phone = %s AND anonymised_at IS NULL LIMIT 1",
        (tenant_id, phone),
    )
    return rows[0] if rows else None


def link_customer_user(tenant_id: str, customer_email: str, user_id: str) -> None:
    """Set customer.user_id for the customer record matching the given email."""
    execute_write_with_tenant(
        tenant_id,
        """
        UPDATE customer SET user_id = %s
        WHERE tenant_id = %s AND email = %s AND user_id IS NULL
        RETURNING id
        """,
        (user_id, tenant_id, customer_email),
    )


# ---------------------------------------------------------------------------
# Charge type operations — tenant RLS scope
# ---------------------------------------------------------------------------


def create_charge_type(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO charge_type (tenant_id, name, description, default_amount_ngn, is_active, created_by)
        VALUES (%(tenant_id)s, %(name)s, %(description)s, %(default_amount_ngn)s, TRUE, %(created_by)s)
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "name": data.get("name"),
            "description": data.get("description"),
            "default_amount_ngn": data.get("default_amount_ngn"),
            "created_by": data.get("created_by"),
        },
    )


def list_charge_types(tenant_id: str) -> list[dict[str, Any]]:
    # usage_count: misc charges attributed back to this configured type via the
    # charge_type_id FK (migration 035). A charge_type.id belongs to exactly one
    # tenant, so the correlated count is inherently tenant-scoped.
    return execute_with_tenant(
        tenant_id,
        """
        SELECT c.*,
               (SELECT COUNT(*) FROM misc_charge mc
                 WHERE mc.charge_type_id = c.id) AS usage_count
        FROM charge_type c
        WHERE c.tenant_id = %s
        ORDER BY c.name ASC
        """,
        (tenant_id,),
    )


def get_charge_type_by_id(tenant_id: str, charge_type_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM charge_type WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, charge_type_id),
    )
    return rows[0] if rows else None


def update_charge_type(tenant_id: str, charge_type_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    set_clause, params = _build_set_clause(updates, _CHARGE_TYPE_UPDATE_FIELDS)
    params["tenant_id"] = tenant_id
    params["id"] = charge_type_id
    return execute_write_with_tenant(
        tenant_id,
        f"UPDATE charge_type SET {set_clause}, updated_at = NOW() WHERE tenant_id = %(tenant_id)s AND id = %(id)s RETURNING *",
        params,
    )


# ---------------------------------------------------------------------------
# Container capacity presets (custom) — tenant RLS scope. The ten well-known
# presets are code constants merged in by the service; only custom ones persist.
# ---------------------------------------------------------------------------


def create_container_capacity(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO container_capacity (tenant_id, name, capacity_cbm, recommended_cbm, created_by)
        VALUES (%(tenant_id)s, %(name)s, %(capacity_cbm)s, %(recommended_cbm)s, %(created_by)s)
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "name": data.get("name"),
            "capacity_cbm": data.get("capacity_cbm"),
            "recommended_cbm": data.get("recommended_cbm"),
            "created_by": data.get("created_by"),
        },
    )


def list_container_capacities(tenant_id: str) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        "SELECT * FROM container_capacity WHERE tenant_id = %s ORDER BY capacity_cbm DESC, name ASC",
        (tenant_id,),
    )


def get_container_capacity_by_id(tenant_id: str, capacity_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM container_capacity WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, capacity_id),
    )
    return rows[0] if rows else None


def update_container_capacity(tenant_id: str, capacity_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    # Column names come from a fixed allowlist, never from caller input, so the
    # interpolated SET clause carries no injection surface.
    allowed = {k: v for k, v in updates.items() if k in ("name", "capacity_cbm", "recommended_cbm")}
    if not allowed:
        return get_container_capacity_by_id(tenant_id, capacity_id)
    set_clause = ", ".join(f"{k} = %({k})s" for k in allowed)
    params = {**allowed, "tenant_id": tenant_id, "id": capacity_id}
    return execute_write_with_tenant(
        tenant_id,
        f"UPDATE container_capacity SET {set_clause} WHERE tenant_id = %(tenant_id)s AND id = %(id)s RETURNING *",
        params,
    )


def delete_container_capacity(tenant_id: str, capacity_id: str) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        "DELETE FROM container_capacity WHERE tenant_id = %s AND id = %s RETURNING id",
        (tenant_id, capacity_id),
    )


# ---------------------------------------------------------------------------
# Platform dashboard + audit — PLATFORM scope
# ---------------------------------------------------------------------------


def get_dashboard_stats() -> dict[str, Any]:
    """Aggregate cross-tenant metrics for the platform admin dashboard."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        """
        SELECT
            COUNT(*) FILTER (WHERE status = 'active')    AS active_tenants,
            COUNT(*) FILTER (WHERE status = 'suspended') AS suspended_tenants,
            COUNT(*) FILTER (WHERE status = 'offboarded') AS offboarded_tenants,
            COUNT(*) FILTER (WHERE subscription_tier = 'starter')    AS starter_tenants,
            COUNT(*) FILTER (WHERE subscription_tier = 'business')   AS business_tenants,
            COUNT(*) FILTER (WHERE subscription_tier = 'enterprise') AS enterprise_tenants
        FROM tenant
        """,
        None,
    )
    tenant_stats: dict[str, Any] = rows[0] if rows else {}

    # Staff seats only (shared.seats), not customer portal accounts (audit PA-03).
    user_rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        f"SELECT COUNT(*) AS total_users FROM tenant_user WHERE {staff_seat_condition()}",
        None,
    )
    container_rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT COUNT(*) AS total_containers FROM container",
        None,
    )

    return {
        "tenants": {k: int(v or 0) for k, v in tenant_stats.items()},
        "total_users": int(user_rows[0]["total_users"] if user_rows else 0),
        "total_containers": int(container_rows[0]["total_containers"] if container_rows else 0),
    }


def list_tenant_activity(
    tenant_id: str,
    limit: int = 20,
    cursor: dict[str, Any] | None = None,
    actor_id: str | None = None,
    entity_type: str | list[str] | None = None,
    action: str | None = None,
    q: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    sort_direction: str = "desc",
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Tenant-scoped activity feed from audit_log (audit gap B6).

    Includes before_state/after_state — a tenant admin auditing money or
    goods movement (a payment claim confirmed, a misc charge added, a
    storage fee waived) needs to see *what* changed, not just that
    something did. The original "lean projection, no JSON blobs" framing
    was fine for the small dashboard widget this was built for, but is not
    an audit trail a tenant admin can actually verify anything against —
    see the dedicated `frontend/src/pages/tenant-admin/ActivityLog.tsx`
    page, which is. Joined to tenant_user for the actor's display name.
    Filtered to the tenant via RLS + explicit predicate.

    Filters, all optional and combinable (found live to be genuinely needed
    — a category dropdown alone isn't "filtering" for a money/goods audit
    trail without a way to narrow by date, actor, action, or a specific
    record):
      - actor_id: one staff member (staff-profile activity table, 3.4).
      - entity_type: one kind of record ("payment_claim"), or several at
        once (a category grouping, e.g. every money-related type) — a
        single string or a list; uses idx_audit_log_entity either way via
        `= ANY(...)`, same pattern as tracking's container status filter.
      - action: CREATE / UPDATE / DELETE / STATUS_CHANGE.
      - q: free-text search — matches the actor's name OR the record's id,
        so pasting a UUID finds every action ever taken on that specific
        record (the actual "search" a money/goods audit needs), and typing
        a name finds everything one person did.
      - created_after / created_before: ISO date strings, same contract as
        `GET /v1/containers`'s date-range filter.
      - sort_direction: "asc" or "desc" (default desc — newest first).
    """
    from shared.pagination import build_paginated_query, extract_page

    # Wrap the join in a subquery so the pagination clause's bare `id` /
    # `created_at` references (build_paginated_query) are unambiguous — the
    # audit_log ⋈ tenant_user join otherwise has two `id` columns.
    # Reported directly by the user: a platform admin's own actions on this
    # tenant (impersonation start/end) are not a tenant-side business event
    # and must never be visible to that tenant's own admins, regardless of
    # what filters they request. Belt-and-suspenders — impersonation is now
    # logged to platform_audit_log instead (see impersonation.py), so this
    # should never match a real row, but a tenant admin must not be able to
    # query their way to one even if a future call site regresses.
    conditions = " AND a.entity_type NOT IN ('impersonation_session')"
    extra: dict[str, Any] = {"tenant_id": tenant_id}
    if actor_id:
        conditions += " AND a.actor_id = %(actor_id)s"
        extra["actor_id"] = actor_id
    if entity_type:
        entity_types = [entity_type] if isinstance(entity_type, str) else list(entity_type)
        conditions += " AND a.entity_type = ANY(%(entity_types)s)"
        extra["entity_types"] = entity_types
    if action:
        conditions += " AND a.action = %(action)s"
        extra["action"] = action
    if created_after:
        conditions += " AND a.created_at >= %(created_after)s"
        extra["created_after"] = created_after
    if created_before:
        conditions += " AND a.created_at <= %(created_before)s"
        extra["created_before"] = created_before
    if q:
        conditions += " AND (u.full_name ILIKE %(q)s OR a.entity_id::text ILIKE %(q)s)"
        extra["q"] = f"%{q}%"

    inner = f"""
        SELECT a.id, a.action, a.entity_type, a.entity_id, a.actor_id,
               a.actor_role, a.before_state, a.after_state, a.created_at,
               u.full_name AS actor_name
        FROM audit_log a
        LEFT JOIN tenant_user u ON u.id = a.actor_id AND u.tenant_id = a.tenant_id
        WHERE a.tenant_id = %(tenant_id)s{conditions}
    """
    base = f"SELECT * FROM ({inner}) AS t WHERE 1=1"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at", sort_direction=sort_direction.upper())
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def list_platform_audit_log(
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
    target_tenant_id: str | None = None,
    action: str | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    from shared.pagination import build_paginated_query, extract_page

    conditions = ""
    extra: dict[str, Any] = {}
    if target_tenant_id:
        conditions += " AND pal.target_tenant_id = %(target_tenant_id)s"
        extra["target_tenant_id"] = target_tenant_id
    if action:
        conditions += " AND pal.action = %(action)s"
        extra["action"] = action
    # Each row carries its tenant's name, so the console never needs the whole tenant list to label a row (PA-02),
    # and its actor's directory name (Phase 1; PA-06 showed the id only). A platform job has no actor.
    inner = f"""
        SELECT pal.*, t.company_name AS target_tenant_name, pu.name AS actor_name, pu.role AS actor_role
        FROM platform_audit_log pal
        LEFT JOIN tenant t ON t.id = pal.target_tenant_id
        LEFT JOIN platform_user pu
            ON pu.subject = pal.actor_id::text OR pal.actor_id::text = ANY(pu.previous_subjects)
        WHERE 1=1{conditions}
    """
    base = f"SELECT * FROM ({inner}) AS paged WHERE 1=1"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(PLATFORM_TENANT_ID, query, params)
    return extract_page(rows, limit)


# ---------------------------------------------------------------------------
# Platform settings — platform_settings table (no RLS — PLATFORM scope)
# ---------------------------------------------------------------------------


def get_platform_settings() -> dict[str, Any]:
    """Return all platform settings as a key→value dict."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT key, value FROM platform_settings ORDER BY key",
        (),
    )
    return {row["key"]: row["value"] for row in rows}


def upsert_platform_setting(key: str, value: Any, actor_id: str | None) -> None:
    """Insert or update a single platform setting."""
    execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        INSERT INTO platform_settings (key, value, updated_at, updated_by)
        VALUES (%(key)s, %(value)s::jsonb, NOW(), %(actor_id)s)
        ON CONFLICT (key) DO UPDATE
        SET value      = EXCLUDED.value,
            updated_at = NOW(),
            updated_by = EXCLUDED.updated_by
        RETURNING key, value, updated_at, updated_by
        """,
        {"key": key, "value": json.dumps(value), "actor_id": actor_id},
    )


# ---------------------------------------------------------------------------
# Tenant reports — aggregate queries (tenant RLS scope)
# ---------------------------------------------------------------------------


def get_tenant_report_data(tenant_id: str, period: str) -> dict[str, Any]:
    """Run aggregate queries for the tenant reports endpoint."""
    # Containers by status
    container_rows = execute_with_tenant(
        tenant_id,
        """
        SELECT status, COUNT(*) AS cnt
        FROM container
        WHERE tenant_id = %s
        GROUP BY status
        """,
        (tenant_id,),
    )
    containers_by_status: dict[str, Any] = {r["status"]: int(r["cnt"]) for r in container_rows}
    total_containers = sum(containers_by_status.values())

    # Customers
    customer_rows = execute_with_tenant(
        tenant_id,
        """
        SELECT
            COUNT(*) AS total,
            COUNT(CASE WHEN EXISTS (
                SELECT 1 FROM shipment_tracking st
                WHERE st.tenant_id = c.tenant_id
                  AND st.status NOT IN ('released')
                  AND st.tracking_code IN (
                    SELECT pli.tracking_code FROM packing_list_item pli
                    JOIN packing_list pl ON pl.id = pli.packing_list_id
                    WHERE pl.customer_id = c.id AND pl.tenant_id = c.tenant_id
                  )
            ) THEN 1 END) AS with_active_shipments
        FROM customer c
        WHERE c.tenant_id = %s
        """,
        (tenant_id,),
    )
    customer_data: dict[str, Any] = customer_rows[0] if customer_rows else {"total": 0, "with_active_shipments": 0}

    # Billing totals
    billing_rows = execute_with_tenant(
        tenant_id,
        """
        SELECT
            COALESCE(SUM(total_ngn), 0)        AS total_billed_ngn,
            COALESCE(SUM(amount_paid_ngn), 0)  AS total_collected_ngn,
            COALESCE(SUM(balance_ngn), 0)      AS outstanding_ngn,
            COALESCE(AVG(total_cbm), 0)        AS average_cbm
        FROM billing
        WHERE tenant_id = %s
        """,
        (tenant_id,),
    )
    billing_data: dict[str, Any] = billing_rows[0] if billing_rows else {}

    # Claims
    claims_rows = execute_with_tenant(
        tenant_id,
        """
        SELECT
            COUNT(CASE WHEN status NOT IN ('resolved', 'closed', 'rejected') THEN 1 END) AS open_claims,
            COUNT(CASE WHEN status IN ('resolved', 'closed')
                        AND date_trunc('month', updated_at) = date_trunc('month', NOW())
                   THEN 1 END) AS resolved_this_month
        FROM damage_claim
        WHERE tenant_id = %s
        """,
        (tenant_id,),
    )
    claims_data: dict[str, Any] = claims_rows[0] if claims_rows else {"open_claims": 0, "resolved_this_month": 0}

    # Disputes
    disputes_rows = execute_with_tenant(
        tenant_id,
        """
        SELECT
            COUNT(CASE WHEN status NOT IN ('resolved_adjusted', 'resolved_no_change', 'closed') THEN 1 END) AS open_disputes,
            COUNT(CASE WHEN status IN ('resolved_adjusted', 'resolved_no_change')
                        AND date_trunc('month', updated_at) = date_trunc('month', NOW())
                   THEN 1 END) AS resolved_this_month
        FROM cbm_dispute
        WHERE tenant_id = %s
        """,
        (tenant_id,),
    )
    disputes_data: dict[str, Any] = disputes_rows[0] if disputes_rows else {"open_disputes": 0, "resolved_this_month": 0}

    return {
        "period": period,
        "containers": {
            "total": total_containers,
            "in_transit": containers_by_status.get("in_transit", 0),
            "at_warehouse": containers_by_status.get("at_warehouse", 0),
            "fully_released": containers_by_status.get("fully_released", 0),
        },
        "customers": {
            "total": int(customer_data["total"]),
            "with_active_shipments": int(customer_data["with_active_shipments"]),
        },
        "billing": {
            "total_billed_ngn": float(billing_data.get("total_billed_ngn", 0)),
            "total_collected_ngn": float(billing_data.get("total_collected_ngn", 0)),
            "outstanding_ngn": float(billing_data.get("outstanding_ngn", 0)),
            "average_cbm_per_container": float(billing_data.get("average_cbm", 0)),
        },
        "claims": {
            "open": int(claims_data["open_claims"]),
            "resolved_this_month": int(claims_data["resolved_this_month"]),
        },
        "disputes": {
            "open": int(disputes_data["open_disputes"]),
            "resolved_this_month": int(disputes_data["resolved_this_month"]),
        },
    }


# ---------------------------------------------------------------------------
# Notification templates — tenant RLS scope
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Rate history — tenant RLS scope
# ---------------------------------------------------------------------------


def append_rate_history(
    tenant_id: str,
    rate_type: str,
    rate_value: dict[str, Any],
    previous_value: dict[str, Any] | None,
    changed_by: str | None,
) -> None:
    execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO rate_history (tenant_id, rate_type, rate_value, previous_value, changed_by)
        VALUES (%(tenant_id)s, %(rate_type)s, %(rate_value)s::jsonb, %(previous_value)s::jsonb, %(changed_by)s)
        RETURNING id
        """,
        {
            "tenant_id": tenant_id,
            "rate_type": rate_type,
            "rate_value": json.dumps(rate_value),
            "previous_value": json.dumps(previous_value) if previous_value else None,
            "changed_by": changed_by,
        },
    )


def list_rate_history(
    tenant_id: str,
    rate_type: str | None = None,
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    from shared.pagination import build_paginated_query, extract_page

    conditions = ["tenant_id = %(tenant_id)s"]
    extra: dict[str, Any] = {"tenant_id": tenant_id}
    if rate_type:
        conditions.append("rate_type = %(rate_type)s")
        extra["rate_type"] = rate_type

    base = f"SELECT * FROM rate_history WHERE {' AND '.join(conditions)}"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


# ---------------------------------------------------------------------------
# Notification templates — tenant RLS scope
# ---------------------------------------------------------------------------


def list_notification_templates(tenant_id: str) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM notification_template
        WHERE tenant_id = %s
        ORDER BY event_type, channel
        """,
        (tenant_id,),
    )


def get_notification_template(
    tenant_id: str,
    event_type: str,
    channel: str,
) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM notification_template
        WHERE tenant_id = %s AND event_type = %s AND channel = %s
        LIMIT 1
        """,
        (tenant_id, event_type, channel),
    )
    return rows[0] if rows else None


def upsert_notification_template(
    tenant_id: str,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO notification_template (
            tenant_id, event_type, channel, template_body, subject, updated_by
        ) VALUES (
            %(tenant_id)s, %(event_type)s, %(channel)s,
            %(template_body)s, %(subject)s, %(updated_by)s
        )
        ON CONFLICT (tenant_id, event_type, channel)
        DO UPDATE SET
            template_body = EXCLUDED.template_body,
            subject       = EXCLUDED.subject,
            updated_by    = EXCLUDED.updated_by,
            updated_at    = NOW()
        RETURNING *
        """,
        data,
    )


# ---------------------------------------------------------------------------
# Company onboarding requests (shipping-company leads) — PLATFORM scope, no RLS
# ---------------------------------------------------------------------------


def insert_onboarding_request(data: dict[str, Any]) -> dict[str, Any]:
    """Insert a company onboarding lead. Returns the created row."""
    row = execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        INSERT INTO tenant_onboarding_request
            (company_name, contact_name, contact_email, contact_phone,
             origin_country, destination_country, monthly_volume, notes)
        VALUES
            (%(company_name)s, %(contact_name)s, %(contact_email)s, %(contact_phone)s,
             %(origin_country)s, %(destination_country)s, %(monthly_volume)s, %(notes)s)
        RETURNING *
        """,
        data,
    )
    if row is None:
        raise RuntimeError("insert_onboarding_request returned no row")
    return row


def list_onboarding_requests(status: str | None = None) -> list[dict[str, Any]]:
    """List onboarding leads, newest first; optionally filtered by status."""
    if status:
        return execute_with_tenant(
            PLATFORM_TENANT_ID,
            "SELECT * FROM tenant_onboarding_request WHERE status = %s ORDER BY created_at DESC",
            (status,),
        )
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT * FROM tenant_onboarding_request ORDER BY created_at DESC",
        (),
    )


def get_onboarding_request(request_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT * FROM tenant_onboarding_request WHERE id = %s LIMIT 1",
        (request_id,),
    )
    return rows[0] if rows else None


def update_onboarding_request(request_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    """Patch an onboarding lead (status/review/link fields). Returns the updated
    row, or None if the id doesn't exist (RETURNING → zero rows)."""
    allowed = ("status", "rejection_reason", "reviewed_by", "reviewed_at", "tenant_id")
    sets = [f"{col} = %({col})s" for col in allowed if col in fields]
    if not sets:
        return get_onboarding_request(request_id)
    params = {col: fields[col] for col in allowed if col in fields}
    params["id"] = request_id
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        f"UPDATE tenant_onboarding_request SET {', '.join(sets)} WHERE id = %(id)s RETURNING *",
        params,
    )
