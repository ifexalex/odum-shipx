"""Microsoft Entra claims mapper.

Reads ShipX's logical identity fields out of a verified Entra (Microsoft
identity platform) JWT. Only the claim names/shape are Entra-specific; the
role interpretation (the `{tenant_id}:{role}` group format, the `platform_admin`
special case, the primary-role fallback) stays cloud-agnostic in
`shared/auth.py` (ADR-004), so this normalizes Entra's claims into the same
canonical shapes `CognitoClaimsMapper` returns.

Entra vs Cognito, and why `groups()` does more than parse a string
-----------------------------------------------------------------
Cognito owns its group *names* (`{tenant_id}:{role}`), so its token carries
them verbatim. Entra does not: a cloud-only security group is emitted in the
`groups` claim as the directory **object id** (a GUID), and emitting group
*display names* is only available for on-prem-synced groups — not the
cloud-only groups ShipX creates. A naive "the groups claim already holds
`{tenant_id}:{role}` names" assumption therefore resolves **no** roles on a
real Entra token (every GUID is dropped), which is the Cognito↔Entra
incompatibility this mapper closes. `groups()` accepts three shapes so the
same backend works regardless of how the Entra tenant's token is configured:

1. **Canonical names** (`platform_admin`, `{tenant_id}:{role}`) — passed through
   unchanged. Covers on-prem-synced groups or a claims-mapping policy that
   already emits names.
2. **Object ids** mapped back to names via `ENTRA_GROUP_ID_MAP` /
   `ENTRA_PLATFORM_ADMIN_GROUP_ID` — no Graph lookup on the auth hot path.
3. **Synthesized** from the `tenant_id` + `role` optional/extension claims,
   which Entra emits reliably. This is the primary, policy-free path: with
   `role=platform_admin` + `tenant_id=PLATFORM` in the token, `groups()`
   yields `["platform_admin"]` and `shared/auth.py` grants PLATFORM_ADMIN.

The claim names are overridable by env so the token config can change without
code changes (e.g. point `ENTRA_TENANT_ID_CLAIM` at a directory extension
`extension_<appId>_tenant_id`).
"""

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Entra emits the ShipX tenant id + primary role as custom/optional claims; the
# names depend on how the app's token config/claims-mapping is set up.
_TENANT_ID_CLAIM = os.environ.get("ENTRA_TENANT_ID_CLAIM", "tenant_id")
_ROLE_CLAIM = os.environ.get("ENTRA_ROLE_CLAIM", "role")

# The prefixless group that denotes a platform admin (ADR-004).
_PLATFORM_ADMIN_GROUP = "platform_admin"


def _load_group_id_map() -> dict[str, str]:
    """Build the Entra group-object-id → ShipX group-name map from env.

    Entra emits cloud-group membership in the `groups` claim as directory
    object ids (GUIDs), not names. This map translates the GUIDs the token
    actually carries back into ShipX's canonical names without a Graph call on
    the auth hot path. Sources are merged (later wins):

        ENTRA_GROUP_ID_MAP             JSON object {"<guid>": "<canonical name>"}
        ENTRA_PLATFORM_ADMIN_GROUP_ID  shorthand for {"<guid>": "platform_admin"}
    """
    mapping: dict[str, str] = {}
    raw = os.environ.get("ENTRA_GROUP_ID_MAP", "").strip()
    if raw:
        try:
            parsed: Any = json.loads(raw)
        except ValueError:
            # Malformed config must never silently grant or deny a role.
            logger.warning("ENTRA_GROUP_ID_MAP is not valid JSON; ignoring it")
        else:
            if isinstance(parsed, dict):
                mapping.update({str(k).strip(): str(v).strip() for k, v in parsed.items()})
            else:
                logger.warning("ENTRA_GROUP_ID_MAP is not a JSON object; ignoring it")
    platform_admin_gid = os.environ.get("ENTRA_PLATFORM_ADMIN_GROUP_ID", "").strip()
    if platform_admin_gid:
        mapping[platform_admin_gid] = _PLATFORM_ADMIN_GROUP
    return mapping


class EntraClaimsMapper:
    """ClaimsMapper for Entra-issued JWTs."""

    def __init__(self) -> None:
        # Captured once per instance; the active mapper is a cached singleton
        # (`get_claims_mapper`), so env is read at process start like the AWS adapter.
        self._group_id_map = _load_group_id_map()

    def user_id(self, claims: dict[str, Any]) -> str:
        # `oid` is the stable per-user object id in the directory; `sub` is
        # app-pairwise. Prefer oid, fall back to sub.
        return str(claims.get("oid") or claims.get("sub", ""))

    def tenant_id(self, claims: dict[str, Any]) -> str:
        # The ShipX tenant id (NOT `tid`, which is the Entra *directory* tenant).
        return str(claims.get(_TENANT_ID_CLAIM, ""))

    def groups(self, claims: dict[str, Any]) -> list[str]:
        """Normalize the `groups` claim to ShipX's canonical group names.

        Returns a list of `{tenant_id}:{role}` strings (plus the prefixless
        `platform_admin`), the shape `shared/auth.py` interprets. See the module
        docstring for the three accepted input shapes. Order is preserved and
        duplicates removed; unmapped object ids are dropped.
        """
        names: list[str] = []
        for entry in self._raw_groups(claims):
            if entry in self._group_id_map:
                names.append(self._group_id_map[entry])
            elif ":" in entry or entry == _PLATFORM_ADMIN_GROUP:
                # Already a canonical display name (on-prem-synced group or a
                # claims-mapping policy that emits names) — pass through.
                names.append(entry)
            # else: an unmapped directory object id we cannot interpret — skip.

        # Policy-free fallback: synthesize the canonical name from the tenant_id
        # + role optional claims, which Entra emits reliably even when the
        # groups claim carries only object ids.
        for synthesized in self._synthesize_groups(claims):
            names.append(synthesized)

        # De-duplicate, preserving first-seen order.
        seen: set[str] = set()
        return [name for name in names if not (name in seen or seen.add(name))]

    def primary_role(self, claims: dict[str, Any]) -> str | None:
        role = claims.get(_ROLE_CLAIM)
        return str(role) if role is not None else None

    def _raw_groups(self, claims: dict[str, Any]) -> list[str]:
        """Parse the raw `groups` claim into a list of strings.

        Accepts a JSON-array string, a bracketed/comma string, or an actual
        list — Entra emits an array in the token; API-GW-style flattening may
        hand it over as a string.
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

    def _synthesize_groups(self, claims: dict[str, Any]) -> list[str]:
        """Derive the canonical group name from the primary-role + tenant_id claims.

        `platform_admin` is prefixless; every other role is `{tenant_id}:{role}`.
        Returns an empty list when the role claim is absent (nothing to synthesize)
        or when a non-platform role has no tenant_id to scope it.
        """
        role = self.primary_role(claims)
        role = role.strip() if role else ""
        if not role:
            return []
        if role == _PLATFORM_ADMIN_GROUP:
            return [_PLATFORM_ADMIN_GROUP]
        tenant_id = self.tenant_id(claims).strip()
        return [f"{tenant_id}:{role}"] if tenant_id else []
