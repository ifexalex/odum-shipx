"""Global search: one box that finds a container, shipment, invoice, release note or customer (audit UX-05).

What a caller may find depends on their role, and is decided here, not by the screen:

* A customer finds their own shipments, invoices and release notes, by reference, container number or a carton's
  tracking code. Every query is pinned to their customer record.
* Staff find records across the tenant, limited to the kinds their role works with. Nigeria staff and tenant
  admins can also look a customer up by phone number, which is personal data and so is not offered to the other
  roles (China staff and warehouse attendants may match a customer by name only).
* Platform admins are refused: this is a tenant-scoped lookup and they span tenants.

The text only ever reaches SQL as a bound, escaped LIKE pattern.
"""

import re
from typing import Any

from shared.exceptions import InsufficientPermissionsError, ValidationError
from shared.tenant_context import UserRole

from . import repository as repo

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 64
PER_KIND_LIMIT = 5
TOTAL_LIMIT = 20

# Which kinds of record each role may find, in the order they are listed.
_KINDS: dict[UserRole, tuple[str, ...]] = {
    UserRole.TENANT_ADMIN: ("container", "shipment", "invoice", "release_note", "customer"),
    UserRole.NIGERIA_OFFICE_STAFF: ("container", "shipment", "invoice", "release_note"),
    UserRole.CHINA_OFFICE_STAFF: ("container", "shipment"),
    UserRole.WAREHOUSE_ATTENDANT: ("release_note",),
    UserRole.CUSTOMER: ("shipment", "invoice", "release_note"),
}

# Roles that may find someone by phone number.
_PHONE_LOOKUP_ROLES = frozenset({UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF})
_KIND_ORDER = {kind: i for i, kind in enumerate(("container", "shipment", "invoice", "release_note", "customer"))}


def _like_pattern(text: str) -> str:
    """`%text%` with the LIKE wildcards in `text` made literal."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _phone_pattern(text: str) -> str:
    """A digits-only LIKE pattern for matching a phone number however it was typed, or "" if `text` is not a number.

    `08012345678`, `+234 801 234 5678` and `2348012345678` are one number: the country code and the trunk 0 are
    dropped, and at least six digits are needed so a short fragment cannot match half the customer list.
    """
    digits = re.sub(r"\D", "", text)
    if not re.fullmatch(r"[\d\s+()\-.]+", text) or len(digits) < 6:
        return ""
    for prefix in ("234", "0"):
        if digits.startswith(prefix):
            digits = digits[len(prefix) :]
            break
    return f"%{digits}%" if len(digits) >= 6 else ""


def search(tenant_id: str, query: str, ctx: Any) -> dict[str, Any]:
    """Find records matching `query` that `ctx`'s role may see, best matches first."""
    role = ctx.role
    kinds = _KINDS.get(role)
    if kinds is None:  # platform admin, or a role added without deciding what it may find
        raise InsufficientPermissionsError("Search is not available for this role")

    text = " ".join(query.split())
    if len(text) > MAX_QUERY_LENGTH:
        raise ValidationError(f"Search text must be at most {MAX_QUERY_LENGTH} characters", field_errors={"q": "too long"})
    if len(text) < MIN_QUERY_LENGTH:
        return {"query": text, "results": []}

    pattern = _like_pattern(text)
    digits = _phone_pattern(text) if role in _PHONE_LOOKUP_ROLES else ""

    customer_id: str | None = None
    if role == UserRole.CUSTOMER:
        customer_id = repo.get_customer_id_for_user(tenant_id, ctx.user_id)
        if customer_id is None:
            return {"query": text, "results": []}
    staff = customer_id is None
    by_phone = bool(digits)

    found: list[dict[str, Any]] = []
    if "container" in kinds:
        for row in repo.search_containers(tenant_id, text, pattern, PER_KIND_LIMIT):
            # The status is its own field; repeating it in the subtitle shows the raw value ("in_transit") beside the label.
            found.append(_result("container", row, row["container_number"], _join(row.get("vessel_name"))))
    if "shipment" in kinds:
        for row in repo.search_shipments(
            tenant_id, text, pattern, digits, PER_KIND_LIMIT, customer_id=customer_id, by_name=staff, by_phone=by_phone
        ):
            found.append(
                _result(
                    "shipment",
                    row,
                    row.get("reference") or "Packing list",
                    _join(row.get("customer_name"), row.get("container_number")),
                )
            )
    if "invoice" in kinds:
        for row in repo.search_invoices(
            tenant_id, text, pattern, digits, PER_KIND_LIMIT, customer_id=customer_id, by_name=staff, by_phone=by_phone
        ):
            title = row.get("invoice_number") or "Invoice"
            found.append(_result("invoice", row, title, _join(row.get("customer_name"), row.get("container_number"))))
    if "release_note" in kinds:
        for row in repo.search_release_notes(
            tenant_id, text, pattern, digits, PER_KIND_LIMIT, customer_id=customer_id, by_name=staff, by_phone=by_phone
        ):
            found.append(
                _result(
                    "release_note", row, row["reference_number"], _join(row.get("customer_name"), row.get("container_number"))
                )
            )
    if "customer" in kinds:
        for row in repo.search_customers(tenant_id, text, pattern, digits, PER_KIND_LIMIT, by_phone=by_phone):
            found.append(_result("customer", row, row["name"], row.get("phone") if by_phone else None))

    # Exact matches first, then in the order the kinds are listed; the sort is stable, so each kind keeps its own ranking.
    found.sort(key=lambda r: (not r.pop("_exact"), _KIND_ORDER[r["kind"]]))
    return {"query": text, "results": found[:TOTAL_LIMIT]}


def _join(*parts: Any) -> str | None:
    joined = " · ".join(str(p) for p in parts if p)
    return joined or None


def _result(kind: str, row: dict[str, Any], title: str, subtitle: str | None) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": str(row["id"]),
        "title": title,
        "subtitle": subtitle,
        "status": row.get("status"),
        "_exact": bool(row.get("is_exact")),
    }
