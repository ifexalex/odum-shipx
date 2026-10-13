"""Cognito refresh-token exchange for the httpOnly-cookie session-persistence flow.

The frontend keeps the ID token in memory only — never persisted, see
11_security_and_compliance.md. The Cognito *refresh* token instead lives in a
Secure, HttpOnly, SameSite=Strict cookie set by this service (services/auth/handler.py),
scoped to Path=/v1/auth so it is never sent to any other endpoint and — because
it's HttpOnly — never readable by frontend JS at all. That closes the classic
"XSS reads localStorage and steals the session" attack for the one token that
would otherwise need multi-day persistence to survive a page reload.

On every app boot the frontend calls POST /v1/auth/refresh; the browser
attaches the cookie automatically (no JS ever touches it) and this module
exchanges it with Cognito's own REFRESH_TOKEN_AUTH flow for a fresh ID token.
"""

import logging
import os
from typing import Any, TypedDict

import boto3
from botocore.exceptions import ClientError

from shared.exceptions import AuthenticationRequiredError, ExternalServiceError, LogisticsBaseError

logger = logging.getLogger(__name__)


class RefreshResult(TypedDict):
    id_token: str
    access_token: str
    expires_in: int


def password_grant(username: str, password: str) -> dict[str, Any]:
    """Not supported on Cognito — the SPA signs in client-side via amazon-cognito-identity-js.

    The server-side password proxy exists only for Entra (whose token endpoint
    blocks the browser with CORS). Keeping this symmetric member means the
    handler can resolve the provider module uniformly without branching.
    """
    raise LogisticsBaseError(
        "Password login is handled client-side on Cognito, not via this endpoint.",
        "NOT_SUPPORTED",
        404,
    )


# boto3.client() has no stub-derived type without boto3-stubs (not a project
# dependency — see mypy --ignore-missing-imports in ci.yml); Any is the
# honest annotation, not a placeholder to fix later.
_client: Any = None


def _cognito_client() -> Any:
    global _client
    if _client is None:
        _client = boto3.client("cognito-idp", region_name=os.environ["AWS_REGION"])
    return _client


def refresh_id_token(refresh_token: str) -> RefreshResult:
    """Exchange a Cognito refresh token for a fresh ID/access token pair.

    Uses the non-admin `initiate_auth` API (not `admin_initiate_auth`) — the
    app client is public with no secret (infrastructure/aws/modules/cognito/main.tf),
    so this needs no AWS-side admin permissions beyond cognito-idp:InitiateAuth
    scoped to the user pool.

    Raises:
        AuthenticationRequiredError: refresh token missing, expired, or revoked
            (e.g. after a password change, admin_user_global_sign_out, or an
            explicit logout) — Cognito reports all of these as NotAuthorizedException.
        ExternalServiceError: any other Cognito failure.
    """
    try:
        resp = _cognito_client().initiate_auth(
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={"REFRESH_TOKEN": refresh_token},
            ClientId=os.environ["COGNITO_CLIENT_ID"],
        )
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("NotAuthorizedException", "UserNotFoundException"):
            raise AuthenticationRequiredError() from exc
        raise ExternalServiceError("Cognito", str(exc)) from exc

    result = resp["AuthenticationResult"]
    return {
        "id_token": result["IdToken"],
        "access_token": result["AccessToken"],
        "expires_in": result["ExpiresIn"],
    }


def revoke_refresh_token(refresh_token: str) -> None:
    """Revoke a refresh token (and every access/ID token issued from it) on logout.

    Best-effort — logout must not fail the client just because Cognito's revoke
    call errors; the cookie is cleared client-side (Set-Cookie Max-Age=0)
    regardless of whether this succeeds. Logged at WARNING, not re-raised.
    """
    try:
        _cognito_client().revoke_token(
            Token=refresh_token,
            ClientId=os.environ["COGNITO_CLIENT_ID"],
        )
    except ClientError as exc:
        logger.warning("Cognito RevokeToken failed (non-fatal, cookie still cleared): %s", exc)
