"""Re-authentication before dangerous platform actions (platform audit C-29, threat model "hijacked session").

A platform admin proves it is still them by re-authenticating with the identity provider; the server checks that proof
itself, then issues a step-up token that is good for five minutes and only for that admin. Dangerous routes refuse a
request without one (:func:`require_step_up`); the console asks, re-authenticates and retries.

How the proof is checked, per identity provider:

* **Cognito** — the server signs in as the caller (``USER_PASSWORD_AUTH`` against the public app client) with the
  password, and the authenticator code when the pool asks for one. The tokens that sign-in returns are revoked at once;
  only the fact that it succeeded is kept. The username is the caller's own directory email, never one from the body.
* **Entra** — the console re-runs sign-in with ``prompt=login`` and sends the fresh ID token. The server verifies it
  (signature, audience, issuer), checks that it names the caller, and that it was issued in the last five minutes.
* **Local / test only** — when ``STEP_UP_LOCAL_PASSWORD`` is set and ``ENVIRONMENT`` is ``local`` or ``test``, that
  password stands in for the identity provider (``LOCAL_TESTING.md``). Ignored in every other environment.

Failed attempts count against the same per-identity lockout as sign-in (``rate_limit.LOGIN_FAILURES``).
"""

import hashlib
import hmac
import logging
import os
import time
import uuid
from typing import Any

from shared import rate_limit
from shared.exceptions import LogisticsBaseError, StepUpRequiredError
from shared.platform_audit import PlatformAuditAction, insert_platform_audit
from shared.tenant_context import TenantContext

logger = logging.getLogger(__name__)

STEP_UP_HEADER = "x-step-up-token"
STEP_UP_TTL_SECONDS = 300
_TOKEN_TYPE = "platform_step_up"  # noqa: S105 - the token type claim, not a secret
_ENTRA_FRESHNESS_SECONDS = 300


class StepUpFailedError(LogisticsBaseError):
    """403 when the re-authentication itself did not succeed."""

    def __init__(self, message: str = "Re-authentication failed. Check your password and code.") -> None:
        super().__init__(message=message, error_code="STEP_UP_FAILED", status_code=403)


class StepUpCodeRequiredError(LogisticsBaseError):
    """403 when the password was right and the pool now wants the authenticator code."""

    def __init__(self) -> None:
        super().__init__(
            message="Enter the 6-digit code from your authenticator app.",
            error_code="STEP_UP_MFA_REQUIRED",
            status_code=403,
        )


# ---------------------------------------------------------------------------
# Step-up tokens
# ---------------------------------------------------------------------------


def _signing_key() -> bytes:
    """A key for step-up tokens only, derived from the impersonation secret (domain-separated)."""
    from .impersonation import _get_signing_secret

    return hashlib.sha256(f"shipx_step_up:{_get_signing_secret()}".encode()).digest()


def mint_step_up_token(subject: str) -> dict[str, Any]:
    """Return ``{"step_up_token", "expires_at"}`` for ``subject``, valid for :data:`STEP_UP_TTL_SECONDS`."""
    import jwt

    now = int(time.time())
    expires_at = now + STEP_UP_TTL_SECONDS
    token = jwt.encode(
        {"sub": subject, "typ": _TOKEN_TYPE, "iat": now, "exp": expires_at, "jti": str(uuid.uuid4())},
        _signing_key(),
        algorithm="HS256",
    )
    return {"step_up_token": str(token), "expires_at": expires_at}


def _header(event: dict[str, Any]) -> str:
    headers = {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items()}
    return headers.get(STEP_UP_HEADER, "").strip()


def require_step_up(event: dict[str, Any], ctx: TenantContext) -> None:
    """Raise :class:`StepUpRequiredError` unless the request carries a valid step-up token for this caller."""
    import jwt

    token = _header(event)
    if not token:
        raise StepUpRequiredError()
    try:
        claims = jwt.decode(token, _signing_key(), algorithms=["HS256"], options={"require": ["exp", "sub", "typ"]})
    except jwt.PyJWTError as exc:
        raise StepUpRequiredError() from exc
    if claims.get("typ") != _TOKEN_TYPE or not hmac.compare_digest(str(claims.get("sub")), ctx.user_id):
        raise StepUpRequiredError()


# ---------------------------------------------------------------------------
# Re-authentication
# ---------------------------------------------------------------------------


def step_up(
    ctx: TenantContext,
    email: str,
    *,
    password: str | None,
    mfa_code: str | None,
    id_token: str | None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Check a re-authentication for the caller and return a fresh step-up token.

    Args:
        ctx: The platform caller.
        email: The caller's directory email (the Cognito username). Never taken from the request.
        password: Cognito and local: the caller's password.
        mfa_code: Cognito: the authenticator code, when the pool requires it.
        id_token: Entra: an ID token from a sign-in with ``prompt=login``.
        ip_address: For the audit row.

    Raises:
        StepUpFailedError: The proof did not check out.
        StepUpCodeRequiredError: Cognito accepted the password and now wants the code.
        RateLimitExceededError: Too many failed attempts for this admin.
    """
    from shared.providers import AUTH_PROVIDER

    rate_key = f"step_up:{ctx.user_id}"
    rate_limit.peek(rate_limit.LOGIN_FAILURES, rate_key)
    try:
        if _local_password() is not None:
            _verify_local(password)
        elif AUTH_PROVIDER == "azure":
            _verify_entra(ctx, id_token)
        else:
            _verify_cognito(ctx, email, password, mfa_code)
    except StepUpFailedError:
        rate_limit.record_failure(rate_limit.LOGIN_FAILURES, rate_key)
        raise
    rate_limit.clear(rate_limit.LOGIN_FAILURES, rate_key)

    try:
        insert_platform_audit(
            action=PlatformAuditAction.STEP_UP_VERIFIED,
            actor_id=ctx.user_id,
            target_tenant_id=None,
            details={"method": "entra" if AUTH_PROVIDER == "azure" else "password"},
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed for step-up: %s", exc)
    return mint_step_up_token(ctx.user_id)


def _local_password() -> str | None:
    if os.environ.get("ENVIRONMENT", "").strip().lower() not in ("local", "test"):
        return None
    return os.environ.get("STEP_UP_LOCAL_PASSWORD") or None


def _verify_local(password: str | None) -> None:
    expected = _local_password() or ""
    if not password or not hmac.compare_digest(password.encode(), expected.encode()):
        raise StepUpFailedError()


_cognito: Any = None


def _cognito_client() -> Any:
    global _cognito
    if _cognito is None:
        import boto3
        from botocore.config import Config

        # Bounded like services/auth/cognito_refresh.py: this sits inside an admin's request.
        config = Config(retries={"max_attempts": 2, "mode": "standard"}, connect_timeout=3, read_timeout=5)
        _cognito = boto3.client("cognito-idp", region_name=os.environ["AWS_REGION"], config=config)
    return _cognito


def _verify_cognito(ctx: TenantContext, email: str, password: str | None, mfa_code: str | None) -> None:
    from botocore.exceptions import ClientError

    from shared.exceptions import ExternalServiceError

    if not password:
        raise StepUpFailedError("Enter your password.")
    client_id = os.environ.get("COGNITO_CLIENT_ID", "")
    if not client_id:
        raise ExternalServiceError("Cognito", "COGNITO_CLIENT_ID is not configured")
    client = _cognito_client()
    try:
        resp = client.initiate_auth(
            AuthFlow="USER_PASSWORD_AUTH",
            ClientId=client_id,
            AuthParameters={"USERNAME": email, "PASSWORD": password},
        )
        challenge = resp.get("ChallengeName")
        if challenge == "SOFTWARE_TOKEN_MFA":
            if not mfa_code:
                raise StepUpCodeRequiredError()
            resp = client.respond_to_auth_challenge(
                ClientId=client_id,
                ChallengeName=challenge,
                Session=resp["Session"],
                ChallengeResponses={"USERNAME": email, "SOFTWARE_TOKEN_MFA_CODE": mfa_code},
            )
            challenge = resp.get("ChallengeName")
        if challenge:
            # NEW_PASSWORD_REQUIRED, MFA_SETUP, SMS_MFA…: not a completed sign-in.
            raise StepUpFailedError("Finish setting up your sign-in first, then try again.")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NotAuthorizedException", "UserNotFoundException", "CodeMismatchException", "ExpiredCodeException"):
            raise StepUpFailedError() from exc
        raise ExternalServiceError("Cognito", code or "step-up sign-in failed") from exc

    result = resp.get("AuthenticationResult") or {}
    claims = _unverified_claims(str(result.get("IdToken") or ""))
    try:
        if not hmac.compare_digest(str(claims.get("sub") or ""), ctx.user_id):
            raise StepUpFailedError()
    finally:
        _revoke_quietly(client, client_id, result.get("RefreshToken"))


def _revoke_quietly(client: Any, client_id: str, refresh_token: str | None) -> None:
    """The step-up sign-in's tokens are never used; revoke them so they are not left valid."""
    if not refresh_token:
        return
    try:
        client.revoke_token(Token=refresh_token, ClientId=client_id)
    except Exception as exc:
        logger.warning("Could not revoke the step-up sign-in's refresh token: %s", type(exc).__name__)


def _unverified_claims(id_token: str) -> dict[str, Any]:
    """Read a token Cognito just returned to this server over TLS; used only to compare its subject."""
    import jwt

    if not id_token:
        return {}
    try:
        return dict(jwt.decode(id_token, options={"verify_signature": False}))
    except jwt.PyJWTError:
        return {}


def _verify_entra(ctx: TenantContext, id_token: str | None) -> None:
    from shared.auth_verify import verify_oidc_jwt

    if not id_token:
        raise StepUpFailedError("Sign in again to confirm.")
    claims = verify_oidc_jwt(id_token)
    if not claims:
        raise StepUpFailedError()
    subject = str(claims.get("oid") or claims.get("sub") or "")
    if not hmac.compare_digest(subject, ctx.user_id):
        raise StepUpFailedError()
    authenticated_at = int(claims.get("auth_time") or claims.get("iat") or 0)
    if time.time() - authenticated_at > _ENTRA_FRESHNESS_SECONDS:
        raise StepUpFailedError("That sign-in is too old. Sign in again to confirm.")
