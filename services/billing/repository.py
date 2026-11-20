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
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from shared.billing_money import (
    adjust_billing,
    adjust_billing_and_refund_overpayment,
    lock_billing,
)
from shared.db import (
    execute_with_tenant,
    execute_write_with_tenant,
    execute_write_with_tenant_many,
    next_tenant_counter,
    tenant_transaction,
)
from shared.list_filters import billing_filter, overdue_condition
from shared.tenant_context import PLATFORM_TENANT_ID

# Owed for over 30 days: a fixed SQL fragment (no input), shared with the invoice list's `overdue` filter.
_OVERDUE = overdue_condition()

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
    """Credits the customer still holds, oldest first.

    A credit is a refund approved as credit for the next shipment. Its value is the approved amount, and
    ``credit_applied_ngn`` is how much of it earlier invoices have already used.
    """
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


# ---------------------------------------------------------------------------
# Billing CRUD — tenant RLS scope
# ---------------------------------------------------------------------------


class BillingStatusConflict(Exception):
    """The invoice is not in a status the operation allows (checked under the row lock)."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


class RecordNotFound(Exception):
    """The row the operation targets no longer exists (e.g. it was removed by a concurrent request)."""


def list_unbilled_customers(tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """Customers with CBM to bill on a cleared container who have no live invoice.

    Only customers with something to bill appear: a customer whose approved packing
    lists carry no CBM is legitimately uninvoiced and would be noise here forever.
    Most recently moved containers first.
    """
    return execute_with_tenant(
        tenant_id,
        """
        SELECT c.id::text AS container_id, c.container_number, c.status AS container_status,
               cu.id::text AS customer_id, cu.name AS customer_name,
               SUM(pli.cbm) AS total_cbm
          FROM container c
          JOIN packing_list pl ON pl.container_id = c.id AND pl.tenant_id = c.tenant_id AND pl.status = 'approved'
          JOIN packing_list_item pli ON pli.packing_list_id = pl.id
          JOIN customer cu ON cu.id = pl.customer_id AND cu.tenant_id = c.tenant_id
         WHERE c.tenant_id = %s
           AND c.status IN ('cleared', 'at_warehouse', 'fully_released')
           AND NOT EXISTS (
               SELECT 1 FROM billing b
                WHERE b.tenant_id = c.tenant_id AND b.container_id = c.id AND b.customer_id = cu.id AND b.status <> 'cancelled'
           )
         GROUP BY c.id, c.container_number, c.status, c.updated_at, cu.id, cu.name
        HAVING SUM(pli.cbm) > 0
         ORDER BY c.updated_at DESC, cu.name
         LIMIT %s
        """,
        (tenant_id, limit),
    )


def get_container_for_billing(tenant_id: str, container_id: str) -> dict[str, Any] | None:
    """Container id, number and status, for the billing guards."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id::text AS id, container_number, status FROM container WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, container_id),
    )
    return rows[0] if rows else None


def get_billable_customers_for_container(tenant_id: str, container_id: str) -> list[dict[str, Any]]:
    """Distinct customers with an approved packing list on the container."""
    return execute_with_tenant(
        tenant_id,
        """
        SELECT DISTINCT c.id::text AS id, c.name
          FROM customer c
          JOIN packing_list pl ON pl.customer_id = c.id AND pl.tenant_id = c.tenant_id
         WHERE pl.container_id = %s AND pl.tenant_id = %s AND pl.status = 'approved'
         ORDER BY c.name
        """,
        (container_id, tenant_id),
    )


class LedgerConflictError(RuntimeError):
    """A carryover or credit was applied by another request while this invoice was being built.

    Raised inside the invoice transaction so everything rolls back, including the
    invoice-number increment. The caller reports the customer as failed and the
    generate-missing-invoices action picks it up again with fresh ledger data.
    """


@dataclass(frozen=True)
class CreditApplication:
    """Part or all of one customer credit, put against one invoice.

    Attributes:
        refund_id: The credit (a ``refund_request`` approved as credit for the next shipment).
        applied_before_ngn: How much of that credit earlier invoices had used when this was worked out. The write
            only goes through if that is still true, so two invoices cannot spend the same credit.
        amount_ngn: How much of it this invoice uses.
    """

    refund_id: str
    applied_before_ngn: Decimal
    amount_ngn: Decimal


class _AlreadyBilled(Exception):
    """Internal: the insert found a live invoice already in place (lost a race)."""


_LIVE_INVOICE_SQL = """
    SELECT * FROM billing
     WHERE tenant_id = %s AND customer_id = %s AND container_id = %s AND status <> 'cancelled'
     LIMIT 1
"""


def get_live_invoice(tenant_id: str, customer_id: str, container_id: str) -> dict[str, Any] | None:
    """The customer's non-cancelled invoice for a container, if one exists."""
    rows = execute_with_tenant(tenant_id, _LIVE_INVOICE_SQL, (tenant_id, customer_id, container_id))
    return rows[0] if rows else None


def create_invoice(
    tenant_id: str,
    data: dict[str, Any],
    number_prefix: str,
    carryover_ids: list[str],
    credit_applications: list[CreditApplication],
) -> tuple[dict[str, Any], bool]:
    """Create one invoice atomically, or return the one that already exists.

    In a single transaction this allocates the next invoice number from the
    tenant counter, inserts the invoice, marks the carryovers it absorbed as
    applied and takes what it used from each credit, recording each use in
    ``billing_credit_application`` so a cancellation can give it back. Either all
    of that happens or none of it does.

    A credit is spent only as far as the invoice needed it: what is left stays
    ``applied_as_credit`` for the next invoice, and the credit becomes
    ``processed`` once it is used up (``completed`` is not a status the table allows: the old code that set it
    failed every invoice that used a credit, found by tests/db/test_invoice_credits.py on 2026-11-17).
    The invoice records the sum it took in
    ``credits_applied_ngn``.

    Idempotent per (customer, container): if a live invoice is already there it
    is returned untouched with ``created=False`` and no number is consumed.

    Args:
        tenant_id: Tenant the invoice belongs to.
        data: Invoice columns except ``invoice_number``.
        number_prefix: Everything before the sequence, e.g. ``ACM-INV-20261114``.
        carryover_ids: Outstanding carryover ledger rows folded into the total.
        credit_applications: What this invoice takes from each credit.

    Returns:
        ``(invoice_row, created)``.

    Raises:
        LedgerConflictError: A carryover or credit was already applied elsewhere.
    """
    try:
        with tenant_transaction(tenant_id) as cur:
            cur.execute(_LIVE_INVOICE_SQL, (tenant_id, data["customer_id"], data["container_id"]))
            existing = cur.fetchone()
            if existing:
                return dict(existing), False

            seq = next_tenant_counter(cur, tenant_id, "invoice")
            cur.execute(
                """
                INSERT INTO billing (
                    tenant_id, customer_id, container_id, invoice_number,
                    total_cartons, total_cbm, cbm_rate_usd, cbm_rate_currency,
                    cbm_rate_mode, cbm_breakdown, subtotal_usd,
                    exchange_rate_ngn, exchange_rate_source, exchange_rate_fetched_at,
                    subtotal_ngn, misc_charges_ngn, credits_applied_ngn,
                    total_ngn, amount_paid_ngn, status, billed_at, created_by
                ) VALUES (
                    %(tenant_id)s, %(customer_id)s, %(container_id)s, %(invoice_number)s,
                    %(total_cartons)s, %(total_cbm)s, %(cbm_rate_usd)s, %(cbm_rate_currency)s,
                    %(cbm_rate_mode)s, %(cbm_breakdown)s::jsonb, %(subtotal_usd)s,
                    %(exchange_rate_ngn)s, %(exchange_rate_source)s, %(exchange_rate_fetched_at)s,
                    %(subtotal_ngn)s, %(misc_charges_ngn)s, %(credits_applied_ngn)s,
                    %(total_ngn)s, %(amount_paid_ngn)s, %(status)s, %(billed_at)s, %(created_by)s
                )
                ON CONFLICT (tenant_id, customer_id, container_id) WHERE status <> 'cancelled'
                DO NOTHING
                RETURNING *
                """,
                {
                    # Unknown unless the caller says (migration 068): an invoice built without a market rate lookup.
                    "exchange_rate_source": None,
                    "exchange_rate_fetched_at": None,
                    **data,
                    "invoice_number": f"{number_prefix}-{seq:04d}",
                    "credits_applied_ngn": sum((c.amount_ngn for c in credit_applications), Decimal("0")),
                },
            )
            row = cur.fetchone()
            if row is None:
                raise _AlreadyBilled
            invoice = dict(row)

            if carryover_ids:
                cur.execute(
                    """
                    UPDATE carryover_ledger
                       SET status = 'applied', target_billing_id = %(billing_id)s,
                           applied_at = NOW(), updated_at = NOW()
                     WHERE tenant_id = %(tenant_id)s AND id = ANY(%(ids)s::uuid[]) AND status = 'outstanding'
                    RETURNING id
                    """,
                    {"tenant_id": tenant_id, "billing_id": invoice["id"], "ids": carryover_ids},
                )
                if len(cur.fetchall()) != len(carryover_ids):
                    raise LedgerConflictError("a carryover was applied by another request")
            for credit in credit_applications:
                cur.execute(
                    """
                    UPDATE refund_request
                       SET credit_applied_ngn = credit_applied_ngn + %(amount)s,
                           status = CASE
                               WHEN credit_applied_ngn + %(amount)s >= COALESCE(amount_approved_ngn, amount_ngn)
                               THEN 'processed' ELSE status
                           END,
                           updated_at = NOW()
                     WHERE tenant_id = %(tenant_id)s AND id = %(id)s AND status = 'applied_as_credit'
                       AND credit_applied_ngn = %(applied_before)s
                       AND credit_applied_ngn + %(amount)s <= COALESCE(amount_approved_ngn, amount_ngn)
                    RETURNING id
                    """,
                    {
                        "tenant_id": tenant_id,
                        "id": credit.refund_id,
                        "amount": credit.amount_ngn,
                        "applied_before": credit.applied_before_ngn,
                    },
                )
                if cur.fetchone() is None:
                    raise LedgerConflictError("a credit was applied by another request")
                # Which credit this invoice used, and how much: what cancelling the invoice gives back (migration 070).
                cur.execute(
                    """
                    INSERT INTO billing_credit_application (tenant_id, billing_id, refund_request_id, amount_ngn)
                    VALUES (%(tenant_id)s, %(billing_id)s, %(refund_id)s, %(amount)s)
                    RETURNING id
                    """,
                    {
                        "tenant_id": tenant_id,
                        "billing_id": invoice["id"],
                        "refund_id": credit.refund_id,
                        "amount": credit.amount_ngn,
                    },
                )
            return invoice, True
    except _AlreadyBilled:
        existing_row = get_live_invoice(tenant_id, data["customer_id"], data["container_id"])
        if existing_row is None:
            raise RuntimeError("invoice insert conflicted but no live invoice was found") from None
        return existing_row, False


def get_billing_by_id(tenant_id: str, billing_id: str) -> dict[str, Any] | None:
    """Fetch one billing row by its own id, joined the same way as list_billing_all.

    The customer join matters: service._enrich_billing() reads customer_name /
    customer_phone / customer_email off the row, so without it a single-record
    read would return a billing whose customer fields are all null while the
    same record listed via GET /v1/billing carries them.
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT b.*, c.container_number,
               cu.name AS customer_name, cu.phone AS customer_phone, cu.email AS customer_email
        FROM billing b
        LEFT JOIN container c  ON c.id  = b.container_id  AND c.tenant_id  = b.tenant_id
        LEFT JOIN customer  cu ON cu.id = b.customer_id   AND cu.tenant_id = b.tenant_id
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

    where_clause, extra = billing_filter(tenant_id, filters)

    base = f"""
        SELECT b.*, c.container_number,
               cu.name AS customer_name, cu.phone AS customer_phone, cu.email AS customer_email
        FROM billing b
        LEFT JOIN container c  ON c.id  = b.container_id  AND c.tenant_id  = b.tenant_id
        LEFT JOIN customer  cu ON cu.id = b.customer_id   AND cu.tenant_id = b.tenant_id
        WHERE {where_clause}
    """
    query, params = build_paginated_query(base, cursor, limit, sort_field=f"b.{sort_field}", sort_direction=sort_direction)
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit, sort_field)


#: How many containers the report page lists: the largest by amount billed. The export has every container.
REPORT_CONTAINER_ROWS = 200


def get_container_billing(
    tenant_id: str,
    created_after: str | None,
    created_before: str | None,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Billing for the period summed per container, largest amount billed first.

    Backs the report page's "CBM & billing by container" table (the top `REPORT_CONTAINER_ROWS`) and its export
    (every container; the caller passes one more than its row limit to learn whether the period has more).

    Args:
        tenant_id: Owning tenant.
        created_after: Earliest billing `created_at` to include, or None for no lower bound.
        created_before: Latest billing `created_at` to include, or None for no upper bound.
        limit: Most rows to return.

    Returns:
        One row per container: number, customer count, CBM, amounts billed, collected and outstanding, and the
        average CBM rate and dollar rate its invoices used.
    """
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": limit}
    where = "b.tenant_id = %(tenant_id)s"
    if created_after:
        where += " AND b.created_at >= %(created_after)s"
        params["created_after"] = created_after
    if created_before:
        where += " AND b.created_at <= %(created_before)s"
        params["created_before"] = created_before
    return execute_with_tenant(
        tenant_id,
        f"""
        SELECT
            COALESCE(c.container_number, b.container_id::text) AS container_number,
            COUNT(DISTINCT b.customer_id)                      AS customers,
            COALESCE(SUM(b.total_cbm), 0)                      AS cbm,
            COALESCE(SUM(b.total_ngn), 0)                      AS billed,
            COALESCE(SUM(b.amount_paid_ngn), 0)                AS collected,
            COALESCE(SUM(b.balance_ngn), 0)                    AS outstanding,
            -- Averages kept at the columns' own 4 places, not AVG's 16.
            COALESCE(ROUND(AVG(NULLIF(b.cbm_rate_usd, 0)), 4), 0)      AS cbm_rate_usd,
            COALESCE(ROUND(AVG(NULLIF(b.exchange_rate_ngn, 0)), 4), 0) AS dollar_rate
        FROM billing b
        LEFT JOIN container c ON c.id = b.container_id AND c.tenant_id = b.tenant_id
        WHERE {where}
        GROUP BY COALESCE(c.container_number, b.container_id::text)
        ORDER BY billed DESC, container_number
        LIMIT %(limit)s
        """,  # noqa: S608 - only the fixed date predicates are interpolated; every value is a bound parameter
        params,
    )


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

    container_billing = get_container_billing(tenant_id, created_after, created_before, limit=REPORT_CONTAINER_ROWS)

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
            COUNT(*) FILTER (WHERE """
        + _OVERDUE
        + """)                                                                    AS overdue,
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


def get_credit_applications(tenant_id: str, billing_id: str) -> list[dict[str, Any]]:
    """The credits an invoice used and has not given back, oldest first."""
    return execute_with_tenant(
        tenant_id,
        """
        SELECT id, refund_request_id, amount_ngn, created_at
          FROM billing_credit_application
         WHERE tenant_id = %s AND billing_id = %s AND reversed_at IS NULL
         ORDER BY created_at, id
        """,
        (tenant_id, billing_id),
    )


@dataclass(frozen=True)
class CancelledInvoice:
    """An invoice cancelled, with what the cancellation gave back.

    Attributes:
        row: The billing row, now ``cancelled``.
        credits_restored: ``(refund_request_id, amount_ngn)`` for each credit returned to the customer.
        carryovers_reopened: Carryover ledger rows put back to ``outstanding`` for the next invoice.
    """

    row: dict[str, Any]
    credits_restored: list[tuple[str, Decimal]]
    carryovers_reopened: list[str]


def cancel_billing(
    tenant_id: str,
    billing_id: str,
    actor_id: str,
    cancel_reason: str,
) -> CancelledInvoice | None:
    """Cancel an unpaid invoice and undo what issuing it took, in one transaction.

    - The credits it used go back to their ``refund_request``: ``credit_applied_ngn`` falls by the amount, and a
      credit it had used up (``processed``) is ``applied_as_credit`` again. Each ``billing_credit_application`` row is
      stamped ``reversed_at``.
    - The earlier balances it carried over (``carryover_ledger`` rows ``applied`` to it) are ``outstanding`` again,
      so the customer's next invoice picks them up rather than the debt disappearing.

    Returns:
        What was cancelled and given back, or None if no unpaid invoice with that id exists (another request
        changed it first: nothing is written).

    Raises:
        LedgerConflictError: A credit could not be given back as recorded; everything rolls back.
    """
    with tenant_transaction(tenant_id) as cur:
        cur.execute(
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
            {"tenant_id": tenant_id, "id": billing_id, "actor_id": actor_id, "cancel_reason": cancel_reason},
        )
        row = cur.fetchone()
        if row is None:
            return None

        cur.execute(
            """
            UPDATE billing_credit_application
               SET reversed_at = NOW()
             WHERE tenant_id = %s AND billing_id = %s AND reversed_at IS NULL
            RETURNING refund_request_id, amount_ngn
            """,
            (tenant_id, billing_id),
        )
        restored = [(str(r["refund_request_id"]), Decimal(str(r["amount_ngn"]))) for r in cur.fetchall()]
        for refund_id, amount in restored:
            cur.execute(
                """
                UPDATE refund_request
                   SET credit_applied_ngn = credit_applied_ngn - %(amount)s,
                       status = CASE WHEN status = 'processed' THEN 'applied_as_credit' ELSE status END,
                       updated_at = NOW()
                 WHERE tenant_id = %(tenant_id)s AND id = %(id)s
                   AND status IN ('applied_as_credit', 'processed')
                   AND credit_applied_ngn >= %(amount)s
                RETURNING id
                """,
                {"tenant_id": tenant_id, "id": refund_id, "amount": amount},
            )
            if cur.fetchone() is None:
                raise LedgerConflictError("a credit used by this invoice could not be given back")

        cur.execute(
            """
            UPDATE carryover_ledger
               SET status = 'outstanding', target_billing_id = NULL, applied_at = NULL, updated_at = NOW()
             WHERE tenant_id = %s AND target_billing_id = %s AND status = 'applied'
            RETURNING id
            """,
            (tenant_id, billing_id),
        )
        reopened = [str(r["id"]) for r in cur.fetchall()]
        return CancelledInvoice(row=dict(row), credits_restored=restored, carryovers_reopened=reopened)


# ---------------------------------------------------------------------------
# Ledger mutations
# ---------------------------------------------------------------------------


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


def get_dispute_measurements(tenant_id: str, dispute_id: str) -> dict[str, Any] | None:
    """A dispute with the measurement facts around it, and no payment data.

    China staff resolve disputes but are not allowed to read invoices, so this selects only what they need to
    judge a measurement: the dispute itself, the customer's and container's names, the CBM that was billed, and
    the packing-list lines that CBM was summed from. `b.total_cbm` is read; no amount, rate or payment column is.
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT d.*, b.total_cbm AS billed_cbm, b.container_id,
               cu.name AS customer_name, co.container_number
        FROM cbm_dispute d
        JOIN billing b ON b.id = d.billing_id AND b.tenant_id = d.tenant_id
        LEFT JOIN customer cu ON cu.id = d.customer_id AND cu.tenant_id = d.tenant_id
        LEFT JOIN container co ON co.id = b.container_id AND co.tenant_id = d.tenant_id
        WHERE d.tenant_id = %s AND d.id = %s
        LIMIT 1
        """,
        (tenant_id, dispute_id),
    )
    return rows[0] if rows else None


def list_measurement_lines(tenant_id: str, container_id: str, customer_id: str) -> list[dict[str, Any]]:
    """The approved packing-list lines a customer's CBM on one container is summed from (same set as the invoice)."""
    return execute_with_tenant(
        tenant_id,
        """
        SELECT pli.carton_tag, pli.description, pli.quantity, pli.package_unit, pli.cbm,
               pli.length_cm, pli.width_cm, pli.height_cm, pli.weight_actual_kg, pl.reference
        FROM packing_list_item pli
        JOIN packing_list pl ON pl.id = pli.packing_list_id AND pl.tenant_id = %s
        WHERE pl.container_id = %s AND pl.customer_id = %s AND pl.status = 'approved'
        ORDER BY pl.reference, pli.carton_tag
        """,
        (tenant_id, container_id, customer_id),
    )


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


def add_misc_charge_to_billing(tenant_id: str, data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Add a misc charge and move the invoice total, atomically.

    The charge row, the new total and the recomputed status commit together. A
    ``paid`` invoice that gains a charge becomes ``partially_paid`` instead of
    staying ``paid`` while owing.

    Returns:
        ``(charge, updated_invoice)``.
    """
    amount = Decimal(str(data["amount_ngn"]))
    with tenant_transaction(tenant_id):
        charge = add_misc_charge(tenant_id, data)
        if charge is None:
            raise RuntimeError("misc_charge insert returned nothing")
        billing = adjust_billing(tenant_id, str(data["billing_id"]), amount, amount)
        if billing is None:
            raise RuntimeError(f"billing {data['billing_id']} not found in tenant")
    return charge, billing


def get_misc_charge_by_id(charge_id: str) -> dict[str, Any] | None:
    """misc_charge has no RLS; use platform scope, scoped by billing_id + id."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT * FROM misc_charge WHERE id = %s LIMIT 1",
        (charge_id,),
    )
    return rows[0] if rows else None


def delete_misc_charge_from_billing(
    tenant_id: str,
    charge_id: str,
    billing_id: str,
    required_status: str,
) -> dict[str, Any]:
    """Remove a misc charge and take its amount off the invoice, atomically.

    The invoice row is locked first and its status re-checked, so a payment that
    arrives between the caller's check and this write cannot slip past it. The
    amount taken off is the one actually deleted, so two requests deleting the same
    charge reduce the total once, not twice.

    Raises:
        BillingStatusConflict: The invoice is not in ``required_status``.
        RecordNotFound: The charge is already gone.
    """
    with tenant_transaction(tenant_id):
        billing = lock_billing(tenant_id, billing_id)
        if billing is None:
            raise RuntimeError(f"billing {billing_id} not found in tenant")
        if billing["status"] != required_status:
            raise BillingStatusConflict(str(billing["status"]))
        deleted = execute_write_with_tenant(
            tenant_id,
            "DELETE FROM misc_charge WHERE id = %s AND billing_id = %s RETURNING *",
            (charge_id, billing_id),
        )
        if deleted is None:
            raise RecordNotFound(charge_id)
        amount = Decimal(str(deleted["amount_ngn"]))
        updated = adjust_billing(tenant_id, billing_id, -amount, -amount)
        if updated is None:
            raise RuntimeError(f"billing {billing_id} not found in tenant")
    return updated


def apply_carryover_to_billing(
    tenant_id: str,
    billing_id: str,
    carryover_id: str,
    customer_id: str,
) -> tuple[dict[str, Any], Decimal]:
    """Apply an outstanding carryover to an invoice, atomically.

    Under the invoice lock: re-check the invoice can take it, mark the carryover
    applied only if it is still ``outstanding`` and the customer's, add the amount
    and recompute the status. Two requests applying the same carryover cannot both
    succeed.

    Returns:
        ``(updated_invoice, carryover_amount)``.

    Raises:
        BillingStatusConflict: The invoice is cancelled or waived.
        RecordNotFound: The carryover is no longer outstanding or is not this customer's.
    """
    with tenant_transaction(tenant_id):
        billing = lock_billing(tenant_id, billing_id)
        if billing is None:
            raise RuntimeError(f"billing {billing_id} not found in tenant")
        if billing["status"] in {"cancelled", "waived"}:
            raise BillingStatusConflict(str(billing["status"]))
        applied = execute_write_with_tenant(
            tenant_id,
            """
            UPDATE carryover_ledger
               SET status = 'applied', target_billing_id = %(billing_id)s, applied_at = NOW(), updated_at = NOW()
             WHERE tenant_id = %(tenant_id)s AND id = %(id)s AND status = 'outstanding' AND customer_id = %(customer_id)s
            RETURNING carryover_amount_ngn
            """,
            {"tenant_id": tenant_id, "billing_id": billing_id, "id": carryover_id, "customer_id": customer_id},
        )
        if applied is None:
            raise RecordNotFound(carryover_id)
        amount = Decimal(str(applied["carryover_amount_ngn"]))
        updated = adjust_billing(tenant_id, billing_id, amount, amount)
        if updated is None:
            raise RuntimeError(f"billing {billing_id} not found in tenant")
    return updated, amount


def resolve_dispute_with_adjustment(
    tenant_id: str,
    dispute_id: str,
    billing_id: str,
    allowed_from: list[str],
    new_cbm: Decimal,
    new_subtotal_usd: Decimal,
    new_subtotal_ngn: Decimal,
    dispute_extra: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], Decimal]:
    """Resolve a CBM dispute and re-price the invoice, atomically.

    Under the invoice lock: set the new CBM and subtotals, move the total by the
    difference measured against the *current* subtotal, recompute the status, open
    a refund for any new overpayment, and move the dispute to ``resolved_adjusted``
    only if it is still in one of ``allowed_from``. A payment that lands during the
    resolution is kept, not overwritten, and a dispute resolved twice reprices once.

    Returns:
        ``(dispute, updated_invoice, overpayment_refunded)``.

    Raises:
        RecordNotFound: The dispute is no longer in a resolvable status.
    """
    with tenant_transaction(tenant_id):
        billing = lock_billing(tenant_id, billing_id)
        if billing is None:
            raise RuntimeError(f"billing {billing_id} not found in tenant")
        dispute = set_dispute_status(tenant_id, dispute_id, "resolved_adjusted", dispute_extra, allowed_from=allowed_from)
        if dispute is None:
            raise RecordNotFound(dispute_id)
        delta = new_subtotal_ngn - Decimal(str(billing["subtotal_ngn"]))
        execute_write_with_tenant(
            tenant_id,
            """
            UPDATE billing
               SET total_cbm = %(cbm)s, subtotal_usd = %(usd)s, subtotal_ngn = %(ngn)s, updated_at = NOW()
             WHERE tenant_id = %(tenant_id)s AND id = %(id)s
            RETURNING id
            """,
            {"tenant_id": tenant_id, "id": billing_id, "cbm": new_cbm, "usd": new_subtotal_usd, "ngn": new_subtotal_ngn},
        )
        updated, overpayment = adjust_billing_and_refund_overpayment(
            tenant_id, billing_id, delta, f"CBM dispute overpayment — dispute {dispute_id}"
        )
    return dispute, updated, overpayment


# ---------------------------------------------------------------------------
# Storage fee log reads
# ---------------------------------------------------------------------------


def get_storage_fees_for_billing(tenant_id: str, billing_id: str) -> list[dict[str, Any]]:
    """Storage fees currently charged on a billing record (waived ones are excluded), by accrual date."""
    return execute_with_tenant(
        tenant_id,
        """
        SELECT * FROM storage_fee_log
        WHERE tenant_id = %s AND billing_id = %s AND waived_at IS NULL
        ORDER BY accrual_date ASC
        """,
        (tenant_id, billing_id),
    )


def get_storage_fee_total(tenant_id: str, billing_id: str) -> Decimal:
    """Sum of the storage fees currently charged on a billing record."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT COALESCE(SUM(amount_ngn), 0) AS total FROM storage_fee_log "
        "WHERE tenant_id = %s AND billing_id = %s AND waived_at IS NULL",
        (tenant_id, billing_id),
    )
    return Decimal(str(rows[0]["total"])) if rows else Decimal("0")


def waive_storage_fees_for_billing(
    tenant_id: str,
    billing_id: str,
    reason: str,
) -> tuple[dict[str, Any] | None, Decimal]:
    """Waive every storage fee currently charged on an invoice, atomically.

    Under the invoice lock: mark the un-waived fee rows waived, take their sum off
    the total, recompute the status, and open a refund if the customer has now
    overpaid. Fees accrued after this call are charged as normal.

    Returns:
        ``(updated_invoice, amount_waived)``; the invoice is ``None`` if it is not
        in this tenant. ``amount_waived`` is ``0`` when there was nothing to waive.
    """
    with tenant_transaction(tenant_id):
        billing = lock_billing(tenant_id, billing_id)
        if billing is None:
            return None, Decimal("0")
        waived_rows = execute_write_with_tenant_many(
            tenant_id,
            """
            UPDATE storage_fee_log
               SET waived_at = NOW(), waive_reason = %(reason)s
             WHERE tenant_id = %(tenant_id)s AND billing_id = %(billing_id)s AND waived_at IS NULL
            RETURNING amount_ngn
            """,
            {"tenant_id": tenant_id, "billing_id": billing_id, "reason": reason},
        )
        waived = sum((Decimal(str(r["amount_ngn"])) for r in waived_rows), Decimal("0"))
        if waived == 0:
            return billing, waived
        updated, _ = adjust_billing_and_refund_overpayment(
            tenant_id,
            billing_id,
            -waived,
            f"Overpayment after storage fees were waived on invoice {billing.get('invoice_number')}",
        )
    return updated, waived


# ---------------------------------------------------------------------------
# Top-level dispute listing (all disputes for tenant)
# ---------------------------------------------------------------------------


def _dispute_predicates(tenant_id: str, filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The WHERE clause (on alias ``d``) and its parameters, shared by the dispute list and its count."""
    conditions = ["d.tenant_id = %(tenant_id)s"]
    params: dict[str, Any] = {"tenant_id": tenant_id}
    if filters.get("status"):
        conditions.append("d.status = %(status)s")
        params["status"] = filters["status"]
    if filters.get("customer_id"):
        conditions.append("d.customer_id = %(customer_id)s")
        params["customer_id"] = filters["customer_id"]
    return " AND ".join(conditions), params


def count_all_disputes(tenant_id: str, filters: dict[str, Any]) -> int:
    """How many disputes match the same filters as ``list_all_disputes``."""
    where_clause, params = _dispute_predicates(tenant_id, filters)
    rows = execute_with_tenant(
        tenant_id,
        f"SELECT COUNT(*)::int AS total FROM cbm_dispute d WHERE {where_clause}",  # noqa: S608 - fixed fragments only
        params,
    )
    return int(rows[0]["total"]) if rows else 0


def list_all_disputes(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    from shared.pagination import build_paginated_query, extract_page

    where_clause, extra = _dispute_predicates(tenant_id, filters)

    # Customer, invoice and container come back with each dispute so the list can say which one it is (audit UX-06).
    # Names and references only, no amounts: China staff read this list too and may not read invoice money.
    base = f"""
        SELECT d.*,
               cu.name             AS customer_name,
               b.invoice_number    AS invoice_number,
               c.container_number  AS container_number
        FROM cbm_dispute d
        LEFT JOIN billing   b  ON b.id  = d.billing_id   AND b.tenant_id  = d.tenant_id
        LEFT JOIN customer  cu ON cu.id = d.customer_id  AND cu.tenant_id = d.tenant_id
        LEFT JOIN container c  ON c.id  = b.container_id AND c.tenant_id  = b.tenant_id
        WHERE {where_clause}
    """  # noqa: S608 - only fixed fragments are interpolated; every value is a bound parameter
    query, params = build_paginated_query(base, cursor, limit, sort_field="d.created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def set_dispute_status(
    tenant_id: str,
    dispute_id: str,
    status: str,
    extra: dict[str, Any] | None = None,
    allowed_from: list[str] | None = None,
) -> dict[str, Any] | None:
    """Update dispute status + optional extra fields (allowlisted).

    With ``allowed_from`` the update only applies if the dispute is currently in
    one of those statuses, so two requests cannot both move it; ``None`` is
    returned when it is not.
    """
    params: dict[str, Any] = {"status": status, "tenant_id": tenant_id, "id": dispute_id}
    guard = ""
    if allowed_from is not None:
        guard = " AND status = ANY(%(allowed_from)s)"
        params["allowed_from"] = allowed_from
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
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s{guard}
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
