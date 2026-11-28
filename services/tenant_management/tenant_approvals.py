"""Tenant Admin Approvals Inbox — unified read model (Phase 1, TC-02, D5).

Aggregates every pending item that needs a tenant admin's decision without
duplicating source-of-truth tables:

1. ``credit_release`` — pending rows in ``credit_release_request``
2. ``refund``         — ``refund_request`` rows in ``pending_approval`` (or ``pending_review``
                        above staff threshold) that exceed staff authority
3. ``claim``          — open ``damage_claim`` rows (``filed``, ``under_inspection``,
                        ``inspection_complete``, ``pending_resolution``) whose ``claimed_amount_ngn``
                        exceeds the tenant's configured staff approval limit
4. ``announcement``   — pending rows in ``announcement_request``

Decisions are executed through each domain's own audited endpoint (credit-release
approve/reject, refund approve/reject, claim resolve, announcement approve/reject),
keeping one source of truth and one audit trail per domain.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from shared.db import execute_with_tenant
from shared.fx_rate import get_effective_dollar_rate
from shared.tenant_policies import resolve_policy_for_date

logger = logging.getLogger(__name__)

APPROVAL_TYPES = ("credit_release", "refund", "claim", "announcement")
_COMPENSATION_REFUND_TYPES = frozenset({"damage_or_loss", "missing_item", "seized_item"})
_HOF_THRESHOLD_NGN = Decimal("30000")


def _staff_limit_ngn(tenant_id: str) -> tuple[Decimal, Decimal]:
    """Return ``(staff_limit_usd, staff_limit_ngn)`` for threshold comparisons."""
    threshold_cfg = resolve_policy_for_date(tenant_id, "refund_threshold_usd")
    staff_limit_usd = Decimal(str(threshold_cfg.get("staff_limit", 50)))
    try:
        dollar_rate = Decimal(str(get_effective_dollar_rate(tenant_id)["rate"]))
    except Exception:
        # Fail-safe fallback for read-only inbox rendering when live FX feed is unavailable
        logger.warning("FX rate unavailable while computing approvals inbox threshold for tenant %s", tenant_id)
        dollar_rate = Decimal("1500")
    return staff_limit_usd, staff_limit_usd * dollar_rate


def _iso(val: Any) -> str | None:
    if val is None:
        return None
    return val.isoformat() if hasattr(val, "isoformat") else str(val)


def _fetch_credit_release_items(tenant_id: str, actor_id: str) -> list[dict[str, Any]]:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT r.id,
               r.billing_id,
               r.customer_id,
               r.carton_tags,
               r.packages_released,
               r.package_unit,
               r.due_date,
               r.amount_ngn,
               r.customer_credit_limit_ngn,
               r.customer_current_exposure_ngn,
               r.exceeds_credit_limit,
               r.reason,
               r.requested_by,
               r.created_at,
               c.name AS customer_name,
               b.invoice_number AS invoice_number,
               b.balance_ngn AS billing_balance_ngn,
               tu.full_name AS requested_by_name
        FROM credit_release_request r
        JOIN customer c ON c.id = r.customer_id AND c.tenant_id = r.tenant_id
        JOIN billing b ON b.id = r.billing_id AND b.tenant_id = r.tenant_id
        LEFT JOIN tenant_user tu ON tu.id = r.requested_by AND tu.tenant_id = r.tenant_id
        WHERE r.tenant_id = %s
          AND r.status = 'pending'
        ORDER BY r.created_at ASC
        """,
        (tenant_id,),
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        req_by = str(row["requested_by"]) if row.get("requested_by") else None
        tags = list(row.get("carton_tags") or [])
        qty_desc = (
            f"{len(tags)} carton(s)" if tags else f"{row.get('packages_released') or 0} {row.get('package_unit') or 'packages'}"
        )
        items.append(
            {
                "id": str(row["id"]),
                "type": "credit_release",
                "title": f"Credit release — {row.get('customer_name') or 'Customer'}",
                "summary": f"{qty_desc} on invoice {row.get('invoice_number') or str(row['billing_id'])[:8]}",
                "amount_ngn": str(row.get("amount_ngn") or "0"),
                "customer_id": str(row["customer_id"]),
                "customer_name": row.get("customer_name"),
                "customer_outstanding_ngn": str(row.get("customer_current_exposure_ngn") or "0"),
                "customer_credit_limit_ngn": (
                    str(row["customer_credit_limit_ngn"]) if row.get("customer_credit_limit_ngn") is not None else None
                ),
                "exceeds_credit_limit": bool(row.get("exceeds_credit_limit")),
                "requested_by": req_by,
                "requested_by_name": row.get("requested_by_name"),
                "self_requested": req_by == actor_id if req_by else False,
                "reason": row.get("reason") or "",
                "created_at": _iso(row.get("created_at")),
                "entity_id": str(row["id"]),
                "detail_path": f"/billing/{row['billing_id']}",
                "metadata": {
                    "billing_id": str(row["billing_id"]),
                    "invoice_number": row.get("invoice_number"),
                    "carton_tags": tags,
                    "packages_released": row.get("packages_released"),
                    "package_unit": row.get("package_unit"),
                    "due_date": _iso(row.get("due_date")),
                },
            }
        )
    return items


def _fetch_refund_items(tenant_id: str, actor_id: str, staff_limit_ngn: Decimal) -> list[dict[str, Any]]:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT rr.id,
               rr.customer_id,
               rr.billing_id,
               rr.refund_type,
               rr.amount_ngn,
               rr.reason,
               rr.status,
               rr.customer_choice,
               rr.requested_by,
               rr.created_at,
               c.name AS customer_name,
               tu.full_name AS requested_by_name
        FROM refund_request rr
        JOIN customer c ON c.id = rr.customer_id AND c.tenant_id = rr.tenant_id
        LEFT JOIN tenant_user tu ON tu.id = rr.requested_by AND tu.tenant_id = rr.tenant_id
        WHERE rr.tenant_id = %s
          AND rr.status = 'pending_approval'
        ORDER BY rr.created_at ASC
        """,
        (tenant_id,),
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        amount = Decimal(str(row.get("amount_ngn") or "0"))
        rtype = str(row.get("refund_type") or "")
        needs_admin = (
            amount > staff_limit_ngn
            or rtype == "cbm_correction"
            or (rtype in _COMPENSATION_REFUND_TYPES and amount > _HOF_THRESHOLD_NGN)
        )
        if not needs_admin:
            continue
        req_by = str(row["requested_by"]) if row.get("requested_by") else None
        items.append(
            {
                "id": str(row["id"]),
                "type": "refund",
                "title": f"Refund — {row.get('customer_name') or 'Customer'}",
                "summary": f"{rtype.replace('_', ' ')} refund ({row.get('customer_choice') or 'payout'})",
                "amount_ngn": str(amount),
                "customer_id": str(row["customer_id"]),
                "customer_name": row.get("customer_name"),
                "customer_outstanding_ngn": None,
                "customer_credit_limit_ngn": None,
                "exceeds_credit_limit": False,
                "requested_by": req_by,
                "requested_by_name": row.get("requested_by_name"),
                "self_requested": req_by == actor_id if req_by else False,
                "reason": row.get("reason") or "",
                "created_at": _iso(row.get("created_at")),
                "entity_id": str(row["id"]),
                "detail_path": f"/refunds/{row['id']}",
                "metadata": {
                    "refund_type": rtype,
                    "status": row.get("status"),
                    "customer_choice": row.get("customer_choice"),
                    "billing_id": str(row["billing_id"]) if row.get("billing_id") else None,
                },
            }
        )
    return items


def _fetch_claim_items(tenant_id: str, actor_id: str, staff_limit_ngn: Decimal) -> list[dict[str, Any]]:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT dc.id,
               dc.reference,
               dc.customer_id,
               dc.container_id,
               dc.claimed_amount_ngn,
               dc.description,
               dc.status,
               dc.submitted_by,
               dc.created_at,
               c.name AS customer_name,
               tu.full_name AS submitted_by_name
        FROM damage_claim dc
        JOIN customer c ON c.id = dc.customer_id AND c.tenant_id = dc.tenant_id
        LEFT JOIN tenant_user tu ON tu.id = dc.submitted_by AND tu.tenant_id = dc.tenant_id
        WHERE dc.tenant_id = %s
          AND dc.status IN ('filed', 'under_inspection', 'inspection_complete', 'pending_resolution')
          AND dc.claimed_amount_ngn IS NOT NULL
          AND dc.claimed_amount_ngn > %s
        ORDER BY dc.created_at ASC
        """,
        (tenant_id, staff_limit_ngn),
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        req_by = str(row["submitted_by"]) if row.get("submitted_by") else None
        items.append(
            {
                "id": str(row["id"]),
                "type": "claim",
                "title": f"Damage claim {row.get('reference') or ''} — {row.get('customer_name') or 'Customer'}".strip(),
                "summary": f"Status: {str(row.get('status') or '').replace('_', ' ')} (above staff limit)",
                "amount_ngn": str(row.get("claimed_amount_ngn") or "0"),
                "customer_id": str(row["customer_id"]),
                "customer_name": row.get("customer_name"),
                "customer_outstanding_ngn": None,
                "customer_credit_limit_ngn": None,
                "exceeds_credit_limit": False,
                "requested_by": req_by,
                "requested_by_name": row.get("submitted_by_name"),
                "self_requested": req_by == actor_id if req_by else False,
                "reason": row.get("description") or "",
                "created_at": _iso(row.get("created_at")),
                "entity_id": str(row["id"]),
                "detail_path": f"/claims/{row['id']}",
                "metadata": {
                    "reference": row.get("reference"),
                    "status": row.get("status"),
                    "container_id": str(row["container_id"]) if row.get("container_id") else None,
                },
            }
        )
    return items


def _fetch_announcement_items(tenant_id: str, actor_id: str) -> list[dict[str, Any]]:
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT ar.id,
               ar.title,
               ar.body,
               ar.audience,
               ar.requested_by,
               ar.created_at,
               tu.full_name AS requested_by_name
        FROM announcement_request ar
        LEFT JOIN tenant_user tu ON tu.id = ar.requested_by AND tu.tenant_id = ar.tenant_id
        WHERE ar.tenant_id = %s
          AND ar.status = 'pending'
        ORDER BY ar.created_at ASC
        """,
        (tenant_id,),
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        req_by = str(row["requested_by"]) if row.get("requested_by") else None
        items.append(
            {
                "id": str(row["id"]),
                "type": "announcement",
                "title": f"Announcement — {row.get('title') or 'Untitled'}",
                "summary": f"Audience: {row.get('audience') or 'all'}",
                "amount_ngn": None,
                "customer_id": None,
                "customer_name": None,
                "customer_outstanding_ngn": None,
                "customer_credit_limit_ngn": None,
                "exceeds_credit_limit": False,
                "requested_by": req_by,
                "requested_by_name": row.get("requested_by_name"),
                "self_requested": req_by == actor_id if req_by else False,
                "reason": row.get("body") or "",
                "created_at": _iso(row.get("created_at")),
                "entity_id": str(row["id"]),
                "detail_path": "/announcements",
                "metadata": {
                    "announcement_title": row.get("title"),
                    "audience": row.get("audience"),
                },
            }
        )
    return items


def get_tenant_approvals(
    tenant_id: str,
    *,
    actor_id: str,
    item_type: str | None = None,
    counts_only: bool = False,
) -> dict[str, Any]:
    """Return pending approval counts and (unless ``counts_only``) the unified queue."""
    staff_limit_usd, staff_limit_ngn = _staff_limit_ngn(tenant_id)

    credit_items = _fetch_credit_release_items(tenant_id, actor_id)
    refund_items = _fetch_refund_items(tenant_id, actor_id, staff_limit_ngn)
    claim_items = _fetch_claim_items(tenant_id, actor_id, staff_limit_ngn)
    announcement_items = _fetch_announcement_items(tenant_id, actor_id)

    counts = {
        "credit_release": len(credit_items),
        "refund": len(refund_items),
        "claim": len(claim_items),
        "announcement": len(announcement_items),
        "total": len(credit_items) + len(refund_items) + len(claim_items) + len(announcement_items),
    }

    if counts_only:
        return {
            "counts": counts,
            "staff_limit_usd": float(staff_limit_usd),
            "staff_limit_ngn": float(staff_limit_ngn),
            "items": [],
        }

    all_items = [*credit_items, *refund_items, *claim_items, *announcement_items]
    if item_type and item_type in APPROVAL_TYPES:
        all_items = [i for i in all_items if i["type"] == item_type]

    # Oldest waiting first so nothing stalls at the bottom of the queue
    all_items.sort(key=lambda i: i.get("created_at") or "")
    return {
        "counts": counts,
        "staff_limit_usd": float(staff_limit_usd),
        "staff_limit_ngn": float(staff_limit_ngn),
        "items": all_items,
    }
