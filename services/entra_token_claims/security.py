"""Inbound-caller authorization for the claims extension (pure, SDK-free).

Entra calls the extension with a bearer token (client-credentials) whose
`aud` is the extension's registered API app and whose `iss` is this tenant.
`function_app.py` verifies the token's signature/expiry against the tenant JWKS
(RS256) and then calls `is_authorized` with the decoded claims. Splitting the
claim checks out here keeps them unit-testable without a signing key.
"""

from typing import Any


def is_authorized(
    claims: dict[str, Any],
    expected_audience: str,
    expected_issuer: str,
) -> bool:
    """Whether the verified caller token is the expected Entra caller.

    Fails closed: an empty expected value is treated as misconfiguration and
    rejects, rather than skipping the check. Both must match.
    """
    if not expected_audience or not expected_issuer:
        return False
    return claims.get("aud") == expected_audience and claims.get("iss") == expected_issuer
