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

# Cache PyJWKClient per JWKS URL so each request does not perform a fresh outbound
# JWKS fetch (PyJWKClient caches keys internally for 300s by default).
_JWKS_CLIENTS: dict[str, Any] = {}


def _jwks_url() -> str:
    """Return the configured JWKS endpoint (OIDC_JWKS_URL, else COGNITO_JWKS_URL)."""
    return os.environ.get("OIDC_JWKS_URL") or os.environ.get("COGNITO_JWKS_URL", "")


def _audience() -> str:
    """Return the expected token audience (OIDC_AUDIENCE, else COGNITO_AUDIENCE)."""
    return os.environ.get("OIDC_AUDIENCE") or os.environ.get("COGNITO_AUDIENCE", "")


def _issuer() -> str:
    """Return the expected token issuer (OIDC_ISSUER, else COGNITO_ISSUER)."""
    return os.environ.get("OIDC_ISSUER") or os.environ.get("COGNITO_ISSUER", "")


def _get_jwks_client(jwks_url: str) -> Any:
    client = _JWKS_CLIENTS.get(jwks_url)
    if client is None:
        from jwt import PyJWKClient

        client = PyJWKClient(jwks_url, cache_keys=True)
        _JWKS_CLIENTS[jwks_url] = client
    return client


def verify_oidc_jwt(token: str) -> dict[str, Any] | None:
    """Return decoded claims if ``token`` is a valid OIDC RS256 JWT, else None.

    Verifies signature, expiry, audience (fail-closed: requires OIDC_AUDIENCE /
    COGNITO_AUDIENCE), issuer (fail-closed outside local/test when OIDC_ISSUER /
    COGNITO_ISSUER is absent), and rejects both Cognito access tokens
    (`token_use != "id"`) and Entra access tokens (`scp` claim present).
    """
    try:
        import jwt

        jwks_url = _jwks_url()
        audience = _audience()
        issuer = _issuer()
        env = os.environ.get("ENVIRONMENT", "").strip().lower()
        if not jwks_url or not audience:
            return None
        if not issuer and env not in ("", "local", "test"):
            logger.warning("OIDC_ISSUER / COGNITO_ISSUER is not configured in environment=%s — rejecting token", env)
            return None
        jwks_client = _get_jwks_client(jwks_url)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        decode_kwargs: dict[str, Any] = {
            "algorithms": ["RS256"],
            "audience": audience,
            "options": {"verify_aud": True},
        }
        if issuer:
            decode_kwargs["issuer"] = issuer
        claims = jwt.decode(token, signing_key.key, **decode_kwargs)
        # Reject Cognito access tokens (only ID tokens carry tenant/role claims).
        if claims.get("token_use") is not None and claims.get("token_use") != "id":
            return None
        # Reject Entra access tokens (ID tokens never carry delegated OAuth scopes).
        if claims.get("scp") is not None:
            return None
        return dict(claims)
    except Exception as exc:  # noqa: BLE001 - any failure means "not a valid OIDC JWT"
        logger.debug("OIDC JWT verification failed: %s", exc)
        return None


def verify_impersonation(token: str) -> dict[str, Any] | None:
    """Return claims if ``token`` is a valid, still-active ShipX impersonation
    token, else None.

    Validates the HS256 signature, confirms the impersonation session has not
    been ended or expired in the DB, and verifies that the token's tenant, user,
    role, and platform_admin claims match the authoritative DB session row.
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
        if (
            str(session.get("target_tenant_id") or "") != str(claims.get("tenant_id") or "")
            or str(session.get("target_user_id") or "") != str(claims.get("sub") or "")
            or str(session.get("platform_admin_id") or "") != str(claims.get("impersonated_by") or "")
            or str(session.get("target_role") or "tenant_admin") != str(claims.get("role") or "")
            or not bool(session.get("read_only", True))
        ):
            logger.warning("Impersonation session %s claim mismatch — rejecting token", claims["session_id"])
            return None
        return claims
    except Exception as exc:  # noqa: BLE001 - any failure means "not a valid impersonation token"
        logger.debug("Impersonation token verification failed: %s", exc)
        return None


def _oidc_claims_to_context(claims: dict[str, Any]) -> dict[str, Any]:
    """Project verified OIDC claims into the authorizer-context shape.

    Passes the verified claims through unchanged except for mirroring API
    Gateway's HTTP-API-v2 flattening of the list-valued ``cognito:groups`` claim
    to a comma-joined string. The claims are interpreted downstream by the active
    cloud's ``ClaimsMapper``, so the provider-specific keys must survive: Cognito
    reads ``sub`` / ``custom:tenant_id`` / ``cognito:groups``, while Entra reads
    ``oid`` / ``tenant_id`` / ``role`` / ``groups`` (GUIDs). Projecting to only the
    Cognito keys (as this did originally) dropped every Entra claim, so on Azure
    the mapper saw an empty identity and every authenticated request 401'd.
    """
    context = dict(claims)
    groups = context.get("cognito:groups")
    if isinstance(groups, list):
        context["cognito:groups"] = ",".join(groups)
    return context


def _impersonation_claims_to_context(claims: dict[str, Any]) -> dict[str, Any]:
    """Project impersonation claims into the authorizer-context shape.

    Emits both Cognito (`custom:tenant_id`, `cognito:groups`) and Entra
    (`oid`, `tenant_id`, `role`, `groups`) keys so impersonation works identically
    regardless of `CLOUD_PROVIDER`, and passes the impersonation markers through
    for fail-closed read-only enforcement.
    """
    sub = claims.get("sub", "")
    tenant_id = claims.get("tenant_id", "")
    role = claims.get("role", "tenant_admin")
    return {
        "sub": sub,
        "oid": sub,
        "tenant_id": tenant_id,
        "role": role,
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
