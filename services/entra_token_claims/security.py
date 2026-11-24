"""Inbound-caller authorization for the claims extension (pure, SDK-free).

Entra calls the extension with a bearer token (client-credentials) whose
`aud` is the extension's registered API app and whose `iss` is this tenant.
`app.py` verifies the token's signature/expiry against the tenant JWKS
(RS256) and then calls `is_authorized` with the decoded claims. Splitting the
claim checks out here keeps them unit-testable without a signing key.
"""

from typing import Any

# Microsoft's built-in Entra External ID custom authentication extension caller app ID.
DEFAULT_ENTRA_EXTENSION_APP_ID = "99045fe1-7639-4a75-9d4a-577b6ca3810f"


def is_authorized(
    claims: dict[str, Any],
    expected_audience: str,
    expected_issuer: str,
    expected_caller_app_id: str | None = None,
) -> bool:
    """Whether the verified caller token is the expected Entra caller.

    Fails closed: an empty expected value is treated as misconfiguration and
    rejects, rather than skipping the check. When `expected_caller_app_id` is
    supplied, also verifies `azp` / `appid` matches the Entra custom-extension
    caller so other service principals in the tenant cannot query arbitrary oids.
    """
    if not expected_audience or not expected_issuer:
        return False
    if claims.get("aud") != expected_audience or claims.get("iss") != expected_issuer:
        return False
    if expected_caller_app_id:
        caller_app = claims.get("azp") or claims.get("appid")
        if caller_app != expected_caller_app_id:
            return False
    return True
