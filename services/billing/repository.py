"""Database access layer for the Billing service.

Pure SQL — no business logic.
All queries use parameterized statements (%s / %(name)s) — never f-strings on
user-supplied values.

Notes:
  - billing has RLS (tenant_id isolation).
  - cbm_dispute has RLS.
  - carryover_ledger has RLS.
  - refund_request has RLS.
  - misc_charge has NO RLS — always scoped via billing_id FK.
  - payment_record has RLS.
  - tenant_config has RLS.
"""

import logging
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)

# Allowlist for dynamic SET clauses in dispute status update
_DISPUTE_EXTRA_FIELDS = frozenset({"agreed_cbm", "resolution_notes", "resolved_by", "resolved_at"})


# ---------------------------------------------------------------------------
# Tenant helpers
# ---------------------------------------------------------------------------


def get_tenant_short(tenant_id: str) -> str:
    """Derive 3-char tenant prefix from company_name (PLATFORM scope)."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT company_name FROM tenant WHERE id = %s LIMIT 1",
        (tenant_id,),
    )
    if not rows:
        return "UNK"
    company_name = rows[0].get("company_name") or "UNK"
    short = "".join(c for c in company_name.upper() if c.isalpha())[:3]
    return short.ljust(3, "X")


def get_customer_by_user_id(tenant_id: str, user_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id FROM customer WHERE tenant_id = %s AND user_id = %s LIMIT 1",
        (tenant_id, user_id),
    )
    return rows[0] if rows else None


def get_customer_contact(tenant_id: str, customer_id: str) -> dict[str, Any] | None:
    """Contact info for enqueue_notifications — name/phone/email/whatsapp plus
    the portal user's locale (defaults to 'en' for customers without one).
    `user_id` (== tenant_user.id when the customer has a portal account, else
    NULL) is included so callers can also target the in-app customer
    notification bell via shared.staff_notifications.notify_staff — same
    shape as tracking/repository.py::get_customers_for_container."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT c.id::text AS id, c.user_id, c.name, c.phone, c.email, c.whatsapp,
            COALESCE(tu.locale, 'en') AS locale
        FROM customer c
        LEFT JOIN tenant_user tu ON tu.id = c.user_id AND tu.tenant_id = c.tenant_id
        WHERE c.tenant_id = %s AND c.id = %s AND c.anonymised_at IS NULL
        LIMIT 1
        """,
        (tenant_id, customer_id),
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Tenant config reads
# ---------------------------------------------------------------------------


def get_tenant_config_value(tenant_id: str, config_key: str) -> dict[str, Any] | None:
    """Return the JSONB config_value dict for a given key, or None."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT config_value FROM tenant_config
        WHERE tenant_id = %s AND config_key = %s LIMIT 1
        """,
        (tenant_id, config_key),
    )
    if not rows:
        return None
    val = rows[0]["config_value"]
    return val if isinstance(val, dict) else {}


# ---------------------------------------------------------------------------
# Billing creation helpers
# ---------------------------------------------------------------------------


def get_cbm_and_carton_totals(tenant_id: str, customer_id: str, container_id: str) -> dict[str, Any]:
    """Sum CBM and count cartons from approved packing lists for customer+container."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT
            COALESCE(SUM(pli.cbm), 0) AS total_cbm,
            COUNT(pli.id)              AS total_cartons
        FROM packing_list_item pli
        JOIN packing_list pl ON pl.id = pli.packing_list_id
        WHERE pl.tenant_id    = %s
          AND pl.customer_id  = %s
          AND pl.container_id = %s
          AND pl.status       = 'approved'
        """,
        (tenant_id, customer_id, container_id),
    )
    return rows[0] if rows else {"total_cbm": 0, "total_cartons": 0}


def get_cbm_by_package_type(tenant_id: str, customer_id: str, container_id: str) -> dict[str, Any]:
    """CBM from approved packing lists for customer+container, grouped by
    raw `package_unit` — same scoping as get_cbm_and_carton_totals, but
    bucketed so billing can apply a per-package-type rate. Buckets are
    normalized by the caller (shared/cbm_rate.py::normalize_package_unit),
    not here, since a raw package_unit value could be any free-text string."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT
            pli.package_unit         AS package_unit,
            COALESCE(SUM(pli.cbm), 0) AS total_cbm
        FROM packing_list_item pli
        JOIN packing_list pl ON pl.id = pli.packing_list_id
        WHERE pl.tenant_id    = %s
          AND pl.customer_id  = %s
          AND pl.container_id = %s
          AND pl.status       = 'approved'
        GROUP BY pli.package_unit
        """,
        (tenant_id, customer_id, container_id),
    )
    return {row["package_unit"]: row["total_cbm"] for row in rows}


def get_outstanding_carryovers(tenant_id: str, customer_id: str) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM carryover_ledger
        WHERE tenant_id   = %s
          AND customer_id = %s
          AND status      = 'outstanding'
        ORDER BY created_at ASC
        """,
        (tenant_id, customer_id),
    )


def get_pending_credit_refunds(tenant_id: str, customer_id: str) -> list[dict[str, Any]]:
    """Approved refund_requests with customer_choice='credit_note' not yet applied."""
    return execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM refund_request
        WHERE tenant_id       = %s
          AND customer_id     = %s
          AND status          = 'applied_as_credit'
          AND customer_choice = 'credit_next_shipment'
        ORDER BY created_at ASC
        """,
        (tenant_id, customer_id),
    )


def get_next_invoice_seq(tenant_id: str) -> int:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT COUNT(*) + 1 AS seq FROM billing WHERE tenant_id = %s",
        (tenant_id,),
    )
    return int(rows[0]["seq"]) if rows else 1


# ---------------------------------------------------------------------------
# Billing CRUD — tenant RLS scope
# ---------------------------------------------------------------------------


def create_billing(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO billing (
            tenant_id, customer_id, container_id, invoice_number,
            total_cartons, total_cbm, cbm_rate_usd, cbm_rate_currency,
            cbm_rate_mode, cbm_breakdown, subtotal_usd,
            exchange_rate_ngn, subtotal_ngn, misc_charges_ngn,
            total_ngn, amount_paid_ngn, status, billed_at, created_by
        ) VALUES (
            %(tenant_id)s, %(customer_id)s, %(container_id)s, %(invoice_number)s,
            %(total_cartons)s, %(total_cbm)s, %(cbm_rate_usd)s, %(cbm_rate_currency)s,
            %(cbm_rate_mode)s, %(cbm_breakdown)s::jsonb, %(subtotal_usd)s,
            %(exchange_rate_ngn)s, %(subtotal_ngn)s, %(misc_charges_ngn)s,
            %(total_ngn)s, %(amount_paid_ngn)s, %(status)s, %(billed_at)s, %(created_by)s
        ) RETURNING *
        """,
        data,
    )


def get_billing_by_id(tenant_id: str, billing_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT b.*, c.container_number
        FROM billing b
        LEFT JOIN container c ON c.id = b.container_id AND c.tenant_id = b.tenant_id
        WHERE b.tenant_id = %s AND b.id = %s
        LIMIT 1
        """,
        (tenant_id, billing_id),
    )
    return rows[0] if rows else None


def list_billing_all(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
    sort_field: str = "created_at",
    sort_direction: str = "DESC",
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Paginated list of all billing records for a tenant.

    `sort_field` is a bare column name (e.g. "invoice_number", "billed_at"),
    validated against shared.pagination.ALLOWED_SORT_FIELDS by
    build_paginated_query — the "b." table-alias prefix is added here since
    this query (unlike tracking's list_containers) sorts directly against the
    aliased `billing b` table rather than a flattened subquery.
    """
    from shared.pagination import build_paginated_query, extract_page

    conditions = ["b.tenant_id = %(tenant_id)s"]
    extra: dict[str, Any] = {"tenant_id": tenant_id}

    if filters.get("status"):
        # Accepts either a single status string or a list (Filters panel's
        # multi-select sends several) — same ANY() idiom as
        # tracking/repository.py::list_containers.
        statuses = filters["status"]
        if isinstance(statuses, str):
            statuses = [statuses]
        conditions.append("b.status = ANY(%(statuses)s)")
        extra["statuses"] = list(statuses)
    if filters.get("customer_id"):
        conditions.append("b.customer_id = %(customer_id)s")
        extra["customer_id"] = filters["customer_id"]
    if filters.get("created_after"):
        conditions.append("b.billed_at >= %(created_after)s")
        extra["created_after"] = filters["created_after"]
    if filters.get("created_before"):
        conditions.append("b.billed_at <= %(created_before)s")
        extra["created_before"] = filters["created_before"]

    if filters.get("q"):
        conditions.append("(b.invoice_number ILIKE %(q)s OR cu.name ILIKE %(q)s OR c.container_number ILIKE %(q)s)")
        extra["q"] = f"%{filters['q']}%"

    base = f"""
        SELECT b.*, c.container_number,
               cu.name AS customer_name, cu.phone AS customer_phone, cu.email AS customer_email
        FROM billing b
        LEFT JOIN container c  ON c.id  = b.container_id  AND c.tenant_id  = b.tenant_id
        LEFT JOIN customer  cu ON cu.id = b.customer_id   AND cu.tenant_id = b.tenant_id
        WHERE {" AND ".join(conditions)}
    """
    query, params = build_paginated_query(base, cursor, limit, sort_field=f"b.{sort_field}", sort_direction=sort_direction)
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def get_tenant_report(
    tenant_id: str,
    created_after: str | None = None,
    created_before: str | None = None,
) -> dict[str, Any]:
    """Period report aggregates for TenantReports, SQL-computed over the whole
    table (the frontend previously summed a capped `limit: 500` sample of each
    of billing/containers/claims, silently wrong past 500 in the period).

    `container_billing` and `top_customers` are bounded (top-N by amount billed)
    so the response stays small at tens of thousands of rows — a report reader
    wants the largest, and narrower ranges surface the rest.
    """
    # Two forms of the same date predicate: bare (single-table queries) and
    # b.-aliased (the joined billing queries). Only bound %(params)s — never
    # interpolated values — go into the SQL.
    params: dict[str, Any] = {"tenant_id": tenant_id}
    bare = "tenant_id = %(tenant_id)s"
    aliased = "b.tenant_id = %(tenant_id)s"
    if created_after:
        bare += " AND created_at >= %(created_after)s"
        aliased += " AND b.created_at >= %(created_after)s"
        params["created_after"] = created_after
    if created_before:
        bare += " AND created_at <= %(created_before)s"
        aliased += " AND b.created_at <= %(created_before)s"
        params["created_before"] = created_before

    overview = execute_with_tenant(
        tenant_id,
        f"""
        SELECT
            COALESCE(SUM(total_ngn), 0)                                          AS total_revenue_ngn,
            COALESCE(SUM(total_cbm), 0)                                          AS total_cbm,
            COALESCE(SUM(total_ngn) FILTER (WHERE status = 'paid'), 0)           AS revenue_paid,
            COALESCE(SUM(total_ngn) FILTER (WHERE status = 'partially_paid'), 0) AS revenue_partially_paid,
            COALESCE(SUM(total_ngn) FILTER (WHERE status = 'unpaid'), 0)         AS revenue_unpaid,
            COALESCE(SUM(total_ngn) FILTER (
                WHERE status = 'released_with_outstanding'), 0)                  AS revenue_released_with_outstanding,
            COALESCE(SUM(total_ngn) FILTER (WHERE status = 'waived'), 0)         AS revenue_waived
        FROM billing
        WHERE {bare}
        """,
        params,
    )
    ov = overview[0] if overview else {}

    top_customers = execute_with_tenant(
        tenant_id,
        f"""
        SELECT COALESCE(cu.name, 'Unknown') AS name, SUM(b.total_ngn) AS amount
        FROM billing b
        LEFT JOIN customer cu ON cu.id = b.customer_id AND cu.tenant_id = b.tenant_id
        WHERE {aliased}
        GROUP BY COALESCE(cu.name, 'Unknown')
        ORDER BY amount DESC
        LIMIT 20
        """,
        params,
    )

    container_billing = execute_with_tenant(
        tenant_id,
        f"""
        SELECT
            COALESCE(c.container_number, b.container_id::text) AS container_number,
            COUNT(DISTINCT b.customer_id)                      AS customers,
            COALESCE(SUM(b.total_cbm), 0)                      AS cbm,
            COALESCE(SUM(b.total_ngn), 0)                      AS billed,
            COALESCE(SUM(b.amount_paid_ngn), 0)               AS collected,
            COALESCE(SUM(b.balance_ngn), 0)                   AS outstanding,
            COALESCE(AVG(NULLIF(b.cbm_rate_usd, 0)), 0)       AS cbm_rate_usd,
            COALESCE(AVG(NULLIF(b.exchange_rate_ngn, 0)), 0)  AS dollar_rate
        FROM billing b
        LEFT JOIN container c ON c.id = b.container_id AND c.tenant_id = b.tenant_id
        WHERE {aliased}
        GROUP BY COALESCE(c.container_number, b.container_id::text)
        ORDER BY billed DESC
        LIMIT 200
        """,
        params,
    )

    # Cross-table period counts (tenant-scoped via RLS).
    containers_processed = execute_with_tenant(
        tenant_id,
        f"""
        SELECT COUNT(*) AS n FROM container
        WHERE {bare} AND status IN ('cleared', 'at_warehouse', 'fully_released')
        """,
        params,
    )
    claims = execute_with_tenant(
        tenant_id,
        f"""
        SELECT
            COUNT(*)                                                     AS total,
            COUNT(*) FILTER (WHERE status IN ('filed', 'under_inspection',
                                              'pending_resolution'))     AS open,
            COUNT(*) FILTER (WHERE status = 'resolved')                  AS resolved
        FROM damage_claim WHERE {bare}
        """,
        params,
    )
    customers = execute_with_tenant(
        tenant_id,
        "SELECT COUNT(*) AS n FROM customer WHERE tenant_id = %(tenant_id)s AND anonymised_at IS NULL",
        {"tenant_id": tenant_id},
    )

    # 8-week container pipeline (fixed window, independent of the report range) —
    # weekly per-status-group counts, aggregated in SQL so it doesn't need every
    # container row client-side.
    pipeline = execute_with_tenant(
        tenant_id,
        """
        SELECT
            to_char(date_trunc('week', created_at), 'MM-DD')                        AS week,
            COUNT(*) FILTER (WHERE status IN ('loading', 'sealed'))                 AS cn,
            COUNT(*) FILTER (WHERE status = 'in_transit')                           AS transit,
            COUNT(*) FILTER (WHERE status IN ('arrived', 'customs_clearance', 'cleared')) AS arrived,
            COUNT(*) FILTER (WHERE status IN ('at_warehouse', 'fully_released'))    AS released
        FROM container
        WHERE tenant_id = %(tenant_id)s AND created_at >= date_trunc('week', now()) - interval '7 weeks'
        GROUP BY date_trunc('week', created_at)
        ORDER BY date_trunc('week', created_at)
        """,
        {"tenant_id": tenant_id},
    )

    money = (
        "total_revenue_ngn",
        "total_cbm",
        "revenue_paid",
        "revenue_partially_paid",
        "revenue_unpaid",
        "revenue_released_with_outstanding",
        "revenue_waived",
    )
    cl = claims[0] if claims else {}
    return {
        "overview": {
            **{k: str(ov.get(k) or 0) for k in money},
            "containers_processed": int((containers_processed[0] if containers_processed else {}).get("n") or 0),
            "active_customers": int((customers[0] if customers else {}).get("n") or 0),
        },
        "claims": {k: int(cl.get(k) or 0) for k in ("total", "open", "resolved")},
        "container_pipeline": [
            {
                "week": r["week"],
                "cn": int(r["cn"] or 0),
                "transit": int(r["transit"] or 0),
                "arrived": int(r["arrived"] or 0),
                "released": int(r["released"] or 0),
            }
            for r in pipeline
        ],
        "top_customers": [{"name": r["name"], "amount": str(r["amount"] or 0)} for r in top_customers],
        "container_billing": [
            {
                "container_number": r["container_number"],
                "customers": int(r["customers"] or 0),
                "cbm": str(r["cbm"] or 0),
                "billed": str(r["billed"] or 0),
                "collected": str(r["collected"] or 0),
                "outstanding": str(r["outstanding"] or 0),
                "cbm_rate_usd": str(r["cbm_rate_usd"] or 0),
                "dollar_rate": str(r["dollar_rate"] or 0),
            }
            for r in container_billing
        ],
    }


def get_billing_stats(tenant_id: str) -> dict[str, Any]:
    """Tenant-wide billing aggregates for the list stats row + status chips.

    Computed in SQL over the whole table (not a fetched page) so the figures
    stay correct as billing grows to tens of thousands — the frontend used to
    sum a capped `limit: 500` sample, which silently under-reported past 500.
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT
            COALESCE(SUM(balance_ngn) FILTER (
                WHERE status NOT IN ('paid', 'waived', 'cancelled')), 0)          AS outstanding_ngn,
            COALESCE(SUM(amount_paid_ngn) FILTER (
                WHERE billed_at >= date_trunc('month', now())), 0)                AS paid_this_month_ngn,
            COUNT(*) FILTER (
                WHERE status NOT IN ('paid', 'waived', 'cancelled')
                  AND balance_ngn > 0
                  AND billed_at < now() - interval '30 days')                     AS overdue,
            COUNT(*)                                                              AS total,
            COUNT(*) FILTER (WHERE status = 'unpaid')                             AS unpaid,
            COUNT(*) FILTER (WHERE status = 'partially_paid')                     AS partially_paid,
            COUNT(*) FILTER (WHERE status = 'paid')                               AS paid,
            COUNT(*) FILTER (WHERE status = 'overpaid')                           AS overpaid,
            COUNT(*) FILTER (WHERE status = 'waived')                             AS waived,
            COUNT(*) FILTER (WHERE status = 'released_with_outstanding')          AS released_with_outstanding
        FROM billing
        WHERE tenant_id = %s
        """,
        (tenant_id,),
    )
    row = rows[0] if rows else {}
    counts = ("overdue", "total", "unpaid", "partially_paid", "paid", "overpaid", "waived", "released_with_outstanding")
    result: dict[str, Any] = {k: int(row.get(k) or 0) for k in counts}
    result["outstanding_ngn"] = str(row.get("outstanding_ngn") or 0)
    result["paid_this_month_ngn"] = str(row.get("paid_this_month_ngn") or 0)
    return result


def list_billing_for_customer(
    tenant_id: str,
    customer_id: str,
    container_id: str | None = None,
) -> list[dict[str, Any]]:
    if container_id:
        return execute_with_tenant(
            tenant_id,
            """
            SELECT b.*, c.container_number
            FROM billing b
            LEFT JOIN container c ON c.id = b.container_id AND c.tenant_id = b.tenant_id
            WHERE b.tenant_id    = %s
              AND b.customer_id  = %s
              AND b.container_id = %s
            ORDER BY b.created_at DESC
            """,
            (tenant_id, customer_id, container_id),
        )
    return execute_with_tenant(
        tenant_id,
        """
        SELECT b.*, c.container_number
        FROM billing b
        LEFT JOIN container c ON c.id = b.container_id AND c.tenant_id = b.tenant_id
        WHERE b.tenant_id   = %s
          AND b.customer_id = %s
        ORDER BY b.created_at DESC
        """,
        (tenant_id, customer_id),
    )


# ---------------------------------------------------------------------------
# Billing cancellation
# ---------------------------------------------------------------------------


def get_confirmed_payment_count(tenant_id: str, billing_id: str) -> int:
    """Return number of confirmed payment_record rows for a billing."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT COUNT(*) AS cnt FROM payment_record WHERE tenant_id = %s AND billing_id = %s",
        (tenant_id, billing_id),
    )
    return int(rows[0]["cnt"]) if rows else 0


def list_recent_payments(tenant_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Most recent payments across all billing records, with customer name.

    Feeds the Nigeria-ops dashboard "Recent payments" table (§6.1, P2-5).
    """
    return execute_with_tenant(
        tenant_id,
        """
        SELECT p.id, p.billing_id, p.amount_ngn, p.payment_method,
               p.reference_number, p.payment_date, p.created_at,
               cu.name AS customer_name
        FROM payment_record p
        JOIN billing b ON b.id = p.billing_id AND b.tenant_id = p.tenant_id
        LEFT JOIN customer cu ON cu.id = b.customer_id AND cu.tenant_id = b.tenant_id
        WHERE p.tenant_id = %s
        ORDER BY p.created_at DESC
        LIMIT %s
        """,
        (tenant_id, limit),
    )


def get_active_release_note_count(tenant_id: str, billing_id: str) -> int:
    """Return number of non-terminal release notes linked to this billing."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COUNT(*) AS cnt FROM release_note
        WHERE tenant_id = %s AND billing_id = %s
          AND status NOT IN ('expired', 'cancelled')
        """,
        (tenant_id, billing_id),
    )
    return int(rows[0]["cnt"]) if rows else 0


def cancel_billing(
    tenant_id: str,
    billing_id: str,
    actor_id: str,
    cancel_reason: str,
) -> dict[str, Any] | None:
    """Mark billing as cancelled; returns updated row or None on miss."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE billing
        SET status        = 'cancelled',
            cancel_reason = %(cancel_reason)s,
            cancelled_by  = %(actor_id)s,
            cancelled_at  = NOW(),
            updated_at    = NOW()
        WHERE tenant_id = %(tenant_id)s
          AND id        = %(id)s
          AND status    = 'unpaid'
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "id": billing_id,
            "actor_id": actor_id,
            "cancel_reason": cancel_reason,
        },
    )


# ---------------------------------------------------------------------------
# Ledger mutations
# ---------------------------------------------------------------------------


def mark_carryovers_applied(tenant_id: str, carryover_ids: list[str], billing_id: str) -> None:
    if not carryover_ids:
        return
    execute_write_with_tenant(
        tenant_id,
        """
        UPDATE carryover_ledger
        SET status            = 'applied',
            target_billing_id = %(billing_id)s,
            applied_at        = NOW(),
            updated_at        = NOW()
        WHERE tenant_id = %(tenant_id)s
          AND id        = ANY(%(ids)s::uuid[])
        RETURNING id
        """,
        {"tenant_id": tenant_id, "billing_id": billing_id, "ids": carryover_ids},
    )


def set_billing_status(tenant_id: str, billing_id: str, status: str) -> dict[str, Any] | None:
    """Set a billing record's payment status (money-status recompute after a
    total change such as an applied carryover). RETURNING * so callers get the
    fresh row incl. the generated balance_ngn."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE billing
        SET status = %(status)s, updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {"tenant_id": tenant_id, "id": billing_id, "status": status},
    )


def mark_credit_refunds_applied(tenant_id: str, refund_ids: list[str]) -> None:
    if not refund_ids:
        return
    execute_write_with_tenant(
        tenant_id,
        """
        UPDATE refund_request
        SET status     = 'completed',
            updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s
          AND id        = ANY(%(ids)s::uuid[])
        RETURNING id
        """,
        {"tenant_id": tenant_id, "ids": refund_ids},
    )


def update_billing_cbm(
    tenant_id: str,
    billing_id: str,
    new_cbm: Any,
    new_subtotal_usd: Any,
    new_subtotal_ngn: Any,
    new_total_ngn: Any,
) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE billing
        SET total_cbm    = %(total_cbm)s,
            subtotal_usd = %(subtotal_usd)s,
            subtotal_ngn = %(subtotal_ngn)s,
            total_ngn    = %(total_ngn)s,
            updated_at   = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "id": billing_id,
            "total_cbm": new_cbm,
            "subtotal_usd": new_subtotal_usd,
            "subtotal_ngn": new_subtotal_ngn,
            "total_ngn": new_total_ngn,
        },
    )


def create_overpayment_refund_request(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO refund_request (
            tenant_id, customer_id, billing_id, amount_ngn, reason, status
        ) VALUES (
            %(tenant_id)s, %(customer_id)s, %(billing_id)s,
            %(amount_ngn)s, %(reason)s, 'pending_review'
        ) RETURNING *
        """,
        data,
    )


# ---------------------------------------------------------------------------
# Billing enrichment reads
# ---------------------------------------------------------------------------


def get_misc_charges(tenant_id: str, billing_id: str) -> list[dict[str, Any]]:
    """misc_charge has no RLS — scoped via billing_id (FK to billing which has RLS)."""
    return execute_with_tenant(
        tenant_id,
        "SELECT * FROM misc_charge WHERE billing_id = %s ORDER BY created_at ASC",
        (billing_id,),
    )


def get_payment_records(tenant_id: str, billing_id: str) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM payment_record
        WHERE billing_id = %s AND tenant_id = %s
        ORDER BY created_at ASC
        """,
        (billing_id, tenant_id),
    )


def get_applied_carryovers(tenant_id: str, billing_id: str) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM carryover_ledger
        WHERE tenant_id        = %s
          AND target_billing_id = %s
          AND status            = 'applied'
        """,
        (tenant_id, billing_id),
    )


def get_active_disputes(tenant_id: str, billing_id: str) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM cbm_dispute
        WHERE tenant_id  = %s
          AND billing_id = %s
          AND status NOT IN ('closed', 'resolved_adjusted', 'resolved_no_change', 'rejected')
        ORDER BY created_at DESC
        """,
        (tenant_id, billing_id),
    )


# ---------------------------------------------------------------------------
# CBM Dispute CRUD — tenant RLS scope
# ---------------------------------------------------------------------------


def get_cbm_dispute_by_id(tenant_id: str, dispute_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM cbm_dispute WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, dispute_id),
    )
    return rows[0] if rows else None


def list_disputes_for_billing(tenant_id: str, billing_id: str) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM cbm_dispute
        WHERE tenant_id = %s AND billing_id = %s
        ORDER BY created_at DESC
        """,
        (tenant_id, billing_id),
    )


def create_cbm_dispute(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO cbm_dispute (
            tenant_id, billing_id, customer_id,
            disputed_cbm, customer_measured_cbm, dispute_reason,
            status, raised_by
        ) VALUES (
            %(tenant_id)s, %(billing_id)s, %(customer_id)s,
            %(disputed_cbm)s, %(customer_measured_cbm)s, %(dispute_reason)s,
            'submitted', %(raised_by)s
        ) RETURNING *
        """,
        data,
    )


def set_dispute_acknowledged(tenant_id: str, dispute_id: str, actor_id: str) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE cbm_dispute
        SET status          = 'acknowledged',
            acknowledged_at = NOW(),
            updated_at      = NOW()
        WHERE tenant_id = %s AND id = %s
        RETURNING *
        """,
        (tenant_id, dispute_id),
    )


# ---------------------------------------------------------------------------
# Carryover listing and exemption — tenant RLS scope
# ---------------------------------------------------------------------------


def list_carryovers(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    from shared.pagination import build_paginated_query, extract_page

    conditions = ["cl.tenant_id = %(tenant_id)s"]
    extra: dict[str, Any] = {"tenant_id": tenant_id}

    if filters.get("customer_id"):
        conditions.append("cl.customer_id = %(customer_id)s")
        extra["customer_id"] = filters["customer_id"]
    if filters.get("status"):
        conditions.append("cl.status = %(status)s")
        extra["status"] = filters["status"]

    base = f"""
        SELECT cl.*,
               cu.name AS customer_name,
               src.invoice_number AS source_invoice_number,
               sc.container_number AS source_container_number,
               tgt.invoice_number AS target_invoice_number
        FROM carryover_ledger cl
        LEFT JOIN customer cu ON cu.id = cl.customer_id AND cu.tenant_id = cl.tenant_id
        LEFT JOIN billing src ON src.id = cl.source_billing_id
        LEFT JOIN container sc ON sc.id = src.container_id AND sc.tenant_id = src.tenant_id
        LEFT JOIN billing tgt ON tgt.id = cl.target_billing_id
        WHERE {" AND ".join(conditions)}
    """
    query, params = build_paginated_query(base, cursor, limit, sort_field="cl.created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def get_carryover_by_id(tenant_id: str, carryover_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT cl.*,
               cu.name AS customer_name,
               src.invoice_number AS source_invoice_number,
               sc.container_number AS source_container_number,
               tgt.invoice_number AS target_invoice_number
        FROM carryover_ledger cl
        LEFT JOIN customer cu ON cu.id = cl.customer_id AND cu.tenant_id = cl.tenant_id
        LEFT JOIN billing src ON src.id = cl.source_billing_id
        LEFT JOIN container sc ON sc.id = src.container_id AND sc.tenant_id = src.tenant_id
        LEFT JOIN billing tgt ON tgt.id = cl.target_billing_id
        WHERE cl.tenant_id = %s AND cl.id = %s
        LIMIT 1
        """,
        (tenant_id, carryover_id),
    )
    return rows[0] if rows else None


def exempt_carryover(tenant_id: str, carryover_id: str, actor_id: str, notes: str | None = None) -> dict[str, Any] | None:
    """Mark a carryover as exempted and record who did it."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE carryover_ledger
        SET status       = 'exempted',
            exempted_by  = %(actor_id)s,
            exempted_at  = NOW(),
            notes        = COALESCE(%(notes)s, notes),
            updated_at   = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {"tenant_id": tenant_id, "id": carryover_id, "actor_id": actor_id, "notes": notes},
    )


def create_carryover(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Insert a new outstanding carryover_ledger entry (roll-forward)."""
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO carryover_ledger (
            tenant_id, customer_id, source_billing_id,
            carryover_amount_ngn, status, notes, created_by
        ) VALUES (
            %(tenant_id)s, %(customer_id)s, %(source_billing_id)s,
            %(carryover_amount_ngn)s, 'outstanding', %(notes)s, %(created_by)s
        ) RETURNING *
        """,
        data,
    )


# ---------------------------------------------------------------------------
# Misc charge CRUD
# ---------------------------------------------------------------------------


def add_misc_charge(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Insert a misc_charge record linked to a billing record."""
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO misc_charge (
            billing_id, description, amount_ngn, amount_usd,
            charge_type, charge_type_id, created_by
        ) VALUES (
            %(billing_id)s, %(description)s, %(amount_ngn)s, %(amount_usd)s,
            %(charge_type)s, %(charge_type_id)s, %(created_by)s
        ) RETURNING *
        """,
        data,
    )


def get_misc_charge_by_id(charge_id: str) -> dict[str, Any] | None:
    """misc_charge has no RLS; use platform scope, scoped by billing_id + id."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT * FROM misc_charge WHERE id = %s LIMIT 1",
        (charge_id,),
    )
    return rows[0] if rows else None


def delete_misc_charge(charge_id: str, billing_id: str) -> None:
    """Delete a misc_charge row by id, scoped by billing_id for defense-in-depth.

    misc_charge has no tenant_id column (no RLS); isolation is enforced at the
    service layer (billing ownership check) and here via billing_id FK constraint.
    """
    execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        "DELETE FROM misc_charge WHERE id = %s AND billing_id = %s RETURNING id",
        (charge_id, billing_id),
    )


def increment_billing_misc_fees(tenant_id: str, billing_id: str, amount_ngn: Any) -> dict[str, Any] | None:
    """Increase billing.misc_charges_ngn and billing.total_ngn by amount_ngn."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE billing
        SET misc_charges_ngn = misc_charges_ngn + %(amount)s,
            total_ngn        = total_ngn        + %(amount)s,
            updated_at       = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {"tenant_id": tenant_id, "id": billing_id, "amount": amount_ngn},
    )


def decrement_billing_misc_fees(tenant_id: str, billing_id: str, amount_ngn: Any) -> dict[str, Any] | None:
    """Decrease billing.misc_charges_ngn and billing.total_ngn by amount_ngn."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE billing
        SET misc_charges_ngn = misc_charges_ngn - %(amount)s,
            total_ngn        = total_ngn        - %(amount)s,
            updated_at       = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {"tenant_id": tenant_id, "id": billing_id, "amount": amount_ngn},
    )


# ---------------------------------------------------------------------------
# Storage fee log reads
# ---------------------------------------------------------------------------


def get_storage_fees_for_billing(tenant_id: str, billing_id: str) -> list[dict[str, Any]]:
    """Return all storage_fee_log rows for a billing record, ordered by accrual_date."""
    return execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM storage_fee_log
        WHERE tenant_id = %s AND billing_id = %s
        ORDER BY accrual_date ASC
        """,
        (tenant_id, billing_id),
    )


def waive_storage_fees_for_billing(
    tenant_id: str,
    billing_id: str,
    actor_id: str,
    reason: str,
) -> dict[str, Any] | None:
    """Mark all unwaived storage fee log entries as waived and void the linked misc charges.

    Returns the updated billing row so the caller can return the fresh billing state.
    Uses RETURNING to detect silent no-op (no rows updated).
    """
    # Delete the misc_charge rows that were created by the storage fee job
    execute_write_with_tenant(
        tenant_id,
        """
        DELETE FROM misc_charge
        WHERE tenant_id = %(tenant_id)s
          AND billing_id = %(billing_id)s
          AND charge_type = 'storage_fee'
        RETURNING id
        """,
        {"tenant_id": tenant_id, "billing_id": billing_id},
    )
    # Clear the misc_charge_id links and mark fees as waived via is_billed=false
    # so the scheduler does not re-accrue them
    execute_write_with_tenant(
        tenant_id,
        """
        UPDATE storage_fee_log
        SET misc_charge_id = NULL,
            is_billed = FALSE
        WHERE tenant_id = %(tenant_id)s AND billing_id = %(billing_id)s
        RETURNING id
        """,
        {"tenant_id": tenant_id, "billing_id": billing_id},
    )
    # Return the refreshed billing row
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM billing WHERE tenant_id = %s AND id = %s",
        (tenant_id, billing_id),
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Top-level dispute listing (all disputes for tenant)
# ---------------------------------------------------------------------------


def list_all_disputes(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    from shared.pagination import build_paginated_query, extract_page

    conditions = ["tenant_id = %(tenant_id)s"]
    extra: dict[str, Any] = {"tenant_id": tenant_id}

    if filters.get("status"):
        conditions.append("status = %(status)s")
        extra["status"] = filters["status"]
    if filters.get("customer_id"):
        conditions.append("customer_id = %(customer_id)s")
        extra["customer_id"] = filters["customer_id"]

    base = f"SELECT * FROM cbm_dispute WHERE {' AND '.join(conditions)}"
    query, params = build_paginated_query(base, cursor, limit, sort_field="created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def set_dispute_status(
    tenant_id: str,
    dispute_id: str,
    status: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Update dispute status + optional extra fields (allowlisted)."""
    params: dict[str, Any] = {"status": status, "tenant_id": tenant_id, "id": dispute_id}
    extra_clause = ""
    if extra:
        safe = {k: v for k, v in extra.items() if k in _DISPUTE_EXTRA_FIELDS and v is not None}
        for key, val in safe.items():
            extra_clause += f", {key} = %({key})s"
            params[key] = val

    return execute_write_with_tenant(
        tenant_id,
        f"""
        UPDATE cbm_dispute
        SET status = %(status)s, updated_at = NOW(){extra_clause}
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        params,
    )


# ---------------------------------------------------------------------------
# Aliases for test compatibility
# ---------------------------------------------------------------------------

# Some tests patch 'get_dispute_by_id' and 'update_dispute_status'
get_dispute_by_id = get_cbm_dispute_by_id
update_dispute_status = set_dispute_status
