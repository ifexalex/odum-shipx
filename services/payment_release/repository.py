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
from decimal import Decimal
from typing import Any

from shared.db import execute_transaction, execute_with_tenant, execute_write_with_tenant
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


def update_billing_payment(
    tenant_id: str,
    billing_id: str,
    amount_to_add: Any,
    new_status: str,
) -> dict[str, Any] | None:
    """Increment amount_paid_ngn and update payment status. balance_ngn is GENERATED."""
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE billing
        SET amount_paid_ngn = amount_paid_ngn + %(amount)s,
            status          = %(status)s,
            updated_at      = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {
            "tenant_id": tenant_id,
            "id": billing_id,
            "amount": amount_to_add,
            "status": new_status,
        },
    )


def mark_billing_released_with_outstanding(tenant_id: str, billing_id: str) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        UPDATE billing
        SET released_with_outstanding = TRUE,
            status                    = 'released_with_outstanding',
            updated_at                = NOW()
        WHERE tenant_id = %(tenant_id)s AND id = %(id)s
        RETURNING *
        """,
        {"tenant_id": tenant_id, "id": billing_id},
    )


# ---------------------------------------------------------------------------
# Refund request — tenant RLS scope
# ---------------------------------------------------------------------------


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
# Carryover ledger — tenant RLS scope
# ---------------------------------------------------------------------------


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


def create_payment_record(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO payment_record (
            tenant_id, billing_id, amount_ngn,
            payment_method, reference_number, payment_date, recorded_by,
            receipt_number, payer_name, payer_address, bank_name,
            cheque_number, warehouse_id, physical_receipt_number
        ) VALUES (
            %(tenant_id)s, %(billing_id)s, %(amount_ngn)s,
            %(payment_method)s, %(reference_number)s, %(payment_date)s, %(recorded_by)s,
            %(receipt_number)s, %(payer_name)s, %(payer_address)s, %(bank_name)s,
            %(cheque_number)s, %(warehouse_id)s, %(physical_receipt_number)s
        ) RETURNING *
        """,
        {
            "receipt_number": None,
            "payer_name": None,
            "payer_address": None,
            "bank_name": None,
            "cheque_number": None,
            "warehouse_id": None,
            "physical_receipt_number": None,
            **data,
        },
    )


def get_next_receipt_number(tenant_id: str) -> int:
    """Return the next sequence value for this tenant's receipt numbers.

    Same race-prone COUNT(*)+1 shape as get_next_release_note_seq — kept
    consistent with the rest of the codebase rather than introducing a new
    locking pattern unilaterally; a `SELECT ... FOR UPDATE`-backed sequence
    would close this whole class of bug across all four generators but is
    out of scope for this pass (flagged in 13_api_payment_release.md).
    """
    rows = execute_with_tenant(
        tenant_id,
        "SELECT COUNT(*) + 1 AS seq FROM payment_record WHERE tenant_id = %s AND receipt_number IS NOT NULL",
        (tenant_id,),
    )
    return int(rows[0]["seq"]) if rows else 1


def create_webhook_payment_record(tenant_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Insert a payment_record that includes gateway_transaction_id for deduplication."""
    return execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO payment_record (
            tenant_id, billing_id, amount_ngn,
            payment_method, reference_number, payment_date, recorded_by,
            gateway_transaction_id
        ) VALUES (
            %(tenant_id)s, %(billing_id)s, %(amount_ngn)s,
            %(payment_method)s, %(reference_number)s, %(payment_date)s, %(recorded_by)s,
            %(gateway_transaction_id)s
        )
        ON CONFLICT (tenant_id, gateway_transaction_id)
        WHERE gateway_transaction_id IS NOT NULL
        DO NOTHING
        RETURNING *
        """,
        data,
    )


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
               col.due_date         AS debt_due_date
        FROM release_note rn
        LEFT JOIN customer  cu   ON cu.id   = rn.customer_id   AND cu.tenant_id   = rn.tenant_id
        LEFT JOIN container cont ON cont.id = rn.container_id  AND cont.tenant_id = rn.tenant_id
        LEFT JOIN billing   b    ON b.id    = rn.billing_id    AND b.tenant_id    = rn.tenant_id
        LEFT JOIN warehouse w    ON w.id    = rn.warehouse_id  AND w.tenant_id    = rn.tenant_id
        LEFT JOIN payment_record pr ON pr.id = rn.payment_record_id AND pr.tenant_id = rn.tenant_id
        LEFT JOIN carryover_ledger col ON col.release_note_id = rn.id AND col.tenant_id = rn.tenant_id
        WHERE {' AND '.join(conditions)}
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
    rows = execute_with_tenant(
        tenant_id,
        "SELECT COUNT(*) + 1 AS seq FROM release_note WHERE tenant_id = %s",
        (tenant_id,),
    )
    return int(rows[0]["seq"]) if rows else 1


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
               ), 0)                AS storage_fees_ngn
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
    """Total cartons billed for a container across all billing records."""
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT COALESCE(SUM(total_cartons), 0) AS total
        FROM billing
        WHERE tenant_id = %s AND container_id = %s
        """,
        (tenant_id, container_id),
    )
    return int(rows[0]["total"]) if rows else 0


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
    """Update all shipment_tracking rows for a customer's items in a container."""
    execute_write_with_tenant(
        tenant_id,
        """
        UPDATE shipment_tracking
        SET status     = %(status)s,
            updated_at = NOW()
        WHERE tenant_id = %(tenant_id)s
          AND packing_list_item_id IN (
              SELECT pli.id
              FROM packing_list_item pli
              JOIN packing_list pl ON pl.id = pli.packing_list_id
              WHERE pl.tenant_id    = %(tenant_id)s
                AND pl.customer_id  = %(customer_id)s
                AND pl.container_id = %(container_id)s
          )
        RETURNING id
        """,
        {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "container_id": container_id,
            "status": status,
        },
    )
