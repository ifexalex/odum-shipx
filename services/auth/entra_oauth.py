"""Interactive Entra login helpers — the authorize-URL + PKCE side of the BFF
auth-code flow (services/auth/handler.py). The token exchange itself lives in
entra_refresh.authorization_code_grant.

The SPA never holds the password, the PKCE verifier, or the refresh token: the
backend mints the authorize URL (with a server-generated PKCE challenge, state,
and nonce stashed in a short-lived httpOnly cookie), and on the callback
validates state, exchanges the code with the stored verifier, and sets the
existing httpOnly refresh cookie. This keeps the project's "no tokens/secrets in
JS-reachable storage" posture (11_security_and_compliance.md) while using the
interactive flow that triggers the custom-claims provider (tenant_id/role).

Environment:
  ENTRA_AUTHORIZE_ENDPOINT — OAuth2 authorize endpoint; defaults to the token
    endpoint with its trailing `/token` swapped for `/authorize`.
  ENTRA_TOKEN_ENDPOINT / ENTRA_CLIENT_ID / ENTRA_SCOPE — as in entra_refresh.
  ENTRA_REDIRECT_URI — the SPA callback URL registered on the app registration.
"""

import base64
import hashlib
import os
import secrets
import urllib.parse

_DEFAULT_SCOPE = "openid profile offline_access"


def _b64url(raw: bytes) -> str:
    """Base64url without padding — the encoding PKCE and OAuth state use."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256.

    The verifier is 32 random bytes (43 base64url chars, within the RFC 7636
    43–128 range); the challenge is its SHA-256, base64url-encoded.
    """
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def generate_token() -> str:
    """A random URL-safe token for the `state` / `nonce` values."""
    return _b64url(secrets.token_bytes(24))


def authorize_endpoint() -> str:
    explicit = os.environ.get("ENTRA_AUTHORIZE_ENDPOINT", "").strip()
    if explicit:
        return explicit
    token_endpoint = os.environ.get("ENTRA_TOKEN_ENDPOINT", "").strip()
    if token_endpoint.endswith("/token"):
        return token_endpoint[: -len("/token")] + "/authorize"
    return token_endpoint


def build_authorize_url(state: str, nonce: str, code_challenge: str) -> str:
    """Build the Entra authorize URL for the interactive auth-code + PKCE flow.

    Raises:
        ValueError: required configuration (endpoint / client id / redirect uri)
            is missing.
    """
    endpoint = authorize_endpoint()
    client_id = os.environ.get("ENTRA_CLIENT_ID", "").strip()
    redirect_uri = os.environ.get("ENTRA_REDIRECT_URI", "").strip()
    scope = os.environ.get("ENTRA_SCOPE", _DEFAULT_SCOPE)
    if not endpoint or not client_id or not redirect_uri:
        raise ValueError("ENTRA_AUTHORIZE/TOKEN_ENDPOINT, ENTRA_CLIENT_ID and ENTRA_REDIRECT_URI must be set")

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": scope,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    # Without a `prompt`, Entra silently reuses its single active SSO session, so a
    # user can never choose or switch accounts — the login button just logs the
    # same person straight back in. `select_account` shows the account picker
    # (still SSO-fast for the chosen account). Override via ENTRA_AUTHORIZE_PROMPT
    # (e.g. "login" to force re-auth, or "" to disable).
    prompt = os.environ.get("ENTRA_AUTHORIZE_PROMPT", "select_account").strip()
    if prompt:
        params["prompt"] = prompt

    return f"{endpoint}?{urllib.parse.urlencode(params)}"


def redirect_uri() -> str:
    return os.environ.get("ENTRA_REDIRECT_URI", "").strip()
