"""Pure request/response logic for the Entra OnTokenIssuanceStart event.

No Azure SDK imports — the lookup is injected as a callable — so this module is
fully unit-testable with a stub. `app.py` supplies the real DB-backed lookup
(`db_lookup.py`), keyed on the user's directory object id (`oid`).

Contract (Microsoft Graph custom authentication extension, token-issuance-start):
    request:  data.authenticationContext.user.id  → the signing-in user's oid
    response: data.actions[provideClaimsForToken].claims → {claim name: value}
See https://learn.microsoft.com/entra/identity-platform/custom-claims-provider-reference
"""

from collections.abc import Callable
from typing import Any

_RESPONSE_ODATA_TYPE = "microsoft.graph.onTokenIssuanceStartResponseData"
_ACTION_ODATA_TYPE = "microsoft.graph.tokenIssuanceStart.provideClaimsForToken"


def extract_object_id(event: dict[str, Any]) -> str:
    """Return the signing-in user's directory object id (`oid`), or "" if absent.

    Microsoft places it at `data.authenticationContext.user.id`.
    """
    try:
        return str(event["data"]["authenticationContext"]["user"]["id"] or "")
    except (KeyError, TypeError):
        return ""


def build_claims_response(
    event: dict[str, Any],
    lookup: Callable[[str], dict[str, str]],
) -> dict[str, Any]:
    """Build the token-issuance-start response carrying ShipX's claims.

    `lookup(oid)` returns a mapping of output claim name → value (e.g.
    ``{"tenant_id": "PLATFORM", "role": "platform_admin"}``); empty values are
    dropped. An unknown user (no oid, or a lookup returning nothing) yields an
    empty claim set — the token is still issued and the backend simply resolves
    no elevated role, so a DB miss fails open on the claim rather than
    blocking sign-in.
    """
    oid = extract_object_id(event)
    claims: dict[str, str] = {}
    if oid:
        for name, value in (lookup(oid) or {}).items():
            if value:
                claims[str(name)] = str(value)
    return {
        "data": {
            "@odata.type": _RESPONSE_ODATA_TYPE,
            "actions": [
                {
                    "@odata.type": _ACTION_ODATA_TYPE,
                    "claims": claims,
                }
            ],
        }
    }
