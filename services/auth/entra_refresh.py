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


class LoginResult(TypedDict):
    id_token: str
    access_token: str
    refresh_token: str
    expires_in: int


def _token_request(form_fields: dict[str, str]) -> dict[str, str]:
    """POST an OAuth2 form to the Entra token endpoint and return the JSON body.

    Shared by the authorization_code, refresh_token and password (ROPC) grants.
    The app's redirect URI is registered under the Entra *Mobile & desktop*
    (publicClient) platform: the BFF redeems the code/refresh token server-side
    with PKCE and no client secret (a public client), which is a same-origin POST
    with no `Origin` header. (An `Origin` header would make Entra treat it as a
    cross-origin SPA redemption and reject it with AADSTS9002326 — that is only
    valid for the SPA client-type.)

    Raises:
        AuthenticationRequiredError: invalid grant/credentials (HTTP 400/401 with
            invalid_grant).
        ExternalServiceError: misconfiguration or any other Entra failure.
    """
    endpoint = os.environ.get("ENTRA_TOKEN_ENDPOINT", "")
    client_id = os.environ.get("ENTRA_CLIENT_ID", "")
    scope = os.environ.get("ENTRA_SCOPE", _DEFAULT_SCOPE)
    if not endpoint or not client_id:
        raise ExternalServiceError("Entra", "ENTRA_TOKEN_ENDPOINT / ENTRA_CLIENT_ID are not set")

    form = urllib.parse.urlencode({"client_id": client_id, "scope": scope, **form_fields}).encode()
    req = urllib.request.Request(
        endpoint,
        data=form,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - Entra token endpoint only
            return json.loads(resp.read())  # type: ignore[no-any-return]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace") if hasattr(exc, "read") else str(exc)
        if exc.code in (400, 401) and "invalid_grant" in body:
            raise AuthenticationRequiredError() from exc
        logger.warning("Entra token request failed: %s %s", exc.code, body)
        raise ExternalServiceError("Entra", f"{exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ExternalServiceError("Entra", str(exc)) from exc


def password_grant(username: str, password: str) -> LoginResult:
    """Exchange a username/password for Entra tokens via the ROPC grant.

    This runs the exact request the SPA used to make directly — moved
    server-side because Entra's token endpoint returns no CORS headers for the
    password grant, so a browser fetch is blocked (EntraClient.ts calls this
    endpoint instead). ROPC is valid only for Entra local accounts without MFA.

    Raises:
        AuthenticationRequiredError: bad credentials / MFA / federated user
            (Entra reports HTTP 400 invalid_grant).
        ExternalServiceError: misconfiguration or any other Entra failure.
    """
    # Let users sign in with their real email even when the account's UPN is the
    # managed-domain form (alex@gmail.com -> alex_gmail.com@tenant.onmicrosoft.com).
    # Idempotent, so a full UPN passed straight through still works.
    from shared.providers.azure.entra import email_to_upn

    upn = email_to_upn(username, os.environ.get("ENTRA_USER_DOMAIN", ""))
    data = _token_request({"grant_type": "password", "username": upn, "password": password})
    id_token = data.get("id_token")
    if not id_token:
        # No id_token means the grant did not yield a usable session.
        raise AuthenticationRequiredError()
    return {
        "id_token": id_token,
        "access_token": data.get("access_token", id_token),
        "refresh_token": data.get("refresh_token", ""),
        "expires_in": int(data.get("expires_in", 3600)),
    }


def authorization_code_grant(code: str, code_verifier: str, redirect_uri: str) -> LoginResult:
    """Exchange an OAuth2 authorization code (+ PKCE verifier) for Entra tokens.

    The server-side half of the interactive auth-code + PKCE login (BFF): the SPA
    redirects the user to Entra, Entra calls the custom-claims provider (which
    injects tenant_id/role) and redirects back with a `code`, and this exchanges
    it for the token set. Unlike ROPC this triggers the claims provider and
    supports MFA/Conditional Access/social — see 04_auth_and_session.md.

    Raises:
        AuthenticationRequiredError: the code is invalid/expired/already used
            (Entra reports HTTP 400 invalid_grant).
        ExternalServiceError: misconfiguration or any other Entra failure.
    """
    data = _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        }
    )
    id_token = data.get("id_token")
    if not id_token:
        raise AuthenticationRequiredError()
    return {
        "id_token": id_token,
        "access_token": data.get("access_token", id_token),
        "refresh_token": data.get("refresh_token", ""),
        "expires_in": int(data.get("expires_in", 3600)),
    }


def refresh_id_token(refresh_token: str) -> RefreshResult:
    """Exchange an Entra refresh token for a fresh ID/access token pair.

    Raises:
        AuthenticationRequiredError: the refresh token is expired/revoked/invalid
            (Entra reports this as HTTP 400 invalid_grant).
        ExternalServiceError: misconfiguration or any other Entra failure.
    """
    data = _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})
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
