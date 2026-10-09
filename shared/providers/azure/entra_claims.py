"""Microsoft Entra claims mapper.

Reads ShipX's logical identity fields out of a verified Entra (Microsoft
identity platform) JWT. Only the claim names/shape are Entra-specific; the
role interpretation (the `{tenant_id}:{role}` group format, the `platform_admin`
special case, the primary-role fallback) stays cloud-agnostic in
`shared/auth.py` (ADR-004), so this normalizes Entra's claims into the same
canonical shapes `CognitoClaimsMapper` returns.

Entra token configuration this assumes (documented in the Phase-4 setup
checklist): the app's token carries the ShipX tenant id and primary role as
optional/extension claims, and the `groups` claim is emitted as **group display
names** in `{tenant_id}:{role}` form (a group-claims / claims-mapping policy —
Entra emits group object ids by default). The two claim names are overridable
by env so the token config can change without code changes.
"""

import json
import os
from typing import Any

# Entra emits the ShipX tenant id + primary role as custom/optional claims; the
# names depend on how the app's token config/claims-mapping is set up.
_TENANT_ID_CLAIM = os.environ.get("ENTRA_TENANT_ID_CLAIM", "tenant_id")
_ROLE_CLAIM = os.environ.get("ENTRA_ROLE_CLAIM", "role")


class EntraClaimsMapper:
    """ClaimsMapper for Entra-issued JWTs."""

    def user_id(self, claims: dict[str, Any]) -> str:
        # `oid` is the stable per-user object id in the directory; `sub` is
        # app-pairwise. Prefer oid, fall back to sub.
        return str(claims.get("oid") or claims.get("sub", ""))

    def tenant_id(self, claims: dict[str, Any]) -> str:
        # The ShipX tenant id (NOT `tid`, which is the Entra *directory* tenant).
        return str(claims.get(_TENANT_ID_CLAIM, ""))

    def groups(self, claims: dict[str, Any]) -> list[str]:
        """Normalize the `groups` claim to a list of `{tenant_id}:{role}` names.

        Accepts a JSON-array string, a bracketed/comma string, or an actual
        list — Entra emits an array in the token; API-GW-style flattening may
        hand it over as a string. Group names are expected in ShipX's canonical
        `{tenant_id}:{role}` form (see the module docstring).
        """
        raw: Any = claims.get("groups", "")
        if isinstance(raw, list):
            return [str(g).strip() for g in raw if str(g).strip()]
        raw_str = str(raw or "")
        if raw_str.startswith("["):
            try:
                parsed: list[str] = json.loads(raw_str)
                return [str(g).strip() for g in parsed if str(g).strip()]
            except ValueError:
                raw_str = raw_str.strip("[]")
        return [g.strip() for g in raw_str.split(",") if g.strip()]

    def primary_role(self, claims: dict[str, Any]) -> str | None:
        role = claims.get(_ROLE_CLAIM)
        return str(role) if role is not None else None
