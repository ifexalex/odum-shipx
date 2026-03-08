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

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Allowed field sets for dynamic UPDATE (SQL-injection prevention §2.2)
# ---------------------------------------------------------------------------

_TENANT_UPDATE_FIELDS = frozenset({
    "company_name",
    "primary_contact_email",
    "primary_contact_phone",
    "origin_country",
    "destination_country",
    "subscription_tier",
    "branding_config",
    "notification_preferences",
})

_USER_UPDATE_FIELDS = frozenset({
    "full_name",
    "email",
})

_CUSTOMER_UPDATE_FIELDS = frozenset({
    "name",
    "phone",
    "email",
    "whatsapp",
    "address",
    "contract_details",
})

_CHARGE_TYPE_UPDATE_FIELDS = frozenset({
    "name",
    "description",
    "default_amount_ngn",
    "is_active",
})


def _build_set_clause(updates: dict, allowed: frozenset) -> tuple[str, dict]:
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


def create_tenant(data: dict) -> dict:
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        INSERT INTO tenant (
            company_name, primary_contact_email, primary_contact_phone,
            origin_country, destination_country, subscription_tier, status
        ) VALUES (
            %(company_name)s, %(primary_contact_email)s, %(primary_contact_phone)s,
            %(origin_country)s, %(destination_country)s, %(subscription_tier)s, 'active'
        ) RETURNING *
        """,
        data,
    )


def get_tenant_by_id(tenant_id: str) -> dict | None:
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT * FROM tenant WHERE id = %s LIMIT 1",
        (tenant_id,),
    )
    return rows[0] if rows else None


def list_tenants(limit: int = 50, cursor: dict | None = None) -> list[dict]:
    from shared.pagination import build_paginated_query, extract_page

    base = "SELECT * FROM tenant WHERE 1=1"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    rows = execute_with_tenant(PLATFORM_TENANT_ID, query, params)
    page, _, _ = extract_page(rows, limit)
    return page


def update_tenant(tenant_id: str, updates: dict) -> dict:
    set_clause, params = _build_set_clause(updates, _TENANT_UPDATE_FIELDS)
    params["updated_at"] = "NOW()"
    params["id"] = tenant_id
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        f"UPDATE tenant SET {set_clause}, updated_at = NOW() WHERE id = %(id)s RETURNING *",
        params,
    )


def set_tenant_status(tenant_id: str, status: str) -> dict:
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        "UPDATE tenant SET status = %(status)s, updated_at = NOW() WHERE id = %(id)s RETURNING *",
        {"status": status, "id": tenant_id},
    )


# ---------------------------------------------------------------------------
# Tenant config — tenant RLS scope
# ---------------------------------------------------------------------------


def get_all_configs(tenant_id: str) -> list[dict]:
    return execute_with_tenant(
        tenant_id,
        "SELECT config_key, config_value, updated_at FROM tenant_config WHERE tenant_id = %s",
        (tenant_id,),
    )


def upsert_config(tenant_id: str, key: str, value: dict, updated_by: str | None = None) -> dict:
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


# ---------------------------------------------------------------------------
# Tenant user operations — tenant RLS scope
# ---------------------------------------------------------------------------


def create_tenant_user(tenant_id: str, data: dict) -> dict:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO tenant_user (
            tenant_id, cognito_sub, email, full_name, role, status, created_by
        ) VALUES (
            %(tenant_id)s, %(cognito_sub)s, %(email)s, %(full_name)s,
            %(role)s, 'active', %(created_by)s
        ) RETURNING *
        """,
        data,
    )


def get_user_by_id(tenant_id: str, user_id: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM tenant_user WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, user_id),
    )
    return rows[0] if rows else None


def get_user_by_email(tenant_id: str, email: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM tenant_user WHERE tenant_id = %s AND email = %s LIMIT 1",
        (tenant_id, email),
    )
    return rows[0] if rows else None


def list_users(tenant_id: str) -> list[dict]:
    return execute_with_tenant(
        tenant_id,
        "SELECT * FROM tenant_user WHERE tenant_id = %s ORDER BY created_at DESC",
        (tenant_id,),
    )


def update_user(tenant_id: str, user_id: str, updates: dict) -> dict:
    set_clause, params = _build_set_clause(updates, _USER_UPDATE_FIELDS)
    params["tenant_id"] = tenant_id
    params["id"] = user_id
    return execute_write_with_tenant(
        tenant_id,
        f"UPDATE tenant_user SET {set_clause}, updated_at = NOW() WHERE tenant_id = %(tenant_id)s AND id = %(id)s RETURNING *",
        params,
    )


def set_user_status(tenant_id: str, user_id: str, status: str) -> dict:
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
    rows = execute_with_tenant(
        tenant_id,
        "SELECT COUNT(*) AS cnt FROM tenant_user WHERE tenant_id = %s AND status = 'active'",
        (tenant_id,),
    )
    return int(rows[0]["cnt"]) if rows else 0


# ---------------------------------------------------------------------------
# Customer operations — tenant RLS scope
# ---------------------------------------------------------------------------


def create_customer(tenant_id: str, data: dict) -> dict:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO customer (tenant_id, name, phone, email, whatsapp, address, contract_details)
        VALUES (%(tenant_id)s, %(name)s, %(phone)s, %(email)s, %(whatsapp)s, %(address)s, %(contract_details)s)
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "name": data.get("name"),
            "phone": data.get("phone"),
            "email": data.get("email"),
            "whatsapp": data.get("whatsapp"),
            "address": data.get("address"),
            "contract_details": data.get("contract_details"),
        },
    )


def get_customer_by_id(tenant_id: str, customer_id: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM customer WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, customer_id),
    )
    return rows[0] if rows else None


def list_customers(
    tenant_id: str,
    q: str | None = None,
    limit: int = 50,
    cursor: dict | None = None,
) -> tuple[list[dict], str | None, bool]:
    from shared.pagination import build_paginated_query, extract_page

    if q:
        pattern = f"%{q}%"
        base = (
            "SELECT * FROM customer WHERE tenant_id = %(tenant_id)s"
            " AND (name ILIKE %(q)s OR phone ILIKE %(q)s OR email ILIKE %(q)s)"
        )
        extra: dict[str, Any] = {"tenant_id": tenant_id, "q": pattern}
    else:
        base = "SELECT * FROM customer WHERE tenant_id = %(tenant_id)s"
        extra = {"tenant_id": tenant_id}

    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def update_customer(tenant_id: str, customer_id: str, updates: dict) -> dict:
    set_clause, params = _build_set_clause(updates, _CUSTOMER_UPDATE_FIELDS)
    params["tenant_id"] = tenant_id
    params["id"] = customer_id
    return execute_write_with_tenant(
        tenant_id,
        f"UPDATE customer SET {set_clause}, updated_at = NOW() WHERE tenant_id = %(tenant_id)s AND id = %(id)s RETURNING *",
        params,
    )


def link_customer_user(tenant_id: str, customer_email: str, user_id: str) -> None:
    """Set customer.user_id for the customer record matching the given email."""
    execute_write_with_tenant(
        tenant_id,
        """
        UPDATE customer SET user_id = %s
        WHERE tenant_id = %s AND email = %s AND user_id IS NULL
        """,
        (user_id, tenant_id, customer_email),
    )


# ---------------------------------------------------------------------------
# Charge type operations — tenant RLS scope
# ---------------------------------------------------------------------------


def create_charge_type(tenant_id: str, data: dict) -> dict:
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


def list_charge_types(tenant_id: str) -> list[dict]:
    return execute_with_tenant(
        tenant_id,
        "SELECT * FROM charge_type WHERE tenant_id = %s ORDER BY name ASC",
        (tenant_id,),
    )


def get_charge_type_by_id(tenant_id: str, charge_type_id: str) -> dict | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM charge_type WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, charge_type_id),
    )
    return rows[0] if rows else None


def update_charge_type(tenant_id: str, charge_type_id: str, updates: dict) -> dict:
    set_clause, params = _build_set_clause(updates, _CHARGE_TYPE_UPDATE_FIELDS)
    params["tenant_id"] = tenant_id
    params["id"] = charge_type_id
    return execute_write_with_tenant(
        tenant_id,
        f"UPDATE charge_type SET {set_clause}, updated_at = NOW() WHERE tenant_id = %(tenant_id)s AND id = %(id)s RETURNING *",
        params,
    )


# ---------------------------------------------------------------------------
# Platform dashboard + audit — PLATFORM scope
# ---------------------------------------------------------------------------


def get_dashboard_stats() -> dict:
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
    tenant_stats = rows[0] if rows else {}

    user_rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT COUNT(*) AS total_users FROM tenant_user WHERE status = 'active'",
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


def list_platform_audit_log(limit: int = 50, cursor: dict | None = None) -> list[dict]:
    from shared.pagination import build_paginated_query, extract_page

    base = "SELECT * FROM platform_audit_log WHERE 1=1"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    rows = execute_with_tenant(PLATFORM_TENANT_ID, query, params)
    page, _, _ = extract_page(rows, limit)
    return page


def insert_platform_audit(
    action: str,
    actor_id: str | None,
    target_tenant_id: str | None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        INSERT INTO platform_audit_log (action, actor_id, target_tenant_id, details, ip_address)
        VALUES (%(action)s, %(actor_id)s, %(target_tenant_id)s, %(details)s::jsonb, %(ip_address)s)
        """,
        {
            "action": action,
            "actor_id": actor_id,
            "target_tenant_id": target_tenant_id,
            "details": json.dumps(details) if details else None,
            "ip_address": ip_address,
        },
    )



# ---------------------------------------------------------------------------
# Platform settings — platform_settings table (no RLS — PLATFORM scope)
# ---------------------------------------------------------------------------


def get_platform_settings() -> dict:
    """Return all platform settings as a key→value dict."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT key, value FROM platform_settings ORDER BY key",
        (),
    )
    return {row["key"]: row["value"] for row in rows}


def upsert_platform_setting(key: str, value, actor_id: str | None) -> None:
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
        """,
        {"key": key, "value": json.dumps(value), "actor_id": actor_id},
    )


# ---------------------------------------------------------------------------
# Tenant reports — aggregate queries (tenant RLS scope)
# ---------------------------------------------------------------------------


def get_tenant_report_data(tenant_id: str, period: str) -> dict:
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
    containers_by_status: dict = {r["status"]: int(r["cnt"]) for r in container_rows}
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
    customer_data = customer_rows[0] if customer_rows else {"total": 0, "with_active_shipments": 0}

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
    billing_data = billing_rows[0] if billing_rows else {}

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
    claims_data = claims_rows[0] if claims_rows else {"open_claims": 0, "resolved_this_month": 0}

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
    disputes_data = disputes_rows[0] if disputes_rows else {"open_disputes": 0, "resolved_this_month": 0}

    return {
        "period":     period,
        "containers": {
            "total":          total_containers,
            "in_transit":     containers_by_status.get("in_transit", 0),
            "at_warehouse":   containers_by_status.get("at_warehouse", 0),
            "fully_released": containers_by_status.get("fully_released", 0),
        },
        "customers": {
            "total":                  int(customer_data["total"]),
            "with_active_shipments":  int(customer_data["with_active_shipments"]),
        },
        "billing": {
            "total_billed_ngn":          float(billing_data.get("total_billed_ngn", 0)),
            "total_collected_ngn":       float(billing_data.get("total_collected_ngn", 0)),
            "outstanding_ngn":           float(billing_data.get("outstanding_ngn", 0)),
            "average_cbm_per_container": float(billing_data.get("average_cbm", 0)),
        },
        "claims": {
            "open":               int(claims_data["open_claims"]),
            "resolved_this_month": int(claims_data["resolved_this_month"]),
        },
        "disputes": {
            "open":               int(disputes_data["open_disputes"]),
            "resolved_this_month": int(disputes_data["resolved_this_month"]),
        },
    }
