"""Bearer-token verification shared by the AWS Lambda authorizer and the
container (Azure Container Apps) in-process auth middleware.

On AWS, API Gateway runs ``services/authorizer/handler.py`` as a REQUEST
authorizer; on Azure there is no API Gateway, so the container's HTTP app runs
the same verification in-process before dispatching. Both call
:func:`build_authorizer_claims`, which returns the flat, Cognito-shaped claims
dict that ``shared.auth.get_tenant_context`` expects at
``requestContext.authorizer`` (keys: ``sub``, ``custom:tenant_id``,
``cognito:groups``, plus the impersonation markers when present).

Token types accepted, in order:
  1. An OIDC RS256 JWT verified against a JWKS endpoint (Cognito today; Entra
     once ``OIDC_JWKS_URL`` / ``OIDC_AUDIENCE`` point at it).
  2. A ShipX HS256 impersonation token (validated + checked live in the DB).

Environment variables:
  OIDC_JWKS_URL   — JWKS endpoint; falls back to COGNITO_JWKS_URL.
  OIDC_AUDIENCE   — expected audience (app client id); falls back to COGNITO_AUDIENCE.

The raw-claim shape is interpreted downstream by the active cloud's
``ClaimsMapper`` (``shared.providers.get_claims_mapper``); this module only
verifies the signature and normalises the claims into the authorizer contract.
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _jwks_url() -> str:
    """Return the configured JWKS endpoint (OIDC_JWKS_URL, else COGNITO_JWKS_URL)."""
    return os.environ.get("OIDC_JWKS_URL") or os.environ.get("COGNITO_JWKS_URL", "")


def _audience() -> str:
    """Return the expected token audience (OIDC_AUDIENCE, else COGNITO_AUDIENCE)."""
    return os.environ.get("OIDC_AUDIENCE") or os.environ.get("COGNITO_AUDIENCE", "")


def verify_oidc_jwt(token: str) -> dict[str, Any] | None:
    """Return decoded claims if ``token`` is a valid OIDC RS256 JWT, else None.

    Verifies the signature against the configured JWKS endpoint. Audience is
    enforced only when one is configured. Any verification failure (bad
    signature, expiry, audience, unreachable JWKS) yields None so the caller can
    fall through to the next token strategy.
    """
    try:
        import jwt
        from jwt import PyJWKClient

        jwks_url = _jwks_url()
        audience = _audience()
        if not jwks_url:
            return None
        jwks_client = PyJWKClient(jwks_url)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience or None,
            options={"verify_aud": bool(audience)},
        )
        return dict(claims)
    except Exception as exc:  # noqa: BLE001 - any failure means "not a valid OIDC JWT"
        logger.debug("OIDC JWT verification failed: %s", exc)
        return None


def verify_impersonation(token: str) -> dict[str, Any] | None:
    """Return claims if ``token`` is a valid, still-active ShipX impersonation
    token, else None.

    Validates the HS256 signature and confirms the impersonation session has not
    been ended or expired in the DB.
    """
    try:
        from services.tenant_management.impersonation import (
            get_active_session,
            verify_impersonation_token,
        )

        claims = verify_impersonation_token(token)
        if "impersonated_by" not in claims or "session_id" not in claims:
            return None

        session = get_active_session(claims["session_id"])
        if not session:
            logger.warning("Impersonation session %s is not active", claims["session_id"])
            return None
        return claims
    except Exception as exc:  # noqa: BLE001 - any failure means "not a valid impersonation token"
        logger.debug("Impersonation token verification failed: %s", exc)
        return None


def _oidc_claims_to_context(claims: dict[str, Any]) -> dict[str, Any]:
    """Project verified OIDC claims into the flat authorizer-context shape.

    Mirrors API Gateway's HTTP-API-v2 flattening of the list-valued
    ``cognito:groups`` claim to a comma-joined string.
    """
    groups = claims.get("cognito:groups", "")
    if isinstance(groups, list):
        groups = ",".join(groups)
    return {
        "sub": claims.get("sub", ""),
        "custom:tenant_id": claims.get("custom:tenant_id", ""),
        "cognito:groups": groups,
    }


def _impersonation_claims_to_context(claims: dict[str, Any]) -> dict[str, Any]:
    """Project impersonation claims into the authorizer-context shape.

    Synthesises ``cognito:groups`` from ``{tenant_id}:{role}`` so
    ``get_tenant_context`` parses the role exactly as it does for a real JWT,
    and passes the impersonation markers through for read-only enforcement.
    """
    tenant_id = claims.get("tenant_id", "")
    role = claims.get("role", "tenant_admin")
    return {
        "sub": claims.get("sub", ""),
        "custom:tenant_id": tenant_id,
        "cognito:groups": f"{tenant_id}:{role}",
        "impersonated_by": claims.get("impersonated_by", ""),
        "session_id": claims.get("session_id", ""),
        "read_only": "true",
    }


def build_authorizer_claims(token: str) -> dict[str, Any] | None:
    """Verify a bearer token and return the authorizer-context claims, or None.

    Tries an OIDC JWT first, then a ShipX impersonation token. The returned dict
    is the flat, Cognito-shaped claims structure that
    ``shared.auth.get_tenant_context`` reads from ``requestContext.authorizer``.
    Returns None when the token is missing/invalid so the caller denies (401).
    """
    if not token:
        return None

    oidc_claims = verify_oidc_jwt(token)
    if oidc_claims:
        return _oidc_claims_to_context(oidc_claims)

    impersonation_claims = verify_impersonation(token)
    if impersonation_claims:
        return _impersonation_claims_to_context(impersonation_claims)

    return None
