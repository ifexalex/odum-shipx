"""Platform Admin impersonation service.

Platform admins may "impersonate" a tenant's Tenant Admin for support/debugging:
  - Read-only (GET/HEAD only)
  - Fully audited (IMPERSONATION_START / IMPERSONATION_END)
  - Auto-expiring after 30 minutes

Token format: HS256 JWT signed with a platform-level secret from Secrets Manager
(env var IMPERSONATION_SECRET_ARN or fallback IMPERSONATION_SECRET for local dev).

The token carries:
  {
    "sub":            target_user_id,
    "tenant_id":      target_tenant_id,
    "role":           "tenant_admin",
    "impersonated_by": platform_admin_id,
    "session_id":     session_id,
    "read_only":      true,
    "exp":            unix_timestamp,
    "iat":            unix_timestamp,
  }

Authorizer: The Lambda authorizer at services/authorizer/handler.py
accepts both Cognito JWTs (validated against Cognito JWKS) and ShipX
impersonation tokens (validated by this module). If it detects an
impersonation token (header "X-Token-Type: impersonation"), it calls
verify_impersonation_token() and checks that the session is still active.

Terraform changes required (services/authorizer/ Lambda):
  1. Remove the native JWT authorizer from api-gateway/main.tf
  2. Add an aws_apigatewayv2_authorizer resource of type REQUEST pointing
     to the authorizer Lambda ARN
  3. Grant the authorizer Lambda IAM permission to call the DB (within VPC)
  4. Pass IMPERSONATION_SECRET_ARN and COGNITO_JWKS_URL to the authorizer Lambda
  5. All existing authenticated routes keep their authorizer_id pointing at
     the new REQUEST authorizer
"""

import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.exceptions import BusinessRuleViolationError, ResourceNotFoundError
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)

_SESSION_TTL_MINUTES = 30


# ---------------------------------------------------------------------------
# Token signing helpers
# ---------------------------------------------------------------------------


def _get_signing_secret() -> str:
    """Return the HS256 signing secret from Secrets Manager or env fallback."""
    secret_arn = os.environ.get("IMPERSONATION_SECRET_ARN", "")
    if secret_arn:
        import boto3

        region = os.environ.get("AWS_REGION", "eu-west-1")
        client = boto3.client("secretsmanager", region_name=region)
        secret = client.get_secret_value(SecretId=secret_arn)
        return str(json.loads(secret["SecretString"])["secret"])

    secret = os.environ.get("IMPERSONATION_SECRET", "")
    if not secret:
        raise RuntimeError("IMPERSONATION_SECRET_ARN or IMPERSONATION_SECRET must be set")
    return secret


def _mint_token(payload: dict[str, Any], secret: str) -> str:
    """Produce a signed HS256 JWT. Uses PyJWT if available, pure-Python fallback."""
    try:
        import jwt

        return str(jwt.encode(payload, secret, algorithm="HS256"))
    except ImportError:
        pass

    import base64
    import hashlib
    import hmac

    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    signing_input = f"{header}.{body}".encode()
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{header}.{body}.{sig_b64}"


def verify_impersonation_token(token: str) -> dict[str, Any]:
    """Validate a ShipX impersonation JWT and return its claims.

    Raises ValueError on invalid/expired token.
    """
    secret = _get_signing_secret()
    try:
        import jwt

        claims = jwt.decode(token, secret, algorithms=["HS256"])
        return dict(claims)
    except ImportError:
        pass

    import base64
    import hashlib
    import hmac

    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token format")

    signing_input = f"{parts[0]}.{parts[1]}".encode()
    expected_sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    padded_sig = parts[2] + "=" * (-len(parts[2]) % 4)
    actual_sig = base64.urlsafe_b64decode(padded_sig)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Invalid token signature")

    padded_body = parts[1] + "=" * (-len(parts[1]) % 4)
    fallback_claims: dict[str, Any] = json.loads(base64.urlsafe_b64decode(padded_body))
    if fallback_claims.get("exp", 0) < time.time():
        raise ValueError("Token has expired")
    return fallback_claims


# ---------------------------------------------------------------------------
# DB helpers (platform-scoped — no RLS on impersonation_session)
# ---------------------------------------------------------------------------


def _get_tenant_admin(target_tenant_id: str) -> dict[str, Any] | None:
    """Return the active tenant_admin user for a given tenant, or None."""
    # tenant_user's PK is `id` and its liveness column is `status` (an
    # 'active'/'deactivated' enum, migration 001) — this query previously
    # selected non-existent tu.user_id / tu.is_active columns, which made
    # every impersonation attempt 500 against the real schema.
    rows = execute_with_tenant(
        target_tenant_id,
        """
        SELECT tu.id AS user_id, tu.full_name
        FROM tenant_user tu
        WHERE tu.tenant_id = %s AND tu.role = 'tenant_admin' AND tu.status = 'active'
        LIMIT 1
        """,
        (target_tenant_id,),
    )
    return rows[0] if rows else None


def _get_tenant_status(target_tenant_id: str) -> str | None:
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT status FROM tenant WHERE id = %s LIMIT 1",
        (target_tenant_id,),
    )
    return rows[0]["status"] if rows else None


def _create_session(data: dict[str, Any]) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        INSERT INTO impersonation_session (
            id, platform_admin_id, target_tenant_id, target_user_id,
            target_role, read_only, started_at, expires_at
        ) VALUES (
            %(id)s, %(platform_admin_id)s, %(target_tenant_id)s, %(target_user_id)s,
            %(target_role)s, %(read_only)s, %(started_at)s, %(expires_at)s
        ) RETURNING *
        """,
        data,
    )


def _end_session(session_id: str, reason: str) -> dict[str, Any] | None:
    return execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        """
        UPDATE impersonation_session
        SET ended_at = NOW(), end_reason = %(reason)s
        WHERE id = %(id)s AND ended_at IS NULL
        RETURNING *
        """,
        {"id": session_id, "reason": reason},
    )


def get_active_session(session_id: str) -> dict[str, Any] | None:
    """Return an impersonation_session row if it's active (not ended, not expired)."""
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        """
        SELECT * FROM impersonation_session
        WHERE id = %s AND ended_at IS NULL AND expires_at > NOW()
        LIMIT 1
        """,
        (session_id,),
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_impersonation(
    platform_admin_id: str,
    target_tenant_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Create an impersonation session and mint a short-lived HS256 token.

    Returns: {"session_id": ..., "token": ..., "expires_at": ..., "target_user_id": ...}

    Raises:
        ResourceNotFoundError: if the tenant does not exist.
        BusinessRuleViolationError: if the tenant is not active, or has no active tenant_admin.
    """
    tenant_status = _get_tenant_status(target_tenant_id)
    if not tenant_status:
        raise ResourceNotFoundError("tenant", target_tenant_id)
    if tenant_status != "active":
        raise BusinessRuleViolationError(
            f"Cannot impersonate tenant in status '{tenant_status}' — must be active",
            rule_id="TENANT_NOT_ACTIVE",
        )

    target_user = _get_tenant_admin(target_tenant_id)
    if not target_user:
        raise BusinessRuleViolationError(
            "Target tenant has no active tenant_admin user",
            rule_id="NO_TENANT_ADMIN",
        )

    session_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=_SESSION_TTL_MINUTES)

    session = _create_session(
        {
            "id": session_id,
            "platform_admin_id": platform_admin_id,
            "target_tenant_id": target_tenant_id,
            "target_user_id": str(target_user["user_id"]),
            "target_role": "tenant_admin",
            "read_only": True,
            "started_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
    )
    if not session:
        raise RuntimeError("Failed to create impersonation session")

    payload: dict[str, Any] = {
        "sub": str(target_user["user_id"]),
        "tenant_id": target_tenant_id,
        "role": "tenant_admin",
        "impersonated_by": platform_admin_id,
        "session_id": session_id,
        "read_only": True,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    secret = _get_signing_secret()
    token = _mint_token(payload, secret)

    # Logged to platform_audit_log, not the tenant's own audit_log — this is
    # a platform-admin action performed *on* a tenant, not a tenant-side
    # business event, and reported directly by the user as something a
    # tenant admin should never see in their own activity log. Visible to
    # platform admins only, via PlatformAuditLog.tsx. Also fixes a real bug
    # found in the same pass: shared.audit.log_audit() writes to a table
    # whose `action` column used to be CHECK-constrained to
    # CREATE/UPDATE/DELETE/STATUS_CHANGE — "IMPERSONATION_START" isn't one
    # of those, so every call here silently failed the insert since this
    # code was written (see migration 045). platform_audit_log.action has
    # no such constraint.
    from .repository import insert_platform_audit

    insert_platform_audit(
        action="IMPERSONATION_START",
        actor_id=platform_admin_id,
        target_tenant_id=target_tenant_id,
        details={
            "target_user_id": str(target_user["user_id"]),
            "expires_at": expires_at.isoformat(),
        },
        ip_address=ip_address,
    )

    return {
        "session_id": session_id,
        "token": token,
        "expires_at": expires_at.isoformat(),
        "target_user_id": str(target_user["user_id"]),
        "target_tenant_id": target_tenant_id,
        "read_only": True,
    }


def end_impersonation(
    session_id: str,
    platform_admin_id: str,
    end_reason: str = "manual",
    ip_address: str | None = None,
) -> dict[str, Any]:
    """End an active impersonation session by session_id.

    Raises ResourceNotFoundError if the session doesn't exist or is already ended.
    """
    active = get_active_session(session_id)
    if not active:
        raise ResourceNotFoundError("impersonation_session", session_id)

    if str(active.get("platform_admin_id", "")) != platform_admin_id:
        raise ResourceNotFoundError("impersonation_session", session_id)

    ended = _end_session(session_id, end_reason)
    if not ended:
        raise ResourceNotFoundError("impersonation_session", session_id)

    target_tenant_id = str(active["target_tenant_id"])
    from .repository import insert_platform_audit

    insert_platform_audit(
        action="IMPERSONATION_END",
        actor_id=platform_admin_id,
        target_tenant_id=target_tenant_id,
        details={"session_id": session_id, "end_reason": end_reason},
        ip_address=ip_address,
    )

    return {"session_id": session_id, "ended_at": str(ended.get("ended_at")), "end_reason": end_reason}


def assert_read_only(method: str) -> None:
    """Raise BusinessRuleViolationError if the HTTP method is mutating.

    Call this in any handler that has detected an impersonation context.
    """
    if method not in ("GET", "HEAD", "OPTIONS"):
        raise BusinessRuleViolationError(
            "Impersonation sessions are read-only — mutating requests are not allowed",
            rule_id="IMPERSONATION_READ_ONLY",
        )
