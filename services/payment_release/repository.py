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

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.encryption import decrypt_field, encrypt_field
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
        SELECT b.*, cont.container_number, cu.name AS customer_name
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
            carryover_amount_ngn, status, notes, created_by
        ) VALUES (
            %(tenant_id)s, %(customer_id)s, %(source_billing_id)s,
            %(carryover_amount_ngn)s, 'outstanding', %(notes)s, %(created_by)s
        ) RETURNING *
        """,
        data,
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
            payment_method, reference_number, payment_date, recorded_by
        ) VALUES (
            %(tenant_id)s, %(billing_id)s, %(amount_ngn)s,
            %(payment_method)s, %(reference_number)s, %(payment_date)s, %(recorded_by)s
        ) RETURNING *
        """,
        data,
    )


# ---------------------------------------------------------------------------
# Release note — tenant RLS scope
# ---------------------------------------------------------------------------


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
            status, issued_by, notes
        ) VALUES (
            %(tenant_id)s, %(billing_id)s, %(customer_id)s, %(container_id)s,
            %(reference_number)s, %(carton_tags)s, %(total_cartons)s, %(is_partial)s,
            %(status)s, %(issued_by)s, %(notes)s
        ) RETURNING *
        """,
        data,
    )


def get_release_note_by_id(tenant_id: str, note_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT rn.*,
               cu.name           AS customer_name,
               cont.container_number,
               b.status          AS payment_status,
               b.total_cartons   AS billing_total_cartons,
               b.total_cbm       AS billing_total_cbm,
               b.total_ngn       AS billing_total_ngn,
               b.amount_paid_ngn AS billing_amount_paid_ngn,
               b.balance_ngn     AS billing_balance_ngn,
               b.customer_id     AS billing_customer_id
        FROM release_note rn
        LEFT JOIN customer  cu   ON cu.id   = rn.customer_id
        LEFT JOIN container cont ON cont.id = rn.container_id
        LEFT JOIN billing   b    ON b.id    = rn.billing_id
        WHERE rn.tenant_id = %s AND rn.id = %s
        LIMIT 1
        """,
        (tenant_id, note_id),
    )
    return rows[0] if rows else None


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
    encrypted_data = {**data, "id_number": encrypt_field(data.get("id_number"))}
    row = execute_write_with_tenant(
        tenant_id,
        """
        INSERT INTO pickup_record (
            tenant_id, release_note_id, customer_id,
            carton_tags_picked, cartons_count, pickup_date,
            is_delegate, delegate_name, delegate_phone,
            id_type, id_number, received_by, notes
        ) VALUES (
            %(tenant_id)s, %(release_note_id)s, %(customer_id)s,
            %(carton_tags_picked)s, %(cartons_count)s, %(pickup_date)s,
            %(is_delegate)s, %(delegate_name)s, %(delegate_phone)s,
            %(id_type)s, %(id_number)s, %(received_by)s, %(notes)s
        ) RETURNING *
        """,
        encrypted_data,
    )
    if row is None:
        return {}
    return {**row, "id_number": decrypt_field(row.get("id_number"))}


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
