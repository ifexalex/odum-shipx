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

import json
import logging
import time
import uuid
from typing import Any

from shared.exceptions import AuthenticationRequiredError, LogisticsBaseError, ResourceNotFoundError
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.observability import init_tracing
from shared.responses import error_response
from shared.validation import parse_validated

from .models import EstablishSessionRequest

setup_logging()
init_tracing()

logger = logging.getLogger(__name__)

_COOKIE_NAME = "shipx_rt"
_COOKIE_PATH = "/v1/auth"
# Matches Cognito's refresh_token_validity (infrastructure/aws/modules/cognito/main.tf) — the
# cookie's lifetime should never exceed the token's own validity, but capping it here too
# means a stale cookie value from a rotated Cognito config still expires client-side on schedule.
_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30

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
        if method == "POST" and path == "/v1/auth/session":
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


def _cookie_header(value: str, max_age: int) -> str:
    return f"{_COOKIE_NAME}={value}; Path={_COOKIE_PATH}; Max-Age={max_age}; HttpOnly; Secure; SameSite=Strict"


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
