"""Auth session Lambda handler — httpOnly-cookie-backed silent session refresh.

Routes (all public — no JWT; these ARE the pre-auth boundary, called before
any ID token exists or right as one is about to expire):

    POST /v1/auth/session  — called once, immediately after a successful
                              client-side Cognito login (CognitoClient.ts).
                              Persists the Cognito refresh token as a Secure,
                              HttpOnly, SameSite=Strict cookie scoped to
                              Path=/v1/auth. The ID token stays exactly where
                              it already lived — the frontend's in-memory
                              tokenStore — this endpoint never sees it.

    POST /v1/auth/refresh  — called on every app boot (SessionProvider mount)
                              and by the API client's 401-recovery path.
                              Reads the cookie the browser attaches
                              automatically, exchanges it with Cognito for a
                              fresh ID token, and returns that token in the
                              JSON body. This is what lets a page reload
                              restore the session without a re-login, without
                              the refresh token ever touching frontend JS.

    POST /v1/auth/logout   — revokes the refresh token server-side (Cognito
                              RevokeToken invalidates it and every access/ID
                              token issued from it) and clears the cookie.

See docs/project docs/frontend/04_auth_and_session.md and
11_security_and_compliance.md for the threat model this closes.
"""

import base64
import json
import logging
import os
import time
import uuid
from typing import Any

from shared.exceptions import AuthenticationRequiredError, LogisticsBaseError, ResourceNotFoundError
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.observability import init_tracing
from shared.responses import error_response
from shared.validation import parse_validated

from .models import EstablishSessionRequest, LoginRequest

setup_logging()
init_tracing()

logger = logging.getLogger(__name__)

_COOKIE_NAME = "shipx_rt"
# Short-lived transaction cookie for the interactive auth-code flow: holds the
# server-generated PKCE verifier + state + nonce across the Entra redirect so
# none of it ever touches JS (entra_oauth.py / _authorize_url / _callback).
_TX_COOKIE_NAME = "shipx_auth_tx"
_COOKIE_PATH = "/v1/auth"
# Matches Cognito's refresh_token_validity (infrastructure/aws/modules/cognito/main.tf) — the
# cookie's lifetime should never exceed the token's own validity, but capping it here too
# means a stale cookie value from a rotated Cognito config still expires client-side on schedule.
_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
_TX_COOKIE_MAX_AGE_SECONDS = 600  # the authorize→callback round-trip is seconds; 10 min is ample.

# SameSite for the auth cookies. Default Strict (AWS: SPA + API share the
# registrable domain, e.g. shipx.co / api.shipx.co). Azure serves the SPA and
# API from different sites (*.azurefd.net vs *.azurecontainerapps.io), where
# only SameSite=None cookies are sent on cross-site fetches — set
# AUTH_COOKIE_SAMESITE=None there. None implies Secure, which we always set.
_COOKIE_SAMESITE = os.environ.get("AUTH_COOKIE_SAMESITE", "Strict")

_STANDARD_HEADERS = {
    "Content-Type": "application/json",
    "X-Content-Type-Options": "nosniff",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Cache-Control": "no-store",
}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    start_time = time.time()
    request_id = event.get("requestContext", {}).get("requestId") or str(uuid.uuid4())
    clear_log_context()
    bind_log_context(request_id=request_id)
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "")
    path = http.get("path", "")

    try:
        if method == "POST" and path == "/v1/auth/authorize-url":
            response = _authorize_url(event, request_id)
        elif method == "POST" and path == "/v1/auth/callback":
            response = _callback(event, request_id)
        elif method == "POST" and path == "/v1/auth/login":
            response = _login(event, request_id)
        elif method == "POST" and path == "/v1/auth/session":
            response = _establish_session(event, request_id)
        elif method == "POST" and path == "/v1/auth/refresh":
            response = _refresh(event, request_id)
        elif method == "POST" and path == "/v1/auth/logout":
            response = _logout(event, request_id)
        else:
            raise ResourceNotFoundError("route", path)
        return response
    except LogisticsBaseError as exc:
        logger.warning("Auth error: %s - %s", exc.error_code, exc.message)
        return error_response(exc, instance=path, request_id=request_id)
    except Exception:
        logger.exception("Unhandled error in auth handler")
        return error_response(
            LogisticsBaseError("Internal server error", "INTERNAL_ERROR", 500),
            instance=path,
            request_id=request_id,
        )
    finally:
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "← %s %s %.0fms",
            method,
            path,
            duration_ms,
            extra={"request_id": request_id, "duration_ms": duration_ms},
        )


def _refresher() -> Any:
    """Return the refresh/revoke module for the active identity provider.

    AUTH_PROVIDER selects it (default = CLOUD_PROVIDER), so the same cookie flow
    exchanges the token against Cognito on AWS and Entra on Azure. Imported
    lazily so neither cloud's SDK/config is required on the other.
    """
    from shared.providers import AUTH_PROVIDER

    if AUTH_PROVIDER == "azure":
        from . import entra_refresh

        return entra_refresh
    from . import cognito_refresh

    return cognito_refresh


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    try:
        return json.loads(raw)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return {}


def _read_refresh_cookie(event: dict[str, Any]) -> str | None:
    """Read the refresh-token cookie off a payload-format-2.0 event.

    HTTP API v2 parses cookies into event["cookies"] (a list of raw
    "name=value" strings) — that's the only place to read from; a stray
    Cookie *header* (there isn't one at this payload version) would bypass
    whatever API Gateway itself parsed and validated.
    """
    for raw in event.get("cookies") or []:
        name, _, value = str(raw).partition("=")
        if name == _COOKIE_NAME and value:
            return value
    return None


def _cookie_header(value: str, max_age: int, name: str = _COOKIE_NAME) -> str:
    return f"{name}={value}; Path={_COOKIE_PATH}; Max-Age={max_age}; " f"HttpOnly; Secure; SameSite={_COOKIE_SAMESITE}"


def _read_cookie(event: dict[str, Any], name: str) -> str | None:
    for raw in event.get("cookies") or []:
        cookie_name, _, value = str(raw).partition("=")
        if cookie_name == name and value:
            return value
    return None


def _authorize_url(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Begin the interactive Entra login (BFF auth-code + PKCE).

    Generates the PKCE verifier, state, and nonce server-side, stashes them in a
    short-lived httpOnly transaction cookie, and returns the Entra authorize URL
    for the SPA to redirect to. Nothing sensitive reaches JS. Entra-only — the
    Cognito SPA uses its own hosted/SRP flow and never calls this.
    """
    from . import entra_oauth

    verifier, challenge = entra_oauth.generate_pkce()
    state = entra_oauth.generate_token()
    nonce = entra_oauth.generate_token()
    try:
        url = entra_oauth.build_authorize_url(state=state, nonce=nonce, code_challenge=challenge)
    except ValueError as exc:
        raise LogisticsBaseError(str(exc), "ENTRA_NOT_CONFIGURED", 503) from exc

    # base64url-encode the JSON so the cookie VALUE is a valid cookie-octet
    # string. Raw JSON contains spaces/commas/quotes/braces, which browsers
    # reject or truncate in a Set-Cookie value — dropping the transaction and
    # 401ing the callback.
    tx = base64.urlsafe_b64encode(json.dumps({"v": verifier, "s": state, "n": nonce}).encode()).decode()
    return {
        "statusCode": 200,
        "cookies": [_cookie_header(tx, _TX_COOKIE_MAX_AGE_SECONDS, name=_TX_COOKIE_NAME)],
        "headers": {**_STANDARD_HEADERS, "X-Request-Id": request_id},
        "body": json.dumps({"data": {"authorize_url": url}}),
    }


def _log_id_token_shape(id_token: str, request_id: str) -> None:
    """Log which claim NAMES the issued id_token carries — never their values.

    Entra silently drops a custom-claims-provider's output when the app
    registration isn't configured to emit it: the provider returns 200 with
    tenant_id/role, the token arrives without them, and the only visible symptom
    is the SPA rejecting the token ("JWT is missing required claims"). This makes
    that answerable from the server side instead of needing the token out of the
    browser. Values are deliberately excluded — they include email and name.
    """
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except Exception as exc:  # noqa: BLE001 - diagnostics must never break login
        logger.warning("Could not decode the issued id_token for diagnostics: %s", exc)
        return
    logger.info(
        "id_token claims present: %s (has tenant_id=%s, has role=%s, has oid=%s)",
        sorted(claims.keys()),
        "tenant_id" in claims,
        "role" in claims,
        "oid" in claims,
        extra={"request_id": request_id},
    )


def _callback(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Complete the interactive login: exchange the auth code for tokens.

    Reads the transaction cookie (PKCE verifier + expected state) set by
    `_authorize_url`, validates the returned `state` (CSRF), exchanges the code
    server-side, persists the refresh token as the httpOnly session cookie, and
    returns the ID token (now carrying the claims-provider-injected
    tenant_id/role). The refresh token never touches JS.
    """
    from . import entra_oauth, entra_refresh
    from .models import AuthCallbackRequest

    req = parse_validated(AuthCallbackRequest, _parse_body(event))
    raw_tx = _read_cookie(event, _TX_COOKIE_NAME)
    if not raw_tx:
        raise AuthenticationRequiredError()
    try:
        tx = json.loads(base64.urlsafe_b64decode(raw_tx))
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthenticationRequiredError() from exc
    # Constant-time-ish state check — the transaction cookie is httpOnly, so this
    # guards against a forged/replayed callback, not a cookie-reading attacker.
    if not tx.get("s") or tx.get("s") != req.state:
        raise AuthenticationRequiredError()

    tokens = entra_refresh.authorization_code_grant(
        code=req.code,
        code_verifier=str(tx.get("v", "")),
        redirect_uri=entra_oauth.redirect_uri(),
    )
    _log_id_token_shape(tokens["id_token"], request_id)
    body = json.dumps({"data": {"id_token": tokens["id_token"], "expires_in": tokens["expires_in"]}})
    return {
        "statusCode": 200,
        # Set the session cookie; expire the one-shot transaction cookie.
        "cookies": [
            _cookie_header(tokens["refresh_token"], _COOKIE_MAX_AGE_SECONDS),
            _cookie_header("", 0, name=_TX_COOKIE_NAME),
        ],
        "headers": {**_STANDARD_HEADERS, "X-Request-Id": request_id},
        "body": body,
    }


def _login(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Entra ROPC login proxy — the server-side half of EntraClient.signIn.

    Entra's token endpoint sends no CORS headers for the password grant, so the
    SPA cannot call it directly; it POSTs here instead. We run the exchange
    server-side and return the tokens so SessionProvider.login() can proceed
    exactly as it does on Cognito (set the in-memory ID token, then persist the
    refresh token via POST /v1/auth/session). On Cognito this route 404s — that
    SPA signs in client-side and never calls it.
    """
    req = parse_validated(LoginRequest, _parse_body(event))
    tokens = _refresher().password_grant(req.username, req.password)
    body = json.dumps(
        {
            "data": {
                "id_token": tokens["id_token"],
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "expires_in": tokens["expires_in"],
            }
        }
    )
    return {
        "statusCode": 200,
        "headers": {**_STANDARD_HEADERS, "X-Request-Id": request_id},
        "body": body,
    }


def _establish_session(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    req = parse_validated(EstablishSessionRequest, _parse_body(event))

    return {
        "statusCode": 204,
        "cookies": [_cookie_header(req.refresh_token, _COOKIE_MAX_AGE_SECONDS)],
        "headers": {**_STANDARD_HEADERS, "X-Request-Id": request_id},
        "body": "",
    }


def _refresh(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    refresh_token = _read_refresh_cookie(event)
    if not refresh_token:
        raise AuthenticationRequiredError()

    tokens = _refresher().refresh_id_token(refresh_token)
    body = json.dumps({"data": {"id_token": tokens["id_token"], "expires_in": tokens["expires_in"]}})
    return {
        "statusCode": 200,
        "headers": {**_STANDARD_HEADERS, "X-Request-Id": request_id},
        "body": body,
    }


def _logout(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    refresh_token = _read_refresh_cookie(event)
    if refresh_token:
        _refresher().revoke_refresh_token(refresh_token)

    return {
        "statusCode": 204,
        "cookies": [_cookie_header("", 0)],
        "headers": {**_STANDARD_HEADERS, "X-Request-Id": request_id},
        "body": "",
    }
