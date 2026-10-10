"""Entra refresh-token exchange — the Azure counterpart of cognito_refresh, so
the httpOnly-cookie session-persistence flow (services/auth/handler.py) works
identically on Azure: a page reload trades the cookie for a fresh ID token
without a re-login, and the refresh token never touches frontend JS.

Uses the OAuth2 `refresh_token` grant against the Entra token endpoint (stdlib
urllib — no SDK dependency, matching shared/providers/azure/entra.py). Selected
by AUTH_PROVIDER=azure in the handler.

Environment:
  ENTRA_TOKEN_ENDPOINT — OAuth2 token endpoint (same value the SPA uses).
  ENTRA_CLIENT_ID      — the app registration client id.
  ENTRA_SCOPE          — space-separated scopes (default below).
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import TypedDict

from shared.exceptions import AuthenticationRequiredError, ExternalServiceError

logger = logging.getLogger(__name__)

_DEFAULT_SCOPE = "openid profile offline_access"


class RefreshResult(TypedDict):
    id_token: str
    access_token: str
    expires_in: int


def refresh_id_token(refresh_token: str) -> RefreshResult:
    """Exchange an Entra refresh token for a fresh ID/access token pair.

    Raises:
        AuthenticationRequiredError: the refresh token is expired/revoked/invalid
            (Entra reports this as HTTP 400 invalid_grant).
        ExternalServiceError: misconfiguration or any other Entra failure.
    """
    endpoint = os.environ.get("ENTRA_TOKEN_ENDPOINT", "")
    client_id = os.environ.get("ENTRA_CLIENT_ID", "")
    scope = os.environ.get("ENTRA_SCOPE", _DEFAULT_SCOPE)
    if not endpoint or not client_id:
        raise ExternalServiceError("Entra", "ENTRA_TOKEN_ENDPOINT / ENTRA_CLIENT_ID are not set")

    form = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "scope": scope,
        }
    ).encode()
    req = urllib.request.Request(
        endpoint,
        data=form,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - Entra token endpoint only
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace") if hasattr(exc, "read") else str(exc)
        if exc.code in (400, 401) and "invalid_grant" in body:
            raise AuthenticationRequiredError() from exc
        logger.warning("Entra refresh failed: %s %s", exc.code, body)
        raise ExternalServiceError("Entra", f"{exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ExternalServiceError("Entra", str(exc)) from exc

    id_token = data.get("id_token")
    if not id_token:
        # No id_token back means the grant didn't yield a usable session.
        raise AuthenticationRequiredError()
    return {
        "id_token": id_token,
        "access_token": data.get("access_token", id_token),
        "expires_in": int(data.get("expires_in", 3600)),
    }


def revoke_refresh_token(refresh_token: str) -> None:
    """Logout hook. Entra has no revoke-by-token-value endpoint (revocation is
    per-user via Graph revokeSignInSessions, which needs the user id, not the
    token), so this is a no-op: the cookie is cleared client-side and the token
    lapses on its own. Full server-side revocation is an identity-provider
    concern handled by global_sign_out in the EntraIdentityProvider.
    """
    logger.debug("Entra refresh-token revoke is a no-op (cookie cleared client-side)")
