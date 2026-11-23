"""Refuse cookie-authenticated requests that did not come from our own frontend.

The session endpoints (`services/auth/handler.py`) read or set the httpOnly refresh cookie. A
browser attaches that cookie to *any* request to our host, including one a third-party page
caused, so the cookie alone proves nothing about who asked. Where it is sent cross-site (the
cookie is `SameSite=None` on some deployments) a hostile page could post its own refresh token
to sign the victim's browser into the attacker's account, or force a logout.

A page cannot forge the `Origin` header a browser sends, so comparing it with the origins we serve
the frontend from closes that. The list is not a second thing to configure: it is the origins
the app already knows (`APP_BASE_URL`, `CUSTOMER_PORTAL_BASE_URL`, the origin of `ENTRA_REDIRECT_URI`)
plus `ALLOWED_ORIGINS`, which Terraform fills from the API's CORS list, plus `CORS_ALLOW_ORIGINS`
for the container app.

A missing `Origin` is refused too: every browser sends one on a POST, and what sends none is not
a browser. With no trusted origin configured at all, every request is refused (fail closed) and
the misconfiguration is logged loudly instead of silently disabling the check.
"""

import logging
import os

from shared.app_urls import origin_of
from shared.exceptions import UnsupportedMediaTypeError, UntrustedOriginError

logger = logging.getLogger(__name__)

# Origins listed directly, comma-separated.
_LIST_ENV_VARS = ("ALLOWED_ORIGINS", "CORS_ALLOW_ORIGINS")
# Variables holding a URL, from which only the origin is used.
_URL_ENV_VARS = ("APP_BASE_URL", "CUSTOMER_PORTAL_BASE_URL", "ENTRA_REDIRECT_URI")


def trusted_origins() -> frozenset[str]:
    """Return the origins that may call the cookie endpoints, as lowercase `scheme://host[:port]`."""
    origins: set[str] = set()
    for name in _LIST_ENV_VARS:
        for entry in os.environ.get(name, "").split(","):
            origin = origin_of(entry)
            if origin:
                origins.add(origin.lower())
    for name in _URL_ENV_VARS:
        origin = origin_of(os.environ.get(name, ""))
        if origin:
            origins.add(origin.lower())
    return frozenset(origins)


def _header(event: dict[str, object], name: str) -> str:
    """Read a header off a payload-format-2.0 event, whose header names are lowercased."""
    headers = event.get("headers") or {}
    value = headers.get(name, "") if isinstance(headers, dict) else ""
    return str(value or "").strip()


def assert_trusted_origin(event: dict[str, object]) -> None:
    """Raise UntrustedOriginError (403) unless the request's `Origin` is one of ours."""
    trusted = trusted_origins()
    if not trusted:
        logger.error("No trusted origin is configured (set APP_BASE_URL or ALLOWED_ORIGINS) — refusing a cookie-endpoint request")
        raise UntrustedOriginError()

    origin = _header(event, "origin")
    if not origin:
        logger.warning("Refused a cookie-endpoint request with no Origin header")
        raise UntrustedOriginError()
    if origin.lower() not in trusted:
        # The value is attacker-controlled, so it is logged only as a bounded, escaped string.
        logger.warning("Refused a cookie-endpoint request from origin %r", origin[:200])
        raise UntrustedOriginError()


def assert_json_content_type(event: dict[str, object]) -> None:
    """Raise UnsupportedMediaTypeError (415) unless the request declares a JSON body.

    The session endpoints parse the body as JSON whatever its type, so without this a cross-site
    HTML form posting `text/plain` could still deliver one without the preflight a JSON
    `Content-Type` forces. Only for the routes that read a body.
    """
    media_type = _header(event, "content-type").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise UnsupportedMediaTypeError()
