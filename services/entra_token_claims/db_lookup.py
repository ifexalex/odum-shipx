"""ShipX-DB-backed claims lookup for the Entra claims provider.

Resolves a signing-in user's tenant_id + primary role from `tenant_user` by the
Entra object id (`oid`) — which provisioning persists in the globally-unique
`cognito_sub` column (the IdP-subject key). Email is deliberately NOT the key:
it is unique only per tenant (`UNIQUE (tenant_id, email)`), so one address can
exist under several tenants and keying on it would be cross-tenant-ambiguous.

The read is PLATFORM-scoped (it spans tenants, exactly like the tenant-status
check in `shared/auth.py`) and parameterized; no Microsoft Graph permission is
required. `app.py` injects an instance as the `lookup` callable.
"""

import logging
from typing import Any

from shared.db import execute_with_tenant
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)

_QUERY = "SELECT tenant_id, role FROM tenant_user WHERE cognito_sub = %s AND status = 'active' LIMIT 1"


class DatabaseClaimsReader:
    """Callable `lookup(oid) -> {output_claim_name: value}` backed by the DB.

    Maps `tenant_user.tenant_id` / `role` onto the output claim names the backend
    reads (`ENTRA_TENANT_ID_CLAIM` / `ENTRA_ROLE_CLAIM`, default `tenant_id` /
    `role`). Any DB failure (or no match) returns an empty mapping so a miss
    never blocks sign-in — the token still issues and the backend grants no
    elevated role (platform admins resolve independently via the group claim).
    """

    def __init__(self, out_tenant_claim: str = "tenant_id", out_role_claim: str = "role") -> None:
        self._out_tenant = out_tenant_claim
        self._out_role = out_role_claim

    def __call__(self, oid: str) -> dict[str, str]:
        if not oid:
            return {}
        try:
            rows = execute_with_tenant(tenant_id=PLATFORM_TENANT_ID, query=_QUERY, params=(oid,))
        except Exception as exc:
            # Fail open on the claim only; never log PII (no email/name).
            logger.warning("Claims DB lookup failed: %s", exc)
            return {}
        if not rows:
            return {}
        row: dict[str, Any] = rows[0]
        out: dict[str, str] = {}
        if row.get("tenant_id"):
            out[self._out_tenant] = str(row["tenant_id"])
        if row.get("role"):
            out[self._out_role] = str(row["role"])
        return out
