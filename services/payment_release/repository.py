"""Database access layer for the Payment Release service.

Pure SQL — no business logic.
All queries use parameterized statements (%s / %(name)s) — never f-strings on
user-supplied values.

Notes:
  - billing has RLS (tenant_id isolation).
  - payment_record has RLS.
  - carryover_ledger has RLS.
  - refund_request has RLS.
  - release_note has RLS.
  - pickup_record has RLS.
  - shipment_tracking has RLS.
  - container has RLS.
  - packing_list / packing_list_item have RLS.
  - tenant_config has RLS.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from shared.db import (
    execute_transaction,
    execute_with_tenant,
    execute_write_with_tenant,
    next_tenant_counter,
    take_tenant_counter,
    tenant_transaction,
)
from shared.encryption import decrypt_field, encrypt_field
from shared.pagination import build_paginated_query, extract_page
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)


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
        "SELECT id, name FROM customer WHERE tenant_id = %s AND user_id = %s LIMIT 1",
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


def get_tenant_paystack_secret(tenant_id: str) -> str | None:
    """Return the tenant's own decrypted Paystack secret key, or None if not
    configured / disabled / unreadable.

    Multi-tenant Paystack (2026-07-19): each tenant connects their own
    Paystack account so customer payments land directly with that tenant —
    there is deliberately no platform-wide fallback key. Used both to
    initialize a checkout (services/payment_release/service.py) and to
    verify inbound webhook HMAC signatures (services/payment_release/
    webhook.py) — Paystack signs webhooks with the same secret key.
    """
    try:
        rows = execute_with_tenant(
            tenant_id,
            "SELECT config_value FROM tenant_config WHERE tenant_id = %s AND config_key = 'paystack_config' LIMIT 1",
            (tenant_id,),
        )
    except Exception:
        logger.exception("Could not fetch paystack_config for tenant %s", tenant_id)
        return None
    if not rows:
        return None
    config = rows[0]["config_value"]
    if not isinstance(config, dict) or not config.get("enabled") or not config.get("secret_key_encrypted"):
        return None
    return decrypt_field(config["secret_key_encrypted"])


def get_default_warehouse(tenant_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM warehouse WHERE tenant_id = %s AND is_default LIMIT 1",
        (tenant_id,),
    )
    return rows[0] if rows else None


def get_warehouse_by_id(tenant_id: str, warehouse_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM warehouse WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, warehouse_id),
    )
    return rows[0] if rows else None


def list_warehouses(tenant_id: str, include_inactive: bool = False) -> list[dict[str, Any]]:
    """Every branch/office a tenant has on file — the letterhead picker for
    release-note generation and pickup recording. A tenant that never adds
    one beyond migration 041's single backfilled default still works
    (generate_release_note falls back to get_default_warehouse)."""
    clause = "" if include_inactive else "AND is_active"
    rows = execute_with_tenant(
        tenant_id,
        f"SELECT * FROM warehouse WHERE tenant_id = %s {clause} ORDER BY is_default DESC, name ASC",
        (tenant_id,),
    )
    return rows


def create_warehouse(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Adds a new branch/office. Never touches is_default for any other
    row — promoting a new warehouse to default is a separate explicit
    action (set_default_warehouse), not implicit on create."""
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO warehouse (tenant_id, name, address, city, state, country, phone, is_default, created_by)
        VALUES (%(tenant_id)s, %(name)s, %(address)s, %(city)s, %(state)s,
                COALESCE(%(country)s, 'Nigeria'), %(phone)s, %(is_default)s, %(created_by)s)
        RETURNING *
        """,
        {
            "address": None,
            "city": None,
            "state": None,
            "country": None,
            "phone": None,
            "is_default": False,
            **data,
        },
    )


def set_default_warehouse(tenant_id: str, warehouse_id: str) -> dict[str, Any] | None:
    """Atomically moves the one-default-per-tenant flag (idx_warehouse_one_default
    is a partial unique index, so both statements must run in the same
    transaction or the second INSERT would violate it mid-flight)."""
    return execute_transaction(
        tenant_id,
        [
            ("UPDATE warehouse SET is_default = FALSE WHERE tenant_id = %s AND is_default", (tenant_id,)),
            (
                "UPDATE warehouse SET is_default = TRUE WHERE tenant_id = %s AND id = %s RETURNING *",
                (tenant_id, warehouse_id),
            ),
        ],
    )[-1]


_WAREHOUSE_EDITABLE_FIELDS = ("name", "address", "city", "state", "country", "phone", "is_active")


def update_warehouse(tenant_id: str, warehouse_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    """Patch a warehouse's editable fields. Keys are allowlisted against
    _WAREHOUSE_EDITABLE_FIELDS (never interpolated raw) so the SET clause is
    injection-safe. is_default is deliberately NOT editable here — promoting a
    default is the separate, atomic set_default_warehouse path."""
    fields = {k: v for k, v in updates.items() if k in _WAREHOUSE_EDITABLE_FIELDS}
    if not fields:
        return get_warehouse_by_id(tenant_id, warehouse_id)
    set_clause = ", ".join(f"{col} = %({col})s" for col in fields)
    params = {**fields, "tenant_id": tenant_id, "id": warehouse_id}
    return execute_write_with_tenant(
        tenant_id,
        f"""
        UPDATE warehouse SET {set_clause}, updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        params,
    )


# Tables whose rows point at a warehouse, as (table, column, human label).
# release_note / pickup_record / payment_record carry NO ON DELETE action by
# design (migration 041): a handover document must never lose the warehouse that
# released the goods. packing_list is ON DELETE SET NULL (migration 053), but a
# list still records where cargo is bound, so losing it silently is just as
# wrong — it is counted here too and blocks a delete the same way.
_WAREHOUSE_REFERENCES: tuple[tuple[str, str, str], ...] = (
    ("release_note", "warehouse_id", "release note"),
    ("pickup_record", "warehouse_id", "pickup record"),
    ("payment_record", "warehouse_id", "payment record"),
    ("packing_list", "arrival_warehouse_id", "packing list"),
)


def count_warehouse_references(tenant_id: str, warehouse_id: str) -> dict[str, int]:
    """Count the rows that would be orphaned by deleting this warehouse.

    Returns only the non-zero counts, keyed by the human label, so the caller can
    name what is actually blocking the delete instead of saying "it is in use".
    Table and column names come from the module-level allowlist above and are
    never caller-supplied, so interpolating them into the SQL is safe; the
    warehouse id stays a bound parameter.
    """
    counts: dict[str, int] = {}
    for table, column, label in _WAREHOUSE_REFERENCES:
        rows = execute_with_tenant(
            tenant_id,
            f"SELECT COUNT(*) AS cnt FROM {table} WHERE tenant_id = %s AND {column} = %s",
            (tenant_id, warehouse_id),
        )
        count = int(rows[0]["cnt"]) if rows else 0
        if count:
            counts[label] = count
    return counts


def delete_warehouse(tenant_id: str, warehouse_id: str) -> dict[str, Any] | None:
    """Hard-delete a warehouse. Returns the deleted row, or None if it was
    already gone.

    A genuine DELETE, not a flag flip: an operator who removes a warehouse they
    added by mistake expects it gone, and expects its name to be reusable. The
    caller must have established that nothing references it
    (count_warehouse_references) — the FKs would refuse anyway, but the service
    turns that into an actionable message first.
    """
    return execute_write_with_tenant(
        tenant_id,
        "DELETE FROM warehouse WHERE tenant_id = %s AND id = %s RETURNING *",
        (tenant_id, warehouse_id),
    )


def find_warehouse_by_name(tenant_id: str, name: str, *, active_only: bool = False) -> dict[str, Any] | None:
    """Look up a warehouse by exact name (case-insensitive).

    Used to turn a would-be unique-index violation into a clear message, and to
    offer restoring a deactivated warehouse rather than rejecting the name.
    """
    clause = "AND is_active" if active_only else ""
    rows = execute_with_tenant(
        tenant_id,
        f"SELECT * FROM warehouse WHERE tenant_id = %s AND LOWER(name) = LOWER(%s) {clause} LIMIT 1",
        (tenant_id, name),
    )
    return rows[0] if rows else None


def count_active_warehouses(tenant_id: str) -> int:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT COUNT(*) AS cnt FROM warehouse WHERE tenant_id = %s AND is_active",
        (tenant_id,),
    )
    return int(rows[0]["cnt"]) if rows else 0


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
# Billing reads/writes — tenant RLS scope
# ---------------------------------------------------------------------------


def get_billing_by_id(tenant_id: str, billing_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT b.*, cont.container_number, cu.name AS customer_name, cu.email AS customer_email,
            cu.phone AS customer_phone
        FROM billing b
        LEFT JOIN container cont
               ON cont.id = b.container_id AND cont.tenant_id = b.tenant_id
        LEFT JOIN customer cu
               ON cu.id = b.customer_id AND cu.tenant_id = b.tenant_id
        WHERE b.tenant_id = %s AND b.id = %s
        LIMIT 1
        """,
        (tenant_id, billing_id),
    )
    return rows[0] if rows else None


class BillingNotPayableError(Exception):
    """Raised inside ``record_payment`` when the locked billing row cannot accept payment."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RecordedPayment:
    """Result of `record_payment`: the new payment, the updated invoice, and any overpayment."""

    payment: dict[str, Any]
    billing: dict[str, Any]
    overpayment_ngn: Decimal


_MANUAL_PAYMENT_COLUMNS = (
    "payment_method",
    "reference_number",
    "payment_date",
    "recorded_by",
    "payer_name",
    "payer_address",
    "bank_name",
    "cheque_number",
    "warehouse_id",
    "physical_receipt_number",
)


def lock_billing(tenant_id: str, billing_id: str) -> dict[str, Any] | None:
    """Lock a billing row FOR UPDATE inside an active tenant_transaction."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM billing WHERE tenant_id = %s AND id = %s FOR UPDATE",
        (tenant_id, billing_id),
    )
    return rows[0] if rows else None


def record_payment(
    tenant_id: str,
    billing_id: str,
    amount_ngn: Decimal,
    payment: dict[str, Any],
    tolerance: Decimal,
    receipt_prefix: str | None = None,
    gateway_transaction_id: str | None = None,
) -> RecordedPayment | None:
    """Record one payment against an invoice, atomically.

    In a single transaction: lock the invoice row ``FOR UPDATE`` and verify it
    is payable, allocate a receipt number (manual payments), insert the payment
    record, add the amount to the invoice and set its status, settle any
    outstanding carryover on direct payment, and create a refund request for
    any overpayment. A failure at any step rolls back all of them, so there is
    never a payment record without a matching invoice update or the reverse.

    Args:
        tenant_id: Tenant scope.
        billing_id: Invoice being paid.
        amount_ngn: Amount received, in naira.
        payment: Extra ``payment_record`` columns; see ``_MANUAL_PAYMENT_COLUMNS``.
        tolerance: Sub-kobo difference treated as settled.
        receipt_prefix: ``ACM-RCT-20261114`` for a manual payment, which gets the
            next receipt number. ``None`` for a gateway payment, which has none.
        gateway_transaction_id: Set for gateway payments; a repeat delivery of
            the same id is ignored.

    Returns:
        The result, or ``None`` when ``gateway_transaction_id`` was already
        recorded (a duplicate webhook delivery). Nothing is changed in that case.

    Raises:
        RuntimeError: The invoice does not exist in this tenant.
        BillingNotPayableError: The invoice is cancelled, waived, or its
            carryover debt was already applied to a subsequent invoice.
    """
    norm_gw_id = (
        str(gateway_transaction_id).strip()
        if gateway_transaction_id is not None and str(gateway_transaction_id).strip()
        else None
    )
    with tenant_transaction(tenant_id) as cur:
        cur.execute(
            "SELECT * FROM billing WHERE tenant_id = %s AND id = %s FOR UPDATE",
            (tenant_id, billing_id),
        )
        locked = cur.fetchone()
        if locked is None:
            raise RuntimeError(f"billing {billing_id} not found in tenant while recording payment")
        prior_status = str(locked["status"])
        if prior_status in {"cancelled", "waived"}:
            raise BillingNotPayableError(prior_status)
        if prior_status == "released_with_outstanding":
            cur.execute(
                """
                SELECT 1 FROM carryover_ledger
                WHERE tenant_id = %s AND source_billing_id = %s AND status = 'applied'
                LIMIT 1
                """,
                (tenant_id, billing_id),
            )
            if cur.fetchone() is not None:
                raise BillingNotPayableError("carryover_already_applied")

        receipt_number = None
        if receipt_prefix is not None:
            receipt_number = f"{receipt_prefix}-{next_tenant_counter(cur, tenant_id, 'receipt'):04d}"

        cur.execute(
            """
            INSERT INTO payment_record (
                tenant_id, billing_id, amount_ngn,
                payment_method, reference_number, payment_date, recorded_by,
                receipt_number, payer_name, payer_address, bank_name,
                cheque_number, warehouse_id, physical_receipt_number,
                gateway_transaction_id
            ) VALUES (
                %(tenant_id)s, %(billing_id)s, %(amount_ngn)s,
                %(payment_method)s, %(reference_number)s, %(payment_date)s, %(recorded_by)s,
                %(receipt_number)s, %(payer_name)s, %(payer_address)s, %(bank_name)s,
                %(cheque_number)s, %(warehouse_id)s, %(physical_receipt_number)s,
                %(gateway_transaction_id)s
            )
            ON CONFLICT (tenant_id, gateway_transaction_id) WHERE gateway_transaction_id IS NOT NULL
            DO NOTHING
            RETURNING *
            """,
            {
                **dict.fromkeys(_MANUAL_PAYMENT_COLUMNS),
                **payment,
                "tenant_id": tenant_id,
                "billing_id": billing_id,
                "amount_ngn": amount_ngn,
                "receipt_number": receipt_number,
                "gateway_transaction_id": norm_gw_id,
            },
        )
        payment_row = cur.fetchone()
        if payment_row is None:
            return None

        cur.execute(
            """
            UPDATE billing
               SET amount_paid_ngn = amount_paid_ngn + %(amount)s,
                   status = CASE
                       WHEN ABS(total_ngn - (amount_paid_ngn + %(amount)s)) <= %(tol)s THEN 'paid'
                       WHEN total_ngn - (amount_paid_ngn + %(amount)s) < -%(tol)s THEN 'overpaid'
                       ELSE 'partially_paid'
                   END,
                   updated_at = NOW()
             WHERE tenant_id = %(tenant_id)s AND id = %(id)s
            RETURNING *
            """,
            {"tenant_id": tenant_id, "id": billing_id, "amount": amount_ngn, "tol": tolerance},
        )
        billing_row = cur.fetchone()
        if billing_row is None:
            raise RuntimeError(f"billing {billing_id} not found in tenant while recording payment")

        # Settle or reduce any outstanding carryover on direct payment of a
        # released_with_outstanding invoice so the customer is never billed twice
        # when a later invoice imports outstanding carryovers.
        if prior_status == "released_with_outstanding":
            new_balance = max(Decimal(str(billing_row["balance_ngn"])), Decimal("0"))
            if new_balance <= tolerance:
                cur.execute(
                    """
                    UPDATE carryover_ledger
                    SET status = 'waived',
                        notes = COALESCE(notes || ' | ', '') || 'Settled by direct payment on source invoice',
                        updated_at = NOW()
                    WHERE tenant_id = %s AND source_billing_id = %s AND status = 'outstanding'
                    """,
                    (tenant_id, billing_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE carryover_ledger
                    SET carryover_amount_ngn = LEAST(carryover_amount_ngn, %s),
                        updated_at = NOW()
                    WHERE tenant_id = %s AND source_billing_id = %s AND status = 'outstanding'
                    """,
                    (new_balance, tenant_id, billing_id),
                )

        # Only the part of THIS payment that lands above the invoice total is an
        # overpayment. An invoice that was already overpaid has its earlier
        # excess refunded separately and must not be counted again.
        total = Decimal(str(billing_row["total_ngn"]))
        paid_after = Decimal(str(billing_row["amount_paid_ngn"]))
        excess_after = max(paid_after - total, Decimal("0"))
        excess_before = max(paid_after - amount_ngn - total, Decimal("0"))
        overpayment = excess_after - excess_before
        if billing_row["status"] == "overpaid" and overpayment > tolerance:
            cur.execute(
                """
                INSERT INTO refund_request (
                    tenant_id, customer_id, billing_id, refund_type, amount_ngn, reason, status
                )
                VALUES (
                    %(tenant_id)s, %(customer_id)s, %(billing_id)s, 'overpayment',
                    %(amount)s, %(reason)s, 'pending_review'
                )
                """,
                {
                    "tenant_id": tenant_id,
                    "customer_id": billing_row["customer_id"],
                    "billing_id": billing_id,
                    "amount": overpayment,
                    "reason": f"Overpayment on invoice {billing_row.get('invoice_number') or billing_id}",
                },
            )
        else:
            overpayment = Decimal("0")

        return RecordedPayment(payment=dict(payment_row), billing=dict(billing_row), overpayment_ngn=overpayment)


def mark_billing_released_with_outstanding(tenant_id: str, billing_id: str) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE billing
        SET released_with_outstanding = TRUE,
            status                    = 'released_with_outstanding',
            updated_at                = NOW()
        WHERE tenant_id = %(tenant_id)s
          AND id = %(id)s
          AND status NOT IN ('cancelled', 'waived')
        RETURNING *
        """,
        {"tenant_id": tenant_id, "id": billing_id},
    )


# ---------------------------------------------------------------------------
# Refund request — tenant RLS scope
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Carryover ledger — tenant RLS scope
# ---------------------------------------------------------------------------


def has_active_carryover_for_billing(tenant_id: str, source_billing_id: str) -> bool:
    """Return True if an outstanding or applied carryover already exists for this billing."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT 1 FROM carryover_ledger
        WHERE tenant_id = %s
          AND source_billing_id = %s
          AND status IN ('outstanding', 'applied')
        LIMIT 1
        """,
        (tenant_id, source_billing_id),
    )
    return bool(rows)


def create_carryover_entry(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO carryover_ledger (
            tenant_id, customer_id, source_billing_id,
            carryover_amount_ngn, status, notes, created_by,
            due_date, granted_by, release_note_id
        ) VALUES (
            %(tenant_id)s, %(customer_id)s, %(source_billing_id)s,
            %(carryover_amount_ngn)s, 'outstanding', %(notes)s, %(created_by)s,
            %(due_date)s, %(granted_by)s, %(release_note_id)s
        ) RETURNING *
        """,
        {
            "due_date": None,
            "granted_by": None,
            "release_note_id": None,
            **data,
        },
    )


# ---------------------------------------------------------------------------
# Payment record — tenant RLS scope
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Payment claims — customer-submitted "I've made this payment" + evidence
# ---------------------------------------------------------------------------


def create_payment_claim(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Returns None if a pending claim already exists for this billing
    (idx_payment_claim_one_pending_per_billing) — the service layer turns
    that into a clean 422 rather than letting a raw IntegrityError 500.
    """
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO payment_claim (
            tenant_id, billing_id, customer_id, amount_ngn,
            evidence_file_key, evidence_file_name, customer_note
        ) VALUES (
            %(tenant_id)s, %(billing_id)s, %(customer_id)s, %(amount_ngn)s,
            %(evidence_file_key)s, %(evidence_file_name)s, %(customer_note)s
        )
        ON CONFLICT (billing_id) WHERE status = 'pending'
        DO NOTHING
        RETURNING *
        """,
        data,
    )


def get_payment_claim_by_id(tenant_id: str, claim_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM payment_claim WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, claim_id),
    )
    return rows[0] if rows else None


def lock_payment_claim(tenant_id: str, claim_id: str) -> dict[str, Any] | None:
    """Lock a payment_claim row FOR UPDATE inside an active tenant_transaction."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM payment_claim WHERE tenant_id = %s AND id = %s FOR UPDATE",
        (tenant_id, claim_id),
    )
    return rows[0] if rows else None


def list_payment_claims_for_billing(tenant_id: str, billing_id: str) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        "SELECT * FROM payment_claim WHERE tenant_id = %s AND billing_id = %s ORDER BY submitted_at DESC",
        (tenant_id, billing_id),
    )


def update_payment_claim_status(
    tenant_id: str,
    claim_id: str,
    status: str,
    reviewed_by: str,
    rejection_reason: str | None = None,
    payment_record_id: str | None = None,
) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE payment_claim
        SET status = %(status)s,
            reviewed_by = %(reviewed_by)s,
            reviewed_at = NOW(),
            rejection_reason = %(rejection_reason)s,
            payment_record_id = %(payment_record_id)s,
            updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s AND status = 'pending'
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "id": claim_id,
            "status": status,
            "reviewed_by": reviewed_by,
            "rejection_reason": rejection_reason,
            "payment_record_id": payment_record_id,
        },
    )


# ---------------------------------------------------------------------------
# Release note — tenant RLS scope
# ---------------------------------------------------------------------------


def list_release_notes(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Paginated list of release notes with optional filters."""
    conditions = ["rn.tenant_id = %(tenant_id)s"]
    extra: dict[str, Any] = {"tenant_id": tenant_id}

    if filters.get("customer_id"):
        conditions.append("rn.customer_id = %(customer_id)s")
        extra["customer_id"] = filters["customer_id"]
    if filters.get("container_id"):
        conditions.append("rn.container_id = %(container_id)s")
        extra["container_id"] = filters["container_id"]
    if filters.get("status"):
        conditions.append("rn.status = %(status)s")
        extra["status"] = filters["status"]
    if filters.get("reference"):
        # Exact-match lookup — the warehouse scan-or-type flow (P2-2).
        conditions.append("rn.reference_number = %(reference)s")
        extra["reference"] = filters["reference"]

    # billing join: payment_status + billing_total_cartons feed _fmt_release_note,
    # so list rows carry the same wire shape as the detail response.
    base = f"""
        SELECT rn.*,
               cu.name              AS customer_name,
               cont.container_number,
               b.status             AS payment_status,
               b.total_cartons      AS billing_total_cartons,
               b.total_ngn          AS billing_total_ngn,
               b.amount_paid_ngn    AS billing_amount_paid_ngn,
               b.balance_ngn        AS billing_balance_ngn,
               w.name               AS warehouse_name,
               w.address            AS warehouse_address,
               w.phone              AS warehouse_phone,
               pr.receipt_number    AS receipt_number,
               col.due_date         AS debt_due_date,
               COALESCE((
                   SELECT SUM(pu.cartons_count)
                   FROM pickup_record pu
                   WHERE pu.tenant_id       = rn.tenant_id
                     AND pu.release_note_id = rn.id
               ), 0)::int           AS cartons_picked_up
        FROM release_note rn
        LEFT JOIN customer  cu   ON cu.id   = rn.customer_id   AND cu.tenant_id   = rn.tenant_id
        LEFT JOIN container cont ON cont.id = rn.container_id  AND cont.tenant_id = rn.tenant_id
        LEFT JOIN billing   b    ON b.id    = rn.billing_id    AND b.tenant_id    = rn.tenant_id
        LEFT JOIN warehouse w    ON w.id    = rn.warehouse_id  AND w.tenant_id    = rn.tenant_id
        LEFT JOIN payment_record pr ON pr.id = rn.payment_record_id AND pr.tenant_id = rn.tenant_id
        LEFT JOIN carryover_ledger col ON col.release_note_id = rn.id AND col.tenant_id = rn.tenant_id
        WHERE {" AND ".join(conditions)}
    """
    query, params = build_paginated_query(base, cursor, limit, sort_field="rn.created_at")
    params.update(extra)
    rows = execute_with_tenant(tenant_id, query, params)
    return extract_page(rows, limit)


def get_release_note_stats(tenant_id: str) -> dict[str, int]:
    """Per-status aggregates for the release-notes list stats row (§9.1, P2-3)."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT
            COUNT(*) FILTER (WHERE status = 'active')                          AS active,
            COUNT(*) FILTER (WHERE status = 'active' AND is_partial)           AS partial_active,
            COUNT(*) FILTER (WHERE status = 'picked_up'
                             AND updated_at::date = CURRENT_DATE)              AS picked_up_today,
            COUNT(*) FILTER (WHERE status = 'picked_up')                       AS picked_up,
            COUNT(*) FILTER (WHERE status = 'expired')                         AS expired
        FROM release_note
        WHERE tenant_id = %s
        """,
        (tenant_id,),
    )
    row = rows[0] if rows else {}
    return {k: int(row.get(k) or 0) for k in ("active", "partial_active", "picked_up_today", "picked_up", "expired")}


def get_next_release_note_seq(tenant_id: str) -> int:
    """Next release-note sequence number for the tenant, from the atomic counter.

    Replaces ``COUNT(*) + 1``, which gave two notes created together the same
    number. Always distinct; a number is skipped if the note insert then fails.
    """
    return take_tenant_counter(tenant_id, "release_note")


def create_release_note(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO release_note (
            tenant_id, billing_id, customer_id, container_id,
            reference_number, carton_tags, total_cartons, is_partial,
            status, issued_by, notes, valid_until,
            warehouse_id, payment_record_id, is_on_credit,
            credit_granted_by, credit_granted_by_name,
            packages_released, package_unit, packages_balance,
            physical_document_number, packing_list_invoice_numbers
        ) VALUES (
            %(tenant_id)s, %(billing_id)s, %(customer_id)s, %(container_id)s,
            %(reference_number)s, %(carton_tags)s, %(total_cartons)s, %(is_partial)s,
            %(status)s, %(issued_by)s, %(notes)s, %(valid_until)s,
            %(warehouse_id)s, %(payment_record_id)s, %(is_on_credit)s,
            %(credit_granted_by)s, %(credit_granted_by_name)s,
            %(packages_released)s, %(package_unit)s, %(packages_balance)s,
            %(physical_document_number)s, %(packing_list_invoice_numbers)s
        ) RETURNING *
        """,
        {
            "warehouse_id": None,
            "payment_record_id": None,
            "is_on_credit": False,
            "credit_granted_by": None,
            "credit_granted_by_name": None,
            "packages_released": None,
            "package_unit": None,
            "packages_balance": None,
            "physical_document_number": None,
            "packing_list_invoice_numbers": [],
            **data,
        },
    )


def get_release_note_by_id(tenant_id: str, note_id: str) -> dict[str, Any] | None:
    # Ground-truth fix: storage_fees_ngn is not a column on `billing` — it's
    # aggregated from storage_fee_log (same pattern as
    # excel/repository.py::get_billing_for_export). Selecting b.storage_fees_ngn
    # directly raised UndefinedColumn on every call, so GET /v1/release-notes/{id}
    # and PATCH .../release (record_pickup, which reads this first) always 500'd.
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT rn.*,
               cu.name              AS customer_name,
               cont.container_number,
               b.status             AS payment_status,
               b.total_cartons      AS billing_total_cartons,
               b.total_cbm          AS billing_total_cbm,
               b.total_ngn          AS billing_total_ngn,
               b.amount_paid_ngn    AS billing_amount_paid_ngn,
               b.balance_ngn        AS billing_balance_ngn,
               b.customer_id        AS billing_customer_id,
               w.name               AS warehouse_name,
               w.address            AS warehouse_address,
               w.phone              AS warehouse_phone,
               pr.receipt_number    AS receipt_number,
               -- The form's "Debt Payment Date" — at most one carryover_ledger
               -- row is ever created per release note (generate_release_note
               -- links release_note_id once, on the credit-release path only).
               col.due_date         AS debt_due_date,
               COALESCE((
                   SELECT SUM(sfl.amount_ngn)
                   FROM storage_fee_log sfl
                   WHERE sfl.tenant_id  = b.tenant_id
                     AND sfl.billing_id = b.id
                     AND sfl.waived_at IS NULL
               ), 0)                AS storage_fees_ngn,
               COALESCE((
                   SELECT SUM(pu.cartons_count)
                   FROM pickup_record pu
                   WHERE pu.tenant_id       = rn.tenant_id
                     AND pu.release_note_id = rn.id
               ), 0)::int           AS cartons_picked_up
        FROM release_note rn
        LEFT JOIN customer  cu   ON cu.id   = rn.customer_id
        LEFT JOIN container cont ON cont.id = rn.container_id
        LEFT JOIN billing   b    ON b.id    = rn.billing_id
        LEFT JOIN warehouse w    ON w.id    = rn.warehouse_id
        LEFT JOIN payment_record pr ON pr.id = rn.payment_record_id
        LEFT JOIN carryover_ledger col ON col.release_note_id = rn.id
        WHERE rn.tenant_id = %s AND rn.id = %s
        LIMIT 1
        """,
        (tenant_id, note_id),
    )
    return rows[0] if rows else None


def create_split_release_note(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Insert a child release note referencing parent_release_note_id — used
    by both split (a genuinely new sub-release for un-collected cartons) and
    reissue (a near-identical clone with a fresh validity window).

    Ground-truth bug fix: this INSERT originally named only the migration-003
    columns, so every migration-041 field (warehouse_id, is_on_credit,
    credit_granted_by(_name), packages_released/package_unit/packages_balance,
    physical_document_number, packing_list_invoice_numbers) silently reset to
    its column default on every split *and* reissue — a reissued "expired"
    note (meant to be the same release, same warehouse, same credit terms,
    just a new 14-day window) would print with no warehouse address and no
    memory of ever having been released on credit. Callers now populate
    whichever of these apply via `data`; defaults below cover the rest.
    """
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO release_note (
            tenant_id, billing_id, customer_id, container_id,
            reference_number, carton_tags, total_cartons, is_partial,
            parent_release_note_id, status, issued_by, notes, valid_until,
            warehouse_id, is_on_credit, credit_granted_by, credit_granted_by_name,
            packages_released, package_unit, packages_balance,
            physical_document_number, packing_list_invoice_numbers
        ) VALUES (
            %(tenant_id)s, %(billing_id)s, %(customer_id)s, %(container_id)s,
            %(reference_number)s, %(carton_tags)s, %(total_cartons)s, %(is_partial)s,
            %(parent_release_note_id)s, %(status)s, %(issued_by)s, %(notes)s, %(valid_until)s,
            %(warehouse_id)s, %(is_on_credit)s, %(credit_granted_by)s, %(credit_granted_by_name)s,
            %(packages_released)s, %(package_unit)s, %(packages_balance)s,
            %(physical_document_number)s, %(packing_list_invoice_numbers)s
        ) RETURNING *
        """,
        {
            "warehouse_id": None,
            "is_on_credit": False,
            "credit_granted_by": None,
            "credit_granted_by_name": None,
            "packages_released": None,
            "package_unit": None,
            "packages_balance": None,
            "physical_document_number": None,
            "packing_list_invoice_numbers": [],
            **data,
        },
    )


def get_picked_carton_tags(tenant_id: str, note_id: str) -> list[str]:
    """Return carton_tags already confirmed picked across all pickup_records for a note."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(array_agg(DISTINCT tag), ARRAY[]::TEXT[]) AS tags
        FROM pickup_record pr,
             LATERAL unnest(pr.carton_tags_picked) AS tag
        WHERE pr.release_note_id = %s AND pr.tenant_id = %s
        """,
        (note_id, tenant_id),
    )
    return list(rows[0]["tags"]) if rows and rows[0]["tags"] else []


def get_active_release_note_carton_tags(tenant_id: str, billing_id: str) -> list[str]:
    """Carton tags already on a non-terminal-loss release note for this billing.

    Scoped to 'active' and 'picked_up' — the two statuses that mean a carton
    is currently or already authorised for pickup. 'expired' and 'cancelled'
    notes release their tags back to the pool (reissue_release_note is the
    sanctioned way to reactivate an expired note's own tags).
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(array_agg(DISTINCT tag), ARRAY[]::TEXT[]) AS tags
        FROM release_note rn,
             LATERAL unnest(rn.carton_tags) AS tag
        WHERE rn.tenant_id = %s AND rn.billing_id = %s AND rn.status IN ('active', 'picked_up')
        """,
        (tenant_id, billing_id),
    )
    return list(rows[0]["tags"]) if rows and rows[0]["tags"] else []


def lock_release_note(tenant_id: str, note_id: str) -> dict[str, Any] | None:
    """Lock a release_note row FOR UPDATE inside an active tenant_transaction."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT * FROM release_note WHERE tenant_id = %s AND id = %s FOR UPDATE",
        (tenant_id, note_id),
    )
    return rows[0] if rows else None


def get_active_release_note_total_cartons(tenant_id: str, billing_id: str) -> int:
    """Sum of total_cartons across this billing's active/picked_up release notes
    (both tag-based and count-based) to prevent mixed-mode over-release."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(SUM(total_cartons), 0) AS total
        FROM release_note
        WHERE tenant_id = %s AND billing_id = %s AND status IN ('active', 'picked_up')
        """,
        (tenant_id, billing_id),
    )
    return int(rows[0]["total"]) if rows else 0


def get_approved_carton_tags_for_billing(tenant_id: str, customer_id: str, container_id: str) -> list[str]:
    """Return distinct non-empty carton tags belonging to approved packing lists for this customer+container."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(array_agg(DISTINCT pli.carton_tag), ARRAY[]::TEXT[]) AS tags
        FROM packing_list_item pli
        JOIN packing_list pl ON pl.id = pli.packing_list_id
        WHERE pl.tenant_id    = %s
          AND pl.customer_id  = %s
          AND pl.container_id = %s
          AND pl.status       = 'approved'
          AND pli.carton_tag IS NOT NULL
          AND pli.carton_tag <> ''
        """,
        (tenant_id, customer_id, container_id),
    )
    return list(rows[0]["tags"]) if rows and rows[0]["tags"] else []


def update_parent_release_note_after_split(
    tenant_id: str,
    note_id: str,
    remaining_tags: list[str],
    remaining_cartons: int,
    new_status: str,
) -> dict[str, Any] | None:
    """Shrink the parent release note when un-picked tags are split onto a child note."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE release_note
        SET carton_tags = %(tags)s,
            total_cartons = %(total_cartons)s,
            status = %(status)s,
            updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s AND status = 'active'
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "id": note_id,
            "tags": remaining_tags,
            "total_cartons": remaining_cartons,
            "status": new_status,
        },
    )


def has_active_child_release_note(tenant_id: str, parent_note_id: str) -> bool:
    """Return True if an active or picked_up child note already exists for parent_note_id."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT 1 FROM release_note
        WHERE tenant_id = %s
          AND parent_release_note_id = %s
          AND status IN ('active', 'picked_up')
        LIMIT 1
        """,
        (tenant_id, parent_note_id),
    )
    return bool(rows)


def get_active_release_note_packages_released(tenant_id: str, billing_id: str) -> int:
    """Sum of packages_released across this billing's active/picked_up release notes.

    Same statuses as get_active_release_note_carton_tags — see its docstring.
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(SUM(packages_released), 0) AS total
        FROM release_note
        WHERE tenant_id = %s AND billing_id = %s AND status IN ('active', 'picked_up')
        """,
        (tenant_id, billing_id),
    )
    return int(rows[0]["total"]) if rows else 0


def set_pickup_code(tenant_id: str, note_id: str, code_hash: str | None) -> dict[str, Any] | None:
    """Store (or, with None, clear) a release note's pickup code hash and reset its failed-attempt count.

    Only the keyed hash is ever stored (`shared/pickup_code.py`). Clearing is for a note whose code could not be sent to
    the customer: requiring a code nobody received would only block the collection.
    """
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE release_note
        SET pickup_code_hash = %s,
            pickup_code_issued_at = CASE WHEN %s::text IS NULL THEN NULL ELSE NOW() END,
            pickup_code_failed_attempts = 0,
            updated_at = NOW()
        WHERE tenant_id = %s AND id = %s
        RETURNING id
        """,
        (code_hash, code_hash, tenant_id, note_id),
    )


def record_failed_pickup_code(tenant_id: str, note_id: str) -> int | None:
    """Count one wrong code against a release note and return the new total (atomic, so concurrent guesses all count)."""
    row = execute_write_with_tenant(
        tenant_id,
        """
        UPDATE release_note
        SET pickup_code_failed_attempts = pickup_code_failed_attempts + 1
        WHERE tenant_id = %s AND id = %s
        RETURNING pickup_code_failed_attempts
        """,
        (tenant_id, note_id),
    )
    return int(row["pickup_code_failed_attempts"]) if row else None


def reset_pickup_code_attempts(tenant_id: str, note_id: str) -> None:
    """Forget earlier wrong codes once the right one has been given."""
    execute_write_with_tenant(
        tenant_id,
        """
        UPDATE release_note SET pickup_code_failed_attempts = 0
        WHERE tenant_id = %s AND id = %s AND pickup_code_failed_attempts > 0
        RETURNING id
        """,
        (tenant_id, note_id),
    )


def update_release_note_status(tenant_id: str, note_id: str, status: str) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE release_note
        SET status = %s, updated_at = NOW()
        WHERE tenant_id = %s AND id = %s
        RETURNING *
        """,
        (status, tenant_id, note_id),
    )


# ---------------------------------------------------------------------------
# Pickup record — tenant RLS scope
# ---------------------------------------------------------------------------


def create_pickup_record(tenant_id: str, data: dict[str, Any]) -> dict[str, Any]:
    # Encrypt passport / national ID before storage (GDPR Art. 32 — enhanced protection).
    # decrypt_field() is applied to the RETURNING * row so callers always receive plaintext.
    merged = {
        "collected_by_name": None,
        "collected_by_phone": None,
        "warehouse_id": None,
        "customer_service_officer_id": None,
        "accounting_officer_id": None,
        "warehouse_attendant_id": None,
        **data,
    }
    encrypted_data = {**merged, "id_number": encrypt_field(merged.get("id_number"))}
    row = execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO pickup_record (
            tenant_id, release_note_id, customer_id,
            carton_tags_picked, cartons_count, pickup_date,
            collected_by_name, collected_by_phone,
            is_delegate, delegate_name, delegate_phone,
            id_type, id_number, received_by, notes,
            warehouse_id, customer_service_officer_id,
            accounting_officer_id, warehouse_attendant_id
        ) VALUES (
            %(tenant_id)s, %(release_note_id)s, %(customer_id)s,
            %(carton_tags_picked)s, %(cartons_count)s, %(pickup_date)s,
            %(collected_by_name)s, %(collected_by_phone)s,
            %(is_delegate)s, %(delegate_name)s, %(delegate_phone)s,
            %(id_type)s, %(id_number)s, %(received_by)s, %(notes)s,
            %(warehouse_id)s, %(customer_service_officer_id)s,
            %(accounting_officer_id)s, %(warehouse_attendant_id)s
        ) RETURNING *
        """,
        encrypted_data,
    )
    if row is None:
        return {}
    return {**row, "id_number": decrypt_field(row.get("id_number"))}


def get_tenant_user_name(tenant_id: str, user_id: str) -> str | None:
    """Resolve a tenant_user's full_name — used to populate attendant_name /
    officer names on the pickup response (bug fix: attendant_name was
    previously hardcoded None).
    """
    rows = execute_with_tenant(
        tenant_id,
        "SELECT full_name FROM tenant_user WHERE tenant_id = %s AND id = %s LIMIT 1",
        (tenant_id, user_id),
    )
    return rows[0]["full_name"] if rows else None


def sum_cartons_picked_for_release_note(tenant_id: str, note_id: str) -> int:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(SUM(cartons_count), 0) AS total
        FROM pickup_record
        WHERE release_note_id = %s AND tenant_id = %s
        """,
        (note_id, tenant_id),
    )
    return int(rows[0]["total"]) if rows else 0


def sum_cartons_released_for_customer(tenant_id: str, customer_id: str, container_id: str) -> int:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(SUM(pr.cartons_count), 0) AS total
        FROM pickup_record pr
        JOIN release_note rn ON rn.id = pr.release_note_id
        WHERE rn.tenant_id    = %s
          AND rn.customer_id  = %s
          AND rn.container_id = %s
        """,
        (tenant_id, customer_id, container_id),
    )
    return int(rows[0]["total"]) if rows else 0


def sum_cartons_released_for_container(tenant_id: str, container_id: str) -> int:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(SUM(pr.cartons_count), 0) AS total
        FROM pickup_record pr
        JOIN release_note rn ON rn.id = pr.release_note_id
        WHERE rn.tenant_id    = %s
          AND rn.container_id = %s
        """,
        (tenant_id, container_id),
    )
    return int(rows[0]["total"]) if rows else 0


def sum_total_cartons_from_billing(tenant_id: str, container_id: str) -> int:
    """Total cartons billed for a container across all non-cancelled billing records."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(SUM(total_cartons), 0) AS total
        FROM billing
        WHERE tenant_id = %s AND container_id = %s AND status <> 'cancelled'
        """,
        (tenant_id, container_id),
    )
    return int(rows[0]["total"]) if rows else 0


def all_container_customers_fully_released(tenant_id: str, container_id: str) -> bool | None:
    """Return True iff the container has >= 1 non-cancelled billing and every
    customer's picked cartons are >= their billed cartons.

    Returns None if no rows are returned (e.g. unit-test fake DB connection) so
    callers can fall back to the aggregate sum check.
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        WITH billed AS (
            SELECT customer_id, COALESCE(SUM(total_cartons), 0) AS billed_cartons
            FROM billing
            WHERE tenant_id = %s AND container_id = %s AND status <> 'cancelled'
            GROUP BY customer_id
        ),
        picked AS (
            SELECT rn.customer_id, COALESCE(SUM(pr.cartons_count), 0) AS picked_cartons
            FROM pickup_record pr
            JOIN release_note rn ON rn.id = pr.release_note_id AND rn.tenant_id = pr.tenant_id
            WHERE rn.tenant_id = %s AND rn.container_id = %s
            GROUP BY rn.customer_id
        )
        SELECT
            COUNT(*) AS customer_count,
            COUNT(*) FILTER (WHERE COALESCE(p.picked_cartons, 0) < b.billed_cartons) AS incomplete_count
        FROM billed b
        LEFT JOIN picked p ON p.customer_id = b.customer_id
        """,
        (tenant_id, container_id, tenant_id, container_id),
    )
    if not rows:
        return None
    customer_count = int(rows[0].get("customer_count") or 0)
    incomplete_count = int(rows[0].get("incomplete_count") or 0)
    return customer_count > 0 and incomplete_count == 0


# ---------------------------------------------------------------------------
# CBM helpers — packing_list_item
# ---------------------------------------------------------------------------


def get_cbm_for_carton_tags(
    tenant_id: str,
    customer_id: str,
    container_id: str,
    tags: list[str],
) -> Decimal:
    """Sum CBM for specific carton tags from approved packing lists."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(SUM(pli.cbm), 0) AS selected_cbm
        FROM packing_list_item pli
        JOIN packing_list pl ON pl.id = pli.packing_list_id
        WHERE pl.tenant_id    = %s
          AND pl.customer_id  = %s
          AND pl.container_id = %s
          AND pl.status       = 'approved'
          AND pli.carton_tag  = ANY(%s)
        """,
        (tenant_id, customer_id, container_id, tags),
    )
    return Decimal(str(rows[0]["selected_cbm"])) if rows else Decimal("0")


def get_carton_tag_quantities(
    tenant_id: str,
    customer_id: str,
    container_id: str,
    tags: list[str],
) -> dict[str, int]:
    """Return {carton_tag: total_quantity} for approved packing list items matching tags."""
    if not tags:
        return {}
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT pli.carton_tag,
               COALESCE(SUM(COALESCE(pli.quantity, 1)), 0)::int AS qty
        FROM packing_list_item pli
        JOIN packing_list pl ON pl.id = pli.packing_list_id
        WHERE pl.tenant_id    = %s
          AND pl.customer_id  = %s
          AND pl.container_id = %s
          AND pl.status       = 'approved'
          AND pli.carton_tag  = ANY(%s)
        GROUP BY pli.carton_tag
        """,
        (tenant_id, customer_id, container_id, tags),
    )
    return {str(r["carton_tag"]): int(r["qty"] or 1) for r in rows if r.get("carton_tag")}


# ---------------------------------------------------------------------------
# Container / shipment_tracking — tenant RLS scope
# ---------------------------------------------------------------------------


def update_container_status(tenant_id: str, container_id: str, status: str) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE container
        SET status = %s, updated_at = NOW()
        WHERE tenant_id = %s AND id = %s
        RETURNING *
        """,
        (status, tenant_id, container_id),
    )


def update_shipment_tracking_for_customer(
    tenant_id: str,
    customer_id: str,
    container_id: str,
    status: str,
) -> None:
    """Update all shipment_tracking rows for a customer's approved items in a container."""
    execute_write_with_tenant(
        tenant_id,
        """
        UPDATE shipment_tracking st
        SET status     = %(status)s,
            updated_at = NOW()
        WHERE st.tenant_id = %(tenant_id)s
          AND EXISTS (
              SELECT 1
              FROM packing_list_item pli
              JOIN packing_list pl ON pl.id = pli.packing_list_id
              WHERE pl.tenant_id    = %(tenant_id)s
                AND pl.customer_id  = %(customer_id)s
                AND pl.container_id = %(container_id)s
                AND pl.status       = 'approved'
                AND (
                    st.packing_list_item_id = pli.id
                    OR (st.tracking_code IS NOT NULL AND st.tracking_code = pli.tracking_code)
                )
          )
        RETURNING st.id
        """,
        {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "container_id": container_id,
            "status": status,
        },
    )
