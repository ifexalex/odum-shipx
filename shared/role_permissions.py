"""Canonical tenant role-to-capability map (Tenant Admin Phase 1, TC-05).

Serves ``GET /v1/tenant/permissions`` so the Staff Detail page never drifts from
the backend's actual role gates. Each capability entry names the handler module
and role-tuple attribute it mirrors (when backed by a module-level constant),
and ``tests/unit/test_role_permissions_parity.py`` imports every listed handler
and fails CI if a handler's role list disagrees with this map.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.tenant_context import UserRole

TENANT_ROLE_ORDER: tuple[UserRole, ...] = (
    UserRole.TENANT_ADMIN,
    UserRole.CHINA_OFFICE_STAFF,
    UserRole.NIGERIA_OFFICE_STAFF,
    UserRole.WAREHOUSE_ATTENDANT,
    UserRole.CUSTOMER,
)


@dataclass(frozen=True)
class CapabilityDef:
    """One business capability and the tenant roles permitted to perform it."""

    key: str
    domain: str
    label: str
    roles: frozenset[UserRole]
    # Optional (module_path, attr_name) pair checked by test_role_permissions_parity.py
    handler_binding: tuple[str, str] | None = None


CAPABILITIES: tuple[CapabilityDef, ...] = (
    # --- Operations ---
    CapabilityDef(
        key="containers.view",
        domain="Operations",
        label="View containers and shipping stages",
        roles=frozenset({UserRole.TENANT_ADMIN, UserRole.CHINA_OFFICE_STAFF, UserRole.NIGERIA_OFFICE_STAFF}),
        handler_binding=("services.tracking.handler", "_CONTAINER_READ_ROLES"),
    ),
    CapabilityDef(
        key="packing_lists.workflow",
        domain="Operations",
        label="Create, submit, and approve packing lists",
        roles=frozenset({UserRole.TENANT_ADMIN, UserRole.CHINA_OFFICE_STAFF}),
        handler_binding=("services.packing_list.handler", "_WORKFLOW_ROLES"),
    ),
    CapabilityDef(
        key="manifests.verify",
        domain="Operations",
        label="Verify cargo manifests",
        roles=frozenset({UserRole.TENANT_ADMIN, UserRole.CHINA_OFFICE_STAFF, UserRole.NIGERIA_OFFICE_STAFF}),
        handler_binding=("services.manifest.handler", "_VERIFY_ROLES"),
    ),
    CapabilityDef(
        key="manifests.resolve_discrepancies",
        domain="Operations",
        label="Resolve manifest discrepancies",
        roles=frozenset({UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF}),
        handler_binding=("services.manifest.handler", "_RESOLVE_ROLES"),
    ),
    # --- Billing & Payments ---
    CapabilityDef(
        key="billing.read",
        domain="Money",
        label="View invoices and billing records",
        roles=frozenset({UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF, UserRole.CUSTOMER}),
        handler_binding=("services.billing.handler", "_BILLING_READ_ROLES"),
    ),
    CapabilityDef(
        key="billing.cancel",
        domain="Money",
        label="Cancel invoices and delete misc charges",
        roles=frozenset({UserRole.TENANT_ADMIN}),
        handler_binding=("services.billing.handler", "_CANCEL_BILLING_ROLES"),
    ),
    CapabilityDef(
        key="carryovers.exempt",
        domain="Money",
        label="Exempt customer debt carryovers",
        roles=frozenset({UserRole.TENANT_ADMIN}),
        handler_binding=("services.billing.handler", "_CARRYOVER_EXEMPT_ROLES"),
    ),
    CapabilityDef(
        key="payments.confirm",
        domain="Money",
        label="Record payments and review payment claims",
        roles=frozenset({UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF}),
        handler_binding=("services.payment_release.handler", "_PAYMENT_ROLES"),
    ),
    CapabilityDef(
        key="disputes.resolve",
        domain="Money",
        label="Investigate and resolve CBM disputes",
        roles=frozenset({UserRole.TENANT_ADMIN, UserRole.CHINA_OFFICE_STAFF, UserRole.NIGERIA_OFFICE_STAFF}),
        handler_binding=("services.billing.handler", "_RESOLVE_ROLES"),
    ),
    # --- Warehouse & Release ---
    CapabilityDef(
        key="release_notes.create",
        domain="Warehouse",
        label="Generate release notes and request credit releases",
        roles=frozenset({UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF}),
        handler_binding=("services.payment_release.handler", "_RELEASE_CREATE_ROLES"),
    ),
    CapabilityDef(
        key="release_notes.approve_credit",
        domain="Warehouse",
        label="Approve goods release on credit",
        roles=frozenset({UserRole.TENANT_ADMIN}),
        handler_binding=("services.payment_release.handler", "_CREDIT_APPROVE_ROLES"),
    ),
    CapabilityDef(
        key="release_notes.pickup",
        domain="Warehouse",
        label="Record physical cargo pickup at the warehouse",
        roles=frozenset({UserRole.WAREHOUSE_ATTENDANT}),
        handler_binding=("services.payment_release.handler", "_PICKUP_ROLES"),
    ),
    CapabilityDef(
        key="release_notes.view",
        domain="Warehouse",
        label="View release notes",
        roles=frozenset(
            {
                UserRole.TENANT_ADMIN,
                UserRole.NIGERIA_OFFICE_STAFF,
                UserRole.WAREHOUSE_ATTENDANT,
                UserRole.CUSTOMER,
            }
        ),
        handler_binding=("services.payment_release.handler", "_RELEASE_READ_ROLES"),
    ),
    # --- Claims & Refunds ---
    CapabilityDef(
        key="claims.resolve",
        domain="Claims",
        label="Inspect and resolve damage claims (within threshold for staff)",
        roles=frozenset({UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF}),
        handler_binding=("services.claims.handler", "_RESOLVE_ROLES"),
    ),
    CapabilityDef(
        key="refunds.approve_within_limit",
        domain="Claims",
        label="Review and approve refunds within staff threshold",
        roles=frozenset({UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF}),
        handler_binding=("services.refunds.handler", "_APPROVE_ROLES"),
    ),
    CapabilityDef(
        key="refunds.approve_above_limit",
        domain="Claims",
        label="Approve refunds and claims above the configured limit",
        roles=frozenset({UserRole.TENANT_ADMIN}),
    ),
    # --- Admin & Governance ---
    CapabilityDef(
        key="admin.staff_and_config",
        domain="Admin",
        label="Manage staff users, roles, policies, rates, and tenant settings",
        roles=frozenset({UserRole.TENANT_ADMIN}),
    ),
    CapabilityDef(
        key="admin.approvals",
        domain="Admin",
        label="Approve credit releases, announcements, and high-value refunds",
        roles=frozenset({UserRole.TENANT_ADMIN}),
    ),
    CapabilityDef(
        key="admin.warehouses",
        domain="Admin",
        label="Create and manage warehouse locations",
        roles=frozenset({UserRole.TENANT_ADMIN}),
        handler_binding=("services.payment_release.handler", "_WAREHOUSE_WRITE_ROLES"),
    ),
    CapabilityDef(
        key="admin.customer_credit",
        domain="Admin",
        label="Set per-customer credit limits and payment terms",
        roles=frozenset({UserRole.TENANT_ADMIN}),
    ),
    CapabilityDef(
        key="admin.customer_gdpr",
        domain="Admin",
        label="Export or erase customer personal data (GDPR/NDPR)",
        roles=frozenset({UserRole.TENANT_ADMIN}),
    ),
)


def get_role_permissions_payload() -> dict[str, Any]:
    """Return the serialized payload for ``GET /v1/tenant/permissions``."""
    roles_map: dict[str, list[dict[str, Any]]] = {}
    for role in TENANT_ROLE_ORDER:
        entries: list[dict[str, Any]] = []
        for cap in CAPABILITIES:
            entries.append(
                {
                    "key": cap.key,
                    "domain": cap.domain,
                    "label": cap.label,
                    "allowed": role in cap.roles,
                }
            )
        roles_map[role.value] = entries
    return {
        "roles": roles_map,
        "capabilities": [
            {
                "key": cap.key,
                "domain": cap.domain,
                "label": cap.label,
                "roles": sorted(r.value for r in cap.roles),
            }
            for cap in CAPABILITIES
        ],
    }
