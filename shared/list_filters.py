"""WHERE-clause builders for the list screens that can also be exported.

A list and its export must agree on which rows match: "Export" on a filtered screen has to give back what is on
the screen. Both therefore build their filter here, once, rather than each keeping its own copy that can drift.

Every value reaches SQL as a bound parameter; only fixed fragments are spliced in. The clauses use the table aliases
of the queries they belong to (`b`, `cu`, `c`), which the caller's FROM clause must define.
"""

from typing import Any


def _status_list(filters: dict[str, Any]) -> list[str]:
    """`status` as a list: it is one string or several (the Filters panel's multi-select)."""
    statuses = filters["status"]
    return [statuses] if isinstance(statuses, str) else list(statuses)


def billing_filter(tenant_id: str, filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """WHERE clause and parameters for the invoice list (aliases `b` billing, `cu` customer, `c` container).

    Recognised filters: `status`, `customer_id`, `created_after` / `created_before` (on `billed_at`), and `q`, a
    free-text match on invoice number, customer name or container number.
    """
    conditions = ["b.tenant_id = %(tenant_id)s"]
    params: dict[str, Any] = {"tenant_id": tenant_id}

    if filters.get("status"):
        conditions.append("b.status = ANY(%(statuses)s)")
        params["statuses"] = _status_list(filters)
    if filters.get("customer_id"):
        conditions.append("b.customer_id = %(customer_id)s")
        params["customer_id"] = filters["customer_id"]
    if filters.get("created_after"):
        conditions.append("b.billed_at >= %(created_after)s")
        params["created_after"] = filters["created_after"]
    if filters.get("created_before"):
        conditions.append("b.billed_at <= %(created_before)s")
        params["created_before"] = filters["created_before"]
    if filters.get("q"):
        conditions.append("(b.invoice_number ILIKE %(q)s OR cu.name ILIKE %(q)s OR c.container_number ILIKE %(q)s)")
        params["q"] = f"%{filters['q']}%"

    return " AND ".join(conditions), params


def container_filter(tenant_id: str, filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """WHERE clause and parameters for the container list (alias `c`).

    Recognised filters: `status`, `created_after` / `created_before`, `eta_after` / `eta_before` (on
    `estimated_arrival_date`), and `q`, a free-text match on container number, vessel name or voyage number.
    """
    conditions = ["c.tenant_id = %(tenant_id)s"]
    params: dict[str, Any] = {"tenant_id": tenant_id}

    if filters.get("status"):
        conditions.append("c.status = ANY(%(statuses)s)")
        params["statuses"] = _status_list(filters)
    if filters.get("created_after"):
        conditions.append("c.created_at >= %(created_after)s")
        params["created_after"] = filters["created_after"]
    if filters.get("created_before"):
        conditions.append("c.created_at <= %(created_before)s")
        params["created_before"] = filters["created_before"]
    if filters.get("eta_after"):
        conditions.append("c.estimated_arrival_date >= %(eta_after)s")
        params["eta_after"] = filters["eta_after"]
    if filters.get("eta_before"):
        conditions.append("c.estimated_arrival_date <= %(eta_before)s")
        params["eta_before"] = filters["eta_before"]
    if filters.get("q"):
        conditions.append("(c.container_number ILIKE %(q)s OR c.vessel_name ILIKE %(q)s OR c.voyage_number ILIKE %(q)s)")
        params["q"] = f"%{filters['q']}%"

    return " AND ".join(conditions), params
