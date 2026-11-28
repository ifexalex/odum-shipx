"""Where platform admins sign in, and whether that sign-in used multi-factor authentication (platform audit Phase 1b, D3).

**AWS.** Platform admins have their own Cognito user pool (``infrastructure/aws/modules/cognito``, ``platform`` pool) with
MFA required (TOTP) for every user. A token from that pool is recognised by its verified ``iss`` claim
(``PLATFORM_COGNITO_ISSUER``); it carries no tenant or group claims, because membership of the pool *is* the platform
admin grant, so the claims mapper reads it as ``tenant_id = PLATFORM`` and group ``platform_admin``. The platform
directory (``shared/platform_directory.py``) then decides who the person is and what their role allows.

**Entra.** Platform admins stay in the one directory, and a Conditional Access policy requires MFA for the
``platform_admin`` group. The token says so in ``amr`` (``mfa``), or in ``acrs`` when an authentication context is
configured (``ENTRA_PLATFORM_MFA_ACR``).

**Enforcement.** With ``PLATFORM_MFA_REQUIRED=true`` a platform request is refused (403 ``PLATFORM_MFA_REQUIRED``)
unless its token shows MFA as above. Terraform sets it on AWS together with the pool, and on Azure when the
Conditional Access policy is in place; it is off locally, where the dev shim has no identity provider.
"""

import os
from typing import Any

# Entra `amr` values that mean a second factor was used.
_ENTRA_MFA_AMR = frozenset({"mfa", "ngcmfa", "fido", "hwk", "otp", "sms", "rsa", "wia"})


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def platform_issuer() -> str:
    """The platform Cognito pool's issuer URL, or "" when there is no platform pool (Azure, local)."""
    return _env("PLATFORM_COGNITO_ISSUER").rstrip("/")


def platform_pool_id() -> str:
    """The platform Cognito user pool id, or ""."""
    return _env("COGNITO_PLATFORM_USER_POOL_ID")


def platform_client_id() -> str:
    """The platform pool's public app client id, or ""."""
    return _env("COGNITO_PLATFORM_CLIENT_ID")


def is_platform_pool_token(claims: dict[str, Any]) -> bool:
    """True when verified claims were issued by the platform Cognito pool."""
    issuer = platform_issuer()
    return bool(issuer) and str(claims.get("iss") or "").rstrip("/") == issuer


def mfa_required() -> bool:
    """Whether platform requests must prove MFA (``PLATFORM_MFA_REQUIRED``)."""
    return _env("PLATFORM_MFA_REQUIRED").lower() == "true"


def token_shows_mfa(claims: dict[str, Any], auth_provider: str) -> bool:
    """True when the token proves a second factor for this identity provider.

    AWS: issued by the platform pool, which requires MFA of every user. Entra: ``amr`` names a second factor, or
    ``acrs`` holds the configured authentication context.
    """
    if auth_provider != "azure":
        return is_platform_pool_token(claims)
    amr = claims.get("amr") or []
    if isinstance(amr, str):
        amr = [amr]
    if _ENTRA_MFA_AMR & {str(a).lower() for a in amr}:
        return True
    acr = _env("ENTRA_PLATFORM_MFA_ACR")
    acrs = claims.get("acrs") or []
    if isinstance(acrs, str):
        acrs = [acrs]
    return bool(acr) and acr in {str(a) for a in acrs}
