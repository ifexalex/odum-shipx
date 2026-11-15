"""Absolute URLs for links emailed or messaged to people outside the system.

Why this is one module
----------------------
Links in notifications were built ad hoc at each call site, each reading its
own environment variable:

- activation links read ``APP_BASE_URL``, falling back to the origin of
  ``ENTRA_REDIRECT_URI`` — so Azure worked, and AWS (which sets neither) would
  have emailed an empty link;
- customer invite links read ``CUSTOMER_PORTAL_BASE_URL``, which **no**
  environment sets — not AWS Terraform, not Azure Terraform, not
  ``.env.local``, only ``.env.example``. Every invite therefore went out as a
  bare relative path, ``/invite/<token>``, which no mail client can open.

A link is the whole point of these messages. Building one from an empty base
produces a message that looks delivered, is recorded as delivered, and is
useless to whoever receives it — and nothing anywhere failed. So the resolution
lives in one place, with one fallback chain, and refuses to produce a relative
URL at all.

Staff and customers share one SPA (``frontend/src/shell/routes.tsx`` serves
``/activate/:token`` and ``/invite/:token`` from the same app), so one base URL
serves both. ``CUSTOMER_PORTAL_BASE_URL`` is kept as an override for the day the
customer portal moves to its own host, not as a second thing to configure.
"""

import logging
import os
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


class MissingBaseUrlError(RuntimeError):
    """No absolute base URL is configured, so no usable link can be built.

    Raised rather than returning a relative URL: a notification carrying a dead
    link is worse than one that was never sent, because it consumes the single
    -use token, tells staff the invite went out, and leaves the recipient with
    nothing to click. Callers that must not fail (notifications are best-effort
    throughout this codebase) catch it and log — but they do so knowing the link
    was unusable, instead of discovering it from a customer.
    """


def origin_of(url: str) -> str:
    """Return ``scheme://host`` for an absolute URL, or "" if it is not one."""
    parts = urlsplit(url.strip())
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


def app_base_url(*, override_env: str | None = None) -> str:
    """Return the absolute base URL of the web app, without a trailing slash.

    Args:
        override_env: An environment variable consulted ahead of the default
            chain — used by ``invite_url`` for ``CUSTOMER_PORTAL_BASE_URL``.

    Resolution order: ``override_env`` → ``APP_BASE_URL`` → the origin of
    ``ENTRA_REDIRECT_URI`` (the SPA host, when the Entra auth flow is
    configured).

    Raises:
        MissingBaseUrlError: Nothing resolved to an absolute URL.
    """
    candidates = [override_env, "APP_BASE_URL"] if override_env else ["APP_BASE_URL"]
    for name in candidates:
        if name is None:
            continue
        value = os.environ.get(name, "").strip()
        if not value:
            continue
        # A value that is set but relative is a misconfiguration, not a
        # fallback: say which variable is wrong rather than silently moving on
        # to the next one and emitting a link to the wrong host.
        if not origin_of(value):
            raise MissingBaseUrlError(f"{name} is set but is not an absolute URL (expected https://host)")
        return value.rstrip("/")

    derived = origin_of(os.environ.get("ENTRA_REDIRECT_URI", ""))
    if derived:
        return derived

    wanted = " or ".join(filter(None, [override_env, "APP_BASE_URL"]))
    raise MissingBaseUrlError(f"No absolute base URL configured — set {wanted} (or ENTRA_REDIRECT_URI)")


def activation_url(token: str) -> str:
    """Absolute ``/activate/{token}`` link for an operator-provisioned user."""
    return f"{app_base_url()}/activate/{token}"


def invite_url(token: str) -> str:
    """Absolute ``/invite/{token}`` link for a customer account invite.

    Prefers ``CUSTOMER_PORTAL_BASE_URL`` so a separately hosted customer portal
    can be pointed at without touching the staff app's own base URL, then falls
    back to the shared app base.
    """
    return f"{app_base_url(override_env='CUSTOMER_PORTAL_BASE_URL')}/invite/{token}"


def login_url() -> str:
    """Absolute ``/login`` link, for messages that point someone at the sign-in page."""
    return f"{app_base_url()}/login"
