"""Read-only lookups for global search (audit UX-05).

One query per kind of record, each tenant-scoped (and RLS applies on top), each parameterized: the user's text
only ever reaches SQL as a bound LIKE pattern, with its wildcards escaped. A customer's lookups add `customer_id`
to every query, so a customer can only ever find their own records.

Each row carries `is_exact`, true when the text equals the identifying value, so an exact container number or invoice
number ranks above partial matches.
"""

from typing import Any

from shared.db import execute_with_tenant

# Matches a customer by name, and (for roles allowed to look people up by number) by phone or WhatsApp. `{c}` is the
# customer table's alias in the query it is spliced into; the pattern parameters are bound, never interpolated.
_CUSTOMER_NAME = "{c}.name ILIKE %(pattern)s ESCAPE '\\'"
_CUSTOMER_PHONE = (
    "(%(digits)s <> '' AND ("
    "regexp_replace(coalesce({c}.phone, ''), '\\D', '', 'g') LIKE %(digits)s "
    "OR regexp_replace(coalesce({c}.whatsapp, ''), '\\D', '', 'g') LIKE %(digits)s))"
)


def _customer_clause(alias: str, by_name: bool, by_phone: bool) -> str:
    parts = []
    if by_name:
        parts.append(_CUSTOMER_NAME.format(c=alias))
    if by_phone:
        parts.append(_CUSTOMER_PHONE.format(c=alias))
    return "".join(f" OR {p}" for p in parts)


def _params(tenant_id: str, text: str, pattern: str, digits: str, limit: int, customer_id: str | None) -> dict[str, Any]:
    return {"tenant": tenant_id, "text": text, "pattern": pattern, "digits": digits, "limit": limit, "customer": customer_id}


def _own(alias: str, customer_id: str | None) -> str:
    """Restrict to one customer's records. A customer's search always passes it."""
    return f" AND {alias}.customer_id = %(customer)s" if customer_id else ""


def search_containers(tenant_id: str, text: str, pattern: str, limit: int) -> list[dict[str, Any]]:
    return execute_with_tenant(
        tenant_id,
        """
        SELECT c.id, c.container_number, c.status, c.vessel_name,
               lower(c.container_number) = lower(%(text)s) AS is_exact
        FROM container c
        WHERE c.tenant_id = %(tenant)s
          AND (c.container_number ILIKE %(pattern)s ESCAPE '\\' OR c.vessel_name ILIKE %(pattern)s ESCAPE '\\')
        ORDER BY is_exact DESC, c.created_at DESC
        LIMIT %(limit)s
        """,
        _params(tenant_id, text, pattern, "", limit, None),
    )


def search_shipments(
    tenant_id: str, text: str, pattern: str, digits: str, limit: int, *, customer_id: str | None, by_name: bool, by_phone: bool
) -> list[dict[str, Any]]:
    """Packing lists: by reference, container number, a carton's tracking code or tag, and (staff) the customer."""
    return execute_with_tenant(
        tenant_id,
        f"""
        SELECT pl.id, pl.reference, pl.status, cu.name AS customer_name, co.container_number,
               lower(pl.reference) = lower(%(text)s) AS is_exact
        FROM packing_list pl
        LEFT JOIN customer cu ON cu.id = pl.customer_id AND cu.tenant_id = pl.tenant_id
        LEFT JOIN container co ON co.id = pl.container_id AND co.tenant_id = pl.tenant_id
        WHERE pl.tenant_id = %(tenant)s{_own("pl", customer_id)}
          AND (pl.reference ILIKE %(pattern)s ESCAPE '\\'
               OR co.container_number ILIKE %(pattern)s ESCAPE '\\'
               OR EXISTS (
                   SELECT 1 FROM packing_list_item pli
                   WHERE pli.packing_list_id = pl.id
                     AND (pli.tracking_code ILIKE %(pattern)s ESCAPE '\\' OR pli.carton_tag ILIKE %(pattern)s ESCAPE '\\')
               ){_customer_clause("cu", by_name, by_phone)})
        ORDER BY is_exact DESC, pl.created_at DESC
        LIMIT %(limit)s
        """,  # noqa: S608 - only fixed fragments are interpolated; every value is a bound parameter
        _params(tenant_id, text, pattern, digits, limit, customer_id),
    )


def search_invoices(
    tenant_id: str, text: str, pattern: str, digits: str, limit: int, *, customer_id: str | None, by_name: bool, by_phone: bool
) -> list[dict[str, Any]]:
    """Invoices: by number, container number, and (staff) the customer."""
    return execute_with_tenant(
        tenant_id,
        f"""
        SELECT b.id, b.invoice_number, b.status, cu.name AS customer_name, co.container_number,
               lower(b.invoice_number) = lower(%(text)s) AS is_exact
        FROM billing b
        LEFT JOIN customer cu ON cu.id = b.customer_id AND cu.tenant_id = b.tenant_id
        LEFT JOIN container co ON co.id = b.container_id AND co.tenant_id = b.tenant_id
        WHERE b.tenant_id = %(tenant)s{_own("b", customer_id)}
          AND (b.invoice_number ILIKE %(pattern)s ESCAPE '\\'
               OR co.container_number ILIKE %(pattern)s ESCAPE '\\'{_customer_clause("cu", by_name, by_phone)})
        ORDER BY is_exact DESC, b.created_at DESC
        LIMIT %(limit)s
        """,  # noqa: S608 - only fixed fragments are interpolated; every value is a bound parameter
        _params(tenant_id, text, pattern, digits, limit, customer_id),
    )


def search_release_notes(
    tenant_id: str, text: str, pattern: str, digits: str, limit: int, *, customer_id: str | None, by_name: bool, by_phone: bool
) -> list[dict[str, Any]]:
    """Release notes: by reference, container number, and (staff) the customer."""
    return execute_with_tenant(
        tenant_id,
        f"""
        SELECT rn.id, rn.reference_number, rn.status, cu.name AS customer_name, co.container_number,
               lower(rn.reference_number) = lower(%(text)s) AS is_exact
        FROM release_note rn
        LEFT JOIN customer cu ON cu.id = rn.customer_id AND cu.tenant_id = rn.tenant_id
        LEFT JOIN container co ON co.id = rn.container_id AND co.tenant_id = rn.tenant_id
        WHERE rn.tenant_id = %(tenant)s{_own("rn", customer_id)}
          AND (rn.reference_number ILIKE %(pattern)s ESCAPE '\\'
               OR co.container_number ILIKE %(pattern)s ESCAPE '\\'{_customer_clause("cu", by_name, by_phone)})
        ORDER BY is_exact DESC, rn.created_at DESC
        LIMIT %(limit)s
        """,  # noqa: S608 - only fixed fragments are interpolated; every value is a bound parameter
        _params(tenant_id, text, pattern, digits, limit, customer_id),
    )


def search_customers(tenant_id: str, text: str, pattern: str, digits: str, limit: int, *, by_phone: bool) -> list[dict[str, Any]]:
    """Customer profiles, by name and (where allowed) by phone. Erased customers never match."""
    return execute_with_tenant(
        tenant_id,
        f"""
        SELECT cu.id, cu.name, cu.phone, lower(cu.name) = lower(%(text)s) AS is_exact
        FROM customer cu
        WHERE cu.tenant_id = %(tenant)s AND cu.anonymised_at IS NULL
          AND ({_CUSTOMER_NAME.format(c="cu")}{" OR " + _CUSTOMER_PHONE.format(c="cu") if by_phone else ""})
        ORDER BY is_exact DESC, cu.name
        LIMIT %(limit)s
        """,  # noqa: S608 - only fixed fragments are interpolated; every value is a bound parameter
        _params(tenant_id, text, pattern, digits, limit, None),
    )


def get_customer_id_for_user(tenant_id: str, user_id: str) -> str | None:
    """The customer record behind a portal login, or None."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT id FROM customer WHERE tenant_id = %s AND user_id = %s AND anonymised_at IS NULL LIMIT 1",
        (tenant_id, user_id),
    )
    return str(rows[0]["id"]) if rows else None
