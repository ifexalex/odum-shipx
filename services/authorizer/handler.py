"""Lambda Authorizer — accepts Cognito JWTs and ShipX impersonation tokens.

This Lambda authorizer replaces the native JWT authorizer in API Gateway so
that impersonation tokens can be accepted alongside real Cognito JWTs.

Token-type detection and verification live in ``shared/auth_verify.py`` so the
exact same logic backs the Azure Container Apps in-process auth middleware
(``services/http_app/app.py``). This handler is the AWS/API-Gateway adapter
around it: it turns the verified claims into an IAM policy + context.

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
      - sub
      - custom:tenant_id
      - cognito:groups  (synthesised from role)
      - impersonated_by (impersonation only)
      - session_id      (impersonation only)
      - read_only       (impersonation only)

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

import logging
from typing import Any

from shared.auth_verify import build_authorizer_claims
from shared.logging_config import bind_log_context, clear_log_context, setup_logging

# Module-level init (runs once on cold start)
setup_logging()

logger = logging.getLogger(__name__)


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

    claims = build_authorizer_claims(token)
    if claims is None:
        logger.warning("Token validation failed for all strategies")
        raise Exception("Unauthorized")

    sub = claims.get("sub", "")
    bind_log_context(
        tenant_id=claims.get("custom:tenant_id") or None,
        user_id=sub or None,
    )
    principal_fallback = "impersonated" if claims.get("impersonated_by") else "user"
    return _build_policy(sub or principal_fallback, "Allow", method_arn, claims)
