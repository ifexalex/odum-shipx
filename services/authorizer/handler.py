"""Lambda Authorizer — accepts Cognito JWTs and ShipX impersonation tokens.

This Lambda authorizer replaces the native JWT authorizer in API Gateway so
that impersonation tokens can be accepted alongside real Cognito JWTs.

Token-type detection:
  - If the Authorization header is a valid Cognito JWT (verified against the
    Cognito JWKS endpoint at COGNITO_JWKS_URL), treat it as a normal user.
  - If the JWT payload contains "impersonated_by" and "session_id", treat it
    as a ShipX impersonation token (HS256, validated against IMPERSONATION_SECRET
    or IMPERSONATION_SECRET_ARN). The session is also checked in the DB to ensure
    it has not been ended or expired.

On success, the authorizer returns an IAM policy + context dict with:
  - principalId:   sub (user_id)
  - context fields injected into requestContext.authorizer:
      - claims.sub
      - claims.custom:tenant_id
      - claims.cognito:groups  (synthesised from role)
      - claims.impersonated_by (impersonation only)
      - claims.session_id      (impersonation only)
      - claims.read_only       (impersonation only)

Terraform changes required to adopt this authorizer:
  1. In infrastructure/aws/modules/api-gateway/main.tf:
     - Replace the existing `aws_apigatewayv2_authorizer.cognito` (type JWT)
       with a new `aws_apigatewayv2_authorizer.custom` (type REQUEST) pointing
       to this Lambda ARN with enableSimpleResponses = false.
     - Add `aws_lambda_permission` to allow API GW to invoke the authorizer Lambda.
  2. Create a new Lambda in infrastructure/aws/modules/lambda/main.tf:
     - handler: services/authorizer/handler.lambda_handler
     - env vars: COGNITO_JWKS_URL, COGNITO_AUDIENCE (user pool client ID),
                 IMPERSONATION_SECRET_ARN
     - VPC config: yes (needs DB access for session validation)
     - IAM: secretsmanager:GetSecretValue on IMPERSONATION_SECRET_ARN
  3. Update all authenticated aws_apigatewayv2_route resources to reference
     the new authorizer_id instead of cognito.id.

Environment variables:
  COGNITO_JWKS_URL   — e.g. https://cognito-idp.eu-west-1.amazonaws.com/{pool_id}/.well-known/jwks.json
  COGNITO_AUDIENCE   — Cognito user pool client ID
  IMPERSONATION_SECRET_ARN — Secrets Manager ARN for the HS256 signing secret
  IMPERSONATION_SECRET     — fallback for local dev
"""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from shared.logging_config import bind_log_context, clear_log_context, setup_logging

# Module-level init (runs once on cold start)
setup_logging()

logger = logging.getLogger(__name__)

# Simple in-process cache for JWKS (refreshed on cold start only)
_jwks_cache: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# JWKS / Cognito helpers
# ---------------------------------------------------------------------------


def _fetch_jwks() -> dict[str, Any]:
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache
    jwks_url = os.environ.get("COGNITO_JWKS_URL", "")
    if not jwks_url:
        return {"keys": []}
    with urllib.request.urlopen(jwks_url, timeout=5) as resp:
        _jwks_cache = json.loads(resp.read())
    return _jwks_cache


def _verify_cognito_jwt(token: str) -> dict[str, Any] | None:
    """Return decoded claims if the token is a valid Cognito JWT, else None."""
    try:
        import jwt
        from jwt import PyJWKClient

        jwks_url = os.environ.get("COGNITO_JWKS_URL", "")
        audience = os.environ.get("COGNITO_AUDIENCE", "")
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
    except Exception as exc:
        logger.debug("Cognito JWT verification failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Impersonation token helpers
# ---------------------------------------------------------------------------


def _verify_impersonation_token(token: str) -> dict[str, Any] | None:
    """Return decoded claims if valid ShipX impersonation token, else None."""
    try:
        from services.tenant_management.impersonation import verify_impersonation_token

        claims = verify_impersonation_token(token)
        if "impersonated_by" not in claims or "session_id" not in claims:
            return None

        # Verify the session is still active in the DB
        from services.tenant_management.impersonation import get_active_session

        session = get_active_session(claims["session_id"])
        if not session:
            logger.warning("Impersonation session %s is not active", claims["session_id"])
            return None
        return claims
    except Exception as exc:
        logger.debug("Impersonation token verification failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# IAM policy helper
# ---------------------------------------------------------------------------


def _build_policy(
    principal_id: str,
    effect: str,
    resource: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource,
                }
            ],
        },
        "context": {k: str(v) if v is not None else "" for k, v in context.items()},
    }


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """API Gateway REQUEST authorizer.

    Accepts:
      - Cognito RS256 JWT (standard user session)
      - ShipX HS256 impersonation JWT (platform admin impersonation)

    Returns an IAM policy document with principal + context claims injected
    into the request so downstream Lambdas can call get_tenant_context() as-is.
    """
    clear_log_context()
    bind_log_context(request_id=event.get("requestContext", {}).get("requestId") or getattr(context, "aws_request_id", None))
    method_arn = event.get("methodArn", "*")
    auth_header = (event.get("headers") or {}).get("authorization", "")
    if not auth_header.startswith("Bearer "):
        logger.warning("Missing or malformed Authorization header")
        raise Exception("Unauthorized")  # API GW interprets this as 401

    token = auth_header[len("Bearer ") :]

    # 1. Try Cognito JWT first
    cognito_claims = _verify_cognito_jwt(token)
    if cognito_claims:
        sub = cognito_claims.get("sub", "")
        tenant_id = cognito_claims.get("custom:tenant_id", "")
        groups = cognito_claims.get("cognito:groups", "")
        if isinstance(groups, list):
            groups = ",".join(groups)

        bind_log_context(tenant_id=tenant_id or None, user_id=sub or None)
        ctx: dict[str, Any] = {
            "sub": sub,
            "custom:tenant_id": tenant_id,
            "cognito:groups": groups,
        }
        return _build_policy(sub or "user", "Allow", method_arn, ctx)

    # 2. Try ShipX impersonation token
    impersonation_claims = _verify_impersonation_token(token)
    if impersonation_claims:
        sub = impersonation_claims.get("sub", "")
        tenant_id = impersonation_claims.get("tenant_id", "")
        role = impersonation_claims.get("role", "tenant_admin")

        # Synthesise cognito:groups so get_tenant_context() parses role normally
        synthesised_groups = f"{tenant_id}:{role}"

        bind_log_context(tenant_id=tenant_id or None, user_id=sub or None)

        ctx = {
            "sub": sub,
            "custom:tenant_id": tenant_id,
            "cognito:groups": synthesised_groups,
            "impersonated_by": impersonation_claims.get("impersonated_by", ""),
            "session_id": impersonation_claims.get("session_id", ""),
            "read_only": "true",
        }
        return _build_policy(sub or "impersonated", "Allow", method_arn, ctx)

    logger.warning("Token validation failed for all strategies")
    raise Exception("Unauthorized")
